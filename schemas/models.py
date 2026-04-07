"""
Pydantic v2 models and TypedDict state for the System Design AI Agent.
"""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LangGraph shared state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """Shared state flowing through the LangGraph pipeline."""
    user_input: str
    diagram_style: str
    preferred_language: str
    requirements: Dict[str, Any]
    template: str
    architectures: List[Dict[str, Any]]
    edge_cases: List[str]
    critic_feedback: List[str]
    revised_architecture: Dict[str, Any]
    mermaid_code: str
    excalidraw_diagram: Dict[str, Any]
    diagram_quality_checks: List[str]
    hld_report: Dict[str, Any]
    lld_report: Dict[str, Any]
    non_technical_doc: Dict[str, Any]
    tech_stack: Dict[str, Any]
    cloud_infrastructure: Dict[str, Any]


# ---------------------------------------------------------------------------
# Pydantic validation models
# ---------------------------------------------------------------------------

class Requirements(BaseModel):
    """Structured requirements extracted from user input."""
    traffic_estimate: str = Field(
        ..., description="Estimated traffic volume, e.g. '5M DAU'"
    )
    latency_requirement: str = Field(
        ..., description="Latency target, e.g. '<100ms p99'"
    )
    consistency_requirement: str = Field(
        ..., description="Consistency model, e.g. 'eventual' or 'strong'"
    )
    budget_constraint: str = Field(
        ..., description="Budget hint, e.g. 'moderate' or 'high'"
    )
    region: str = Field(
        ..., description="Primary deployment region"
    )
    scale_growth_projection: str = Field(
        ..., description="Expected growth, e.g. '3x in 12 months'"
    )
    critical_features: List[str] = Field(
        default_factory=list,
        description="List of business-critical features",
    )


class ArchitectureVariant(BaseModel):
    """A single architecture design variant."""
    services: List[str] = Field(
        default_factory=list, description="Micro-services / components"
    )
    databases: List[str] = Field(
        default_factory=list, description="Database technologies"
    )
    message_queues: List[str] = Field(
        default_factory=list, description="Message queue / streaming systems"
    )
    caching_layer: List[str] = Field(
        default_factory=list, description="Caching technologies"
    )
    scaling_strategy: str = Field(
        ..., description="Scaling approach"
    )
    bottlenecks: List[str] = Field(
        default_factory=list, description="Known bottlenecks"
    )
    monitoring_metrics: List[str] = Field(
        default_factory=list, description="Key metrics to monitor"
    )


# ---------------------------------------------------------------------------
# FastAPI request / response models
# ---------------------------------------------------------------------------

class DesignRequest(BaseModel):
    """POST /design request body."""
    input: str = Field(..., description="Free-text system design prompt")
    preferred_language: str = Field(
        default="Python",
        description="Preferred implementation language for generated design artifacts",
    )
    diagram_style: str = Field(
        default="balanced",
        description="Diagram density style: minimal, balanced, detailed",
    )
    provider: str = Field(
        default="",
        description="LLM provider override: openai, anthropic, or ollama",
    )
    model: str = Field(
        default="",
        description="Model name override. If empty, uses the default for the provider.",
    )
    api_key: str = Field(
        default="",
        description="Optional runtime API key override (OpenAI/Anthropic only).",
    )
    base_url: str = Field(
        default="",
        description="Optional runtime provider base URL override.",
    )
    role: str = Field(
        default="",
        description="Design role/persona, e.g. DevOps or Principal Architect.",
    )
    report_style: str = Field(
        default="balanced",
        description="Report depth style: minimal, balanced, detailed.",
    )
    cloud_target: str = Field(
        default="local",
        description="Cloud target preference: local, aws, gcp, azure, hybrid.",
    )
    search_mode: str = Field(
        default="auto",
        description="Web search preference: auto, on, off.",
    )


class DesignResponse(BaseModel):
    """POST /design response body."""
    session_id: str = Field(default="")
    diagram_style: str = Field(default="balanced")
    preferred_language: str = Field(default="Python")
    chat_history: List[Dict[str, str]] = Field(default_factory=list)
    requirements: Dict[str, Any]
    architectures: List[Dict[str, Any]]
    critic_feedback: List[str]
    critic_summary: Dict[str, Any] = Field(default_factory=dict)
    final_architecture: Dict[str, Any]
    system_design_doc: Dict[str, Any] = Field(default_factory=dict)
    non_technical_doc: Dict[str, Any] = Field(default_factory=dict)
    mermaid_code: str
    excalidraw_diagram: Dict[str, Any] = Field(default_factory=dict)
    hld_report: Dict[str, Any] = Field(default_factory=dict)
    lld_report: Dict[str, Any] = Field(default_factory=dict)
    tech_stack: Dict[str, Any] = Field(default_factory=dict)
    cloud_infrastructure: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    execution_mode: str = Field(default="full")


class ReviewRequest(BaseModel):
    """POST /review request body."""
    architecture: Dict[str, Any] = Field(
        ..., description="Architecture JSON to review"
    )


class ReviewResponse(BaseModel):
    """POST /review response body."""
    critic_feedback: List[str]
    suggested_improvements: List[str]


class CloudRedesignRequest(BaseModel):
    """POST /design/cloud-redesign request body."""
    provider: str = Field(
        ..., description="Cloud provider key: aws, gcp, azure, digitalocean, on_prem"
    )
    architecture: Dict[str, Any] = Field(
        default_factory=dict, description="Current architecture JSON"
    )
    requirements: Dict[str, Any] = Field(
        default_factory=dict, description="Extracted requirements"
    )
    cloud_infrastructure: Dict[str, Any] = Field(
        default_factory=dict, description="Existing cloud mappings keyed by provider"
    )
    user_input: str = Field(
        default="", description="Original user prompt"
    )


class CloudRedesignResponse(BaseModel):
    """POST /design/cloud-redesign response body."""
    mermaid_code: str
    hld_report: Dict[str, Any] = Field(default_factory=dict)
    lld_report: Dict[str, Any] = Field(default_factory=dict)
    cloud_services: Dict[str, Any] = Field(default_factory=dict)


class FollowUpRequest(BaseModel):
    """POST /design/followup request body."""
    session_id: str = Field(..., description="Session id returned by POST /design")
    message: str = Field(..., description="Follow-up question or change request")
    preferred_language: str = Field(
        default="Python",
        description="Preferred implementation language for regenerated artifacts",
    )
    diagram_style: str = Field(
        default="balanced",
        description="Diagram density style: minimal, balanced, detailed",
    )
    preserve_core_diagram: bool = Field(
        default=True,
        description="If true, keeps existing core diagram structure and only applies incremental add/remove changes.",
    )
    provider: str = Field(
        default="",
        description="LLM provider override: openai, anthropic, or ollama",
    )
    model: str = Field(
        default="",
        description="Model name override. If empty, uses the default for the provider.",
    )
    api_key: str = Field(
        default="",
        description="Optional runtime API key override (OpenAI/Anthropic only).",
    )
    base_url: str = Field(
        default="",
        description="Optional runtime provider base URL override.",
    )
    role: str = Field(
        default="",
        description="Design role/persona, e.g. DevOps or Principal Architect.",
    )
    report_style: str = Field(
        default="balanced",
        description="Report depth style: minimal, balanced, detailed.",
    )
    cloud_target: str = Field(
        default="local",
        description="Cloud target preference: local, aws, gcp, azure, hybrid.",
    )
    search_mode: str = Field(
        default="auto",
        description="Web search preference: auto, on, off.",
    )


class LLMCheckRequest(BaseModel):
    """POST /health/llm-check request body."""
    provider: str = Field(
        default="",
        description="Provider to validate: openai, anthropic, or ollama.",
    )
    model: str = Field(
        default="",
        description="Model to validate.",
    )
    api_key: str = Field(
        default="",
        description="API key for OpenAI/Anthropic checks.",
    )
    base_url: str = Field(
        default="",
        description="Provider base URL override for connectivity checks.",
    )


class FollowUpResponse(BaseModel):
    """POST /design/followup response body."""
    session_id: str
    diagram_style: str = Field(default="balanced")
    preferred_language: str = Field(default="Python")
    chat_history: List[Dict[str, str]] = Field(default_factory=list)
    requirements: Dict[str, Any] = Field(default_factory=dict)
    architectures: List[Dict[str, Any]] = Field(default_factory=list)
    critic_feedback: List[str] = Field(default_factory=list)
    critic_summary: Dict[str, Any] = Field(default_factory=dict)
    final_architecture: Dict[str, Any] = Field(default_factory=dict)
    system_design_doc: Dict[str, Any] = Field(default_factory=dict)
    non_technical_doc: Dict[str, Any] = Field(default_factory=dict)
    mermaid_code: str = Field(default="")
    excalidraw_diagram: Dict[str, Any] = Field(default_factory=dict)
    hld_report: Dict[str, Any] = Field(default_factory=dict)
    lld_report: Dict[str, Any] = Field(default_factory=dict)
    tech_stack: Dict[str, Any] = Field(default_factory=dict)
    cloud_infrastructure: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    execution_mode: str = Field(default="full")


class DesignCriticRequest(BaseModel):
    """POST /design/critic request body."""
    session_id: str = Field(..., description="Session id returned by POST /design")
    focus: str = Field(
        default="",
        description="Optional review focus, e.g. security hardening or cost optimization",
    )
    search_mode: str = Field(
        default="on",
        description="Web search mode for critic grounding: on | off",
    )


class DesignCriticResponse(BaseModel):
    """POST /design/critic response body."""
    session_id: str
    critic_feedback: List[str] = Field(default_factory=list)
    critic_summary: Dict[str, Any] = Field(default_factory=dict)
    suggested_improvements: List[str] = Field(default_factory=list)
    overall_verdict: str = Field(default="major_rework_required")
    risk_score: int = Field(default=70)
    reasoning_summary: str = Field(default="")


class ConversationListItem(BaseModel):
    """Conversation entry for sidebar listing."""

    session_id: str
    title: str
    preview: str = Field(default="")
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    """GET /conversations response body."""

    conversations: List[ConversationListItem] = Field(default_factory=list)


class ConversationDetailResponse(BaseModel):
    """GET /conversations/{session_id} response body."""

    session_id: str
    title: str
    created_at: str
    updated_at: str
    chat_history: List[Dict[str, str]] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)
