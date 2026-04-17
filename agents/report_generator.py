"""
Report Generator Agent — produces HLD and LLD reports from the final architecture.

HLD (High-Level Design): For product engineers and architects.
LLD (Low-Level Design): For developers building the system.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any, Dict

from schemas.models import AgentState
from services.llm import get_llm
from utils.parser import extract_json_block, normalize_llm_text, parse_json_block_loose

logger = logging.getLogger(__name__)

_HLD_DEFAULT = {
    "system_overview": "Architecture overview is pending refinement.",
    "components": [{"name": "API Service", "responsibility": "Handles client requests", "type": "service"}],
    "data_flow": ["Client sends request to API service", "API service processes request and returns response"],
    "scaling_strategy": "Horizontal scaling with stateless services and autoscaling.",
    "availability": "Multi-instance deployment with health checks and automated failover.",
    "trade_offs": ["Favor managed services for speed of delivery over deep infrastructure customization."],
    "estimated_capacity": {
        "requests_per_second": "100-500 RPS",
        "storage": "100 GB initial",
        "bandwidth": "100 Mbps baseline",
    },
}

_LLD_DEFAULT = {
    "api_endpoints": [
        {
            "method": "POST",
            "path": "/api/v1/process",
            "description": "Submit a processing request.",
            "request_body": {"payload": "object"},
            "response_body": {"status": "accepted", "id": "string"},
        }
    ],
    "database_schemas": [
        {
            "name": "primary_db",
            "type": "PostgreSQL",
            "tables_or_collections": [{"name": "items", "fields": ["id", "created_at", "status"]}],
        }
    ],
    "service_communication": [
        {"from": "API Service", "to": "Worker Service", "protocol": "REST", "description": "Submit jobs for processing."}
    ],
    "caching_strategy": [
        {
            "layer": "Application",
            "technology": "Redis",
            "ttl": "300s",
            "invalidation_strategy": "Event-based invalidation on write",
        }
    ],
    "error_handling": [
        {"scenario": "Upstream timeout", "strategy": "Retry with backoff", "fallback": "Return 503 with retry-after"}
    ],
    "deployment": {
        "containerization": "Docker",
        "orchestration": "Kubernetes",
        "ci_cd": "GitHub Actions",
        "environments": ["dev", "staging", "prod"],
    },
    "security": ["TLS everywhere", "JWT authentication", "Role-based authorization"],
}


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and len(value) > 0


def _normalize_hld_report(report: Any) -> dict:
    data = report if isinstance(report, dict) else {}
    normalized = deepcopy(_HLD_DEFAULT)

    if _non_empty_str(data.get("system_overview")):
        normalized["system_overview"] = data["system_overview"].strip()
    if _non_empty_list(data.get("components")):
        cleaned_components = []
        for item in data["components"]:
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip() or "Unnamed Component"
                responsibility = str(item.get("responsibility", "")).strip() or "Responsibility not specified."
                comp_type = str(item.get("type", "")).strip().lower() or "service"
                cleaned_components.append({"name": name, "responsibility": responsibility, "type": comp_type})
            elif isinstance(item, str) and item.strip():
                cleaned_components.append(
                    {"name": item.strip(), "responsibility": "Supports core platform capabilities.", "type": "service"}
                )
        if cleaned_components:
            normalized["components"] = cleaned_components
    if _non_empty_list(data.get("data_flow")):
        normalized["data_flow"] = data["data_flow"]
    if _non_empty_str(data.get("scaling_strategy")):
        normalized["scaling_strategy"] = data["scaling_strategy"].strip()
    if _non_empty_str(data.get("availability")):
        normalized["availability"] = data["availability"].strip()
    if _non_empty_list(data.get("trade_offs")):
        normalized["trade_offs"] = data["trade_offs"]
    if _non_empty_dict(data.get("estimated_capacity")):
        normalized["estimated_capacity"] = data["estimated_capacity"]

    return normalized


def _normalize_lld_report(report: Any) -> dict:
    data = report if isinstance(report, dict) else {}
    normalized = deepcopy(_LLD_DEFAULT)

    for key in ["api_endpoints", "database_schemas", "service_communication", "caching_strategy", "error_handling", "security"]:
        if _non_empty_list(data.get(key)):
            normalized[key] = data[key]
    if _non_empty_dict(data.get("deployment")):
        normalized["deployment"] = data["deployment"]

    return normalized


_HLD_SYSTEM_PROMPT = """You are a principal architect writing a High-Level Design (HLD) document
for product engineers, engineering managers, and solution architects.

Given a system architecture, requirements, and critic feedback, produce a structured HLD.

You MUST respond with ONLY a valid JSON object with these keys:
- system_overview (string): 2-3 sentence overview of what the system does and its scale
- components (list of objects, each with "name", "responsibility", "type" where type is one of: service, database, cache, queue, storage, cdn, gateway, monitoring)
- data_flow (list of strings): step-by-step data flow description from user request to response
- scaling_strategy (string): how the system scales horizontally and vertically
- availability (string): availability guarantees and disaster recovery approach
- trade_offs (list of strings): key architectural trade-offs made and why
- estimated_capacity (object with keys "requests_per_second", "storage", "bandwidth"): rough capacity estimates

Output constraints (important):
- Keep total response under ~2500 tokens
- Keep each string concise (prefer <= 220 chars)
- Keep lists practical (prefer <= 12 items)
- Components must be concrete deployable/logical units (no vague entries like "System" or "Infrastructure").
- Every component must include all three keys: name, responsibility, type.
- Components should be implementation-ready and operationally meaningful for production use.

Respond with ONLY the JSON object — no explanation, no markdown."""


_LLD_SYSTEM_PROMPT = """You are a senior backend engineer writing a Low-Level Design (LLD) document
for developers who will implement the system.

Given a system architecture, requirements, and critic feedback, produce a detailed LLD.

You MUST respond with ONLY a valid JSON object with these keys:
- api_endpoints (list of objects, each with "method", "path", "description", "request_body", "response_body")
- database_schemas (list of objects, each with "name", "type" like "PostgreSQL/Redis/Cassandra", "tables_or_collections" as list of objects with "name" and "fields" as list of strings)
- service_communication (list of objects, each with "from", "to", "protocol" like "REST/gRPC/WebSocket/Kafka", "description")
- caching_strategy (list of objects, each with "layer", "technology", "ttl", "invalidation_strategy")
- error_handling (list of objects, each with "scenario", "strategy", "fallback")
- deployment (object with "containerization", "orchestration", "ci_cd", "environments" as list of strings)
- security (list of strings): security measures to implement

Output constraints (important):
- Keep total response under ~3500 tokens
- Keep each string concise (prefer <= 260 chars)
- Limit list sizes for reliability:
  - api_endpoints <= 20
  - database_schemas <= 8
  - service_communication <= 20
  - caching_strategy <= 8
  - error_handling <= 12
- Use implementation-level details: auth boundaries, validation, idempotency, retry/backoff, and failure handling where relevant.

Respond with ONLY the JSON object — no explanation, no markdown."""


_JSON_REPAIR_PROMPT = """You are a strict JSON repair assistant.
You receive malformed JSON text. Return ONLY a valid JSON object.
Do not add markdown, code fences, commentary, or extra keys."""


def _clean_json_text(text: str) -> str:
    """Apply lightweight cleanup before decode."""
    cleaned = text.replace("\ufeff", "").strip()
    # Remove trailing commas before object/array close.
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    # Replace smart quotes that commonly break strict JSON.
    cleaned = (
        cleaned
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
    )
    return cleaned


def _extract_best_json_candidate(raw: str) -> str:
    """Pick the most likely JSON payload from a raw model response."""
    text = raw.replace("\ufeff", "").strip()
    if not text:
        return ""

    # Prefer fenced blocks that look like JSON and keep the largest one.
    fence_matches = re.findall(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
    scored: list[str] = []
    for block in fence_matches:
        candidate = block.strip()
        if candidate and any(ch in candidate for ch in ("{", "[")):
            scored.append(candidate)
    if scored:
        return max(scored, key=len)

    return extract_json_block(text)


def _parse_json_with_repair(raw: str, llm, label: str) -> dict:
    """Best-effort parse with deterministic cleanup + LLM repair fallback."""
    candidate = _extract_best_json_candidate(raw)
    if not candidate.strip():
        raise ValueError(f"{label} model response did not contain JSON content.")

    # Attempt 1: local tolerant parser for common LLM JSON glitches.
    try:
        data = parse_json_block_loose(candidate)
        if not isinstance(data, dict):
            raise ValueError(f"{label} response was {type(data).__name__}, expected object")
        return data
    except Exception as exc:
        logger.debug("%s local parse failed; invoking JSON repair model: %s", label, exc)

    # Attempt 2: ask LLM to repair malformed JSON.
    cleaned = _clean_json_text(candidate)
    repair_resp = llm.invoke([
        {"role": "system", "content": _JSON_REPAIR_PROMPT},
        {"role": "user", "content": cleaned},
    ])
    repaired_raw = normalize_llm_text(
        repair_resp.content if hasattr(repair_resp, "content") else repair_resp
    )
    repaired_candidate = _extract_best_json_candidate(repaired_raw)
    if not repaired_candidate.strip():
        raise ValueError(f"{label} JSON repair produced empty output.")
    repaired_data = parse_json_block_loose(_clean_json_text(repaired_candidate))
    if not isinstance(repaired_data, dict):
        raise ValueError(f"{label} repaired response was {type(repaired_data).__name__}, expected object")
    return repaired_data


def _retry_generation_prompt(label: str) -> str:
    return (
        f"{label} generation retry:\n"
        "Return ONLY one compact, valid JSON object.\n"
        "No markdown, no commentary, no trailing commas, no truncation."
    )


def report_generator(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — generate HLD and LLD reports."""
    revised = state.get("revised_architecture", {})
    requirements = state.get("requirements", {})
    critic_feedback = state.get("critic_feedback", [])
    user_input = state.get("user_input", "")
    preferred_language = state.get("preferred_language", "Python")

    logger.info("Generating HLD and LLD reports")

    context = (
        f"User request: {user_input}\n\n"
        f"Preferred implementation language: {preferred_language}\n\n"
        f"Requirements:\n{json.dumps(requirements, indent=2)}\n\n"
        f"Final Architecture:\n{json.dumps(revised, indent=2)}\n\n"
        f"Critic Feedback:\n{json.dumps(critic_feedback, indent=2)}\n\n"
    )

    llm = get_llm()

    # --- Generate HLD ---
    hld_report = {}
    try:
        hld_resp = llm.invoke([
            {"role": "system", "content": _HLD_SYSTEM_PROMPT},
            {"role": "user", "content": context + "Generate the HLD report as a JSON object."},
        ])
        hld_raw = normalize_llm_text(
            hld_resp.content if hasattr(hld_resp, "content") else hld_resp
        )
        logger.debug("HLD response: %s", hld_raw[:500])
        try:
            hld_report = _parse_json_with_repair(hld_raw, llm, "HLD")
        except Exception as first_exc:
            logger.info("HLD: compact regeneration retry")
            hld_retry_resp = llm.invoke([
                {"role": "system", "content": _HLD_SYSTEM_PROMPT},
                {"role": "user", "content": context + _retry_generation_prompt("HLD")},
            ])
            hld_retry_raw = normalize_llm_text(
                hld_retry_resp.content if hasattr(hld_retry_resp, "content") else hld_retry_resp
            )
            hld_report = _parse_json_with_repair(hld_retry_raw, llm, "HLD")
        logger.info("HLD report generated successfully")
    except Exception as exc:
        logger.error("HLD generation failed: %s", exc)
        hld_report = {
            "system_overview": "HLD generation failed — review manually.",
            "components": [],
            "data_flow": [],
            "scaling_strategy": "Unknown",
            "availability": "Unknown",
            "trade_offs": [],
            "estimated_capacity": {},
        }

    # --- Generate LLD ---
    lld_report = {}
    try:
        lld_resp = llm.invoke([
            {"role": "system", "content": _LLD_SYSTEM_PROMPT},
            {"role": "user", "content": context + "Generate the LLD report as a JSON object."},
        ])
        lld_raw = normalize_llm_text(
            lld_resp.content if hasattr(lld_resp, "content") else lld_resp
        )
        logger.debug("LLD response: %s", lld_raw[:500])
        try:
            lld_report = _parse_json_with_repair(lld_raw, llm, "LLD")
        except Exception as first_exc:
            logger.info("LLD: compact regeneration retry")
            lld_retry_resp = llm.invoke([
                {"role": "system", "content": _LLD_SYSTEM_PROMPT},
                {"role": "user", "content": context + _retry_generation_prompt("LLD")},
            ])
            lld_retry_raw = normalize_llm_text(
                lld_retry_resp.content if hasattr(lld_retry_resp, "content") else lld_retry_resp
            )
            lld_report = _parse_json_with_repair(lld_retry_raw, llm, "LLD")
        logger.info("LLD report generated successfully")
    except Exception as exc:
        logger.error("LLD generation failed: %s", exc)
        lld_report = {
            "api_endpoints": [],
            "database_schemas": [],
            "service_communication": [],
            "caching_strategy": [],
            "error_handling": [],
            "deployment": {},
            "security": [],
        }

    return {
        "hld_report": _normalize_hld_report(hld_report),
        "lld_report": _normalize_lld_report(lld_report),
    }


_CLOUD_HLD_PROMPT = """You are a principal architect writing a High-Level Design (HLD) document
specialised for deployment on {provider}.

Given a system architecture and requirements, produce an HLD that references
{provider}-specific managed services throughout.

You MUST respond with ONLY a valid JSON object with these keys:
- system_overview (string): 2-3 sentence overview mentioning {provider} services
- components (list of objects: name, responsibility, type)
- data_flow (list of strings): step-by-step using {provider} service names
- scaling_strategy (string): {provider}-specific scaling approach
- availability (string): {provider} availability features used
- trade_offs (list of strings): trade-offs specific to {provider}
- estimated_capacity (object: requests_per_second, storage, bandwidth)

Output constraints:
- Keep total response under ~2500 tokens
- Keep each string concise (prefer <= 220 chars)
- Keep lists practical (prefer <= 12 items)

Respond with ONLY the JSON object — no explanation, no markdown."""


_CLOUD_LLD_PROMPT = """You are a senior backend engineer writing a Low-Level Design (LLD) document
for deployment on {provider}.

Given a system architecture, produce an LLD using {provider}-specific services and configurations.

You MUST respond with ONLY a valid JSON object with these keys:
- api_endpoints (list: method, path, description, request_body, response_body)
- database_schemas (list: name, type using {provider} DB services, tables_or_collections)
- service_communication (list: from, to, protocol, description)
- caching_strategy (list: layer, technology using {provider} caching, ttl, invalidation_strategy)
- error_handling (list: scenario, strategy, fallback)
- deployment (object: containerization, orchestration, ci_cd, environments)
- security (list of strings): {provider}-specific security measures

Output constraints:
- Keep total response under ~3500 tokens
- Keep each string concise (prefer <= 260 chars)
- api_endpoints <= 20
- database_schemas <= 8
- service_communication <= 20
- caching_strategy <= 8
- error_handling <= 12

Respond with ONLY the JSON object — no explanation, no markdown."""


def generate_cloud_reports(
    architecture: dict,
    provider: str,
    requirements: dict | None = None,
    user_input: str = "",
) -> dict:
    """Generate HLD and LLD reports for a specific cloud provider."""
    provider_labels = {
        "aws": "AWS",
        "gcp": "Google Cloud Platform (GCP)",
        "azure": "Microsoft Azure",
        "digitalocean": "DigitalOcean",
        "on_prem": "On-Premises / Self-Hosted",
    }
    label = provider_labels.get(provider, provider.upper())

    context = (
        f"Target cloud provider: {label}\n\n"
        f"User request: {user_input}\n\n"
        f"Requirements:\n{json.dumps(requirements or {}, indent=2)}\n\n"
        f"Architecture:\n{json.dumps(architecture, indent=2)}\n\n"
    )

    llm = get_llm()

    # HLD
    hld_report = {}
    try:
        hld_resp = llm.invoke([
            {"role": "system", "content": _CLOUD_HLD_PROMPT.format(provider=label)},
            {"role": "user", "content": context + f"Generate the HLD for {label}."},
        ])
        hld_raw = normalize_llm_text(
            hld_resp.content if hasattr(hld_resp, "content") else hld_resp
        )
        hld_report = _parse_json_with_repair(hld_raw, llm, f"Cloud HLD ({provider})")
        logger.info("Cloud HLD (%s) generated", provider)
    except Exception as exc:
        logger.error("Cloud HLD generation failed: %s", exc)
        hld_report = {"system_overview": f"HLD for {label} generation failed."}

    # LLD
    lld_report = {}
    try:
        lld_resp = llm.invoke([
            {"role": "system", "content": _CLOUD_LLD_PROMPT.format(provider=label)},
            {"role": "user", "content": context + f"Generate the LLD for {label}."},
        ])
        lld_raw = normalize_llm_text(
            lld_resp.content if hasattr(lld_resp, "content") else lld_resp
        )
        lld_report = _parse_json_with_repair(lld_raw, llm, f"Cloud LLD ({provider})")
        logger.info("Cloud LLD (%s) generated", provider)
    except Exception as exc:
        logger.error("Cloud LLD generation failed: %s", exc)
        lld_report = {"api_endpoints": []}

    return {
        "hld_report": _normalize_hld_report(hld_report),
        "lld_report": _normalize_lld_report(lld_report),
    }
