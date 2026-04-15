"""
Cloud Infrastructure Agent — maps architecture to cloud services across providers
and extracts a structured tech stack breakdown.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any, Dict

from schemas.models import AgentState
from services.llm import get_llm
from utils.parser import normalize_llm_text, parse_json_block_loose

logger = logging.getLogger(__name__)

_TECH_STACK_KEYS = [
    "languages",
    "frameworks",
    "databases",
    "message_queues",
    "caching",
    "monitoring",
    "ci_cd",
    "containerization",
]

_PROVIDERS = ["aws", "gcp", "azure", "digitalocean", "on_prem", "local"]
_CLOUD_KEYS = ["compute", "database", "cache", "queue", "storage", "cdn", "monitoring", "networking"]

_CLOUD_DEFAULTS = {
    "aws": {"compute": ["ECS"], "database": ["RDS"], "cache": ["ElastiCache"], "queue": ["SQS"], "storage": ["S3"], "cdn": ["CloudFront"], "monitoring": ["CloudWatch"], "networking": ["ALB"]},
    "gcp": {"compute": ["Cloud Run"], "database": ["Cloud SQL"], "cache": ["Memorystore"], "queue": ["Pub/Sub"], "storage": ["GCS"], "cdn": ["Cloud CDN"], "monitoring": ["Cloud Monitoring"], "networking": ["Cloud Load Balancing"]},
    "azure": {"compute": ["AKS"], "database": ["Azure SQL"], "cache": ["Azure Cache for Redis"], "queue": ["Service Bus"], "storage": ["Blob Storage"], "cdn": ["Azure CDN"], "monitoring": ["Azure Monitor"], "networking": ["Application Gateway"]},
    "digitalocean": {"compute": ["App Platform"], "database": ["Managed PostgreSQL"], "cache": ["Managed Redis"], "queue": ["Kafka (managed/third-party)"], "storage": ["Spaces"], "cdn": ["Spaces CDN"], "monitoring": ["DigitalOcean Monitoring"], "networking": ["Load Balancer"]},
    "on_prem": {"compute": ["Kubernetes"], "database": ["Self-hosted PostgreSQL"], "cache": ["Redis"], "queue": ["RabbitMQ"], "storage": ["MinIO"], "cdn": ["Nginx"], "monitoring": ["Prometheus + Grafana"], "networking": ["HAProxy"]},
    "local": {"compute": ["Docker Compose"], "database": ["PostgreSQL / SQLite"], "cache": ["Redis"], "queue": ["RabbitMQ"], "storage": ["Local filesystem / MinIO"], "cdn": ["Nginx"], "monitoring": ["Prometheus + Grafana"], "networking": ["Docker Network"]},
}


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _normalize_tech_stack(tech_stack: Any, preferred_language: str) -> dict:
    data = tech_stack if isinstance(tech_stack, dict) else {}
    normalized = {
        "languages": [preferred_language],
        "frameworks": ["FastAPI", "React"],
        "databases": ["PostgreSQL"],
        "message_queues": ["RabbitMQ"],
        "caching": ["Redis"],
        "monitoring": ["Prometheus", "Grafana"],
        "ci_cd": ["GitHub Actions"],
        "containerization": ["Docker"],
    }
    for key in _TECH_STACK_KEYS:
        if _non_empty_list(data.get(key)):
            normalized[key] = data[key]
    return normalized


def _normalize_cloud_infrastructure(cloud_infrastructure: Any) -> dict:
    data = cloud_infrastructure if isinstance(cloud_infrastructure, dict) else {}
    normalized: dict[str, dict[str, list[str]]] = {}

    for provider in _PROVIDERS:
        provider_data = data.get(provider, {})
        provider_defaults = _CLOUD_DEFAULTS[provider]
        normalized_provider = deepcopy(provider_defaults)
        if isinstance(provider_data, dict):
            for key in _CLOUD_KEYS:
                if _non_empty_list(provider_data.get(key)):
                    normalized_provider[key] = provider_data[key]
        normalized[provider] = normalized_provider
    return normalized


_SYSTEM_PROMPT = """You are a cloud infrastructure architect with deep expertise in
AWS, GCP, Azure, DigitalOcean, on-premises, and local/self-hosted deployments.

Given a system architecture and requirements, you must produce TWO things:

1. A tech_stack object categorising all technologies used
2. A cloud_infrastructure object mapping every architecture component to the equivalent
   managed service on each cloud provider

You MUST respond with ONLY a valid JSON object with these exact keys:

{
  "tech_stack": {
    "languages": ["list of programming languages"],
    "frameworks": ["list of frameworks"],
    "databases": ["list of database technologies"],
    "message_queues": ["list of queue/streaming systems"],
    "caching": ["list of caching technologies"],
    "monitoring": ["list of monitoring/observability tools"],
    "ci_cd": ["list of CI/CD tools"],
    "containerization": ["list of container technologies"]
  },
  "cloud_infrastructure": {
    "aws": {
      "compute": ["e.g. ECS, EKS, Lambda"],
      "database": ["e.g. RDS PostgreSQL, DynamoDB"],
      "cache": ["e.g. ElastiCache Redis"],
      "queue": ["e.g. SQS, MSK"],
      "storage": ["e.g. S3"],
      "cdn": ["e.g. CloudFront"],
      "monitoring": ["e.g. CloudWatch, X-Ray"],
      "networking": ["e.g. ALB, API Gateway, Route 53"]
    },
    "gcp": {
      "compute": [], "database": [], "cache": [], "queue": [],
      "storage": [], "cdn": [], "monitoring": [], "networking": []
    },
    "azure": {
      "compute": [], "database": [], "cache": [], "queue": [],
      "storage": [], "cdn": [], "monitoring": [], "networking": []
    },
    "digitalocean": {
      "compute": [], "database": [], "cache": [], "queue": [],
      "storage": [], "cdn": [], "monitoring": [], "networking": []
    },
    "on_prem": {
      "compute": [], "database": [], "cache": [], "queue": [],
      "storage": [], "cdn": [], "monitoring": [], "networking": []
    },
    "local": {
      "compute": [], "database": [], "cache": [], "queue": [],
      "storage": [], "cdn": [], "monitoring": [], "networking": []
    }
  }
}

Fill in ALL providers with real, specific service names. Be precise and practical.
Respond with ONLY the JSON object — no explanation, no markdown."""


def cloud_infra_agent(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — generate tech stack and cloud infrastructure mappings."""
    revised = state.get("revised_architecture", {})
    requirements = state.get("requirements", {})
    user_input = state.get("user_input", "")
    preferred_language = state.get("preferred_language", "Python")

    logger.info("Generating tech stack and cloud infrastructure mappings")

    user_content = (
        f"User request: {user_input}\n\n"
        f"Preferred implementation language: {preferred_language}\n\n"
        f"Requirements:\n{json.dumps(requirements, indent=2)}\n\n"
        f"Architecture:\n{json.dumps(revised, indent=2)}\n\n"
        "Generate the tech stack and cloud infrastructure mappings as a JSON object."
    )

    llm = get_llm()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    max_attempts = 2
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = llm.invoke(messages)
            raw = normalize_llm_text(
                response.content if hasattr(response, "content") else response
            )
            logger.debug("Cloud infra response (attempt %d): %s", attempt, raw[:500])

            data = parse_json_block_loose(raw)
            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object from cloud infra agent, got {type(data).__name__}")

            tech_stack = _normalize_tech_stack(data.get("tech_stack", {}), preferred_language)
            cloud_infra = _normalize_cloud_infrastructure(data.get("cloud_infrastructure", {}))

            logger.info(
                "Cloud infra generated: %d providers, tech stack with %d categories",
                len(cloud_infra),
                len(tech_stack),
            )
            return {
                "tech_stack": tech_stack,
                "cloud_infrastructure": cloud_infra,
            }

        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                logger.info("Cloud infra: retrying with stricter JSON request")
            else:
                logger.warning("Cloud infra generation failed on final attempt: %s", exc)
            messages.append({"role": "assistant", "content": raw if "raw" in dir() else ""})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was not valid JSON. "
                    "Please respond with ONLY a valid JSON object matching the schema."
                ),
            })

    # Fallback
    logger.warning("Cloud infra fallback applied after %d attempts", max_attempts)
    tech_stack_fallback = {
        "languages": [preferred_language],
        "frameworks": ["FastAPI", "React"],
        "databases": revised.get("databases", []),
        "message_queues": revised.get("message_queues", []),
        "caching": revised.get("caching_layer", []),
        "monitoring": ["Prometheus", "Grafana"],
        "ci_cd": ["GitHub Actions"],
        "containerization": ["Docker"],
    }
    return {
        "tech_stack": _normalize_tech_stack(tech_stack_fallback, preferred_language),
        "cloud_infrastructure": _normalize_cloud_infrastructure(_CLOUD_DEFAULTS),
    }
