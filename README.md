# Assay

**Unit tests for AI agents.** Know whether your agent actually works — and get told the moment a prompt tweak or model swap silently breaks it.

You have tests for your code. You have nothing for the part of your product that decides what to say and do: the model. So you change a prompt, ship it, and find out three days later from an angry user that it started leaking system instructions on 8% of inputs. Assay is the missing test suite for that layer — dead simple, zero dependencies, and it treats a silent quality regression like a failing test.

```bash
pip install assay-evals
```

## The whole idea in 20 seconds

An *eval* is a task (your agent — any function from input to output), a list of cases, and the scorers that judge the output.

```python
# evals/support.py
from assay import Eval, scorers as S

def agent(inp):                       # your real agent: an LLM call, a chain, anything
    return route_ticket(inp["message"])

support = Eval("support-router", task=agent, scorers=[S.exact_match], cases=[
    {"input": {"message": "I want a refund"},      "expect": "billing"},
    {"input": {"message": "I can't log in"},       "expect": "account"},
    {"input": {"message": "the app keeps crashing"}, "expect": "bug"},
])
```

```bash
assay run evals/
```

```
support-router  2026-07-22T04:48
  PASS  case-1  312ms
  PASS  case-2  298ms
  PASS  case-3  341ms

  ████████████████████████  100%  3/3 passed
```

## The part that matters: it catches regressions

Every run is saved. The next run is automatically diffed against the last, so a change that breaks a case can't slip through — and `assay` exits non-zero, so your CI fails the build.

```
support-router   100% -> 80%  (-20 pts)

  1 regression — was passing, now failing:
    - case-2: expected 'account', got 'general'
```

That single feature is the difference between "I think the new prompt is better" and "I know it fixed 4 cases and broke 1."

## Scorers

Pass one or many; a case passes when all of them do.

| Scorer | Checks |
|---|---|
| `exact_match` | output equals `expect` |
| `contains(s)` / `not_contains(s)` | substring present / absent (great for banned words, PII, prompt leaks) |
| `regex(p)` | pattern matches |
| `is_json` / `json_has_keys(...)` | output is valid JSON with the right keys |
| `matches_schema(schema)` | output matches a nested type schema (fields, lists, types) |
| `similarity(threshold, embed=None)` | output is close enough — lexical, or semantic with your embedder |
| `length_between(lo, hi)` | output length is sane |
| `llm_judge(rubric, judge)` | a model grades open-ended output against a rubric |

`llm_judge` takes *your* model call, so Assay never ships an API dependency or touches a key:

```python
S.llm_judge("Is the reply polite and factually correct?", judge=my_llm)
```

Writing your own scorer is just a function `(output, case) -> Score`. There is nothing privileged about the built-ins.

## In CI

```yaml
- run: pip install assay-evals && assay run evals/
```

Green build = the model layer still does what it did yesterday. Red build = something changed, and the diff tells you exactly what.

## Dashboard

```bash
assay serve      # opens a local dashboard at http://127.0.0.1:8787
```

A dark, zero-dependency web UI over your `.assay/` history: pass rate over time,
a banner listing exactly what regressed, and a drill-down of every case (input,
output, expected, per-scorer reasons). It refreshes as new runs land, so you can
watch a prompt change land in real time. Nothing leaves your machine.

## Commands

```bash
assay run evals/              # run evals, save results, auto-diff vs last run
assay compare support-router  # diff the last two runs
assay history support-router  # pass rate over time
assay serve                   # web dashboard on localhost
```

## Why it's built this way

- **Zero dependencies.** Standard library only. It installs instantly and never fights your environment.
- **Model-agnostic.** A task is a plain function; a judge is a plain function. Assay has no opinion about OpenAI vs. Anthropic vs. your local model.
- **The filesystem is the database.** Runs are JSON files under `.assay/` — greppable, diffable, and commit-able. No service to run.

## Where this is going

The library is the wedge. The problem it points at — *is my AI reliable, and did my last change make it worse?* — doesn't stop at one developer's laptop. The roadmap is a hosted layer on top of the same open format: shared run history across a team, trend dashboards, alerting when production quality drifts, and eval datasets you can share. The CLI stays free and open forever; the collaboration lives in the cloud.

## License

MIT © 2026 Neil Gilani
