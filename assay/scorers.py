"""Built-in scorers.

A scorer takes the task's ``output`` and the ``Case`` and returns a ``Score``.
Some are plain scorers you pass directly (``exact_match``); others are factories
you call with a config (``contains("ok")``). Writing your own is just a function
with the same signature — there is nothing special about these.
"""
from __future__ import annotations

import difflib
import json
import math
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


# --- similarity ----------------------------------------------------------- #
def similarity(threshold: float = 0.8,
               embed: Callable[[str], list] | None = None) -> Callable[[Any, Case], Score]:
    """Pass when the output is *similar enough* to ``case.expect`` — for outputs
    that are correct without being character-identical.

    Lexical by default (difflib ratio, 0..1, no dependencies). Pass an ``embed``
    function (text -> vector) to score true *semantic* similarity by cosine — the
    same pluggable pattern as ``llm_judge``, so Assay never bundles an embedder.
    """
    def scorer(output: Any, case: Case) -> Score:
        a, b = _str(output), _str(case.expect)
        if embed is not None:
            sim = _cosine(embed(a), embed(b))
            kind = "semantic"
        else:
            sim = difflib.SequenceMatcher(None, a, b).ratio()
            kind = "lexical"
        ok = sim >= threshold
        return Score("similarity", ok, sim,
                     "" if ok else f"{kind} similarity {sim:.2f} < {threshold}")
    return scorer


def _cosine(u: list, v: list) -> float:
    if not u or not v or len(u) != len(v):
        return 0.0
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    return dot / (nu * nv) if nu and nv else 0.0


# --- schema --------------------------------------------------------------- #
def matches_schema(schema: dict) -> Callable[[Any, Case], Score]:
    """Validate structured output against a lightweight schema.

    A schema maps field -> expected type: a Python type (``str``, ``int``,
    ``float``, ``bool``, ``list``, ``dict``), the string ``"number"`` (int or
    float), a nested schema ``dict`` for objects, or ``[item_type]`` for a list of
    a given type. Every field is required.

        matches_schema({"intent": str, "confidence": "number",
                        "entities": [str], "meta": {"lang": str}})
    """
    def scorer(output: Any, case: Case) -> Score:
        try:
            obj = output if isinstance(output, (dict, list)) else json.loads(output)
        except Exception as exc:
            return Score("matches_schema", False, 0.0, f"not JSON: {exc}")
        errors: list[str] = []
        _check(obj, schema, "", errors)
        ok = not errors
        return Score("matches_schema", ok, 1.0 if ok else 0.0,
                     "" if ok else "; ".join(errors[:4]))
    return scorer


def _type_ok(value: Any, spec: Any) -> bool:
    if spec == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(spec, type):
        if spec in (int, float) and isinstance(value, bool):
            return False
        return isinstance(value, spec)
    return False


def _check(obj: Any, spec: Any, path: str, errors: list) -> None:
    if isinstance(spec, dict):
        if not isinstance(obj, dict):
            errors.append(f"{path or 'root'}: expected object")
            return
        for key, sub in spec.items():
            p = f"{path}.{key}" if path else key
            if key not in obj:
                errors.append(f"{p}: missing")
            else:
                _check(obj[key], sub, p, errors)
    elif isinstance(spec, list):
        if not isinstance(obj, list):
            errors.append(f"{path}: expected list")
            return
        item_spec = spec[0] if spec else None
        for i, item in enumerate(obj):
            if item_spec is not None:
                _check(item, item_spec, f"{path}[{i}]", errors)
    else:
        if not _type_ok(obj, spec):
            name = spec if isinstance(spec, str) else getattr(spec, "__name__", spec)
            errors.append(f"{path or 'root'}: expected {name}, got {type(obj).__name__}")


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
