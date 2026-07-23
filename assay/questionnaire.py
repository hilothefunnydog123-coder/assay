"""Questionnaire export — the coverage record, in the form a reviewer sends you.

The security questionnaire is the moment Assay is built for. A prospect's review
arrives with a spreadsheet: *for each of these controls, do you test it, and can
you show evidence?* Today the answer is assembled by hand from a Slack thread.
This turns the local record into that spreadsheet automatically — one row per
control, each answered from the verified ledger and pointing at the evals that
back it.

The answer for a control is not a checkbox someone ticked. It is derived:

* **Evidenced** — at least one eval covering it has a current passing run, *and*
  the hash chain verifies. Both halves are required. A passing eval whose record
  has been altered is not evidence, and the export says so rather than claiming
  a coverage the ledger no longer supports.
* **Partial** — covered by an eval, but the latest run is below the passing bar,
  or the record does not verify. There is a test; it is not currently green.
* **Not evidenced** — a control in the framework that no eval maps to. Showing
  the gaps is the point: a questionnaire that hides them is a liability, and a
  reviewer trusts a document that admits what it does not cover far more than
  one that claims everything.

Three formats, because different reviewers want different things: CSV to paste
into their tracker, Markdown to read, JSON for a GRC tool. All carry the same
scope note — a mapping says an eval *produces evidence relevant to* a control,
not that you are compliant with it. That determination is the auditor's; this
document exists so it has something real to stand on.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from . import controls as _controls

EVIDENCED, PARTIAL, NONE = "evidenced", "partial", "not evidenced"

_ANSWER = {
    EVIDENCED: "Yes — current passing test evidence, in a verified record.",
    PARTIAL: "Partial — a test exists but is not currently passing, or the "
             "record does not verify.",
    NONE: "No mapped test evidence yet.",
}

#: A control counts as evidenced only above this pass rate on its latest run.
#: Below it, there is a test but not a clean result, which is "partial".
PASS_BAR = 0.9


@dataclass
class Row:
    framework: str
    ref: str
    control_id: str
    title: str
    requirement: str
    status: str
    answer: str
    evals: list[str] = field(default_factory=list)
    pass_rate: float | None = None
    last_run: str = ""

    def as_dict(self) -> dict:
        return {"framework": self.framework, "ref": self.ref,
                "control_id": self.control_id, "title": self.title,
                "requirement": self.requirement, "status": self.status,
                "answer": self.answer, "evidence_from": self.evals,
                "pass_rate": self.pass_rate, "last_run": self.last_run}


@dataclass
class Questionnaire:
    system: str
    generated_at: str
    verified: bool
    fingerprint: str
    rows: list[Row]
    frameworks: list[str]
    scope_note: str = (
        "A mapping indicates that an eval produces evidence relevant to a "
        "control; it is not a compliance determination. Answers reflect the "
        "local, hash-chained Assay record and its verification status at the "
        "time of export. Re-run `assay verify` against the repository to confirm "
        "the record is intact.")

    @property
    def covered(self) -> int:
        return sum(1 for r in self.rows if r.status == EVIDENCED)

    def summary(self) -> dict:
        counts = {EVIDENCED: 0, PARTIAL: 0, NONE: 0}
        for r in self.rows:
            counts[r.status] += 1
        return counts

    def as_dict(self) -> dict:
        return {"system": self.system, "generated_at": self.generated_at,
                "record_verified": self.verified, "fingerprint": self.fingerprint,
                "frameworks": self.frameworks, "summary": self.summary(),
                "scope_note": self.scope_note,
                "controls": [r.as_dict() for r in self.rows]}


def build(evidence, *, frameworks: list[str] | None = None,
          include_uncovered: bool = True) -> Questionnaire:
    """Assemble a questionnaire from an :class:`assay.audit.Evidence` object.

    ``frameworks`` restricts the export to named frameworks; by default it
    covers every framework the mapped controls touch. ``include_uncovered``
    lists the framework's other controls as gaps — on by default, because the
    gaps are the honest part.
    """
    verified = bool(evidence.verification and evidence.verification.ok)
    fingerprint = evidence.verification.fingerprint if evidence.verification else ""

    # control id -> (best pass rate, last run, covering evals)
    latest: dict[str, dict] = {}
    for e in evidence.evals:
        pr = e["latest"].get("pass_rate", 0.0)
        when = e["latest"].get("started_at", "")
        for cid in e["controls"]:
            slot = latest.setdefault(cid, {"pass_rate": 0.0, "last_run": "",
                                           "evals": []})
            slot["evals"].append(e["name"])
            if pr >= slot["pass_rate"]:
                slot["pass_rate"] = pr
            if when > slot["last_run"]:
                slot["last_run"] = when

    # Decide which frameworks to render. If uncovered controls are wanted, we
    # enumerate the whole catalogue for each touched framework so gaps show.
    touched = {c.framework for cid in latest
               for c in [_controls.get(cid)] if c}
    custom = [cid for cid in latest if _controls.get(cid) is None]
    want_fw = frameworks if frameworks is not None else sorted(touched)

    rows: list[Row] = []
    seen: set[str] = set()

    catalogue = _controls.CATALOG
    for cid, ctl in catalogue.items():
        if ctl.framework not in want_fw:
            continue
        cov = latest.get(cid)
        if cov is None and not include_uncovered:
            continue
        rows.append(_row(ctl.framework, ctl.ref, cid, ctl.title, ctl.requirement,
                         cov, verified))
        seen.add(cid)

    # Custom (non-catalogue) controls an eval declared — always shown, because a
    # team that tagged one cares about it.
    for cid in custom:
        if cid in seen:
            continue
        cov = latest.get(cid)
        rows.append(_row("Custom", cid, cid, cid, "", cov, verified))

    rows.sort(key=lambda r: (r.framework, r.ref))
    fws = sorted({r.framework for r in rows})
    return Questionnaire(system=evidence.system, generated_at=evidence.generated_at,
                         verified=verified, fingerprint=fingerprint, rows=rows,
                         frameworks=fws)


def _row(framework, ref, cid, title, requirement, cov, verified) -> Row:
    if cov is None:
        status = NONE
        pass_rate = None
        evals: list[str] = []
        last_run = ""
    else:
        pass_rate = cov["pass_rate"]
        evals = sorted(set(cov["evals"]))
        last_run = cov["last_run"][:19]
        if verified and pass_rate >= PASS_BAR:
            status = EVIDENCED
        else:
            status = PARTIAL
    return Row(framework=framework, ref=ref, control_id=cid, title=title,
               requirement=requirement, status=status, answer=_ANSWER[status],
               evals=evals, pass_rate=pass_rate, last_run=last_run)


# --- rendering ------------------------------------------------------------ #
def to_csv(q: Questionnaire) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Framework", "Ref", "Control", "Requirement", "Status",
                "Answer", "Evidence (evals)", "Pass rate", "Last run",
                "Record verified", "Fingerprint"])
    for r in q.rows:
        w.writerow([r.framework, r.ref, r.title, r.requirement, r.status,
                    r.answer, "; ".join(r.evals),
                    f"{r.pass_rate*100:.0f}%" if r.pass_rate is not None else "",
                    r.last_run, "yes" if q.verified else "no", q.fingerprint])
    return buf.getvalue()


def to_markdown(q: Questionnaire) -> str:
    s = q.summary()
    seal = (f"Record **verified** (fingerprint `{q.fingerprint}`)." if q.verified
            else "Record **NOT verified** — this history has been altered since "
                 "it was written and the answers below should not be relied on.")
    lines = [
        f"# AI assurance questionnaire — {q.system or 'AI system'}",
        "",
        f"_Generated {q.generated_at} by Assay._  {seal}",
        "",
        f"**Coverage:** {s[EVIDENCED]} evidenced · {s[PARTIAL]} partial · "
        f"{s[NONE]} not evidenced, across {len(q.frameworks)} framework(s).",
        "",
    ]
    by_fw: dict[str, list[Row]] = {}
    for r in q.rows:
        by_fw.setdefault(r.framework, []).append(r)
    mark = {EVIDENCED: "✅", PARTIAL: "🟡", NONE: "⬜"}
    for fw in sorted(by_fw):
        lines += [f"## {fw}", "",
                  "| Ref | Control | Status | Answer | Evidence |",
                  "|---|---|---|---|---|"]
        for r in by_fw[fw]:
            ev = ", ".join(f"`{e}`" for e in r.evals) or "—"
            rate = f" ({r.pass_rate*100:.0f}%)" if r.pass_rate is not None else ""
            lines.append(f"| {r.ref} | {r.title} | {mark[r.status]} {r.status} | "
                         f"{r.answer}{rate} | {ev} |")
        lines.append("")
    lines += ["---", "", f"_{q.scope_note}_"]
    return "\n".join(lines)


def write(q: Questionnaire, path: str) -> str:
    import os
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    if path.endswith(".json"):
        body = json.dumps(q.as_dict(), indent=2)
    elif path.endswith(".csv"):
        body = to_csv(q)
    else:
        body = to_markdown(q)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    return path
