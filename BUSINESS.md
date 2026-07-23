# Assay: the commercial plan

Written to be argued with. If a section is wrong, the fix is to change it here first and the code second.

## 1. The honest starting position

Assay v0.1 was an eval framework called "unit tests for AI agents." That is the same sentence used by Braintrust, LangSmith, Langfuse, Promptfoo, DeepEval, Arize Phoenix, Ragas, and Inspect. Most are funded, all are more featured, several are free.

The v0.1 roadmap — *hosted dashboards, shared run history, trend charts* — was the most crowded and least defensible business in the category. It would have been a worse Braintrust, sold by one person, at a lower price. There is no version of that which is profitable.

The problem was never the code. It was that the code pointed at a job somebody else already does.

## 2. What is actually differentiated

One property of Assay is not shared by any well-funded competitor, and it was being described as a limitation:

> The filesystem is the database. No service to run.

Every serious competitor is a SaaS. To use them you send your prompts, your inputs, and your model's outputs to a third party. For a large and growing set of buyers — health, finance, legal, defence, public sector, anyone with a DPA that forbids sub-processing, anyone in an air-gapped environment — that is a procurement conversation, sometimes a blocker, always a delay.

Assay has nothing to send anywhere. Turn that from a footnote into the thesis.

## 3. The wedge: sell evidence, not dashboards

A dashboard cannot prove anything. It is mutable, it lives in a vendor's database, and it cannot demonstrate that the number on screen is the number that was produced.

Two things now happen to every team shipping an LLM feature, on a schedule they do not control:

1. **The security questionnaire.** A prospect's review asks how the AI system is tested and how you know the last change did not degrade it. Today the answer is a Slack thread. The deal waits.
2. **The framework.** EU AI Act Art. 9 and 15 (risk management; accuracy and robustness across the lifecycle), NIST AI RMF MEASURE, ISO/IEC 42001 §8.3 — all require *documented, repeated* testing with change control. Not a dashboard. A record.

Neither is discretionary, which is the whole point. Discretionary tools get cut; the thing blocking a deal or an audit gets bought.

So: **Assay produces cryptographically verifiable proof that an AI system was tested, what it scored, and what changed.** The eval framework is how you get people using it daily. The evidence is what gets paid for.

### The technical moat

Two properties that are hard to bolt onto a SaaS competitor:

- **The hash-chained ledger.** Every run links to the one before it. Edits, deletions, back-dating, and reordering are all detectable by anyone holding the repo — including the customer's auditor, without an account. A vendor-hosted dashboard cannot make this claim credibly, because the vendor can always rewrite its own database.
- **The suite hash.** The cheapest way to make a red eval green is to delete the failing case. Every other tool reports that as an improvement. Assay hashes the suite *definition* — cases, expectations, and scorer configuration — separately from the results, so `require_suite_stable` blocks a pass rate that was bought by weakening the tests. It is the single feature most likely to be described out loud as "wait, does ours not do that?"
- **Statistical honesty.** Everyone else reports a pass rate as if it were a measurement. It is an estimate from a small sample of a nondeterministic system, and both halves of that are wrong in the same direction — toward overconfidence. Assay reports a Wilson confidence interval on every run, gates on the lower bound rather than the point estimate, and with `--repeat N` catches cases that pass only some of the time and fails them. A competitor can add this; the reason none has is that it makes your numbers look worse, which is exactly why a buyer performing diligence on a vendor's AI trusts it.

The three compound into one sentence that no dashboard can say: *this system was tested, here is what it scored, here is how confident that score is, and here is proof nobody edited any of it afterwards.*

## 4. Who buys

**Primary ICP.** A 20–200 person software company that ships an LLM feature and sells to enterprise or into the EU. The buyer is the engineering lead or founding engineer who owns the security questionnaire. They already have a red build; what they lack is the artifact.

**Trigger events, in order of how well they convert:**
1. A deal is blocked on an AI security review.
2. An AI incident (a leak, a wrong answer at scale) and the postmortem asks why nothing caught it.
3. SOC 2 / ISO 42001 prep where the auditor asks about the model layer.
4. EU AI Act scoping work.

**Explicitly not the ICP.** Research labs (they build their own), hobbyists (free tier forever, gladly), and large AI-first companies (they have a platform team and will not buy from one person).

## 5. Free vs. paid

The line is **developer vs. company**, not features-with-holes-in-them. Anything a developer needs to do their job is free forever, or the adoption engine stops.

| Free (MIT, forever) | Commercial |
|---|---|
| Eval runner, all scorers, diff, dashboard | Organisation attestation keys + rotation |
| Hash-chained ledger, `assay verify` | Branded evidence packs, retention, shareable verification link |
| Control tagging and coverage | Multi-repo coverage across every AI system you ship |
| `assay audit` evidence pack | PR bot: the eval diff and control delta as a comment |
| The gate, `assay init`, CI workflow | Custom control mappings and framework packs |
| `assay questionnaire` export | Priority support, mapping review |
| Confidence intervals, flakiness detection | |

Note what is *not* on the paid side: no case limits, no run limits, no "free for 7 days of history." Metering the thing developers do hourly is how open-core tools lose the developers.

## 6. Pricing

| | Price | For |
|---|---|---|
| **Open source** | $0 | Everyone. Complete and unlimited. |
| **Team** | $299 / month per organisation | Attestation keys, branded packs, PR bot, up to 10 repos |
| **Compliance** | $1,200 / month | Multi-system coverage, questionnaire export, retention, mapping review |
| **Design partner** | $0 for 6 months | First 10, in exchange for a call every two weeks and a public reference |

Priced per organisation, not per seat. Per-seat pricing on a CI tool creates an incentive to not run it, which is the opposite of the point.

$299/mo is deliberately below the threshold that needs procurement at the ICP size — it clears on a card. The comparison in the buyer's head is not another eval tool; it is the week of engineering time the blocked security review is already costing.

## 7. Go to market

The library is the top of the funnel and it is the only channel that works for a solo developer. Nobody is buying compliance software from a stranger; they will install a zero-dependency Python package that fixes their Tuesday.

1. **Ship the wedge features into the free CLI.** Done: ledger, `verify`, suite hash, gate, controls, `audit`, `init`. Without these the pitch is a slide.
2. **One artifact that travels.** A written piece: *"Your eval suite went from 80% to 100% because someone deleted the failing test — here is how to detect it."* Concrete, demonstrable in 20 lines, and it names a problem people recognise immediately. That is the post that gets linked, not "introducing Assay."
3. **Be where the trigger is.** The `assay init` safety pack is the hook — most teams have no injection or leakage tests at all, and one command gives them a real suite. Publish the pack contents as a standalone reference so it is useful even to people who never install it.
4. **Design partners before pricing pages.** Ten teams using it in CI, free, with a standing call. Their questionnaires tell you which controls to map next. Ship the paid layer only once three of them have asked for the same thing.
5. **Then the paid layer.** Build the hosted verification link and PR bot last. They are the easiest things here to build and the least useful to build early.

## 8. Unit economics

The cost structure is the advantage of local-first. The free product costs nothing to serve — no inference, no storage, no per-run cost, because it runs on the user's machine. The paid layer serves small signed documents and webhook comments; a $299/mo customer costs single-digit dollars a month to serve.

The real cost is attention. The plan therefore has to fit around whatever else the author is doing, which rules out anything with an on-call rotation. That is another argument for shipping the CLI properly and the hosted layer late: a CLI that fails does not page anyone at 3am.

Rough shape of a viable outcome: 30 Team customers is ~$107k ARR against near-zero COGS. That does not need a funding round, a sales team, or a category win — only that the tool is genuinely the best answer to a specific question a few hundred teams are being asked.

## 9. What would make this wrong

Stated plainly, so it can be checked rather than rationalised later:

- **A funded competitor ships a ledger.** Possible; the crypto is easy. Harder for them is the *local-first* claim, which is architectural. If Braintrust ships signed evidence packs, the differentiation narrows to the deployment model and the price.
- **The compliance urgency slips.** Enforcement timelines move. If nobody is being asked the question in 18 months, the wedge is the security questionnaire alone — narrower, but still real, because enterprise procurement is not going to start asking *fewer* questions about AI.
- **Buyers want the dashboard anyway.** Some will. They are not the ICP; do not chase them by rebuilding the crowded product.
- **Evidence is a compliance-officer purchase, not a developer one.** The biggest risk in the plan. The mitigation is that the developer adopts it for the gate (a real daily benefit that stands alone) and the evidence is already there when someone upstairs asks. If the gate is not independently worth using, the whole funnel fails — which is why `require_suite_stable` and the safety pack matter more than the audit renderer.
- **One person cannot support enterprise buyers.** True at the Compliance tier. Cap it, or partner, rather than promise support that cannot be delivered.

## 10. What is done and what is next

**Done (v0.2):**
hash-chained ledger with HMAC attestation · `assay verify` detecting edits, deletions, reordering, and back-dating · suite hashing including scorer configuration · policy gate with per-eval overrides and `require_suite_stable` · control catalogue across OWASP LLM / NIST AI RMF / EU AI Act / ISO 42001 / SOC 2 · `assay audit` HTML and JSON evidence packs · `assay init` with runnable safety, quality, and structure packs · CI workflow scaffold · Windows console fix.

**Done (v0.3, in this repository):**

- **`assay init --pack rag`** — grounding, abstention, and citation evals. Three new scorers behind it: `grounded` (lexical or, with your embedder, semantic), `no_unsupported_numbers` (every figure in the answer appears in the sources — the precise, high-signal hallucination check), and `cites`. This closes the gap that was item 3 on the old list, and it is the pack most teams will install first.
- **Statistical honesty** — Wilson confidence intervals on every run; `--repeat N` to catch nondeterministic cases; a flaky case fails rather than passing. Two new gate rules: `min_lower_bound` and `max_flaky`.
- **`assay questionnaire`** — control coverage exported as CSV, Markdown or JSON, answered from the verified ledger, with gaps shown rather than hidden. This was scoped as a paid feature; shipping it free is deliberate (see below).
- **Safety scorers promoted to first class** — `no_pii` (Luhn-validated, so an order number is not reported as a card) and `is_refusal`/`not_refusal`, which also catches over-refusal: a model quietly declining legitimate work is a real regression nobody tests for.
- 29 passing tests, zero dependencies, Python 3.9+.

**A revision to §5.** The plan had questionnaire export on the paid side. It ships free. The reason: the questionnaire is the moment the tool proves its worth, and putting it behind a wall means the developer who installed Assay for the gate never sees the thing that makes their manager care. Sell the *organisation* layer instead — attestation key management, cross-repo coverage, retention, the shareable verification link, the PR bot. Those are genuinely company-shaped and cannot be replicated by a single developer with a local checkout, which is the correct test for what belongs on the paid side.

**Next, in order:**
1. Publish 0.3.0 to PyPI.
2. Write the suite-deletion post; still the only marketing asset that matters.
3. A second post on flaky evals — "your eval suite is 95% and you do not know the error bars" — now that the code backs it.
4. Recruit ten design partners.
5. Hosted verification link, then the PR bot. Not before step 4.
