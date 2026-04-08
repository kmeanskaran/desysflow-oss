"""
Requirement Extractor Agent — extracts structured requirements from user input.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from schemas.models import AgentState, Requirements
from services.llm import get_llm
from utils.parser import normalize_llm_text, parse_json_response

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior system design analyst.

Given a user's system design request, extract structured requirements.

You MUST respond with ONLY a valid JSON object — no explanation, no markdown.

The JSON must have exactly these keys:
- traffic_estimate (string): estimated traffic, e.g. "5M DAU"
- latency_requirement (string): target latency, e.g. "<100ms p99"
- consistency_requirement (string): "eventual" or "strong"
- budget_constraint (string): "low", "moderate", or "high"
- region (string): primary region, e.g. "us-east-1"
- scale_growth_projection (string): expected growth, e.g. "3x in 12 months"
- critical_features (list of strings): key features the system must support

Respond with ONLY the JSON object."""


def extract_requirements(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — extract structured requirements from user input."""
    user_input = state["user_input"]
    logger.info("Extracting requirements from user input: %s", user_input[:100])

    llm = get_llm()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    max_attempts = 2
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = llm.invoke(messages)
            raw = normalize_llm_text(
                response.content if hasattr(response, "content") else response
            )
            logger.debug("LLM response (attempt %d): %s", attempt, raw[:500])

            requirements = parse_json_response(raw, Requirements)
            logger.info("Requirements extracted successfully on attempt %d", attempt)
            return {"requirements": requirements.model_dump()}

        except Exception as exc:
            last_error = exc
            logger.warning(
                "Requirement extraction failed on attempt %d: %s", attempt, exc
            )
            # Add a correction hint for the retry
            messages.append({"role": "assistant", "content": raw if "raw" in dir() else ""})
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Please respond with ONLY a valid JSON object matching the schema."
                ),
            })

    # Fallback: return sensible defaults
    logger.error("Requirement extraction failed after %d attempts: %s", max_attempts, last_error)
    fallback = Requirements(
        traffic_estimate="unknown",
        latency_requirement="unknown",
        consistency_requirement="eventual",
        budget_constraint="moderate",
        region="us-east-1",
        scale_growth_projection="unknown",
        critical_features=[],
    )
    return {"requirements": fallback.model_dump()}
