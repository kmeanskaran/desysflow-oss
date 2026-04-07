"""
System design document builder from workflow outputs.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def build_system_design_doc(result: Dict[str, Any]) -> Dict[str, Any]:
    """Build a single mixed HLD/LLD design document payload."""
    hld = result.get("hld_report", {}) or {}
    lld = result.get("lld_report", {}) or {}
    revised = result.get("revised_architecture", {}) or {}
    tech_stack = result.get("tech_stack", {}) or {}
    cloud_infra = result.get("cloud_infrastructure", {}) or {}
    requirements = result.get("requirements", {}) or {}

    components = _as_list(hld.get("components"))
    api_endpoints = _as_list(lld.get("api_endpoints"))
    db_schemas = _as_list(lld.get("database_schemas"))
    service_comm = _as_list(lld.get("service_communication"))
    caching = _as_list(lld.get("caching_strategy"))
    errors = _as_list(lld.get("error_handling"))
    security = _as_list(lld.get("security"))
    tech_languages = _as_list(tech_stack.get("languages"))
    preferred_language = requirements.get("preferred_language", "") or (tech_languages[0] if tech_languages else "Python")
    future_improvements = [
        "Add SLO-driven autoscaling and capacity guardrails for burst traffic.",
        "Introduce contract testing and schema governance for service-to-service APIs.",
        "Add progressive delivery controls (canary/rollback) with tighter release observability.",
        "Expand threat modeling and runtime security checks for critical data paths.",
    ]

    return {
        "title": "System Design Document",
        "meta": {
            "preferred_language": preferred_language,
            "implementation_contract": (
                "This document is intended to be implementation-ready for coding agents. "
                "Treat APIs, data flow, deployment constraints, and service boundaries as the source of truth."
            ),
        },
        "overview": {
            "summary": hld.get("system_overview", ""),
            "requirements": requirements,
            "capacity": hld.get("estimated_capacity", {}),
        },
        "architecture": {
            "services": _as_list(revised.get("services")),
            "databases": _as_list(revised.get("databases")),
            "message_queues": _as_list(revised.get("message_queues")),
            "caching_layer": _as_list(revised.get("caching_layer")),
            "components": components,
            "data_flow": _as_list(hld.get("data_flow")),
            "scaling_strategy": hld.get("scaling_strategy", revised.get("scaling_strategy", "")),
            "availability": hld.get("availability", ""),
            "trade_offs": _as_list(hld.get("trade_offs")),
        },
        "implementation": {
            "api_endpoints": api_endpoints,
            "database_schemas": db_schemas,
            "service_communication": service_comm,
            "caching_strategy": caching,
            "error_handling": errors,
            "deployment": lld.get("deployment", {}) if isinstance(lld.get("deployment"), dict) else {},
            "security": security,
        },
        "platform": {
            "tech_stack": tech_stack,
            "cloud_infrastructure": cloud_infra,
        },
        "future_improvements": future_improvements,
    }
