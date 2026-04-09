import pytest

from utils.workflow_contract import (
    normalize_workflow_result,
    validate_delivery_payload,
    validate_workflow_result,
)


def _valid_result():
    return {
        "requirements": {
            "traffic_estimate": "5M DAU",
            "latency_requirement": "<100ms p99",
            "consistency_requirement": "eventual",
            "budget_constraint": "moderate",
            "region": "us-east-1",
            "scale_growth_projection": "3x in 12 months",
            "critical_features": ["recommendations", "history"],
        },
        "architectures": [{"services": ["API Gateway", "Recommender"]}],
        "revised_architecture": {
            "services": ["API Gateway", "Recommender"],
            "databases": ["PostgreSQL"],
            "message_queues": ["Kafka"],
            "caching_layer": ["Redis"],
            "scaling_strategy": "Horizontal scaling",
            "bottlenecks": ["Hot partitions"],
            "monitoring_metrics": ["latency_p99", "throughput"],
        },
        "mermaid_code": "flowchart TD\nA-->B",
        "hld_report": {
            "system_overview": "Recommendation platform.",
            "components": [{"name": "API Gateway"}],
            "data_flow": ["User request reaches gateway."],
            "scaling_strategy": "Horizontal",
            "availability": "Multi-AZ",
            "trade_offs": ["Eventual consistency"],
            "estimated_capacity": {"requests_per_second": "10k", "storage": "5TB", "bandwidth": "2Gbps"},
        },
        "lld_report": {
            "api_endpoints": [{"method": "POST", "path": "/feed"}],
            "database_schemas": [{"name": "users", "type": "PostgreSQL"}],
            "service_communication": [{"from": "api", "to": "recommender", "protocol": "gRPC"}],
            "caching_strategy": [{"layer": "feed", "technology": "Redis"}],
            "error_handling": [{"scenario": "timeout", "strategy": "retry", "fallback": "cached"}],
            "deployment": {"containerization": "Docker"},
            "security": ["JWT"],
        },
        "tech_stack": {
            "languages": ["Python"],
            "frameworks": ["FastAPI"],
            "databases": ["PostgreSQL"],
            "message_queues": ["Kafka"],
            "caching": ["Redis"],
            "monitoring": ["Prometheus"],
            "ci_cd": ["GitHub Actions"],
            "containerization": ["Docker"],
        },
        "cloud_infrastructure": {
            provider: {
                "compute": ["service"],
                "database": ["db"],
                "cache": ["cache"],
                "queue": ["queue"],
                "storage": ["storage"],
                "cdn": ["cdn"],
                "monitoring": ["monitoring"],
                "networking": ["networking"],
            }
            for provider in ["aws", "gcp", "azure", "digitalocean", "on_prem", "local"]
        },
    }


def test_validate_workflow_result_accepts_complete_payload() -> None:
    validate_workflow_result(_valid_result())


def test_validate_workflow_result_rejects_missing_hld_content() -> None:
    result = _valid_result()
    result["hld_report"] = {}

    with pytest.raises(ValueError, match="hld_report"):
        validate_workflow_result(result)


def test_validate_delivery_payload_rejects_empty_postprocessed_docs() -> None:
    with pytest.raises(ValueError, match="system_design_doc"):
        validate_delivery_payload(_valid_result(), {}, {"summary": "brief"})


def test_normalize_workflow_result_backfills_required_hld_fields() -> None:
    result = _valid_result()
    result["hld_report"] = {"system_overview": "Custom overview"}
    normalized = normalize_workflow_result(result)

    assert normalized["hld_report"]["system_overview"] == "Custom overview"
    assert normalized["hld_report"]["scaling_strategy"]
    assert normalized["hld_report"]["availability"]
    assert normalized["hld_report"]["trade_offs"]
    assert normalized["hld_report"]["estimated_capacity"]

    validate_workflow_result(normalized)
