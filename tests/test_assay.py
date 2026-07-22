"""Test suite for Assay. Run: python -m pytest -q   (or: python tests/test_assay.py)"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assay import Eval, scorers as S       # noqa: E402
from assay import store, compare           # noqa: E402


# --- scorers -------------------------------------------------------------- #
def test_exact_and_substring():
    from assay.core import Case
    c = Case(input=None, expect="billing")
    assert S.exact_match("billing", c).passed
    assert not S.exact_match("account", c).passed
    assert S.contains("bill")("the bill", c).passed
    assert not S.contains("bill")("invoice", c).passed
    assert S.not_contains("secret")("all good", c).passed
    assert not S.not_contains("secret")("the secret is out", c).passed
    assert S.regex(r"\d{3}")("id 123", c).passed
    print("ok  exact / contains / not_contains / regex")


def test_structure_scorers():
    from assay.core import Case
    c = Case(input=None)
    assert S.is_json('{"a": 1}', c).passed
    assert S.is_json({"a": 1}, c).passed
    assert not S.is_json("nope", c).passed
    assert S.json_has_keys("a", "b")({"a": 1, "b": 2}, c).passed
    assert not S.json_has_keys("a", "b")({"a": 1}, c).passed
    assert S.length_between(1, 5)("abc", c).passed
    assert not S.length_between(1, 2)("abcd", c).passed
    print("ok  is_json / json_has_keys / length_between")


def test_llm_judge_pluggable():
    from assay.core import Case
    # a fake judge that always scores 0.9 — proves the wiring without an API key
    judge = lambda prompt: '{"score": 0.9, "reason": "looks good"}'
    sc = S.llm_judge("is it polite?", judge)("hello there", Case(input="x"))
    assert sc.passed and sc.score == 0.9
    bad = lambda prompt: "not json"
    assert not S.llm_judge("x", bad)("out", Case(input="x")).passed
    print("ok  llm_judge (pluggable, key-free)")


# --- run engine ----------------------------------------------------------- #
def test_run_pass_fail_and_error():
    ev = Eval("t", task=lambda i: i["x"] * 2, scorers=[S.exact_match])
    ev.add(input={"x": 2}, expect=4)      # pass
    ev.add(input={"x": 3}, expect=99)     # fail
    run = ev.run(now="2026-01-01T00:00:00")
    assert run.n == 2 and run.passed == 1 and run.pass_rate == 0.5
    assert all(r.latency_ms >= 0 for r in run.results)

    boom = Eval("boom", task=lambda i: 1 / 0, scorers=[S.exact_match])
    boom.add(input={}, expect=1)
    r2 = boom.run()
    assert r2.passed == 0 and r2.results[0].error is not None
    print("ok  run: pass/fail counts, latency, error capture")


# --- store + regression detection ---------------------------------------- #
def test_store_and_regression():
    with tempfile.TemporaryDirectory() as d:
        root = os.path.join(d, ".assay")

        good = Eval("router", task=lambda i: i["k"], scorers=[S.exact_match])
        for k in ("a", "b", "c"):
            good.add(input={"k": k}, expect=k, id=k)
        r1 = good.run(now="2026-01-01T00:00:00")
        store.save(r1, root=root)

        # a broken version: case "b" now returns the wrong thing
        bad = Eval("router", task=lambda i: "WRONG" if i["k"] == "b" else i["k"],
                   scorers=[S.exact_match])
        for k in ("a", "b", "c"):
            bad.add(input={"k": k}, expect=k, id=k)
        r2 = bad.run(now="2026-01-02T00:00:00")
        store.save(r2, root=root)

        prev, latest = store.latest_two("router", root=root)
        d2 = compare.diff(prev, latest)
        assert d2.regressed
        assert [r["case_id"] for r in d2.regressions] == ["b"]
        assert d2.pass_rate_before == 1.0 and abs(d2.pass_rate_after - 2 / 3) < 1e-9
        assert len(store.history("router", root=root)) == 2
    print("ok  store + regression detection (catches the one broken case)")


def test_example_runs():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(here, "examples"))
    import support_bot
    run = support_bot.router.run()
    assert run.pass_rate == 1.0, "the shipped example should pass cleanly"
    print("ok  bundled example runs green")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nall tests passed")
