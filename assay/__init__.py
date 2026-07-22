"""Assay — unit tests for AI agents.

Define an eval, run it, and know whether your agent actually works — and get told
the moment a prompt or model change breaks something.

    from assay import Eval, scorers

    ev = Eval("greeter")

    @ev.task
    def agent(inp):
        return my_agent(inp["name"])

    ev.add(input={"name": "Ada"}, expect="Hello, Ada!")
    ev.scorer(scorers.exact_match)

    run = ev.run()
"""
from . import controls, ledger, scorers
from .compare import Diff, diff
from .core import Case, CaseResult, Eval, Run, Score, Scorer
from .ledger import Verification, verify
from .policy import Gate, Violation, check_run

__version__ = "0.2.0"
__all__ = ["Eval", "Case", "CaseResult", "Run", "Score", "Scorer",
           "scorers", "diff", "Diff",
           "controls", "ledger", "verify", "Verification",
           "Gate", "Violation", "check_run"]
