"""
JSON parsing utilities — extract and validate structured output from LLM text.
"""

from __future__ import annotations

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


def _repair_json_text(text: str) -> str:
    """Repair common local-LLM JSON issues without changing valid JSON."""
    text = text.strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def parse_json_response(
    raw: str,
    model: Type[T],
) -> T:
    """Parse raw LLM text into a validated Pydantic model.

    Raises ``ValidationError`` or ``json.JSONDecodeError`` on failure.
    """
    json_str = _repair_json_text(extract_json_block(raw))
    data = json.loads(json_str)
    return model.model_validate(data)


def parse_json_list(
    raw: str,
    model: Type[T],
) -> List[T]:
    """Parse raw LLM text into a list of validated Pydantic models."""
    json_str = _repair_json_text(extract_json_block(raw))
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
