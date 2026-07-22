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


def save(run: Run, root: str = ROOT) -> str:
    d = _eval_dir(run.eval, root)
    os.makedirs(d, exist_ok=True)
    stamp = run.started_at.replace(":", "-")
    path = os.path.join(d, f"{stamp}.json")
    with open(path, "w") as f:
        json.dump(run.to_dict(), f, indent=2, default=str)
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
