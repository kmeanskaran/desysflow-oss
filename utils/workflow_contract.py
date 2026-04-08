"""Shared workflow status and completeness rules for CLI and API/UI."""

from __future__ import annotations

from typing import Any, Dict


DESIGN_PROGRESS_STEPS = [
    {"key": "scope", "label": "Reading prompt and constraints"},
    {"key": "extract", "label": "Extracting requirements in parallel"},
    {"key": "draft", "label": "Drafting architecture, diagram, and reports"},
    {"key": "review", "label": "Reviewer loop improving consistency"},
    {"key": "package", "label": "Packaging final artifacts"},
]

FOLLOWUP_PROGRESS_STEPS = [
    {"key": "context", "label": "Loading current design context"},
    {"key": "update", "label": "Updating requirements and trade-offs"},
    {"key": "draft", "label": "Refreshing architecture and reports"},
    {"key": "review", "label": "Running reviewer loop"},
    {"key": "package", "label": "Returning updated artifacts"},
]

DESIGN_NODE_TO_STAGE = {
    "extract_requirements": "extract",
    "select_template": "extract",
    "generate_architecture": "draft",
    "inject_edge_cases": "draft",
    "select_primary_architecture": "draft",
    "diagram_generator": "draft",
    "diagram_quality_agent": "review",
    "report_generator": "review",
    "cloud_infra_agent": "package",
}

FOLLOWUP_NODE_TO_STAGE = {
    "extract_requirements": "update",
    "select_template": "update",
    "generate_architecture": "draft",
    "inject_edge_cases": "draft",
    "select_primary_architecture": "draft",
    "diagram_generator": "draft",
    "diagram_quality_agent": "review",
    "report_generator": "review",
    "cloud_infra_agent": "package",
}


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and len(value) > 0


def _append_missing(missing: list[str], value: Any, label: str, *, kind: str = "string") -> None:
    validators = {
        "string": _non_empty_string,
        "list": _non_empty_list,
        "dict": _non_empty_dict,
    }
    if not validators[kind](value):
        missing.append(label)


def validate_workflow_result(result: Dict[str, Any]) -> None:
    """Raise if the workflow result is incomplete for final delivery."""
    if not isinstance(result, dict):
        raise ValueError("Workflow result is not a dictionary")

    missing: list[str] = []

    requirements = result.get("requirements", {})
    _append_missing(missing, requirements, "requirements", kind="dict")
    if isinstance(requirements, dict):
        for key in [
            "traffic_estimate",
            "latency_requirement",
            "consistency_requirement",
            "budget_constraint",
            "region",
            "scale_growth_projection",
        ]:
            _append_missing(missing, requirements.get(key), f"requirements.{key}")
        if "critical_features" not in requirements or not isinstance(requirements.get("critical_features"), list):
            missing.append("requirements.critical_features")

    architectures = result.get("architectures", [])
    _append_missing(missing, architectures, "architectures", kind="list")

    final_architecture = result.get("revised_architecture", {})
    _append_missing(missing, final_architecture, "revised_architecture", kind="dict")
    if isinstance(final_architecture, dict):
        _append_missing(missing, final_architecture.get("services"), "revised_architecture.services", kind="list")
        _append_missing(missing, final_architecture.get("databases"), "revised_architecture.databases", kind="list")
        _append_missing(missing, final_architecture.get("scaling_strategy"), "revised_architecture.scaling_strategy")
        _append_missing(missing, final_architecture.get("monitoring_metrics"), "revised_architecture.monitoring_metrics", kind="list")

    _append_missing(missing, result.get("mermaid_code"), "mermaid_code")

    hld_report = result.get("hld_report", {})
    _append_missing(missing, hld_report, "hld_report", kind="dict")
    if isinstance(hld_report, dict):
        _append_missing(missing, hld_report.get("system_overview"), "hld_report.system_overview")
        _append_missing(missing, hld_report.get("components"), "hld_report.components", kind="list")
        _append_missing(missing, hld_report.get("data_flow"), "hld_report.data_flow", kind="list")
        _append_missing(missing, hld_report.get("scaling_strategy"), "hld_report.scaling_strategy")
        _append_missing(missing, hld_report.get("availability"), "hld_report.availability")
        _append_missing(missing, hld_report.get("trade_offs"), "hld_report.trade_offs", kind="list")
        _append_missing(missing, hld_report.get("estimated_capacity"), "hld_report.estimated_capacity", kind="dict")

    lld_report = result.get("lld_report", {})
    _append_missing(missing, lld_report, "lld_report", kind="dict")
    if isinstance(lld_report, dict):
        _append_missing(missing, lld_report.get("api_endpoints"), "lld_report.api_endpoints", kind="list")
        _append_missing(missing, lld_report.get("database_schemas"), "lld_report.database_schemas", kind="list")
        _append_missing(missing, lld_report.get("service_communication"), "lld_report.service_communication", kind="list")
        _append_missing(missing, lld_report.get("caching_strategy"), "lld_report.caching_strategy", kind="list")
        _append_missing(missing, lld_report.get("error_handling"), "lld_report.error_handling", kind="list")
        _append_missing(missing, lld_report.get("deployment"), "lld_report.deployment", kind="dict")
        _append_missing(missing, lld_report.get("security"), "lld_report.security", kind="list")

    tech_stack = result.get("tech_stack", {})
    _append_missing(missing, tech_stack, "tech_stack", kind="dict")
    if isinstance(tech_stack, dict):
        for key in [
            "languages",
            "frameworks",
            "databases",
            "message_queues",
            "caching",
            "monitoring",
            "ci_cd",
            "containerization",
        ]:
            if key not in tech_stack or not isinstance(tech_stack.get(key), list):
                missing.append(f"tech_stack.{key}")

    cloud_infra = result.get("cloud_infrastructure", {})
    _append_missing(missing, cloud_infra, "cloud_infrastructure", kind="dict")
    if isinstance(cloud_infra, dict):
        for provider in ["aws", "gcp", "azure", "digitalocean", "on_prem", "local"]:
            provider_data = cloud_infra.get(provider)
            _append_missing(missing, provider_data, f"cloud_infrastructure.{provider}", kind="dict")
            if isinstance(provider_data, dict):
                for key in [
                    "compute",
                    "database",
                    "cache",
                    "queue",
                    "storage",
                    "cdn",
                    "monitoring",
                    "networking",
                ]:
                    _append_missing(
                        missing,
                        provider_data.get(key),
                        f"cloud_infrastructure.{provider}.{key}",
                        kind="list",
                    )

    if missing:
        raise ValueError("Incomplete workflow output: " + ", ".join(missing))


def validate_delivery_payload(
    result: Dict[str, Any],
    system_design_doc: Dict[str, Any],
    non_technical_doc: Dict[str, Any],
) -> None:
    validate_workflow_result(result)
    if not _non_empty_dict(system_design_doc):
        raise ValueError("Incomplete workflow output: system_design_doc")
    if not _non_empty_dict(non_technical_doc):
        raise ValueError("Incomplete workflow output: non_technical_doc")
