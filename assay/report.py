"""Terminal rendering for runs and diffs. ANSI colour, no dependencies; degrades
to plain text when the output is not a terminal."""
from __future__ import annotations

import sys

from .compare import Diff
from .core import Run

_COLOR = sys.stdout.isatty()


def _unicode_ok() -> bool:
    """Whether the stream can actually render the block glyphs.

    A Windows console on cp1252 raises UnicodeEncodeError on `█`, which would
    crash the run *after* it succeeded — the worst possible time. Ask the stream
    rather than guessing from the platform.
    """
    enc = getattr(sys.stdout, "encoding", None) or ""
    try:
        "█░·→".encode(enc)
        return True
    except (LookupError, UnicodeEncodeError):
        return False


_UNICODE = _unicode_ok()
_FULL, _EMPTY, _DOT = ("█", "░", "·") if _UNICODE else ("#", "-", "*")
# Punctuation a cp1252 console technically encodes but some Windows terminals
# still render as mojibake; ASCII wherever full Unicode is not available.
_DASH, _ELL = ("—", "…") if _UNICODE else ("-", "...")


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


green = lambda s: _c("32", s)
red = lambda s: _c("31", s)
yellow = lambda s: _c("33", s)
dim = lambda s: _c("2", s)
bold = lambda s: _c("1", s)


def _bar(rate: float, width: int = 24) -> str:
    filled = round(rate * width)
    body = _FULL * filled + _EMPTY * (width - filled)
    color = green if rate >= 0.9 else yellow if rate >= 0.7 else red
    return color(body)


def render_run(run: Run, *, verbose: bool = False) -> str:
    out = [f"\n{bold(run.eval)}  {dim(run.started_at[:19])}"]
    for r in run.results:
        mark = green("PASS") if r.passed else red("FAIL")
        head = f"  {mark}  {r.case_id}  {dim(f'{r.latency_ms:.0f}ms')}"
        out.append(head)
        if not r.passed or verbose:
            if r.error:
                out.append(dim(f"        error: {r.error.splitlines()[-1]}"))
            for s in r.scores:
                if not s.passed or verbose:
                    tag = red("x") if not s.passed else green("+")
                    reason = f"  {dim(s.reason)}" if s.reason else ""
                    out.append(f"        {tag} {s.name}{reason}")
    rate = run.pass_rate
    summary = f"{run.passed}/{run.n} passed"
    color = green if rate == 1 else yellow if rate >= 0.7 else red
    out.append(f"\n  {_bar(rate)}  {color(f'{rate*100:.0f}%')}  {summary}"
               f"  {dim(f'{_DOT} mean {run.mean_score:.2f} {_DOT} {run.total_ms:.0f}ms total')}")
    return "\n".join(out)


def render_diff(d: Diff) -> str:
    arrow = f"{d.pass_rate_before*100:.0f}% -> {d.pass_rate_after*100:.0f}%"
    delta = d.pass_rate_delta * 100
    head = green(arrow) if delta >= 0 else red(arrow)
    out = [f"\n{bold('compare ' + d.eval)}   {head}  ({delta:+.0f} pts)"]

    if d.regressions:
        out.append(red(f"\n  {len(d.regressions)} regression(s) {_DASH} were passing, now failing:"))
        for r in d.regressions:
            out.append(f"    {red('-')} {r['case_id']}: {dim(r['why'])}")
            out.append(dim(f"        got {str(r['output'])[:80]!r}"))
    if d.fixes:
        out.append(green(f"\n  {len(d.fixes)} fixed:"))
        out.append("    " + ", ".join(f["case_id"] for f in d.fixes))
    if d.score_drops:
        out.append(yellow(f"\n  {len(d.score_drops)} score drop(s) (still passing):"))
        for s in d.score_drops:
            out.append(f"    {yellow('~')} {s['case_id']}: {s['before']:.2f} -> {s['after']:.2f}")
    if d.added:
        out.append(dim(f"\n  {len(d.added)} new case(s): " + ", ".join(d.added)))
    if d.removed:
        out.append(dim(f"  {len(d.removed)} removed case(s): " + ", ".join(d.removed)))

    if not (d.regressions or d.fixes or d.score_drops):
        out.append(green(f"\n  no changes {_DASH} stable."))
    return "\n".join(out)


def render_violations(violations: list) -> str:
    """Why the gate said no. One line per broken rule, rule name first, because
    the first question after a red build is always 'which bar did I miss'."""
    if not violations:
        return green(f"\n  gate passed {_DASH} every rule in assay.toml is satisfied.")
    out = [red(f"\n  GATE FAILED {_DASH} {len(violations)} rule(s) broken:")]
    for v in violations:
        where = dim(f" [{v.eval}]") if v.eval else ""
        out.append(f"    {red('x')} {bold(v.rule)}{where}  {v.detail}")
    return "\n".join(out)


def render_verification(v) -> str:
    """The integrity check, phrased the way it would be quoted to someone who
    is not going to run it themselves."""
    if v.records == 0:
        return dim(f"\n  no ledger yet {_DASH} run an eval to start the record.")
    if v.ok:
        extra = f" {_DOT} {v.attested} attested" if v.attested else ""
        return (green(f"\n  VERIFIED  {v.records} record(s), unbroken chain")
                + dim(f"\n  {v.checked_files} run file(s) match their recorded digest"
                      f"{extra}\n  fingerprint {v.fingerprint}"))
    out = [red(f"\n  NOT VERIFIED {_DASH} {len(v.problems)} problem(s):")]
    for p in v.problems[:12]:
        out.append(f"    {red('x')} {p}")
    if len(v.problems) > 12:
        out.append(dim(f"    {_ELL} and {len(v.problems) - 12} more"))
    out.append(dim("\n  This history has been altered since it was written."))
    return "\n".join(out)
