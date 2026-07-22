"""Run persistence.

Every run is written to ``.assay/runs/<eval>/<timestamp>.json`` so the history
of an eval is just a folder of files — greppable, diffable, commit-able. No
database, no service; the store is the filesystem.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .core import Run

ROOT = ".assay"


def _eval_dir(name: str, root: str = ROOT) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return os.path.join(root, "runs", safe)


def save(run: Run, root: str = ROOT, *, ledger: bool = True) -> str:
    """Write the run file and append it to the tamper-evident ledger.

    Order matters: the file lands first, then the ledger records its digest. A
    crash between the two leaves an unrecorded run (visible, harmless) rather
    than a ledger entry pointing at nothing (a verification failure).
    """
    d = _eval_dir(run.eval, root)
    os.makedirs(d, exist_ok=True)
    stamp = run.started_at.replace(":", "-")
    path = os.path.join(d, f"{stamp}.json")
    payload = run.to_dict()
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    if ledger:
        from . import ledger as _ledger
        # The digest must cover exactly the bytes a verifier will re-read, so
        # round-trip through JSON rather than hashing the in-memory objects.
        with open(path, "r", encoding="utf-8") as f:
            _ledger.append(json.load(f), path, root)
    return path


def history(name: str, root: str = ROOT) -> list[dict]:
    """All runs of an eval, oldest first."""
    d = _eval_dir(name, root)
    if not os.path.isdir(d):
        return []
    runs = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            with open(os.path.join(d, fn)) as f:
                runs.append(json.load(f))
    return runs


def latest_two(name: str, root: str = ROOT) -> tuple[Optional[dict], Optional[dict]]:
    """Return (previous, latest) runs, either of which may be None."""
    runs = history(name, root)
    if not runs:
        return None, None
    if len(runs) == 1:
        return None, runs[-1]
    return runs[-2], runs[-1]
