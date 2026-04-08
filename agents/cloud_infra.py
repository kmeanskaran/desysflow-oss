"""
Cloud Infrastructure Agent — maps architecture to cloud services across providers
and extracts a structured tech stack breakdown.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from schemas.models import AgentState
from services.llm import get_llm
from utils.parser import extract_json_block, normalize_llm_text

logger = logging.getLogger(__name__)


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

            json_str = extract_json_block(raw)
            data = json.loads(json_str)

            tech_stack = data.get("tech_stack", {})
            cloud_infra = data.get("cloud_infrastructure", {})

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
            logger.warning("Cloud infra generation failed on attempt %d: %s", attempt, exc)
            messages.append({"role": "assistant", "content": raw if "raw" in dir() else ""})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was not valid JSON. "
                    "Please respond with ONLY a valid JSON object matching the schema."
                ),
            })

    # Fallback
    logger.error("Cloud infra generation failed after %d attempts: %s", max_attempts, last_error)
    return {
        "tech_stack": {
            "languages": [preferred_language],
            "frameworks": ["FastAPI", "React"],
            "databases": revised.get("databases", []),
            "message_queues": revised.get("message_queues", []),
            "caching": revised.get("caching_layer", []),
            "monitoring": ["Prometheus", "Grafana"],
            "ci_cd": ["GitHub Actions"],
            "containerization": ["Docker"],
        },
        "cloud_infrastructure": {
            "aws": {"compute": ["ECS"], "database": ["RDS"], "cache": ["ElastiCache"], "queue": ["SQS"], "storage": ["S3"], "cdn": ["CloudFront"], "monitoring": ["CloudWatch"], "networking": ["ALB"]},
            "gcp": {"compute": ["Cloud Run"], "database": ["Cloud SQL"], "cache": ["Memorystore"], "queue": ["Pub/Sub"], "storage": ["GCS"], "cdn": ["Cloud CDN"], "monitoring": ["Cloud Monitoring"], "networking": ["Cloud Load Balancing"]},
            "azure": {"compute": ["AKS"], "database": ["Azure SQL"], "cache": ["Azure Cache"], "queue": ["Service Bus"], "storage": ["Blob Storage"], "cdn": ["Azure CDN"], "monitoring": ["Azure Monitor"], "networking": ["Application Gateway"]},
            "digitalocean": {"compute": ["App Platform"], "database": ["Managed DB"], "cache": ["Managed Redis"], "queue": ["N/A"], "storage": ["Spaces"], "cdn": ["Spaces CDN"], "monitoring": ["Monitoring"], "networking": ["Load Balancer"]},
            "on_prem": {"compute": ["Kubernetes"], "database": ["Self-hosted"], "cache": ["Redis"], "queue": ["RabbitMQ"], "storage": ["MinIO"], "cdn": ["Nginx"], "monitoring": ["Prometheus + Grafana"], "networking": ["HAProxy"]},
            "local": {"compute": ["Docker Compose / Podman"], "database": ["PostgreSQL / SQLite"], "cache": ["Redis"], "queue": ["RabbitMQ / Kafka"], "storage": ["Local filesystem / MinIO"], "cdn": ["Nginx"], "monitoring": ["Prometheus + Grafana"], "networking": ["Docker Network"]},
        },
    }
