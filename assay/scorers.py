"""Built-in scorers.

A scorer takes the task's ``output`` and the ``Case`` and returns a ``Score``.
Some are plain scorers you pass directly (``exact_match``); others are factories
you call with a config (``contains("ok")``). Writing your own is just a function
with the same signature — there is nothing special about these.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .core import Case, Score


def _str(x: Any) -> str:
    return x if isinstance(x, str) else json.dumps(x, default=str)


# --- exact / substring ---------------------------------------------------- #
def exact_match(output: Any, case: Case) -> Score:
    """Output equals ``case.expect`` exactly."""
    ok = output == case.expect
    return Score("exact_match", ok, 1.0 if ok else 0.0,
                 "" if ok else f"expected {case.expect!r}, got {output!r}")


def contains(substr: str, *, ignore_case: bool = False) -> Callable[[Any, Case], Score]:
    """Output contains ``substr``."""
    def scorer(output: Any, case: Case) -> Score:
        hay, needle = _str(output), substr
        if ignore_case:
            hay, needle = hay.lower(), needle.lower()
        ok = needle in hay
        return Score("contains", ok, 1.0 if ok else 0.0,
                     "" if ok else f"missing substring {substr!r}")
    return scorer


def not_contains(substr: str, *, ignore_case: bool = False) -> Callable[[Any, Case], Score]:
    """Output must NOT contain ``substr`` — useful for banned words, PII, leaks."""
    inner = contains(substr, ignore_case=ignore_case)

    def scorer(output: Any, case: Case) -> Score:
        hit = inner(output, case).passed
        return Score("not_contains", not hit, 0.0 if hit else 1.0,
                     f"found forbidden substring {substr!r}" if hit else "")
    return scorer


def regex(pattern: str, *, flags: int = 0) -> Callable[[Any, Case], Score]:
    """Output matches ``pattern`` anywhere."""
    rx = re.compile(pattern, flags)

    def scorer(output: Any, case: Case) -> Score:
        ok = bool(rx.search(_str(output)))
        return Score("regex", ok, 1.0 if ok else 0.0,
                     "" if ok else f"no match for /{pattern}/")
    return scorer


# --- structure ------------------------------------------------------------ #
def is_json(output: Any, case: Case) -> Score:
    """Output is valid JSON (or already a dict/list)."""
    if isinstance(output, (dict, list)):
        return Score("is_json", True, 1.0)
    try:
        json.loads(output)
        return Score("is_json", True, 1.0)
    except Exception as exc:
        return Score("is_json", False, 0.0, f"not valid JSON: {exc}")


def json_has_keys(*keys: str) -> Callable[[Any, Case], Score]:
    """Parsed JSON output contains every named key."""
    def scorer(output: Any, case: Case) -> Score:
        try:
            obj = output if isinstance(output, dict) else json.loads(output)
        except Exception as exc:
            return Score("json_has_keys", False, 0.0, f"not JSON: {exc}")
        missing = [k for k in keys if k not in obj]
        return Score("json_has_keys", not missing,
                     1.0 - len(missing) / len(keys) if keys else 1.0,
                     f"missing keys {missing}" if missing else "")
    return scorer


# --- numeric / length ----------------------------------------------------- #
def length_between(lo: int, hi: int) -> Callable[[Any, Case], Score]:
    """Output length falls within [lo, hi]."""
    def scorer(output: Any, case: Case) -> Score:
        n = len(_str(output))
        ok = lo <= n <= hi
        return Score("length_between", ok, 1.0 if ok else 0.0,
                     "" if ok else f"length {n} not in [{lo}, {hi}]")
    return scorer


# --- model-graded --------------------------------------------------------- #
def llm_judge(rubric: str, judge: Callable[[str], str], *,
              threshold: float = 0.5) -> Callable[[Any, Case], Score]:
    """Grade an open-ended output with a model.

    ``judge`` is any function that takes a prompt string and returns the model's
    reply — you plug in your own provider so Assay stays dependency- and key-free.
    The judge is asked to return a JSON object ``{"score": 0..1, "reason": ...}``;
    the case passes when the score meets ``threshold``.
    """
    prompt_tmpl = (
        "You are grading an AI system's output against a rubric. "
        "Respond with ONLY a JSON object: {{\"score\": <0..1>, \"reason\": <short>}}.\n\n"
        "RUBRIC: {rubric}\n\nINPUT: {input}\n\nOUTPUT: {output}\n\n"
        "EXPECTED (may be blank): {expect}\n"
    )

    def scorer(output: Any, case: Case) -> Score:
        prompt = prompt_tmpl.format(rubric=rubric, input=_str(case.input),
                                    output=_str(output), expect=_str(case.expect))
        try:
            reply = judge(prompt)
            obj = json.loads(_extract_json(reply))
            score = float(obj.get("score", 0.0))
        except Exception as exc:
            return Score("llm_judge", False, 0.0, f"judge failed: {exc}")
        return Score("llm_judge", score >= threshold, score,
                     str(obj.get("reason", "")))
    return scorer


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text
