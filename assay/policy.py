"""The gate: the rule that decides whether a change ships.

A pass rate printed in a terminal is a fact nobody acts on. A build that goes red
is a decision. ``assay.toml`` turns your quality bar into that decision, in one
place, versioned with the code it guards::

    [gate]
    min_pass_rate = 0.95        # suite-wide floor
    allow_regressions = 0       # cases that were passing and now fail
    max_score_drop = 0.10       # per-case score erosion, even while passing
    require_controls = ["owasp-llm:llm01", "owasp-llm:llm02"]
    require_suite_stable = true # pass rate may not rise because tests were cut

    [gate.evals."support-router"]
    min_pass_rate = 1.0         # per-eval override: this one is load-bearing

``require_suite_stable`` is the rule the rest of the category is missing. Without
it, the cheapest way to make a red build green is to delete the failing case, and
nothing notices.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

CONFIG_NAMES = ("assay.toml", ".assay.toml")


# --- config loading ------------------------------------------------------- #
def _load_toml(path: str) -> dict:
    try:
        import tomllib                       # Python 3.11+
    except ModuleNotFoundError:              # 3.9 / 3.10 — parse the small subset
        return _mini_toml(path)              # our own config actually uses
    with open(path, "rb") as f:
        return tomllib.load(f)


def _mini_toml(path: str) -> dict:
    """A deliberately small TOML reader for 3.9/3.10, where ``tomllib`` does not
    exist and taking a dependency would cost more than it is worth.

    Handles what a gate config needs: ``[a.b]`` tables (including quoted keys),
    and scalar or single-line-array values. Anything fancier belongs in 3.11+.
    """
    import json as _json
    root: dict[str, Any] = {}
    table = root
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip() if not raw.strip().startswith(
                ("'", '"')) else raw.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                table = root
                for part in _split_key(line[1:-1]):
                    table = table.setdefault(part, {})
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            table[_split_key(key.strip())[-1]] = _scalar(value.strip(), _json)
    return root


def _split_key(key: str) -> list[str]:
    """Split a dotted TOML key, honouring quoted segments like ``"my-eval"``."""
    parts, buf, quote = [], "", ""
    for ch in key.strip():
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf += ch
        elif ch in "\"'":
            quote = ch
        elif ch == ".":
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    parts.append(buf.strip())
    return [p for p in parts if p]


def _scalar(text: str, _json) -> Any:
    if text in ("true", "false"):
        return text == "true"
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p.strip(), _json) for p in inner.split(",") if p.strip()]
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def find_config(start: str = ".") -> Optional[str]:
    """Nearest config walking up from ``start`` — so the gate works from any
    subdirectory of the repo, the way git and pytest do."""
    d = os.path.abspath(start)
    while True:
        for name in CONFIG_NAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


# --- the gate ------------------------------------------------------------- #
@dataclass
class Gate:
    min_pass_rate: float = 0.0
    allow_regressions: int = 0
    max_score_drop: float = 1.0
    require_controls: list[str] = field(default_factory=list)
    require_suite_stable: bool = False
    max_mean_latency_ms: float = 0.0        # 0 = unenforced
    per_eval: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[str] = None, start: str = ".") -> "Gate":
        path = path or find_config(start)
        if not path:
            return cls()
        cfg = _load_toml(path).get("gate", {}) or {}
        per_eval = cfg.get("evals", {}) or {}
        return cls(
            min_pass_rate=float(cfg.get("min_pass_rate", 0.0)),
            allow_regressions=int(cfg.get("allow_regressions", 0)),
            max_score_drop=float(cfg.get("max_score_drop", 1.0)),
            require_controls=list(cfg.get("require_controls", []) or []),
            require_suite_stable=bool(cfg.get("require_suite_stable", False)),
            max_mean_latency_ms=float(cfg.get("max_mean_latency_ms", 0.0)),
            per_eval={k: v for k, v in per_eval.items() if isinstance(v, dict)},
        )

    def for_eval(self, name: str) -> "Gate":
        """This gate with any per-eval overrides applied."""
        over = self.per_eval.get(name)
        if not over:
            return self
        merged = Gate(**{**self.__dict__, "per_eval": {}})
        for key, value in over.items():
            if hasattr(merged, key):
                setattr(merged, key, value)
        return merged


@dataclass
class Violation:
    rule: str
    detail: str
    eval: str = ""


def check_run(run: dict, gate: Gate, diff=None, previous: Optional[dict] = None
              ) -> list[Violation]:
    """Every way this run breaks the bar. Empty list means ship it."""
    g = gate.for_eval(run.get("eval", ""))
    name = run.get("eval", "")
    out: list[Violation] = []

    rate = run.get("pass_rate", 0.0)
    if g.min_pass_rate and rate < g.min_pass_rate:
        out.append(Violation("min_pass_rate",
                             f"{rate*100:.0f}% is below the {g.min_pass_rate*100:.0f}% floor",
                             name))

    if diff is not None:
        n = len(diff.regressions)
        if n > g.allow_regressions:
            cases = ", ".join(r["case_id"] for r in diff.regressions[:5])
            out.append(Violation("allow_regressions",
                                 f"{n} regression(s) (limit {g.allow_regressions}): {cases}",
                                 name))
        for drop in diff.score_drops:
            delta = drop["before"] - drop["after"]
            if delta > g.max_score_drop:
                out.append(Violation("max_score_drop",
                                     f"{drop['case_id']} fell {delta:.2f} "
                                     f"(limit {g.max_score_drop:.2f})", name))

    if g.require_controls:
        have = set(run.get("controls", []) or [])
        missing = [c for c in g.require_controls if c not in have]
        if missing:
            out.append(Violation("require_controls",
                                 "no evidence for " + ", ".join(missing), name))

    # The anti-gaming rule: a suite may change, but not silently, and not in the
    # same breath as claiming an improvement.
    if g.require_suite_stable and previous:
        before, after = previous.get("suite_hash", ""), run.get("suite_hash", "")
        if before and after and before != after:
            shrank = run.get("n", 0) < previous.get("n", 0)
            improved = run.get("pass_rate", 0) > previous.get("pass_rate", 0)
            if shrank or improved:
                out.append(Violation(
                    "require_suite_stable",
                    f"the suite itself changed ({previous.get('n')} cases -> "
                    f"{run.get('n')}) while the pass rate moved "
                    f"{previous.get('pass_rate',0)*100:.0f}% -> {rate*100:.0f}%; "
                    "review the test change before trusting the score", name))

    if g.max_mean_latency_ms:
        results = run.get("results", []) or []
        if results:
            mean_ms = sum(r.get("latency_ms", 0) for r in results) / len(results)
            if mean_ms > g.max_mean_latency_ms:
                out.append(Violation("max_mean_latency_ms",
                                     f"mean {mean_ms:.0f}ms exceeds "
                                     f"{g.max_mean_latency_ms:.0f}ms", name))
    return out
