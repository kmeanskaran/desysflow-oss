"""
Revision Agent — improves architecture based on critic feedback.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from schemas.models import AgentState, ArchitectureVariant
from services.llm import get_llm
from utils.parser import normalize_llm_text, parse_json_block_loose

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a principal distributed systems architect performing a revision.

Given an architecture design and critic feedback, produce an improved version.

The improved architecture must be a single JSON object with these keys:
- services (list of strings)
- databases (list of strings)
- message_queues (list of strings)
- caching_layer (list of strings)
- scaling_strategy (string)
- bottlenecks (list of strings)
- monitoring_metrics (list of strings)

Address every point in the critic feedback.
Respond with ONLY the JSON object — no explanation, no markdown."""


def revision_agent(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — revise architecture using critic feedback."""
    architectures = state["architectures"]
    critic_feedback = state.get("critic_feedback", [])
    edge_cases = state.get("edge_cases", [])

    # Use the first (primary) variant as the base for revision
    base_architecture = architectures[0] if architectures else {}

    logger.info("Revising architecture based on %d critic findings", len(critic_feedback))

    user_content = (
        f"Original architecture:\n{json.dumps(base_architecture, indent=2)}\n\n"
        f"Edge cases:\n{json.dumps(edge_cases, indent=2)}\n\n"
        f"Critic feedback:\n{json.dumps(critic_feedback, indent=2)}\n\n"
        "Produce an improved architecture as a single JSON object."
    )

    llm = get_llm()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    max_attempts = 2
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = llm.invoke(messages)
            raw = normalize_llm_text(
                response.content if hasattr(response, "content") else response
            )
            logger.debug("Revision response (attempt %d): %s", attempt, raw[:500])

            parsed = parse_json_block_loose(raw)
            if not isinstance(parsed, dict):
                raise ValueError(f"Expected JSON object from revision agent, got {type(parsed).__name__}")
            revised = ArchitectureVariant.model_validate(parsed)
            logger.info("Architecture revised successfully on attempt %d", attempt)
            return {"revised_architecture": revised.model_dump()}

        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                logger.info("Revision: retrying with stricter JSON request")
            else:
                logger.warning("Revision failed on final attempt: %s", exc)
            messages.append({"role": "assistant", "content": raw if "raw" in dir() else ""})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was not valid JSON. "
                    "Please respond with ONLY a valid JSON object matching the schema."
                ),
            })

    # Fallback: return original architecture with a note
    logger.warning("Revision fallback applied after %d attempts", max_attempts)
    fallback = dict(base_architecture)
    fallback.setdefault("bottlenecks", []).append("Revision failed — manual review needed")
    return {"revised_architecture": fallback}
