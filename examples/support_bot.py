"""A runnable example: evaluating a support-ticket router.

`agent` stands in for whatever your real agent is (an LLM call, a chain, a whole
pipeline) — Assay does not care, it only needs a function from input to output.
Run it with:  assay run examples/support_bot.py
"""
from assay import Eval, scorers as S


def agent(inp: dict) -> str:
    """Route a support message to a team. (A real one would call a model.)"""
    text = inp["message"].lower()
    if "refund" in text or "charge" in text or "money back" in text:
        return "billing"
    if "password" in text or "log in" in text or "sign in" in text:
        return "account"
    if "crash" in text or "error" in text or "broken" in text:
        return "bug"
    return "general"


router = Eval(
    "support-router",
    task=agent,
    cases=[
        {"input": {"message": "I want a refund for last month"}, "expect": "billing"},
        {"input": {"message": "I can't log in anymore"}, "expect": "account"},
        {"input": {"message": "the app keeps crashing on startup"}, "expect": "bug"},
        {"input": {"message": "what are your opening hours?"}, "expect": "general"},
        {"input": {"message": "you charged me twice"}, "expect": "billing"},
    ],
    scorers=[S.exact_match],
)
