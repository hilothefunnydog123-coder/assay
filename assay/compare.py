"""Regression detection.

The single most useful thing an eval tool does: tell you, when you change a
prompt or swap a model, *exactly which cases broke*. `diff` compares two runs of
the same eval case-by-case and sorts the changes into regressions (were passing,
now failing), fixes (the reverse), and score drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Diff:
    eval: str
    pass_rate_before: float
    pass_rate_after: float
    regressions: list[dict] = field(default_factory=list)   # passing -> failing
    fixes: list[dict] = field(default_factory=list)         # failing -> passing
    score_drops: list[dict] = field(default_factory=list)   # still passing, but worse
    added: list[str] = field(default_factory=list)          # cases only in the new run
    removed: list[str] = field(default_factory=list)        # cases only in the old run

    @property
    def pass_rate_delta(self) -> float:
        return self.pass_rate_after - self.pass_rate_before

    @property
    def regressed(self) -> bool:
        return bool(self.regressions) or self.pass_rate_after < self.pass_rate_before


def _by_id(run: dict) -> dict[str, dict]:
    return {r["case_id"]: r for r in run["results"]}


def diff(before: dict, after: dict, *, score_drop_eps: float = 0.05) -> Diff:
    a, b = _by_id(before), _by_id(after)
    d = Diff(eval=after.get("eval", ""),
             pass_rate_before=before.get("pass_rate", 0.0),
             pass_rate_after=after.get("pass_rate", 0.0))

    for cid in b:
        if cid not in a:
            d.added.append(cid)
            continue
        was, now = a[cid], b[cid]
        if was["passed"] and not now["passed"]:
            d.regressions.append({"case_id": cid, "input": now["input"],
                                  "output": now["output"], "expect": now["expect"],
                                  "why": _first_reason(now)})
        elif not was["passed"] and now["passed"]:
            d.fixes.append({"case_id": cid})
        elif now["score"] < was["score"] - score_drop_eps:
            d.score_drops.append({"case_id": cid, "before": was["score"],
                                  "after": now["score"]})

    d.removed = [cid for cid in a if cid not in b]
    return d


def _first_reason(result: dict) -> str:
    if result.get("error"):
        return "task errored"
    for s in result.get("scores", []):
        if not s["passed"] and s.get("reason"):
            return s["reason"]
    return "failed"
