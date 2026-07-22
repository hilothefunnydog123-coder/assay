"""Tamper-evident run ledger.

Every eval run is appended to ``.assay/ledger.jsonl`` as one line: a summary of
the run, the SHA-256 of the full run file, and the hash of the record before it.
Each record's own hash covers all of that, so the file is a hash chain — editing
a score, back-dating a run, deleting an embarrassing one, or reordering history
all break the chain and are detected by :func:`verify`.

This is the difference between a dashboard and *evidence*. A dashboard shows you
a number; a ledger lets a third party confirm the number is the one that was
actually produced, on that date, against that eval definition. That is what a
security questionnaire, an auditor, or a regulator is actually asking for.

What it proves: the run records have not been altered or removed since they were
written, and each run file on disk still matches the digest recorded at the time.
What it does not prove on its own: that the run was honest at the moment of
writing. Nothing can prove that from inside the process — but the chain means
tampering has to happen *before* the fact, in the open, rather than quietly
afterwards. Adding :func:`attest` with a key held outside the repo (in CI) also
proves records were written by something holding that key.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

LEDGER = "ledger.jsonl"
GENESIS = "0" * 64
_ENV_KEY = "ASSAY_ATTEST_KEY"


# --- hashing -------------------------------------------------------------- #
def canonical(obj: Any) -> bytes:
    """Deterministic JSON encoding — sorted keys, no incidental whitespace.

    Two structurally equal objects must always produce identical bytes, or the
    chain would break on formatting alone.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str, ensure_ascii=True).encode("utf-8")


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def file_digest(path: str) -> Optional[str]:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --- reading / writing ---------------------------------------------------- #
def path_for(root: str) -> str:
    return os.path.join(root, LEDGER)


def entries(root: str) -> list[dict]:
    """Every ledger record, oldest first. Unparseable lines are surfaced as
    ``{"_corrupt": <raw>}`` rather than skipped — a line that will not parse is
    itself a finding, and silently dropping it would hide tampering."""
    p = path_for(root)
    if not os.path.isfile(p):
        return []
    out: list[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                out.append({"_corrupt": line[:200]})
    return out


def head(root: str) -> str:
    """Hash of the most recent record — the tip of the chain."""
    es = entries(root)
    for e in reversed(es):
        if "record_hash" in e:
            return e["record_hash"]
    return GENESIS


def _attest(record_hash: str, key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return hmac.new(key.encode("utf-8"), record_hash.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def append(run: dict, run_path: str, root: str, *,
           key: Optional[str] = None) -> dict:
    """Append one run to the chain and return the record written.

    ``key`` (or ``$ASSAY_ATTEST_KEY``) adds an HMAC over the record hash. Hold
    that key in CI rather than the repo and the record additionally proves it
    was written by the pipeline, not by a laptop.
    """
    key = key if key is not None else os.environ.get(_ENV_KEY)
    es = entries(root)
    rec = {
        "seq": len(es),
        "eval": run.get("eval", ""),
        "started_at": run.get("started_at", ""),
        "n": run.get("n", 0),
        "passed": run.get("passed", 0),
        "pass_rate": run.get("pass_rate", 0.0),
        "mean_score": run.get("mean_score", 0.0),
        "controls": sorted(run.get("controls", []) or []),
        "system": run.get("system") or "",
        "suite_hash": run.get("suite_hash", ""),
        "run_file": os.path.relpath(run_path, root).replace(os.sep, "/"),
        "run_hash": digest(run),
        "prev_hash": es[-1].get("record_hash", GENESIS) if es else GENESIS,
    }
    rec["record_hash"] = digest(rec)
    sig = _attest(rec["record_hash"], key)
    if sig:
        rec["attestation"] = sig

    os.makedirs(root, exist_ok=True)
    with open(path_for(root), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return rec


# --- verification --------------------------------------------------------- #
@dataclass
class Verification:
    ok: bool = True
    records: int = 0
    problems: list[str] = field(default_factory=list)
    head: str = GENESIS
    attested: int = 0
    checked_files: int = 0

    @property
    def fingerprint(self) -> str:
        """Short form of the chain tip — quotable in a report or a questionnaire."""
        return self.head[:16]


def verify(root: str, *, key: Optional[str] = None,
           check_files: bool = True) -> Verification:
    """Re-derive the whole chain and report anything that does not add up."""
    key = key if key is not None else os.environ.get(_ENV_KEY)
    es = entries(root)
    v = Verification(records=len(es))
    prev = GENESIS

    for i, rec in enumerate(es):
        if "_corrupt" in rec:
            v.problems.append(f"record {i}: unparseable line in ledger")
            v.ok = False
            continue

        stated = rec.get("record_hash")
        body = {k: val for k, val in rec.items()
                if k not in ("record_hash", "attestation")}
        if digest(body) != stated:
            v.problems.append(
                f"record {i} ({rec.get('eval','?')} @ {rec.get('started_at','?')[:19]}): "
                "contents were modified after it was written")
            v.ok = False

        if rec.get("prev_hash") != prev:
            # ASCII only: these strings reach Windows consoles and CI log
            # scrapers, where a stray em dash reads as a mojibake box.
            v.problems.append(
                f"record {i}: chain broken - expected prev {prev[:12]}..., "
                f"found {str(rec.get('prev_hash'))[:12]}... "
                "(a record was deleted, reordered, or inserted)")
            v.ok = False

        if rec.get("seq") != i:
            v.problems.append(f"record {i}: sequence number is {rec.get('seq')}")
            v.ok = False

        if check_files and rec.get("run_file"):
            rp = os.path.join(root, rec["run_file"])
            if not os.path.isfile(rp):
                v.problems.append(
                    f"record {i}: run file {rec['run_file']} is missing")
                v.ok = False
            else:
                v.checked_files += 1
                try:
                    with open(rp, "r", encoding="utf-8") as f:
                        on_disk = json.load(f)
                except Exception as exc:
                    v.problems.append(f"record {i}: run file unreadable ({exc})")
                    v.ok = False
                else:
                    if digest(on_disk) != rec.get("run_hash"):
                        v.problems.append(
                            f"record {i}: run file {rec['run_file']} no longer "
                            "matches the digest recorded when it was written")
                        v.ok = False

        if key and rec.get("attestation"):
            if not hmac.compare_digest(
                    rec["attestation"], _attest(stated or "", key) or ""):
                v.problems.append(f"record {i}: attestation does not match the key")
                v.ok = False
            else:
                v.attested += 1
        elif rec.get("attestation"):
            v.attested += 1

        prev = stated or prev

    v.head = prev
    return v
