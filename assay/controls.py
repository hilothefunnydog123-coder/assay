"""Control catalogue — the vocabulary that turns a pass rate into an answer.

Tag an eval with the controls it exercises::

    Eval("support-router", controls=["owasp-llm:llm01", "nist:measure-2.5"])

and ``assay audit`` can answer the question that actually blocks deals and
launches: *which of our AI assurance obligations do we have current, verifiable
test evidence for, and which are bare?*

Scope note, deliberately narrow: a control here means "this eval produces
evidence relevant to that requirement." It is not a compliance determination.
Whether your evidence is *sufficient* for the EU AI Act or an ISO 42001 audit is
a judgement for your counsel and your auditor. Assay's job is to make the
evidence real, dated, and verifiable so that judgement has something to stand on.
Requirement text below is paraphrased for orientation — cite the source document.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Control:
    id: str
    framework: str
    ref: str
    title: str
    requirement: str


def _c(cid, framework, ref, title, requirement) -> Control:
    return Control(cid, framework, ref, title, requirement)


CATALOG: dict[str, Control] = {c.id: c for c in [
    # --- OWASP Top 10 for LLM Applications ------------------------------- #
    _c("owasp-llm:llm01", "OWASP LLM Top 10", "LLM01", "Prompt injection",
       "Untrusted input must not be able to override system instructions or "
       "redirect the model's behaviour."),
    _c("owasp-llm:llm02", "OWASP LLM Top 10", "LLM02", "Sensitive information disclosure",
       "Output must not leak secrets, credentials, system prompts, or personal "
       "data belonging to other users."),
    _c("owasp-llm:llm05", "OWASP LLM Top 10", "LLM05", "Improper output handling",
       "Model output consumed downstream must be well-formed and constrained to "
       "the expected shape."),
    _c("owasp-llm:llm06", "OWASP LLM Top 10", "LLM06", "Excessive agency",
       "The system must not take actions beyond the scope it was granted."),
    _c("owasp-llm:llm09", "OWASP LLM Top 10", "LLM09", "Misinformation",
       "Output must be factually grounded; unsupported claims must be avoided or "
       "flagged."),

    # --- NIST AI Risk Management Framework -------------------------------- #
    _c("nist:measure-2.3", "NIST AI RMF 1.0", "MEASURE 2.3", "Performance is measured",
       "System performance against declared purpose is measured and the results "
       "are documented."),
    _c("nist:measure-2.5", "NIST AI RMF 1.0", "MEASURE 2.5", "Validity and reliability",
       "The system is validated and its reliability is demonstrated under "
       "conditions similar to deployment."),
    _c("nist:measure-2.7", "NIST AI RMF 1.0", "MEASURE 2.7", "Security and resilience",
       "Resilience to adversarial input and misuse is evaluated."),
    _c("nist:measure-2.11", "NIST AI RMF 1.0", "MEASURE 2.11", "Fairness and bias",
       "Harmful bias in system behaviour is evaluated across relevant groups."),
    _c("nist:measure-4.2", "NIST AI RMF 1.0", "MEASURE 4.2", "Measurement is repeated",
       "Measurement is repeated over time so that changes in system behaviour "
       "are detected."),

    # --- EU AI Act --------------------------------------------------------- #
    _c("eu-ai-act:art9", "EU AI Act", "Art. 9", "Risk management system",
       "A continuous, iterative risk management process across the system's "
       "lifecycle, including testing against identified risks."),
    _c("eu-ai-act:art10", "EU AI Act", "Art. 10", "Data and data governance",
       "Data used for evaluation is relevant, representative, and examined for "
       "bias."),
    _c("eu-ai-act:art12", "EU AI Act", "Art. 12", "Record-keeping",
       "Automatic recording of events over the system's lifetime, enabling "
       "traceability."),
    _c("eu-ai-act:art15", "EU AI Act", "Art. 15", "Accuracy, robustness, cybersecurity",
       "An appropriate level of accuracy and robustness, consistent across the "
       "lifecycle, resilient to error and adversarial manipulation."),
    _c("eu-ai-act:art17", "EU AI Act", "Art. 17", "Quality management system",
       "Documented procedures for testing, validation, and change control."),

    # --- ISO/IEC 42001 ----------------------------------------------------- #
    _c("iso42001:8.3", "ISO/IEC 42001", "8.3", "AI system verification and validation",
       "The AI system is verified and validated against defined requirements "
       "before and during use."),
    _c("iso42001:8.4", "ISO/IEC 42001", "8.4", "AI system operation and monitoring",
       "System behaviour is monitored in operation and deviations are handled."),
    _c("iso42001:9.1", "ISO/IEC 42001", "9.1", "Monitoring and measurement",
       "What is measured, how, and when, is determined and the results retained."),

    # --- SOC 2 ------------------------------------------------------------- #
    _c("soc2:cc7.1", "SOC 2", "CC7.1", "Detection of deviations",
       "Procedures detect changes that could introduce new vulnerabilities or "
       "degrade the service."),
    _c("soc2:cc8.1", "SOC 2", "CC8.1", "Change management",
       "Changes are authorised, designed, tested, and approved before "
       "implementation."),
]}

# Convenience groupings for `assay init --pack`.
PACKS: dict[str, list[str]] = {
    "safety": ["owasp-llm:llm01", "owasp-llm:llm02", "nist:measure-2.7",
               "eu-ai-act:art15"],
    "quality": ["nist:measure-2.3", "nist:measure-2.5", "nist:measure-4.2",
                "iso42001:8.3", "soc2:cc7.1"],
    "structure": ["owasp-llm:llm05", "iso42001:8.3"],
}


def get(cid: str) -> Control | None:
    return CATALOG.get(cid)


def resolve(ids) -> list[Control]:
    """Known controls for these ids, in catalogue order. Unknown ids are dropped
    by this helper — :func:`unknown` reports them so they can be surfaced rather
    than silently ignored."""
    want = set(ids or [])
    return [c for cid, c in CATALOG.items() if cid in want]


def unknown(ids) -> list[str]:
    return sorted(i for i in (ids or []) if i not in CATALOG)


def frameworks(ids=None) -> dict[str, list[Control]]:
    """Group controls by framework, for a coverage matrix."""
    cs = resolve(ids) if ids is not None else list(CATALOG.values())
    out: dict[str, list[Control]] = {}
    for c in cs:
        out.setdefault(c.framework, []).append(c)
    return out


def coverage(tagged: dict[str, list[str]]) -> dict[str, dict]:
    """Map control id -> which evals cover it.

    ``tagged`` maps eval name -> the control ids that eval declares. Returns an
    entry for every control any eval mentions, so an audit can show both what is
    covered and (against a declared scope) what is not.
    """
    out: dict[str, dict] = {}
    for eval_name, ids in tagged.items():
        for cid in ids or []:
            c = CATALOG.get(cid)
            out.setdefault(cid, {
                "id": cid,
                "framework": c.framework if c else "custom",
                "ref": c.ref if c else cid,
                "title": c.title if c else cid,
                "requirement": c.requirement if c else "",
                "known": c is not None,
                "evals": [],
            })["evals"].append(eval_name)
    return out
