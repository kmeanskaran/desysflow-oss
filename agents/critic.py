"""
Critic Agent — reviews architecture for risks, gaps, and concerns.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from schemas.models import AgentState
from services.llm import get_llm
from utils.parser import normalize_llm_text, safe_parse_string_list

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a principal distributed systems reviewer with 20+ years of
experience at FAANG-scale companies.

Given an architecture design and its edge cases, perform a thorough review.

You MUST identify issues in ALL of these categories:
1. Scalability risks
2. Operational complexity
3. Observability gaps
4. Security concerns
5. Cost blind spots

Respond with ONLY a JSON array of strings — each string is one specific finding.
No explanation, no markdown. Example: ["finding 1", "finding 2", ...]"""


def critic_agent(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — review architectures and return structured feedback."""
    architectures = state["architectures"]
    edge_cases = state.get("edge_cases", [])
    requirements = state.get("requirements", {})

    logger.info("Running critic review on %d architectures", len(architectures))

    user_content = (
        f"Requirements:\n{json.dumps(requirements, indent=2)}\n\n"
        f"Architectures:\n{json.dumps(architectures, indent=2)}\n\n"
        f"Known edge cases:\n{json.dumps(edge_cases, indent=2)}\n\n"
        "Provide your review as a JSON array of specific findings."
    )

    llm = get_llm()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        response = llm.invoke(messages)
        raw = normalize_llm_text(
            response.content if hasattr(response, "content") else response
        )
        logger.debug("Critic response: %s", raw[:500])
        feedback = safe_parse_string_list(raw)
        logger.info("Critic produced %d findings", len(feedback))
        return {"critic_feedback": feedback}

    except Exception as exc:
        logger.error("Critic agent failed: %s", exc)
        return {
            "critic_feedback": [
                "Critic review failed — manual review recommended.",
                str(exc),
            ]
        }


def run_critic_standalone(architecture: Dict[str, Any]) -> Dict[str, List[str]]:
    """Run the critic agent in standalone mode (for POST /review endpoint).

    Returns dict with ``critic_feedback`` and ``suggested_improvements``.
    """
    logger.info("Running standalone critic review")

    review_prompt = (
        f"Architecture:\n{json.dumps(architecture, indent=2)}\n\n"
        "Provide your review as a JSON array of specific findings."
    )

    improvement_prompt = (
        f"Architecture:\n{json.dumps(architecture, indent=2)}\n\n"
        "Suggest specific improvements as a JSON array of strings."
    )

    llm = get_llm()

    # Get feedback
    try:
        resp1 = llm.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": review_prompt},
        ])
        raw1 = normalize_llm_text(
            resp1.content if hasattr(resp1, "content") else resp1
        )
        feedback = safe_parse_string_list(raw1)
    except Exception as exc:
        logger.error("Standalone critic failed: %s", exc)
        feedback = [f"Review failed: {exc}"]

    # Get improvements
    try:
        resp2 = llm.invoke([
            {"role": "system", "content": (
                "You are a principal distributed systems architect. "
                "Suggest concrete improvements to the given architecture. "
                "Respond with ONLY a JSON array of strings."
            )},
            {"role": "user", "content": improvement_prompt},
        ])
        raw2 = normalize_llm_text(
            resp2.content if hasattr(resp2, "content") else resp2
        )
        improvements = safe_parse_string_list(raw2)
    except Exception as exc:
        logger.error("Standalone improvement suggestions failed: %s", exc)
        improvements = [f"Improvement generation failed: {exc}"]

    return {
        "critic_feedback": feedback,
        "suggested_improvements": improvements,
    }
