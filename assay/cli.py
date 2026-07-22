"""Command line.

    assay init                    scaffold real evals + a gate config
    assay run evals/ --gate       run, record, diff, and enforce the bar
    assay verify                  prove the recorded history is intact
    assay audit -o evidence.html  produce the document you hand someone
    assay compare / history / serve / controls

`run` discovers every ``Eval`` object defined in the given Python file(s), runs
each, appends the result to the tamper-evident ledger, and prints a report — plus
a diff against the previous run so regressions surface without being asked for.
Exit codes are the contract with CI: 0 ship it, 1 something failed or regressed,
2 could not run, 3 the gate said no, 4 the record does not verify.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys

from . import audit as _audit
from . import controls as _controls
from . import ledger as _ledger
from . import packs as _packs
from . import policy as _policy
from . import report, store
from .compare import diff
from .core import Eval

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_GATE, EXIT_TAMPER = 0, 1, 2, 3, 4


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


def cmd_init(args) -> int:
    written = _packs.init(args.dir, packs=args.pack, ci=args.ci, force=args.force)
    if not written:
        print("nothing written — files already exist (use --force to overwrite)")
        return EXIT_OK
    print("\n  created:")
    for w in written:
        print(f"    {w}")
    print("\n  next:")
    print("    assay run evals/ --gate      run them (green out of the box)")
    print("    then replace the placeholder tasks with calls to your agent.\n")
    return EXIT_OK


def cmd_run(args) -> int:
    evals = [ev for f in _iter_files(args.paths) for ev in _load_evals(f)]
    if not evals:
        print("no Eval objects found", file=sys.stderr)
        return EXIT_USAGE

    gate = _policy.Gate.load(args.config) if args.gate else None
    worst = EXIT_OK
    violations = []

    for ev in evals:
        unknown = _controls.unknown(ev.controls)
        if unknown:
            print(f"  note: {ev.name} declares unknown control(s): "
                  f"{', '.join(unknown)}", file=sys.stderr)

        prior = store.history(ev.name)
        prev = prior[-1] if prior else None      # newest existing run = baseline
        run = ev.run()
        store.save(run)
        print(report.render_run(run, verbose=args.verbose))

        d = None
        if prev is not None:
            d = diff(prev, run.to_dict())
            if d.regressions or d.score_drops or args.verbose:
                print(report.render_diff(d))
            if d.regressions:
                worst = max(worst, EXIT_FAIL)
        if run.pass_rate < 1.0:
            worst = max(worst, EXIT_FAIL)

        if gate is not None:
            violations += _policy.check_run(run.to_dict(), gate, diff=d, previous=prev)

    if gate is not None:
        print(report.render_violations(violations))
        if violations:
            return EXIT_GATE
    return worst


def cmd_verify(args) -> int:
    v = _ledger.verify(args.root, check_files=not args.quick)
    print(report.render_verification(v))
    return EXIT_OK if v.ok else EXIT_TAMPER


def cmd_audit(args) -> int:
    import datetime as _dt
    ev = _audit.collect(args.root, system=args.system,
                        now=_dt.datetime.now().isoformat(timespec="seconds"))
    if not ev.evals:
        print("no runs found — run some evals first", file=sys.stderr)
        return EXIT_USAGE
    path = _audit.write(ev, args.out)

    v = ev.verification
    status = "verified" if (v and v.ok) else "NOT VERIFIED"
    print(f"\n  {report.bold('evidence pack')}  {path}")
    print(f"    system        {ev.system or '(unnamed)'}")
    print(f"    period        {ev.period[0]} .. {ev.period[1]}")
    print(f"    evals/runs    {len(ev.evals)} / {ev.total_runs}")
    print(f"    pass rate     {ev.pass_rate*100:.0f}%  ({ev.total_cases} cases)")
    print(f"    controls      {len(ev.coverage)} covered")
    print(f"    integrity     {status}"
          + (f"  ({v.fingerprint})" if v and v.ok else ""))
    print()
    return EXIT_OK if (v and v.ok) else EXIT_TAMPER


def cmd_controls(args) -> int:
    """The catalogue, so you can find the id to tag an eval with."""
    for fw, cs in sorted(_controls.frameworks().items()):
        print(f"\n  {report.bold(fw)}")
        for c in cs:
            print(f"    {c.id:<24} {c.ref:<12} {c.title}")
    print("\n  packs: " + ", ".join(_controls.PACKS) + "\n")
    return EXIT_OK


def cmd_compare(args) -> int:
    prev, latest = store.latest_two(args.eval)
    if latest is None:
        print(f"no runs for '{args.eval}'", file=sys.stderr)
        return EXIT_USAGE
    if prev is None:
        print(f"only one run for '{args.eval}' — nothing to compare yet")
        return EXIT_OK
    d = diff(prev, latest)
    print(report.render_diff(d))
    return EXIT_FAIL if d.regressed else EXIT_OK


def cmd_serve(args) -> int:
    from . import server
    server.serve(port=args.port)
    return EXIT_OK


def cmd_history(args) -> int:
    runs = store.history(args.eval)
    if not runs:
        print(f"no runs for '{args.eval}'", file=sys.stderr)
        return EXIT_USAGE
    for r in runs:
        bar = report._bar(r["pass_rate"], 16)
        print(f"  {r['started_at'][:19]}  {bar}  {r['pass_rate']*100:5.0f}%  "
              f"{r['passed']}/{r['n']}")
    return EXIT_OK


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="assay",
        description="Verifiable evals for AI systems — test it, gate on it, prove it.")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="scaffold runnable evals and a gate config")
    i.add_argument("dir", nargs="?", default=".")
    i.add_argument("--pack", action="append", choices=list(_packs.FILES),
                   help="starter pack to write; repeatable (default: all)")
    i.add_argument("--ci", action="store_true",
                   help="also write a GitHub Actions workflow")
    i.add_argument("--force", action="store_true", help="overwrite existing files")
    i.set_defaults(fn=cmd_init)

    r = sub.add_parser("run", help="run eval file(s), record them, diff, and gate")
    r.add_argument("paths", nargs="+", help="python files or directories of evals")
    r.add_argument("-v", "--verbose", action="store_true")
    r.add_argument("--gate", action="store_true",
                   help="enforce assay.toml; exit 3 if the bar is not met")
    r.add_argument("--config", help="path to assay.toml (default: nearest one)")
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("verify", help="check the recorded history has not been altered")
    v.add_argument("--root", default=store.ROOT)
    v.add_argument("--quick", action="store_true",
                   help="chain only; skip re-hashing every run file")
    v.set_defaults(fn=cmd_verify)

    a = sub.add_parser("audit", help="generate an evidence pack from the record")
    a.add_argument("-o", "--out", default="evidence.html",
                   help="output path; use .json for machine-readable")
    a.add_argument("--system", default="", help="name of the system under test")
    a.add_argument("--root", default=store.ROOT)
    a.set_defaults(fn=cmd_audit)

    ctl = sub.add_parser("controls", help="list the control catalogue")
    ctl.set_defaults(fn=cmd_controls)

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
    if args.cmd == "init" and not args.pack:
        args.pack = tuple(_packs.FILES)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
