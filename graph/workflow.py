"""
LangGraph workflow — compiles the full agent pipeline into a runnable graph.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from langgraph.graph import END, StateGraph

from agents.cloud_infra import cloud_infra_agent
from agents.diagram import diagram_generator
from agents.diagram_quality import diagram_quality_agent
from agents.extractor import extract_requirements
from agents.generator import generate_architecture
from agents.report_generator import report_generator
from rules.edge_cases import inject_edge_cases as _inject_edge_cases
from schemas.models import AgentState, Requirements
from templates.base_templates import select_template as _select_template
from utils.workflow_contract import normalize_workflow_result, validate_workflow_result

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thin wrapper nodes for pure-Python steps
# ---------------------------------------------------------------------------

def _select_template_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — deterministic template selection."""
    requirements = Requirements.model_validate(state["requirements"])
    template_key = _select_template(requirements)
    return {"template": template_key}


def _inject_edge_cases_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — deterministic edge-case injection."""
    edge_cases = _inject_edge_cases(
        requirements=state["requirements"],
        architectures=state["architectures"],
    )
    return {"edge_cases": edge_cases}


def _select_primary_architecture_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node — choose base architecture without critic revision."""
    architectures = state.get("architectures", [])
    revised = architectures[0] if architectures else {}
    return {"revised_architecture": revised}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Construct and return the compiled LangGraph StateGraph."""
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("extract_requirements", extract_requirements)
    graph.add_node("select_template", _select_template_node)
    graph.add_node("generate_architecture", generate_architecture)
    graph.add_node("inject_edge_cases", _inject_edge_cases_node)
    graph.add_node("select_primary_architecture", _select_primary_architecture_node)
    graph.add_node("diagram_generator", diagram_generator)
    graph.add_node("diagram_quality_agent", diagram_quality_agent)
    graph.add_node("report_generator", report_generator)
    graph.add_node("cloud_infra_agent", cloud_infra_agent)

    # Linear edges
    graph.set_entry_point("extract_requirements")
    graph.add_edge("extract_requirements", "select_template")
    graph.add_edge("select_template", "generate_architecture")
    graph.add_edge("generate_architecture", "inject_edge_cases")
    graph.add_edge("inject_edge_cases", "select_primary_architecture")
    graph.add_edge("select_primary_architecture", "diagram_generator")
    graph.add_edge("diagram_generator", "diagram_quality_agent")
    graph.add_edge("diagram_quality_agent", "report_generator")
    graph.add_edge("report_generator", "cloud_infra_agent")
    graph.add_edge("cloud_infra_agent", END)

    return graph.compile()


# Singleton compiled graph
_compiled_graph = None


def get_graph():
    """Return the singleton compiled graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _build_initial_state(
    user_input: str,
    diagram_style: str,
    preferred_language: str,
) -> AgentState:
    return {
        "user_input": user_input,
        "diagram_style": diagram_style,
        "preferred_language": preferred_language,
        "requirements": {},
        "template": "",
        "architectures": [],
        "edge_cases": [],
        "critic_feedback": [],
        "revised_architecture": {},
        "mermaid_code": "",
        "excalidraw_diagram": {},
        "diagram_quality_checks": [],
        "hld_report": {},
        "lld_report": {},
        "tech_stack": {},
        "cloud_infrastructure": {},
    }


def run_workflow_with_updates(
    user_input: str,
    diagram_style: str = "balanced",
    preferred_language: str = "Python",
    on_update: Callable[[str, Dict[str, Any], Dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    """Execute the graph while exposing per-node updates to callers."""
    logger.info("Starting workflow for input: %s", user_input[:120])

    initial_state = _build_initial_state(user_input, diagram_style, preferred_language)
    state: Dict[str, Any] = dict(initial_state)
    graph = get_graph()

    for update in graph.stream(initial_state, stream_mode="updates"):
        if not isinstance(update, dict):
            continue
        for node_key, node_payload in update.items():
            if isinstance(node_payload, dict):
                state.update(node_payload)
                if on_update:
                    on_update(str(node_key), node_payload, dict(state))

    state = normalize_workflow_result(state)
    validate_workflow_result(state)
    logger.info("Workflow completed successfully")
    return state

def run_workflow(
    user_input: str,
    diagram_style: str = "balanced",
    preferred_language: str = "Python",
) -> Dict[str, Any]:
    """Execute the full agent pipeline and return the final state.

    Parameters
    ----------
    user_input : str
        Free-text system design request from the user.

    Returns
    -------
    Dict[str, Any]
        The completed ``AgentState`` dictionary.
    """
    return run_workflow_with_updates(
        user_input,
        diagram_style=diagram_style,
        preferred_language=preferred_language,
    )
