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


def test_similarity():
    from assay.core import Case
    c = Case(input=None, expect="the quick brown fox")
    assert S.similarity(0.9)("the quick brown fox", c).passed          # identical
    assert S.similarity(0.7)("the quick brown fax", c).passed          # close
    assert not S.similarity(0.9)("something else entirely", c).passed  # far
    # pluggable semantic mode via a fake embedder
    embed = {"cat": [1, 0], "kitten": [0.9, 0.1], "car": [0, 1]}
    c2 = Case(input=None, expect="cat")
    assert S.similarity(0.9, embed=lambda t: embed.get(t, [0, 0]))("kitten", c2).passed
    assert not S.similarity(0.9, embed=lambda t: embed.get(t, [0, 0]))("car", c2).passed
    print("ok  similarity (lexical + pluggable semantic)")


def test_matches_schema():
    from assay.core import Case
    c = Case(input=None)
    schema = {"intent": str, "confidence": "number", "tags": [str], "meta": {"lang": str}}
    good = {"intent": "billing", "confidence": 0.9, "tags": ["a", "b"], "meta": {"lang": "en"}}
    assert S.matches_schema(schema)(good, c).passed
    assert S.matches_schema(schema)(json.dumps(good), c).passed        # from JSON string
    assert not S.matches_schema(schema)({"intent": "x"}, c).passed     # missing fields
    bad_type = {"intent": "x", "confidence": "high", "tags": ["a"], "meta": {"lang": "en"}}
    r = S.matches_schema(schema)(bad_type, c)
    assert not r.passed and "confidence" in r.reason
    assert not S.matches_schema(schema)({"intent": 1, "confidence": 1, "tags": [1], "meta": {"lang": "en"}}, c).passed
    print("ok  matches_schema (nested, lists, types)")


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


# --- ledger: the evidence claim ------------------------------------------- #
def _seed(root, n=3, name="router"):
    """n saved runs of a trivial eval, so there is a chain to attack."""
    for i in range(n):
        ev = Eval(name, task=lambda x: x["k"], scorers=[S.exact_match],
                  controls=["nist:measure-2.5"], system="demo", owner="me@example.com")
        ev.add(input={"k": "a"}, expect="a", id="a")
        store.save(ev.run(now=f"2026-01-0{i+1}T00:00:00"), root=root)


def test_ledger_verifies_clean_history():
    from assay import ledger
    with tempfile.TemporaryDirectory() as root:
        _seed(root, 3)
        v = ledger.verify(root)
        assert v.ok and v.records == 3 and v.checked_files == 3
        assert len(v.fingerprint) == 16
        # Chain linkage is real, not decorative.
        es = ledger.entries(root)
        assert es[0]["prev_hash"] == ledger.GENESIS
        assert es[1]["prev_hash"] == es[0]["record_hash"]
    print("ok  ledger verifies an untouched history")


def test_ledger_catches_edited_run_file():
    from assay import ledger
    with tempfile.TemporaryDirectory() as root:
        _seed(root, 2)
        target = os.path.join(root, ledger.entries(root)[0]["run_file"])
        with open(target) as f:
            run = json.load(f)
        run["pass_rate"] = 0.0                      # rewrite history
        with open(target, "w") as f:
            json.dump(run, f, indent=2)
        v = ledger.verify(root)
        assert not v.ok and any("no longer matches" in p for p in v.problems)
    print("ok  ledger catches a doctored run file")


def test_ledger_catches_edited_and_deleted_records():
    from assay import ledger
    with tempfile.TemporaryDirectory() as root:
        _seed(root, 4)
        p = ledger.path_for(root)

        lines = open(p).read().splitlines()
        rec = json.loads(lines[1]); rec["n"] = 99            # inflate in place
        lines[1] = json.dumps(rec, sort_keys=True)
        open(p, "w").write("\n".join(lines) + "\n")
        v = ledger.verify(root)
        assert not v.ok and any("modified after it was written" in x for x in v.problems)

        lines = open(p).read().splitlines()
        del lines[1]                                          # delete a bad run
        open(p, "w").write("\n".join(lines) + "\n")
        v = ledger.verify(root)
        assert not v.ok and any("chain broken" in x for x in v.problems)
    print("ok  ledger catches in-place edits and deletions")


def test_attestation_requires_the_key():
    from assay import ledger
    with tempfile.TemporaryDirectory() as root:
        ev = Eval("router", task=lambda x: "a", scorers=[S.exact_match])
        ev.add(input={}, expect="a")
        run = ev.run(now="2026-01-01T00:00:00")
        path = store.save(run, root=root, ledger=False)
        ledger.append(json.load(open(path)), path, root, key="ci-key")

        assert ledger.verify(root, key="ci-key").ok
        bad = ledger.verify(root, key="wrong-key")
        assert not bad.ok and any("attestation" in p for p in bad.problems)
    print("ok  attestation binds records to the key that wrote them")


# --- suite identity: the anti-gaming property ----------------------------- #
def test_suite_hash_tracks_the_tests_not_the_results():
    a = Eval("x", task=lambda i: i, scorers=[S.exact_match])
    a.add(input="1", expect="1"); a.add(input="2", expect="2")
    b = Eval("x", task=lambda i: "always wrong", scorers=[S.exact_match])
    b.add(input="1", expect="1"); b.add(input="2", expect="2")
    assert a.suite_hash() == b.suite_hash(), "same tests, different results"

    c = Eval("x", task=lambda i: i, scorers=[S.exact_match])
    c.add(input="1", expect="1")                      # a case was dropped
    assert c.suite_hash() != a.suite_hash()

    d = Eval("x", task=lambda i: i, scorers=[S.similarity(0.9)])
    d.add(input="1", expect="1"); d.add(input="2", expect="2")
    e = Eval("x", task=lambda i: i, scorers=[S.similarity(0.2)])   # loosened
    e.add(input="1", expect="1"); e.add(input="2", expect="2")
    assert d.suite_hash() != e.suite_hash(), "scorer config must be part of identity"
    print("ok  suite hash tracks the tests, including scorer configuration")


# --- the gate -------------------------------------------------------------- #
def test_gate_rules():
    from assay import policy
    from assay.policy import Gate

    run = {"eval": "r", "pass_rate": 0.8, "n": 5, "controls": ["a"],
           "suite_hash": "h1", "results": [{"latency_ms": 10}]}
    assert policy.check_run(run, Gate(min_pass_rate=0.95))[0].rule == "min_pass_rate"
    assert not policy.check_run(run, Gate(min_pass_rate=0.75))

    class D:
        regressions = [{"case_id": "b"}]
        score_drops = []
    assert policy.check_run(run, Gate(), diff=D())[0].rule == "allow_regressions"

    assert policy.check_run(run, Gate(require_controls=["a", "z"]))[0].rule \
        == "require_controls"

    # A per-eval override must beat the global floor.
    g = Gate(min_pass_rate=0.5, per_eval={"r": {"min_pass_rate": 0.99}})
    assert policy.check_run(run, g)[0].rule == "min_pass_rate"
    print("ok  gate enforces floors, regressions, controls, and overrides")


def test_gate_catches_deleting_the_failing_case():
    """The cheapest way to make a red build green is to delete the test. That is
    the one move every other eval tool lets through silently."""
    from assay import policy
    before = {"eval": "r", "pass_rate": 0.8, "n": 5, "suite_hash": "h1"}
    after = {"eval": "r", "pass_rate": 1.0, "n": 4, "suite_hash": "h2",
             "results": [], "controls": []}
    vs = policy.check_run(after, policy.Gate(require_suite_stable=True),
                          previous=before)
    assert [v.rule for v in vs] == ["require_suite_stable"]

    # An honest suite change — cases added, rate unchanged — is not blocked.
    honest = {"eval": "r", "pass_rate": 0.8, "n": 7, "suite_hash": "h3",
              "results": [], "controls": []}
    assert not policy.check_run(honest, policy.Gate(require_suite_stable=True),
                                previous=before)
    print("ok  gate blocks a pass rate bought by deleting cases")


def test_gate_config_roundtrip():
    from assay.policy import Gate
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "assay.toml")
        with open(p, "w") as f:
            f.write('[gate]\nmin_pass_rate = 0.9\nallow_regressions = 2\n'
                    'require_controls = ["owasp-llm:llm01"]\n'
                    'require_suite_stable = true\n\n'
                    '[gate.evals."safety-x"]\nmin_pass_rate = 1.0\n')
        g = Gate.load(p)
        assert g.min_pass_rate == 0.9 and g.allow_regressions == 2
        assert g.require_controls == ["owasp-llm:llm01"] and g.require_suite_stable
        assert g.for_eval("safety-x").min_pass_rate == 1.0
        assert g.for_eval("other").min_pass_rate == 0.9
    print("ok  assay.toml parses, including per-eval overrides")


# --- controls + audit ------------------------------------------------------ #
def test_controls_and_coverage():
    from assay import controls
    assert controls.get("owasp-llm:llm01").framework == "OWASP LLM Top 10"
    assert controls.unknown(["owasp-llm:llm01", "made-up"]) == ["made-up"]
    cov = controls.coverage({"safety": ["owasp-llm:llm01"], "other": ["owasp-llm:llm01"]})
    assert sorted(cov["owasp-llm:llm01"]["evals"]) == ["other", "safety"]
    print("ok  control catalogue and coverage mapping")


def test_audit_pack():
    from assay import audit
    with tempfile.TemporaryDirectory() as root:
        _seed(root, 3)
        ev = audit.collect(root, now="2026-01-09T00:00:00")
        assert len(ev.evals) == 1 and ev.total_runs == 3
        assert ev.verification.ok and ev.pass_rate == 1.0
        assert "nist:measure-2.5" in ev.coverage

        blob = audit.to_json(ev)
        assert blob["integrity"]["verified"] and blob["summary"]["runs"] == 3

        html = audit.render(ev)
        assert "Record verified" in html and "MEASURE 2.5" in html
        assert "{" not in html.split("<style>")[0], "template placeholders unfilled"

        # A tampered record must be stated on the face of the document.
        with open(os.path.join(root, "ledger.jsonl"), "a") as f:
            f.write('{"seq": 99, "record_hash": "x", "prev_hash": "y"}\n')
        ev2 = audit.collect(root, now="2026-01-09T00:00:00")
        assert "Record NOT verified" in audit.render(ev2)
    print("ok  audit pack reports coverage, integrity, and tampering")


# --- scaffolding ----------------------------------------------------------- #
def test_init_scaffold_is_green_out_of_the_box():
    """`assay init` must produce evals that run and pass. A red first run would
    read as 'this tool is broken', not 'your agent is'."""
    from assay import packs
    from assay.cli import main
    with tempfile.TemporaryDirectory() as d:
        written = packs.init(d, ci=True)
        assert "assay.toml" in written and ".github/workflows/assay.yml" in written

        cwd = os.getcwd()
        try:
            os.chdir(d)
            assert main(["run", "evals/", "--gate"]) == 0
            assert main(["verify"]) == 0
            assert main(["audit", "-o", "e.html", "--system", "T"]) == 0
            assert os.path.getsize("e.html") > 2000
        finally:
            os.chdir(cwd)

        # Re-running init must never clobber someone's work.
        assert packs.init(d) == []
    print("ok  scaffold runs green, gates, verifies, and audits end to end")


# --- statistics: the pass rate is an estimate ----------------------------- #
def test_wilson_interval_is_honest_at_small_n():
    from assay import stats
    # Reference values (Wilson score interval, 95%, 19/20).
    i = stats.wilson_interval(19, 20)
    assert abs(i.low - 0.76387) < 1e-4 and abs(i.high - 0.99112) < 1e-4
    # The headline property: 3/3 is "100%" but the evidence is thin, and the
    # interval says so instead of implying certainty.
    tiny = stats.wilson_interval(3, 3)
    assert tiny.point == 1.0 and tiny.low < 0.5 and tiny.high == 1.0
    # Ten times the sample, same rate, a much tighter interval.
    assert stats.wilson_interval(190, 200).width < stats.wilson_interval(19, 20).width
    # Never escapes [0, 1] — the failure mode of the Wald interval it replaces.
    for passed, n in ((0, 1), (1, 1), (0, 30), (30, 30), (0, 0)):
        w = stats.wilson_interval(passed, n)
        assert 0.0 <= w.low <= w.high <= 1.0
    print("ok  Wilson interval: correct, bounded, and honest about small n")


def test_agreement_and_two_proportion():
    from assay import stats
    assert stats.agreement([True, True, True]).verdict          # unanimous pass
    assert not stats.agreement([True, True, True]).flaky
    mixed = stats.agreement([True, False, True, True])
    assert mixed.flaky and not mixed.verdict, "a flaky case must not pass"
    assert mixed.majority_verdict() and abs(mixed.consistency - 0.75) < 1e-9
    # A two-case swing on a 50-case suite is noise, and the p-value says so —
    # nowhere near significance, so a diff should not raise an alarm on it.
    assert stats.two_proportion_p(48, 50, 46, 50) > 0.05
    assert stats.two_proportion_p(48, 50, 47, 50) > 0.05
    # A collapse from 100% to 50% is not noise.
    assert stats.two_proportion_p(50, 50, 25, 50) < 0.001
    print("ok  agreement (flaky != passing) and two-proportion test")


def test_repeat_catches_a_flaky_case():
    """A single run cannot see nondeterminism: it records whichever outcome it
    happened to get. This is the property that motivates --repeat."""
    import itertools
    seq = itertools.count()

    def flip(inp):
        if inp["k"] != "flip":
            return inp["k"]
        return "a" if next(seq) % 2 == 0 else "WRONG"

    ev = Eval("flk", task=flip, scorers=[S.exact_match])
    ev.add(input={"k": "a"}, expect="a", id="stable")
    ev.add(input={"k": "flip"}, expect="a", id="flip")

    one = ev.run(now="2026-01-01T00:00:00", repeat=1)
    assert one.passed == 2 and one.flaky == 0, "one trial cannot see the flake"

    globals()["_"] = itertools.count()
    seq = itertools.count()
    many = ev.run(now="2026-01-02T00:00:00", repeat=5)
    assert many.flaky == 1 and many.passed == 1, "five trials must expose it"
    flaky = [r for r in many.results if r.case_id == "flip"][0]
    assert flaky.flaky and not flaky.passed and flaky.trials == 5
    assert 0 < flaky.trial_passes < 5 and flaky.consistency < 1.0
    # repeat=1 must leave the recorded shape exactly as it was before.
    stable = [r for r in one.results if r.case_id == "stable"][0]
    assert stable.trials == 1 and stable.consistency == 1.0 and not stable.flaky
    print("ok  --repeat exposes a flaky case a single run reports as passing")


def test_gate_flakiness_and_lower_bound():
    from assay import policy
    from assay.policy import Gate
    run = {"eval": "r", "pass_rate": 1.0, "n": 3, "passed": 3, "flaky": 2,
           "pass_rate_ci": [0.4385, 1.0], "controls": [], "results": []}
    assert policy.check_run(run, Gate(max_flaky=0))[0].rule == "max_flaky"
    assert not policy.check_run(run, Gate(max_flaky=2))
    assert not policy.check_run(run, Gate()), "max_flaky is unenforced by default"
    # 3/3 is 100% but its lower bound is 44%, so a real floor rejects it.
    assert policy.check_run(run, Gate(min_lower_bound=0.8))[0].rule == "min_lower_bound"
    assert not policy.check_run(run, Gate(min_lower_bound=0.4))
    print("ok  gate enforces flakiness and the statistical lower bound")


# --- safety scorers -------------------------------------------------------- #
def test_pii_scorer():
    from assay.core import Case
    c = Case(input=None)
    assert not S.no_pii()("his ssn is 123-45-6789", c).passed
    assert S.no_pii()("nothing sensitive here", c).passed
    # A Luhn-valid card is a leak; a 16-digit order number is not.
    assert not S.no_pii()("card 4242 4242 4242 4242", c).passed
    assert S.no_pii()("order 1234567890123456", c).passed
    # Email is off by default (support replies mention them legitimately).
    assert S.no_pii()("we emailed a@b.com", c).passed
    assert not S.no_pii(["email"])("we emailed a@b.com", c).passed
    assert "ssn" in S.no_pii()("ssn 123-45-6789", c).reason
    print("ok  no_pii: shapes, Luhn validation, opt-in kinds")


def test_refusal_scorers():
    from assay.core import Case
    c = Case(input=None)
    assert S.is_refusal("I can't share my configuration.", c).passed
    assert not S.is_refusal("Sure — here is the key.", c).passed
    # Abstention is a refusal for eval purposes; this phrasing is what RAG
    # systems actually emit and leaving it out marked correct behaviour failing.
    assert S.is_refusal("I don't have enough information to answer that.", c).passed
    assert S.is_refusal("That is not covered in the provided sources.", c).passed
    # The over-refusal check: a model that declines legitimate work.
    assert S.not_refusal("Your balance is $12.", c).passed
    assert not S.not_refusal("I cannot help with that.", c).passed
    print("ok  is_refusal / not_refusal, including abstention phrasings")


# --- RAG scorers ----------------------------------------------------------- #
def test_rag_grounding_scorers():
    from assay.core import Case
    ctx = "Our refund policy allows returns within 30 days of purchase."
    c = Case(input=None, meta={"context": ctx})

    assert S.grounded(threshold=0.5)("Returns are allowed within 30 days.", c).passed
    bad = S.grounded(threshold=0.5)("Bananas orbit Jupiter on Tuesdays.", c)
    assert not bad.passed and "supported by the context" in bad.reason
    # An abstention claims nothing, so there is nothing to ground — it must not
    # be scored as the least grounded output the system can produce.
    assert S.grounded(threshold=0.5)("I don't have enough information.", c).passed
    # Missing context is a setup error and must be loud, not silently passing.
    assert not S.grounded()("anything", Case(input=None)).passed

    # Fabricated figures are the consequential RAG failure.
    assert S.no_unsupported_numbers()("You have 30 days.", c).passed
    n = S.no_unsupported_numbers()("You have 90 days.", c)
    assert not n.passed and "90" in n.reason
    # Citation markers are not fabricated numbers.
    assert S.no_unsupported_numbers()("You have 30 days [1].", c).passed
    # Thousands separators normalise.
    big = Case(input=None, meta={"context": "The total was 1200 units."})
    assert S.no_unsupported_numbers()("The total was 1,200 units.", big).passed

    assert S.cites()("Refunds take 30 days [1].", c).passed
    assert not S.cites()("Refunds take 30 days.", c).passed
    assert not S.cites(min_count=2)("One source [1].", c).passed
    # Context can also arrive on the input dict, not only meta.
    inp = Case(input={"question": "q", "context": ctx})
    assert S.grounded(threshold=0.5)("Returns within 30 days.", inp).passed
    print("ok  grounded / no_unsupported_numbers / cites")


def test_rag_pack_is_green_out_of_the_box():
    """Every shipped pack must pass on a fresh init. A red first run reads as
    'this tool is broken', not 'your system is'."""
    from assay import packs
    from assay.cli import main
    with tempfile.TemporaryDirectory() as d:
        written = packs.init(d, packs=("rag",))
        assert "evals/rag.py" in written
        cwd = os.getcwd()
        try:
            os.chdir(d)
            assert main(["run", "evals/", "--gate"]) == 0
        finally:
            os.chdir(cwd)
    # RAG is opt-in, so a default init must not write it.
    with tempfile.TemporaryDirectory() as d:
        assert "evals/rag.py" not in packs.init(d)
    print("ok  RAG pack runs green and is opt-in")


# --- questionnaire export --------------------------------------------------- #
def test_questionnaire_export():
    from assay import audit, questionnaire
    with tempfile.TemporaryDirectory() as root:
        _seed(root, 2)                       # tagged nist:measure-2.5, passing
        ev = audit.collect(root, system="Demo", now="2026-01-09T00:00:00")
        q = questionnaire.build(ev)

        by_id = {r.control_id: r for r in q.rows}
        assert by_id["nist:measure-2.5"].status == questionnaire.EVIDENCED
        assert by_id["nist:measure-2.5"].evals == ["router"]
        # Gaps are shown rather than hidden — the honest half of the document.
        assert by_id["nist:measure-2.11"].status == questionnaire.NONE
        assert q.summary()[questionnaire.EVIDENCED] == 1
        assert q.verified

        # Restricting to a framework, and suppressing gaps, both work.
        only = questionnaire.build(ev, frameworks=["NIST AI RMF 1.0"])
        assert {r.framework for r in only.rows} == {"NIST AI RMF 1.0"}
        covered = questionnaire.build(ev, include_uncovered=False)
        assert all(r.status != questionnaire.NONE for r in covered.rows)

        # All three renderings carry the substance.
        md = questionnaire.to_markdown(q)
        assert "MEASURE 2.5" in md and "Record **verified**" in md
        csv_text = questionnaire.to_csv(q)
        assert "MEASURE 2.5" in csv_text and csv_text.count("\n") > 5
        blob = json.loads(json.dumps(q.as_dict()))
        assert blob["record_verified"] and blob["summary"]["evidenced"] == 1

        # A broken chain must downgrade the answer, not keep claiming coverage.
        with open(os.path.join(root, "ledger.jsonl"), "a") as f:
            f.write('{"seq": 99, "record_hash": "x", "prev_hash": "y"}\n')
        ev2 = audit.collect(root, system="Demo", now="2026-01-09T00:00:00")
        q2 = questionnaire.build(ev2)
        assert not q2.verified
        assert {r.control_id: r for r in q2.rows}["nist:measure-2.5"].status \
            == questionnaire.PARTIAL
        assert "NOT verified" in questionnaire.to_markdown(q2)
    print("ok  questionnaire export: coverage, gaps, formats, integrity")


def test_questionnaire_cli_end_to_end():
    from assay.cli import main
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        try:
            os.chdir(d)
            from assay import packs
            packs.init(d)
            assert main(["run", "evals/"]) == 0
            for name in ("q.csv", "q.md", "q.json"):
                assert main(["questionnaire", "-o", name, "--system", "T"]) == 0
                assert os.path.getsize(name) > 200
        finally:
            os.chdir(cwd)
    print("ok  assay questionnaire writes csv, md, and json")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nall tests passed")
