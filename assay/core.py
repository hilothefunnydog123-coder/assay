"""Core data model and run engine.

An *eval* pairs a task (your agent — any function from input to output) with a
list of cases and one or more scorers. Running it feeds every case through the
task, scores the output, and returns a Run: a timestamped, comparable record of
how the agent did. Everything is a plain dataclass so runs serialise to JSON and
can be diffed across time.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

# A scorer takes (output, case) and returns a Score.
Scorer = Callable[[Any, "Case"], "Score"]


@dataclass
class Case:
    input: Any
    expect: Any = None
    id: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass
class Score:
    name: str
    passed: bool
    score: float = 0.0          # 0..1, for graded (non-binary) scorers
    reason: str = ""


@dataclass
class CaseResult:
    case_id: str
    input: Any
    output: Any
    expect: Any
    passed: bool
    score: float
    scores: list[Score]
    latency_ms: float
    error: Optional[str] = None
    # --- repeated-trial fields (only meaningful when the case ran >1 time) --- #
    # A model is not a function: the same case at temperature can pass once and
    # fail once. When ``repeat > 1`` these record how the trials landed, and
    # ``passed`` above holds the strict verdict — every trial had to pass.
    trials: int = 1
    trial_passes: int = 1
    flaky: bool = False
    consistency: float = 1.0


@dataclass
class Run:
    eval: str
    started_at: str
    results: list[CaseResult]
    n: int
    passed: int
    pass_rate: float
    mean_score: float
    total_ms: float
    # --- evidence metadata ------------------------------------------------ #
    controls: list[str] = field(default_factory=list)
    system: str = ""
    owner: str = ""
    # Digest of the eval *definition* (cases + scorers), not its results. Lets a
    # reader tell "the system changed" from "the test changed" — a pass rate
    # that rose because cases were deleted is the failure mode every eval tool
    # has and none of them surface.
    suite_hash: str = ""
    # --- statistical honesty --------------------------------------------- #
    # A pass rate is an estimate from a sample, not a measurement. These carry
    # the Wilson 95% interval around it, how many cases ran, how many trials
    # each, and how many came out flaky. See assay.stats.
    repeat: int = 1
    flaky: int = 0
    pass_rate_ci: tuple = (0.0, 0.0)

    def to_dict(self) -> dict:
        return asdict(self)


class Eval:
    """A named suite: a task, its cases, and the scorers applied to every case.

    Build it with the constructor or fluently::

        ev = Eval("classifier")
        ev.task(my_agent)                      # or @ev.task
        ev.add(input=..., expect=...)
        ev.scorer(scorers.exact_match)
    """

    def __init__(self, name: str, task: Optional[Callable] = None,
                 cases: Optional[list] = None, scorers: Optional[list[Scorer]] = None,
                 controls: Optional[list[str]] = None, system: str = "",
                 owner: str = "", description: str = ""):
        self.name = name
        self._task = task
        self.cases: list[Case] = []
        self.scorers: list[Scorer] = list(scorers or [])
        # Evidence metadata: which assurance controls this eval produces evidence
        # for, which system it covers, and who answers for it. See controls.py.
        self.controls: list[str] = list(controls or [])
        self.system = system
        self.owner = owner
        self.description = description
        for c in (cases or []):
            self.add(**c) if isinstance(c, dict) else self.cases.append(c)

    # --- fluent builders -------------------------------------------------- #
    def task(self, fn: Callable) -> Callable:
        """Register the task. Usable as a decorator; returns fn unchanged."""
        self._task = fn
        return fn

    def add(self, input: Any, expect: Any = None, id: Optional[str] = None, **meta):
        self.cases.append(Case(input=input, expect=expect, id=id, meta=meta))
        return self

    def scorer(self, *scorers: Scorer):
        self.scorers.extend(scorers)
        return self

    def control(self, *ids: str):
        """Declare the assurance controls this eval produces evidence for."""
        self.controls.extend(ids)
        return self

    # --- identity --------------------------------------------------------- #
    def suite_hash(self) -> str:
        """Digest of what this eval *tests* — case inputs, expectations, and the
        scorers applied. Independent of the results, so two runs of an unchanged
        suite share a hash and a weakened suite announces itself."""
        from .ledger import digest
        return digest({
            "name": self.name,
            "cases": [{"id": c.id, "input": c.input, "expect": c.expect}
                      for c in self.cases],
            "scorers": [_scorer_name(s) for s in self.scorers],
        })

    # --- execution -------------------------------------------------------- #
    def run(self, now: Optional[str] = None, *, repeat: int = 1) -> Run:
        """Run every case and score it.

        ``repeat`` runs each case that many times, which is how you catch a
        nondeterministic system: a case that passes on some trials and fails on
        others is *flaky*, and a flaky check is treated as failing (it must pass
        every trial to count), because a check that only sometimes holds is not
        one you can gate a release behind. With ``repeat=1`` — the default —
        behaviour and the recorded schema are unchanged.
        """
        if self._task is None:
            raise ValueError(f"eval '{self.name}': no task registered")
        if not self.cases:
            raise ValueError(f"eval '{self.name}': no cases to run")
        if not self.scorers:
            raise ValueError(f"eval '{self.name}': no scorers registered")
        repeat = max(1, int(repeat))

        import datetime as _dt
        from . import stats as _stats
        # microsecond precision so two runs in the same second get distinct,
        # correctly-sortable filenames; the report trims this to seconds.
        started = now or _dt.datetime.now().isoformat()
        results: list[CaseResult] = []

        for i, case in enumerate(self.cases):
            cid = case.id or f"case-{i + 1}"
            results.append(self._run_case(cid, case, repeat, _stats))

        n = len(results)
        passed = sum(1 for r in results if r.passed)
        flaky = sum(1 for r in results if r.flaky)
        ci = _stats.wilson_interval(passed, n) if n else _stats.wilson_interval(0, 0)
        return Run(
            eval=self.name,
            started_at=started,
            results=results,
            n=n,
            passed=passed,
            pass_rate=passed / n if n else 0.0,
            mean_score=sum(r.score for r in results) / n if n else 0.0,
            total_ms=sum(r.latency_ms for r in results),
            controls=list(self.controls),
            system=self.system,
            owner=self.owner,
            suite_hash=self.suite_hash(),
            repeat=repeat,
            flaky=flaky,
            pass_rate_ci=(round(ci.low, 4), round(ci.high, 4)),
        )

    def _run_case(self, cid: str, case: "Case", repeat: int, _stats) -> CaseResult:
        """One case, run ``repeat`` times, collapsed to a single strict verdict.

        The first trial's output, scores and latency are the ones recorded so
        the run file reads the same as a single-shot run; the extra trials feed
        the flakiness measurement and nothing else. Keeping the recorded shape
        stable matters: the ledger hashes it, and a reader should not have to
        special-case repeated runs to read the evidence.
        """
        trial_passes: list[bool] = []
        first: Optional[CaseResult] = None
        for _ in range(repeat):
            t0 = time.perf_counter()
            output, error = None, None
            try:
                output = self._task(case.input)
            except Exception:
                error = traceback.format_exc(limit=3).strip()
            latency = (time.perf_counter() - t0) * 1000

            if error is not None:
                scores, passed, mean = [], False, 0.0
                res = CaseResult(cid, case.input, None, case.expect,
                                 False, 0.0, [], latency, error)
            else:
                scores = [s(output, case) for s in self.scorers]
                passed = all(s.passed for s in scores)
                mean = sum(s.score for s in scores) / len(scores) if scores else 0.0
                res = CaseResult(cid, case.input, output, case.expect,
                                 passed, mean, scores, latency)
            trial_passes.append(passed)
            if first is None:
                first = res

        ag = _stats.agreement(trial_passes)
        first.trials = ag.trials
        first.trial_passes = ag.passes
        first.flaky = ag.flaky
        first.consistency = round(ag.consistency, 4)
        # Strict verdict: pass only if every trial passed. A flaky case, having
        # failed at least one trial, therefore does not pass — which is the
        # whole point of running it more than once.
        first.passed = ag.verdict
        return first


def _scorer_name(s: Scorer) -> str:
    """A stable identity for a scorer, including its configuration.

    Built-ins that are factories (``contains("refund")``) return a closure named
    ``scorer``; the useful name is the factory's, and the useful configuration is
    in the closure cells. Capturing both means loosening a threshold changes the
    suite hash instead of slipping through as "same tests, better score".
    """
    base = (getattr(s, "__qualname__", None) or getattr(s, "__name__", None)
            or type(s).__name__)
    base = base.replace(".<locals>.scorer", "")
    cfg = []
    for cell in (getattr(s, "__closure__", None) or ()):
        try:
            value = cell.cell_contents
        except ValueError:      # cell not yet filled (recursive closure)
            continue
        if callable(value):     # a judge or embedder — identity, not config
            continue
        cfg.append(repr(value))
    return f"{base}({', '.join(cfg)})" if cfg else base
