"""
Diagram Quality Agent — produces a clean minimal Mermaid diagram and
an Excalidraw-like JSON graph spec for frontend rendering.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Tuple

from schemas.models import AgentState
from services.llm import get_llm
from utils.parser import extract_json_block, normalize_llm_text

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are a principal architecture diagram quality reviewer.

Your job is to produce MINIMAL, high-signal system design diagrams.

Context-engineering constraints (must follow):
1. Keep the diagram compact:
   - max 12 nodes
   - max 14 edges
2. Use only essential concepts:
   - Client
   - Edge/Gateway
   - Core Services
   - Data Store
   - Cache
   - Async Queue/Stream (if relevant)
   - Observability/Security (grouped, optional if needed)
3. Avoid over-detail and avoid repeated technologies.
4. Use clear labels and clean linear flow with one failure/edge-case path.
5. Output must be implementation-ready for UI rendering.

Return ONLY valid JSON with this exact structure:
{
  "mermaid_code": "flowchart TD ...",
  "excalidraw_diagram": {
    "nodes": [
      {"id": "n1", "label": "Client", "kind": "client"},
      {"id": "n2", "label": "API Gateway", "kind": "edge"}
    ],
    "edges": [
      {"from": "n1", "to": "n2", "label": "request"}
    ]
  },
  "quality_checks": [
    "short note 1",
    "short note 2"
  ]
}

Do not include markdown fences."""


def _sanitise_mermaid(raw: str) -> str:
    cleaned = re.sub(r"```(?:mermaid)?\s*\n?", "", raw)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    cleaned = cleaned.strip()
    if not cleaned.lower().startswith("flowchart"):
        cleaned = "flowchart TD\n" + cleaned
    return cleaned


def _kind_for(label: str) -> str:
    low = label.lower()
    if "client" in low or "user" in low:
        return "client"
    if "gateway" in low or "edge" in low or "load balancer" in low:
        return "edge"
    if "cache" in low or "redis" in low:
        return "cache"
    if "queue" in low or "kafka" in low or "stream" in low or "sqs" in low:
        return "async"
    if any(x in low for x in ["db", "postgres", "mysql", "mongo", "dynamo", "cassandra"]):
        return "data"
    if any(x in low for x in ["monitor", "observ", "security", "auth"]):
        return "ops"
    return "service"


def _fallback_from_architecture(architecture: Dict[str, Any]) -> Tuple[str, Dict[str, Any], List[str]]:
    services = architecture.get("services", [])[:5]
    databases = architecture.get("databases", [])[:1]
    queues = architecture.get("message_queues", [])[:1]
    caches = architecture.get("caching_layer", [])[:1]

    nodes: List[Dict[str, str]] = [
        {"id": "n1", "label": "Client", "kind": "client"},
        {"id": "n2", "label": "API Gateway", "kind": "edge"},
    ]
    edges: List[Dict[str, str]] = [{"from": "n1", "to": "n2", "label": "request"}]

    index = 3
    for svc in services:
        node_id = f"n{index}"
        nodes.append({"id": node_id, "label": str(svc), "kind": _kind_for(str(svc))})
        edges.append({"from": "n2", "to": node_id, "label": "route"})
        index += 1

    if databases:
        node_id = f"n{index}"
        nodes.append({"id": node_id, "label": str(databases[0]), "kind": "data"})
        if services:
            edges.append({"from": "n3", "to": node_id, "label": "read/write"})
        index += 1

    if caches:
        node_id = f"n{index}"
        nodes.append({"id": node_id, "label": str(caches[0]), "kind": "cache"})
        if services:
            edges.append({"from": "n3", "to": node_id, "label": "cache"})
        index += 1

    if queues:
        node_id = f"n{index}"
        nodes.append({"id": node_id, "label": str(queues[0]), "kind": "async"})
        if services:
            edges.append({"from": "n3", "to": node_id, "label": "publish"})

    # Keep compact
    nodes = nodes[:12]
    valid_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["from"] in valid_ids and e["to"] in valid_ids][:14]

    mermaid_lines = ["flowchart TD"]
    for node in nodes:
        mermaid_lines.append(f'    {node["id"]}["{node["label"].replace(chr(34), chr(39))}"]')
    for edge in edges:
        label = edge.get("label", "").replace('"', "'")
        if label:
            mermaid_lines.append(f'    {edge["from"]} -->|{label}| {edge["to"]}')
        else:
            mermaid_lines.append(f'    {edge["from"]} --> {edge["to"]}')

    return (
        "\n".join(mermaid_lines),
        {"nodes": nodes, "edges": edges},
        [
            "Fallback compact diagram used.",
            "Kept output within max node/edge budget.",
        ],
    )


def diagram_quality_agent(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — optimize diagram quality and produce Excalidraw-like spec."""
    revised = state.get("revised_architecture", {})
    requirements = state.get("requirements", {})
    edge_cases = state.get("edge_cases", [])
    base_mermaid = state.get("mermaid_code", "")
    style = str(state.get("diagram_style", "balanced")).lower().strip()
    if style not in {"minimal", "balanced", "detailed"}:
        style = "balanced"

    budgets = {
        "minimal": {"max_nodes": 8, "max_edges": 10},
        "balanced": {"max_nodes": 12, "max_edges": 14},
        "detailed": {"max_nodes": 16, "max_edges": 22},
    }[style]

    logger.info("Running diagram quality agent")

    user_content = (
        f"Diagram style: {style}\n"
        f"Style budget: max_nodes={budgets['max_nodes']}, max_edges={budgets['max_edges']}\n\n"
        f"Requirements:\n{json.dumps(requirements, indent=2)}\n\n"
        f"Architecture:\n{json.dumps(revised, indent=2)}\n\n"
        f"Edge cases:\n{json.dumps(edge_cases, indent=2)}\n\n"
        f"Base Mermaid (optional):\n{base_mermaid}\n\n"
        "Return compact high-quality mermaid + excalidraw_diagram JSON."
    )

    llm = get_llm()
    try:
        response = llm.invoke(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        raw = normalize_llm_text(
            response.content if hasattr(response, "content") else response
        )
        data = json.loads(extract_json_block(raw))

        mermaid = _sanitise_mermaid(str(data.get("mermaid_code", "")))
        excalidraw_diagram = data.get("excalidraw_diagram", {})
        if not isinstance(excalidraw_diagram, dict):
            excalidraw_diagram = {}
        quality_checks = data.get("quality_checks", [])
        if not isinstance(quality_checks, list):
            quality_checks = []

        nodes = excalidraw_diagram.get("nodes", [])
        edges = excalidraw_diagram.get("edges", [])
        if not isinstance(nodes, list):
            nodes = []
        if not isinstance(edges, list):
            edges = []
        excalidraw_diagram = {
            "nodes": nodes[: budgets["max_nodes"]],
            "edges": edges[: budgets["max_edges"]],
        }

        return {
            "mermaid_code": mermaid,
            "excalidraw_diagram": excalidraw_diagram,
            "diagram_quality_checks": [f"Applied style: {style}", *[str(x) for x in quality_checks]][:8],
        }
    except Exception as exc:
        logger.error("Diagram quality agent failed: %s", exc)
        mermaid, spec, checks = _fallback_from_architecture(revised)
        checks.append(f"Quality agent fallback reason: {exc}")
        return {
            "mermaid_code": mermaid,
            "excalidraw_diagram": spec,
            "diagram_quality_checks": checks,
        }
