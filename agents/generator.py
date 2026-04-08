"""
Architecture Generator Agent — produces 2 architecture variants.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from schemas.models import AgentState, ArchitectureVariant
from services.llm import get_llm
from templates.base_templates import TEMPLATES
from utils.parser import normalize_llm_text, parse_json_list

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a principal distributed systems architect.

Given the requirements and a template hint, generate exactly 2 distinct architecture variants.

Each variant must be a JSON object with these keys:
- services (list of strings)
- databases (list of strings)
- message_queues (list of strings)
- caching_layer (list of strings)
- scaling_strategy (string)
- bottlenecks (list of strings)
- monitoring_metrics (list of strings)

Respond with ONLY a JSON array of exactly 2 objects — no explanation, no markdown."""


def generate_architecture(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — generate 2 architecture variants."""
    requirements = state["requirements"]
    template_key = state["template"]
    preferred_language = state.get("preferred_language", "Python")
    template = TEMPLATES.get(template_key, TEMPLATES["web_scale"])

    logger.info("Generating architectures with template: %s", template_key)

    user_content = (
        f"Requirements:\n{json.dumps(requirements, indent=2)}\n\n"
        f"Preferred implementation language:\n{preferred_language}\n\n"
        f"Template hint ({template_key}):\n{json.dumps(template, indent=2)}\n\n"
        "Generate exactly 2 architecture variants as a JSON array."
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
            logger.debug("LLM response (attempt %d): %s", attempt, raw[:500])

            variants = parse_json_list(raw, ArchitectureVariant)
            if len(variants) < 2:
                raise ValueError(f"Expected 2 variants, got {len(variants)}")

            architectures = [v.model_dump() for v in variants[:2]]
            logger.info("Generated %d architecture variants on attempt %d", len(architectures), attempt)
            return {"architectures": architectures}

        except Exception as exc:
            last_error = exc
            logger.warning("Architecture generation failed on attempt %d: %s", attempt, exc)
            messages.append({"role": "assistant", "content": raw if "raw" in dir() else ""})
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response was invalid. "
                    "Respond with ONLY a JSON array of exactly 2 architecture objects."
                ),
            })

    # Fallback
    logger.error("Architecture generation failed after %d attempts: %s", max_attempts, last_error)
    fallback = ArchitectureVariant(
        services=template.get("core_services", ["API Gateway", "Core Service"]),
        databases=template.get("recommended_databases", ["PostgreSQL"]),
        message_queues=template.get("recommended_queues", ["RabbitMQ"]),
        caching_layer=template.get("recommended_caching", ["Redis"]),
        scaling_strategy=template.get("scaling_hint", "Horizontal scaling"),
        bottlenecks=["LLM generation failed — review manually"],
        monitoring_metrics=["latency_p99", "error_rate", "throughput"],
    )
    return {"architectures": [fallback.model_dump(), fallback.model_dump()]}
