"""
JSON parsing utilities — extract and validate structured output from LLM text.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any, Dict, List, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def extract_json_block(text: str) -> str:
    """Extract a JSON block from text that may contain markdown fences.

    Tries the following strategies in order:
    1. ```json ... ``` fenced block
    2. ``` ... ``` fenced block (no language tag)
    3. First { ... } or [ ... ] spanning multiple lines
    4. Raw text as-is
    """
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()

    # Strategy 1 & 2: fenced code blocks
    pattern = r"```(?:json)?\s*\n?([\s\S]*?)```"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()

    # Strategy 3: outermost braces / brackets
    start_brace = text.find("{")
    start_bracket = text.find("[")
    p_start = -1
    open_ch, close_ch = "", ""
    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        p_start, open_ch, close_ch = start_brace, "{", "}"
    elif start_bracket != -1:
        p_start, open_ch, close_ch = start_bracket, "[", "]"
        
    if p_start != -1:
        depth = 0
        for i in range(p_start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    return text[p_start : i + 1]

    # Strategy 4: return as-is
    return text.strip()


def normalize_llm_text(raw: Any) -> str:
    """Flatten provider-specific LLM payloads into a plain text response."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = [normalize_llm_text(item) for item in raw]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(raw, dict):
        if isinstance(raw.get("text"), str):
            return raw["text"]
        if isinstance(raw.get("content"), (str, list, dict)):
            return normalize_llm_text(raw["content"])
        if isinstance(raw.get("value"), str):
            return raw["value"]
        if isinstance(raw.get("output_text"), str):
            return raw["output_text"]
        parts = [normalize_llm_text(value) for value in raw.values()]
        return "\n".join(part for part in parts if part).strip()
    return str(raw)


def _repair_json_text(text: str) -> str:
    """Repair common local-LLM JSON issues without changing valid JSON."""
    text = text.strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _normalize_json_candidate(text: str) -> str:
    """Normalize common model-output artifacts before parsing."""
    text = text.replace("\ufeff", "").strip()
    text = (
        text
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
    )
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = _repair_json_text(text)
    return text.strip()


def _python_literal_candidate(text: str) -> str:
    """Convert JSON-like text into a safer Python-literal form for fallback parsing."""
    converted = text
    converted = re.sub(r"\btrue\b", "True", converted, flags=re.IGNORECASE)
    converted = re.sub(r"\bfalse\b", "False", converted, flags=re.IGNORECASE)
    converted = re.sub(r"\bnull\b", "None", converted, flags=re.IGNORECASE)
    return converted


def parse_json_block_loose(raw: Any) -> Union[Dict[str, Any], List[Any]]:
    """Parse LLM output into JSON with local repairs and Python-literal fallback.

    This is intentionally tolerant for local model outputs that may include:
    trailing commas, smart quotes, comments, and Python-like dict/list literals.
    """
    candidate = _normalize_json_candidate(extract_json_block(normalize_llm_text(raw)))
    if not candidate:
        raise ValueError("LLM returned an empty response")

    errors: list[str] = []

    seen_variants: set[str] = set()
    for variant in (candidate, _repair_json_text(candidate)):
        if variant in seen_variants:
            continue
        seen_variants.add(variant)
        try:
            parsed = json.loads(variant)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception as exc:
            errors.append(f"json:{exc}")

    try:
        py_like = _python_literal_candidate(candidate)
        parsed = ast.literal_eval(py_like)
        if isinstance(parsed, (dict, list)):
            return parsed
        raise ValueError(f"Expected dict/list, got {type(parsed).__name__}")
    except Exception as exc:
        errors.append(f"literal_eval:{exc}")

    unique_errors: list[str] = []
    for item in errors:
        if item not in unique_errors:
            unique_errors.append(item)
    short = " | ".join(unique_errors[:2]) if unique_errors else "unknown parse failure"
    raise ValueError(f"Malformed JSON after local repair ({short})")


def parse_json_response(
    raw: str,
    model: Type[T],
) -> T:
    """Parse raw LLM text into a validated Pydantic model.

    Raises ``ValidationError`` or ``json.JSONDecodeError`` on failure.
    """
    json_str = _repair_json_text(extract_json_block(raw))
    if not json_str:
        raise ValueError("LLM returned an empty response")
    data = json.loads(json_str)
    return model.model_validate(data)


def parse_json_list(
    raw: str,
    model: Type[T],
) -> List[T]:
    """Parse raw LLM text into a list of validated Pydantic models."""
    json_str = _repair_json_text(extract_json_block(raw))
    if not json_str:
        raise ValueError("LLM returned an empty response")
    data = json.loads(json_str)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list, got {type(data).__name__}")
    return [model.model_validate(item) for item in data]


def safe_parse_string_list(raw: str) -> List[str]:
    """Best-effort extraction of a JSON string list from LLM output."""
    json_str = extract_json_block(raw)
    try:
        data = json.loads(json_str)
        if isinstance(data, list):
            return [str(item) for item in data]
    except json.JSONDecodeError:
        pass

    # Fallback: split numbered / bulleted lines
    lines: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        cleaned = re.sub(r"^[\d\-\*\•\.]+\s*", "", line)
        if cleaned:
            lines.append(cleaned)
    return lines
