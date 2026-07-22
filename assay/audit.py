"""``assay audit`` — turn a folder of runs into a document you can hand someone.

The output is a single self-contained HTML file (no assets, no network, prints
to PDF cleanly) that answers, in order, the questions an enterprise reviewer or
an auditor actually asks:

1. What system is this, who owns it, and over what period was it tested?
2. Is this record intact, or has it been edited since it was written?
3. Which assurance controls have current test evidence — and which are bare?
4. What changed over the period, and did anything regress?
5. Show me the actual cases.

Everything is derived from ``.assay/`` — the same files the CLI already writes.
No service, no upload, no account: the evidence never leaves the machine that
produced it, which is the point for anyone who cannot send prompts and model
outputs to a third party.
"""
from __future__ import annotations

import html
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import controls as _controls
from . import ledger as _ledger
from . import store
from .compare import diff


# --- gathering ------------------------------------------------------------ #
@dataclass
class Evidence:
    system: str
    generated_at: str
    root: str
    evals: list[dict] = field(default_factory=list)
    verification: Optional[_ledger.Verification] = None
    coverage: dict = field(default_factory=dict)
    period: tuple[str, str] = ("", "")
    owners: list[str] = field(default_factory=list)

    @property
    def total_runs(self) -> int:
        return sum(len(e["runs"]) for e in self.evals)

    @property
    def total_cases(self) -> int:
        return sum(e["latest"]["n"] for e in self.evals if e["latest"])

    @property
    def pass_rate(self) -> float:
        """Case-weighted across the latest run of every eval — a suite with 200
        cases should not be averaged flat against one with 3."""
        n = sum(e["latest"]["n"] for e in self.evals if e["latest"])
        p = sum(e["latest"]["passed"] for e in self.evals if e["latest"])
        return p / n if n else 0.0


def collect(root: str = store.ROOT, system: str = "", now: str = "") -> Evidence:
    runs_dir = os.path.join(root, "runs")
    ev = Evidence(system=system, generated_at=now, root=root)

    names = sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []
    stamps: list[str] = []
    owners: set[str] = set()
    tagged: dict[str, list[str]] = {}

    for name in names:
        d = os.path.join(runs_dir, name)
        if not os.path.isdir(d):
            continue
        runs = []
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    runs.append(json.load(f))
        if not runs:
            continue
        latest = runs[-1]
        eval_name = latest.get("eval", name)
        tagged[eval_name] = latest.get("controls", []) or []
        if latest.get("owner"):
            owners.add(latest["owner"])
        if not ev.system and latest.get("system"):
            ev.system = latest["system"]
        stamps += [r.get("started_at", "") for r in runs if r.get("started_at")]

        # Consecutive-run diffs are the change log: what a reviewer means by
        # "show me your change control" for the model layer.
        changes = []
        for before, after in zip(runs, runs[1:]):
            d_ = diff(before, after)
            if d_.regressions or d_.fixes or d_.score_drops or d_.added or d_.removed:
                changes.append({
                    "at": after.get("started_at", "")[:19],
                    "before": before.get("pass_rate", 0.0),
                    "after": after.get("pass_rate", 0.0),
                    "regressions": d_.regressions,
                    "fixes": [f["case_id"] for f in d_.fixes],
                    "score_drops": d_.score_drops,
                    "added": d_.added,
                    "removed": d_.removed,
                    "suite_changed": (before.get("suite_hash", "")
                                      != after.get("suite_hash", "")),
                })

        ev.evals.append({
            "name": eval_name,
            "runs": runs,
            "latest": latest,
            "controls": latest.get("controls", []) or [],
            "changes": changes,
        })

    ev.owners = sorted(owners)
    ev.coverage = _controls.coverage(tagged)
    if stamps:
        ev.period = (min(stamps)[:19], max(stamps)[:19])
    ev.verification = _ledger.verify(root)
    return ev


def to_json(ev: Evidence) -> dict:
    v = ev.verification
    return {
        "system": ev.system,
        "generated_at": ev.generated_at,
        "period": {"from": ev.period[0], "to": ev.period[1]},
        "owners": ev.owners,
        "summary": {
            "evals": len(ev.evals),
            "runs": ev.total_runs,
            "cases": ev.total_cases,
            "pass_rate": ev.pass_rate,
        },
        "integrity": {
            "verified": bool(v and v.ok),
            "records": v.records if v else 0,
            "fingerprint": v.fingerprint if v else "",
            "attested_records": v.attested if v else 0,
            "problems": v.problems if v else [],
        },
        "controls": list(ev.coverage.values()),
        "evals": [{
            "name": e["name"],
            "controls": e["controls"],
            "runs": len(e["runs"]),
            "pass_rate": e["latest"].get("pass_rate", 0.0),
            "cases": e["latest"].get("n", 0),
            "suite_hash": e["latest"].get("suite_hash", ""),
            "last_run": e["latest"].get("started_at", ""),
            "changes": e["changes"],
        } for e in ev.evals],
    }


# --- rendering ------------------------------------------------------------ #
def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _short(x: Any, n: int = 160) -> str:
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s if len(s) <= n else s[:n] + "…"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _spark(runs: list[dict]) -> str:
    if len(runs) < 2:
        return '<div class="none">one run so far</div>'
    w, h, p = 640, 90, 8
    ys = [r.get("pass_rate", 0.0) for r in runs]
    X = lambda i: p + (w - 2 * p) * i / (len(ys) - 1)
    Y = lambda v: h - p - (h - 2 * p) * v
    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    dots = "".join(
        f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="2.6" fill="'
        f'{"#1a7f37" if v >= .9 else "#9a6700" if v >= .7 else "#cf222e"}"/>'
        for i, v in enumerate(ys))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="none">'
            f'<line x1="{p}" y1="{Y(1):.1f}" x2="{w-p}" y2="{Y(1):.1f}" '
            f'stroke="#d8dee4" stroke-dasharray="3 4"/>'
            f'<polyline points="{line}" fill="none" stroke="#1a7f37" '
            f'stroke-width="2" stroke-linejoin="round"/>{dots}</svg>')


def render(ev: Evidence) -> str:
    v = ev.verification
    ok = bool(v and v.ok)

    if ok:
        banner = (f'<div class="seal good"><b>Record verified.</b> '
                  f'{v.records} run record(s) form an unbroken SHA-256 chain; '
                  f'{v.checked_files} run file(s) still match the digest taken '
                  f'when they were written. Chain fingerprint '
                  f'<code>{_e(v.fingerprint)}</code>.'
                  + (f' {v.attested} record(s) carry a key attestation.'
                     if v and v.attested else '') + '</div>')
    else:
        items = "".join(f"<li>{_e(p)}</li>" for p in (v.problems if v else [])[:12])
        banner = ('<div class="seal bad"><b>Record NOT verified.</b> This history '
                  'has been altered since it was written and should not be relied '
                  f'on as evidence.<ul>{items}</ul></div>')

    # --- control coverage --------------------------------------------------- #
    by_fw: dict[str, list[dict]] = {}
    for c in ev.coverage.values():
        by_fw.setdefault(c["framework"], []).append(c)
    if by_fw:
        blocks = []
        for fw in sorted(by_fw):
            rows = "".join(
                f'<tr><td class="ref">{_e(c["ref"])}</td>'
                f'<td><b>{_e(c["title"])}</b><div class="req">{_e(c["requirement"])}</div></td>'
                f'<td class="ev">{"".join(f"<span class=chip>{_e(n)}</span>" for n in sorted(set(c["evals"])))}</td>'
                f'<td class="yes">covered</td></tr>'
                for c in sorted(by_fw[fw], key=lambda c: c["ref"]))
            blocks.append(f'<h3>{_e(fw)}</h3><table class="controls">'
                          f'<thead><tr><th>Ref</th><th>Control</th>'
                          f'<th>Evidence from</th><th>Status</th></tr></thead>'
                          f'<tbody>{rows}</tbody></table>')
        coverage_html = "".join(blocks)
    else:
        coverage_html = ('<div class="none">No evals declare controls yet. Add '
                         '<code>controls=[…]</code> to an Eval to map its results '
                         'onto a framework.</div>')

    # --- per-eval ----------------------------------------------------------- #
    sections = []
    for e in ev.evals:
        latest, runs = e["latest"], e["runs"]
        rate = latest.get("pass_rate", 0.0)
        cls = "good" if rate >= .9 else "warn" if rate >= .7 else "bad"
        chips = "".join(f'<span class="chip">{_e(c)}</span>' for c in e["controls"])

        changes = ""
        if e["changes"]:
            rows = []
            for c in reversed(e["changes"][-12:]):
                bits = []
                if c["regressions"]:
                    bits.append(f'<span class="bad">{len(c["regressions"])} regressed</span>: '
                                + ", ".join(_e(r["case_id"]) for r in c["regressions"][:4]))
                if c["fixes"]:
                    bits.append(f'<span class="good">{len(c["fixes"])} fixed</span>')
                if c["score_drops"]:
                    bits.append(f'{len(c["score_drops"])} score drop(s)')
                if c["added"]:
                    bits.append(f'{len(c["added"])} case(s) added')
                if c["removed"]:
                    bits.append(f'<span class="bad">{len(c["removed"])} case(s) removed</span>')
                if c["suite_changed"]:
                    bits.append('<span class="warn">suite definition changed</span>')
                rows.append(f'<tr><td class="ref">{_e(c["at"])}</td>'
                            f'<td>{_pct(c["before"])} &rarr; {_pct(c["after"])}</td>'
                            f'<td>{" · ".join(bits)}</td></tr>')
            changes = ('<h4>Change log</h4><table class="controls"><thead><tr>'
                       '<th>When</th><th>Pass rate</th><th>What changed</th>'
                       f'</tr></thead><tbody>{"".join(rows)}</tbody></table>')

        case_rows = "".join(
            f'<tr class="{"p" if r.get("passed") else "f"}">'
            f'<td>{"PASS" if r.get("passed") else "FAIL"}</td>'
            f'<td class="ref">{_e(r.get("case_id"))}</td>'
            f'<td><code>{_e(_short(r.get("input")))}</code></td>'
            f'<td><code>{_e(_short(r.get("output")))}</code></td>'
            f'<td>{_e("; ".join(s.get("reason","") for s in r.get("scores",[]) if not s.get("passed")))}</td>'
            f'</tr>' for r in latest.get("results", []))

        sections.append(f"""
<section class="eval">
  <div class="ehead">
    <h2>{_e(e["name"])}</h2>
    <div class="rate {cls}">{_pct(rate)}<small> {latest.get("passed",0)}/{latest.get("n",0)} cases</small></div>
  </div>
  <div class="meta">{chips}<span class="dim">{len(runs)} run(s) · last
    {_e(latest.get("started_at","")[:19])} · suite
    <code>{_e(latest.get("suite_hash","")[:12])}</code></span></div>
  <div class="chart">{_spark(runs)}</div>
  {changes}
  <h4>Cases · latest run</h4>
  <table class="cases"><thead><tr><th></th><th>Case</th><th>Input</th>
    <th>Output</th><th>Failure reason</th></tr></thead>
    <tbody>{case_rows}</tbody></table>
</section>""")

    return _TEMPLATE.format(
        title=_e(ev.system or "AI system"),
        system=_e(ev.system or "(unnamed system)"),
        generated=_e(ev.generated_at),
        period=_e(f"{ev.period[0]} — {ev.period[1]}" if ev.period[0] else "n/a"),
        owners=_e(", ".join(ev.owners) or "unassigned"),
        n_evals=len(ev.evals),
        n_runs=ev.total_runs,
        n_cases=ev.total_cases,
        rate=_pct(ev.pass_rate),
        rate_cls="good" if ev.pass_rate >= .9 else "warn" if ev.pass_rate >= .7 else "bad",
        banner=banner,
        coverage=coverage_html,
        sections="".join(sections) or '<div class="none">No runs found.</div>',
        fingerprint=_e(v.fingerprint if v else ""),
    )


_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI assurance evidence — {title}</title><style>
*{{box-sizing:border-box}}
body{{margin:0;padding:40px 24px 80px;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:#1f2328;background:#fff}}
.wrap{{max-width:980px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:19px;margin:0}}
h3{{font-size:15px;margin:26px 0 8px;color:#57606a;text-transform:uppercase;letter-spacing:.06em}}
h4{{font-size:14px;margin:22px 0 8px;color:#57606a}}
.sub{{color:#57606a;margin-bottom:24px}}
code{{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:#f0f2f5;padding:1px 5px;border-radius:4px;word-break:break-all}}
.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:20px 0}}
.fact{{border:1px solid #d8dee4;border-radius:8px;padding:12px 14px}}
.fact .k{{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:#57606a}}
.fact .v{{font-size:21px;font-weight:600;margin-top:2px}}
.seal{{border-radius:8px;padding:14px 16px;margin:18px 0;border:1px solid}}
.seal.good{{background:#e8f5ec;border-color:#4ac26b;color:#0d4429}}
.seal.bad{{background:#ffebe9;border-color:#ff8182;color:#82071e}}
.seal ul{{margin:8px 0 0 18px;padding:0}}
table{{width:100%;border-collapse:collapse;margin:6px 0 4px;font-size:13.5px}}
th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#57606a;border-bottom:1px solid #d8dee4;padding:6px 8px}}
td{{padding:7px 8px;border-bottom:1px solid #eaeef2;vertical-align:top}}
.ref{{white-space:nowrap;color:#57606a;font:12.5px ui-monospace,Menlo,monospace}}
.req{{color:#57606a;font-size:12.5px;margin-top:2px}}
.yes{{color:#1a7f37;font-weight:600;white-space:nowrap}}
.chip{{display:inline-block;background:#eaeef2;border-radius:20px;padding:2px 9px;font-size:11.5px;margin:0 5px 4px 0;font-family:ui-monospace,Menlo,monospace}}
.eval{{border:1px solid #d8dee4;border-radius:10px;padding:18px 20px;margin:16px 0;break-inside:avoid}}
.ehead{{display:flex;justify-content:space-between;align-items:baseline;gap:12px}}
.rate{{font-size:24px;font-weight:700}} .rate small{{font-size:12px;font-weight:400;color:#57606a}}
.good{{color:#1a7f37}} .warn{{color:#9a6700}} .bad{{color:#cf222e}}
.meta{{margin:8px 0 4px}} .dim{{color:#57606a;font-size:12.5px}}
.chart{{margin:10px 0 4px}}
.cases td:first-child{{font-weight:600;font-size:11.5px}}
tr.p td:first-child{{color:#1a7f37}} tr.f td:first-child{{color:#cf222e}}
.none{{color:#57606a;padding:14px 0}}
footer{{margin-top:40px;padding-top:16px;border-top:1px solid #d8dee4;color:#57606a;font-size:12.5px}}
@media print{{body{{padding:0}} .eval{{break-inside:avoid}}}}
</style></head><body><div class="wrap">
<h1>AI assurance evidence</h1>
<div class="sub"><b>{system}</b> · generated {generated}</div>
{banner}
<div class="facts">
  <div class="fact"><div class="k">pass rate</div><div class="v {rate_cls}">{rate}</div></div>
  <div class="fact"><div class="k">evals</div><div class="v">{n_evals}</div></div>
  <div class="fact"><div class="k">runs recorded</div><div class="v">{n_runs}</div></div>
  <div class="fact"><div class="k">cases</div><div class="v">{n_cases}</div></div>
</div>
<table><tbody>
<tr><td style="width:180px"><b>Evidence period</b></td><td>{period}</td></tr>
<tr><td><b>Accountable owner</b></td><td>{owners}</td></tr>
<tr><td><b>Chain fingerprint</b></td><td><code>{fingerprint}</code></td></tr>
</tbody></table>
<h3>Control coverage</h3>
{coverage}
<h3>Evidence by eval</h3>
{sections}
<footer>Generated by Assay from the local <code>.assay/</code> record. Every figure
above is derived from run files whose digests are recorded in a hash-chained
ledger; re-run <code>assay verify</code> against this repository to confirm the
record is intact. Control mappings indicate which requirements an eval produces
evidence for; they are not a compliance determination.</footer>
</div></body></html>"""


def write(ev: Evidence, path: str) -> str:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    body = json.dumps(to_json(ev), indent=2) if path.endswith(".json") else render(ev)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path
