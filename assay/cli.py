"""Command line: `assay run <path>`, `assay compare <eval>`, `assay history <eval>`.

`run` discovers every ``Eval`` object defined in the given Python file(s), runs
each, saves the result, and prints a report — plus a compare against the previous
run so regressions surface automatically. Exits non-zero if anything fails or
regresses, so it drops straight into CI.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys

from . import report, store
from .compare import diff
from .core import Eval


def _load_evals(path: str) -> list[Eval]:
    spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [v for v in vars(mod).values() if isinstance(v, Eval)]


def _iter_files(paths: list[str]):
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if f.endswith(".py") and not f.startswith("_"):
                        yield os.path.join(root, f)
        elif p.endswith(".py"):
            yield p


def cmd_run(args) -> int:
    evals = [ev for f in _iter_files(args.paths) for ev in _load_evals(f)]
    if not evals:
        print("no Eval objects found", file=sys.stderr)
        return 2
    worst = 0
    for ev in evals:
        prior = store.history(ev.name)
        prev = prior[-1] if prior else None      # newest existing run = the baseline
        run = ev.run()
        store.save(run)
        print(report.render_run(run, verbose=args.verbose))
        if run.pass_rate < 1.0:
            worst = max(worst, 1)
        if prev is not None:
            d = diff(prev, run.to_dict())
            if d.regressions or d.score_drops or args.verbose:
                print(report.render_diff(d))
            if d.regressions:
                worst = max(worst, 1)
    return worst


def cmd_compare(args) -> int:
    prev, latest = store.latest_two(args.eval)
    if latest is None:
        print(f"no runs for '{args.eval}'", file=sys.stderr)
        return 2
    if prev is None:
        print(f"only one run for '{args.eval}' — nothing to compare yet")
        return 0
    d = diff(prev, latest)
    print(report.render_diff(d))
    return 1 if d.regressed else 0


def cmd_serve(args) -> int:
    from . import server
    server.serve(port=args.port)
    return 0


def cmd_history(args) -> int:
    runs = store.history(args.eval)
    if not runs:
        print(f"no runs for '{args.eval}'", file=sys.stderr)
        return 2
    for r in runs:
        bar = report._bar(r["pass_rate"], 16)
        print(f"  {r['started_at'][:19]}  {bar}  {r['pass_rate']*100:5.0f}%  "
              f"{r['passed']}/{r['n']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="assay", description="Unit tests for AI agents.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run eval file(s) and save the results")
    r.add_argument("paths", nargs="+", help="python files or directories of evals")
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("compare", help="diff the last two runs of an eval")
    c.add_argument("eval")
    c.set_defaults(fn=cmd_compare)

    h = sub.add_parser("history", help="show pass rate over time for an eval")
    h.add_argument("eval")
    h.set_defaults(fn=cmd_history)

    s = sub.add_parser("serve", help="open the web dashboard on localhost")
    s.add_argument("-p", "--port", type=int, default=8787)
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
