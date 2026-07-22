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
    def run(self, now: Optional[str] = None) -> Run:
        if self._task is None:
            raise ValueError(f"eval '{self.name}': no task registered")
        if not self.cases:
            raise ValueError(f"eval '{self.name}': no cases to run")
        if not self.scorers:
            raise ValueError(f"eval '{self.name}': no scorers registered")

        import datetime as _dt
        # microsecond precision so two runs in the same second get distinct,
        # correctly-sortable filenames; the report trims this to seconds.
        started = now or _dt.datetime.now().isoformat()
        results: list[CaseResult] = []

        for i, case in enumerate(self.cases):
            cid = case.id or f"case-{i + 1}"
            t0 = time.perf_counter()
            output, error = None, None
            try:
                output = self._task(case.input)
            except Exception:
                error = traceback.format_exc(limit=3).strip()
            latency = (time.perf_counter() - t0) * 1000

            if error is not None:
                results.append(CaseResult(cid, case.input, None, case.expect,
                                          False, 0.0, [], latency, error))
                continue

            scores = [s(output, case) for s in self.scorers]
            passed = all(s.passed for s in scores)
            mean = sum(s.score for s in scores) / len(scores)
            results.append(CaseResult(cid, case.input, output, case.expect,
                                      passed, mean, scores, latency))

        n = len(results)
        passed = sum(1 for r in results if r.passed)
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
        )


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
