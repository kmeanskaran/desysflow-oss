"""
FastAPI route definitions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from agents.critic import run_critic_standalone
from agents.critic_judge import run_design_judge
from agents.diagram import generate_cloud_diagram
from agents.diagram import diagram_generator
from agents.diagram_quality import diagram_quality_agent
from agents.reviser import revision_agent
from agents.report_generator import generate_cloud_reports
from agents.report_generator import report_generator
from agents.cloud_infra import cloud_infra_agent
from graph.workflow import run_workflow, run_workflow_with_updates
from schemas.models import (
    ConversationDetailResponse,
    ConversationListResponse,
    CloudRedesignRequest,
    CloudRedesignResponse,
    DesignCriticRequest,
    DesignCriticResponse,
    DesignRequest,
    DesignResponse,
    FollowUpRequest,
    FollowUpResponse,
    LLMCheckRequest,
    ReviewRequest,
    ReviewResponse,
)
from services.conversation_store import get_conversation_store
from services.llm import (
    check_llm_status,
    clear_request_model_override,
    get_critic_llm_config,
    get_llm_config,
    is_llm_available,
    set_request_model_override,
)
from services.search import get_search_config
from services.session_store import get_session_store
from utils.critic import build_critic_summary
from utils.design_doc import build_system_design_doc
from utils.diagram_stability import stabilize_followup_mermaid
from utils.non_technical_doc import build_non_technical_doc
from utils.session_memory import (
    build_repo_context_snapshot,
    build_followup_prompt,
    compact_chat_history,
    init_session_memory,
    init_session_state,
    mark_session_status,
    memory_to_markdown,
    record_error_and_correction,
    update_memory_after_run,
    write_session_note,
)
from utils.workflow_contract import (
    DESIGN_NODE_TO_STAGE,
    DESIGN_PROGRESS_STEPS,
    FOLLOWUP_NODE_TO_STAGE,
    FOLLOWUP_PROGRESS_STEPS,
    validate_delivery_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter()
SESSION_STORE = get_session_store()
CONVERSATION_STORE = get_conversation_store()
_OPERATIONS: Dict[str, Dict[str, Any]] = {}
_OPERATIONS_LOCK = threading.Lock()
_MAX_OPERATION_HISTORY = 200


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


_CRITIC_MAX_RUNS_PER_SESSION = _env_int("CRITIC_MAX_RUNS_PER_SESSION", 3)
_CRITIC_ITERATION_LIMIT = _env_int("CRITIC_ITERATION_LIMIT", 3)
_CRITIC_PASS_MAX_RISK = _env_int("CRITIC_PASS_MAX_RISK", 45)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_operation(mode: str, steps: list[Dict[str, str]]) -> str:
    operation_id = str(uuid.uuid4())
    with _OPERATIONS_LOCK:
        _OPERATIONS[operation_id] = {
            "operation_id": operation_id,
            "mode": mode,
            "status": "running",
            "steps": steps,
            "current_step": steps[0]["key"] if steps else "",
            "current_step_label": steps[0]["label"] if steps else "",
            "current_step_index": 0,
            "progress_percent": 0,
            "started_at": _now_iso(),
            "updated_at": _now_iso(),
            "result": None,
            "error": "",
        }
        if len(_OPERATIONS) > _MAX_OPERATION_HISTORY:
            oldest = sorted(_OPERATIONS.items(), key=lambda kv: kv[1].get("updated_at", ""))[:20]
            for key, value in oldest:
                if value.get("status") in {"completed", "failed"}:
                    _OPERATIONS.pop(key, None)
    return operation_id


def _operation_get(operation_id: str) -> Dict[str, Any] | None:
    with _OPERATIONS_LOCK:
        op = _OPERATIONS.get(operation_id)
        return dict(op) if op else None


def _operation_mark_step(operation_id: str, step_key: str) -> None:
    with _OPERATIONS_LOCK:
        op = _OPERATIONS.get(operation_id)
        if not op or op.get("status") != "running":
            return
        steps = op.get("steps", [])
        for idx, step in enumerate(steps):
            if step.get("key") == step_key:
                op["current_step"] = step_key
                op["current_step_label"] = step.get("label", step_key)
                op["current_step_index"] = idx
                op["progress_percent"] = int(((idx + 1) / max(1, len(steps))) * 100)
                op["updated_at"] = _now_iso()
                return


def _operation_mark_stage(operation_id: str, stage_key: str) -> None:
    _operation_mark_step(operation_id, stage_key)


def _operation_complete(operation_id: str, result: Dict[str, Any]) -> None:
    with _OPERATIONS_LOCK:
        op = _OPERATIONS.get(operation_id)
        if not op:
            return
        op["status"] = "completed"
        op["progress_percent"] = 100
        op["result"] = result
        op["updated_at"] = _now_iso()


def _operation_fail(operation_id: str, error: str) -> None:
    with _OPERATIONS_LOCK:
        op = _OPERATIONS.get(operation_id)
        if not op:
            return
        op["status"] = "failed"
        op["error"] = error
        op["updated_at"] = _now_iso()


def _run_workflow_with_progress(
    user_input: str,
    diagram_style: str,
    preferred_language: str,
    operation_id: str,
    node_to_stage: Dict[str, str],
    initial_stage_key: str,
) -> Dict[str, Any]:
    _operation_mark_stage(operation_id, initial_stage_key)
    return run_workflow_with_updates(
        user_input,
        diagram_style=diagram_style,
        preferred_language=preferred_language,
        on_update=lambda node_key, _payload, _state: (
            _operation_mark_stage(operation_id, node_to_stage[node_key])
            if node_key in node_to_stage
            else None
        ),
    )


def _apply_request_model_override(
    provider: str = "",
    model: str = "",
    api_key: str = "",
    base_url: str = "",
) -> None:
    if provider and model:
        set_request_model_override(provider, model, api_key=api_key, base_url=base_url)
    else:
        clear_request_model_override()


def _assistant_message(result: Dict[str, Any]) -> str:
    """Generate a concise assistant message for chat history."""
    summary = (
        result.get("hld_report", {}).get("system_overview")
        or "Generated architecture and technical design."
    )
    findings = len(result.get("critic_feedback", []))
    return f"{summary} Critic findings: {findings}."


def _attach_mermaid_metadata(
    result: Dict[str, Any],
    source: str,
    previous_result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Attach persisted Mermaid render metadata + per-chat version history."""
    updated = dict(result or {})
    code = str(updated.get("mermaid_code", "") or "").strip()
    previous = previous_result or {}
    previous_history = previous.get("mermaid_history", [])
    history = list(previous_history) if isinstance(previous_history, list) else []

    checksum = hashlib.sha256(code.encode("utf-8")).hexdigest() if code else ""
    latest_hash = ""
    if history and isinstance(history[-1], dict):
        latest_hash = str(history[-1].get("code_sha256", ""))

    generated_at = _now_iso()
    quality_checks = updated.get("diagram_quality_checks", [])
    quality_check_count = len(quality_checks) if isinstance(quality_checks, list) else 0

    metadata = {
        "generated_at": generated_at,
        "source": source,
        "code_sha256": checksum,
        "code_length": len(code),
        "has_flowchart_prefix": code.lower().startswith("flowchart"),
        "diagram_style": str(updated.get("diagram_style", "")),
        "quality_check_count": quality_check_count,
        "version": len(history) + (1 if code and checksum != latest_hash else 0),
    }
    updated["mermaid_render_metadata"] = metadata

    if code and checksum != latest_hash:
        history.append(
            {
                "version": len(history) + 1,
                "generated_at": generated_at,
                "source": source,
                "code_sha256": checksum,
                "mermaid_code": code,
            }
        )
        history = history[-20:]
    updated["mermaid_history"] = history
    updated["mermaid_version"] = history[-1]["version"] if history else 0
    return updated


def _conversation_title(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return "New Chat"
    return cleaned[:60]


def _build_design_markdown(session: Dict[str, Any], latest_result: Dict[str, Any], design_doc: Dict[str, Any]) -> str:
    title = _conversation_title(str(session.get("initial_input", "Architecture Design")))
    summary = latest_result.get("hld_report", {}).get("system_overview", "")
    return (
        f"# {title}\n\n"
        f"## Summary\n{summary or 'No summary available.'}\n\n"
        "## Design Document\n"
        f"{json.dumps(design_doc, indent=2)}\n\n"
        "## Latest Result\n"
        f"{json.dumps(latest_result, indent=2)}"
    )


def _persist_conversation(session_id: str, payload: Dict[str, Any]) -> None:
    initial_input = str(payload.get("initial_input", "")).strip()
    title = _conversation_title(initial_input)
    CONVERSATION_STORE.upsert(session_id=session_id, title=title, payload=payload)
    write_session_note(session_id, payload)


def _ensure_live_session(session_id: str) -> Dict[str, Any] | None:
    session = SESSION_STORE.get(session_id)
    if session:
        return session

    detail = CONVERSATION_STORE.get(session_id)
    if not detail:
        return None

    payload = detail.get("payload", {})
    if not isinstance(payload, dict):
        return None

    SESSION_STORE.set(session_id, payload)
    return payload


async def _run_postprocessors(result: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Run lightweight side-work in parallel (subagent-like post processing)."""
    critic_feedback = result.get("critic_feedback", [])
    critic_summary, system_design_doc, non_technical_doc = await asyncio.gather(
        asyncio.to_thread(build_critic_summary, critic_feedback),
        asyncio.to_thread(build_system_design_doc, result),
        asyncio.to_thread(build_non_technical_doc, result),
    )
    return critic_summary, system_design_doc, non_technical_doc


def _critic_passed(judge_output: Dict[str, Any]) -> bool:
    verdict = str(judge_output.get("overall_verdict", "")).strip()
    try:
        risk = int(judge_output.get("risk_score", 100))
    except Exception:
        risk = 100
    findings = judge_output.get("findings", [])
    critical_count = 0
    if isinstance(findings, list):
        for item in findings:
            if isinstance(item, dict) and str(item.get("severity", "")).lower() == "critical":
                critical_count += 1
    return (
        verdict == "approve_with_changes"
        and risk <= _CRITIC_PASS_MAX_RISK
        and critical_count == 0
    )


def _build_reviser_state(
    session: Dict[str, Any],
    latest_result: Dict[str, Any],
    critic_feedback: list[str],
) -> Dict[str, Any]:
    requirements = latest_result.get("requirements", {}) or {}
    architectures = latest_result.get("architectures", []) or []
    revised = latest_result.get("revised_architecture", {}) or {}
    if revised:
        if architectures:
            architectures = [revised, *architectures[1:]]
        else:
            architectures = [revised]

    return {
        "user_input": str(session.get("initial_input", "")),
        "diagram_style": str(session.get("diagram_style", "balanced")),
        "preferred_language": str(session.get("preferred_language", "Python")),
        "requirements": requirements,
        "template": str(latest_result.get("template", "")),
        "architectures": architectures,
        "edge_cases": latest_result.get("edge_cases", []) or [],
        "critic_feedback": critic_feedback,
        "revised_architecture": revised,
        "mermaid_code": str(latest_result.get("mermaid_code", "")),
        "excalidraw_diagram": latest_result.get("excalidraw_diagram", {}) or {},
        "diagram_quality_checks": latest_result.get("diagram_quality_checks", []) or [],
        "hld_report": latest_result.get("hld_report", {}) or {},
        "lld_report": latest_result.get("lld_report", {}) or {},
        "tech_stack": latest_result.get("tech_stack", {}) or {},
        "cloud_infrastructure": latest_result.get("cloud_infrastructure", {}) or {},
    }


def _append_workspace_preferences(
    text: str,
    *,
    role: str = "",
    report_style: str = "",
    cloud_target: str = "",
    search_mode: str = "",
) -> str:
    details = []
    if role.strip():
        details.append(f"- Role: {role.strip()}")
    if report_style.strip():
        details.append(f"- Report depth: {report_style.strip()}")
    if cloud_target.strip():
        details.append(f"- Cloud target: {cloud_target.strip()}")
    if search_mode.strip():
        details.append(f"- Web search mode: {search_mode.strip()}")
    if not details:
        return text
    return f"{text}\n\nWorkspace preferences:\n" + "\n".join(details)


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """Serve desysflow.config.yml as JSON for the UI."""
    import yaml  # noqa: local import to avoid hard dep at module level

    config_path = Path(__file__).resolve().parent.parent / "desysflow.config.yml"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="desysflow.config.yml not found")
    raw = config_path.read_text(encoding="utf-8")
    return yaml.safe_load(raw)


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    llm_config = get_llm_config()
    critic_llm_config = get_critic_llm_config()
    llm_status = check_llm_status(probe=False)
    search_config = get_search_config()
    session_store_status = SESSION_STORE.status()
    conversation_store_status = CONVERSATION_STORE.status()
    return {
        "status": "ok",
        "llm_status": llm_status.get("status", "unknown"),
        "llm_provider": llm_status.get("provider", llm_config.provider),
        "llm_model": llm_config.model,
        "llm_message": llm_status.get("message", ""),
        "critic_model": critic_llm_config.model,
        "web_search_enabled": str(search_config.enabled).lower(),
        "session_store": session_store_status.get("backend", "unknown"),
        "session_store_status": session_store_status.get("status", "unknown"),
        "chat_db": conversation_store_status.get("db", "unknown"),
        "chat_cache_status": conversation_store_status.get("cache_status", "unknown"),
    }


@router.post("/health/llm-check")
async def check_llm_runtime(request: LLMCheckRequest) -> Dict[str, str]:
    """Run an explicit provider/model/auth connectivity probe."""
    _apply_request_model_override(
        provider=request.provider.strip().lower(),
        model=request.model.strip(),
        api_key=request.api_key.strip(),
        base_url=request.base_url.strip(),
    )
    try:
        return check_llm_status(probe=True)
    finally:
        clear_request_model_override()


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    """List persisted chats for sidebar navigation."""
    conversations = CONVERSATION_STORE.list_conversations()
    return ConversationListResponse(conversations=conversations)


@router.get("/conversations/{session_id}", response_model=ConversationDetailResponse)
async def get_conversation(session_id: str) -> ConversationDetailResponse:
    """Get full persisted conversation payload and chat history."""
    detail = CONVERSATION_STORE.get(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return ConversationDetailResponse(
        session_id=detail["session_id"],
        title=detail["title"],
        created_at=detail["created_at"],
        updated_at=detail["updated_at"],
        chat_history=detail.get("chat_history", []),
        payload=detail.get("payload", {}),
    )


@router.delete("/conversations/{session_id}")
async def delete_conversation(session_id: str) -> Dict[str, str]:
    """Delete a conversation from storage and active session cache."""
    deleted = CONVERSATION_STORE.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    SESSION_STORE.delete(session_id)
    return {"status": "deleted", "session_id": session_id}


@router.get("/operations/{operation_id}")
async def get_operation_status(operation_id: str) -> Dict[str, Any]:
    """Fetch real-time orchestration status for async operations."""
    op = _operation_get(operation_id)
    if not op:
        raise HTTPException(status_code=404, detail="Operation not found.")
    return op


async def _run_design_async_operation(
    operation_id: str,
    user_input: str,
    preferred_language: str,
    diagram_style: str,
) -> None:
    llm_available = is_llm_available()
    warnings: list[str] = []
    if not llm_available:
        llm_config = get_llm_config()
        warnings.append(
            f"{llm_config.provider} is unreachable at "
            f"{llm_config.base_url}. The workflow may fail or return incomplete outputs until the provider is reachable."
        )

    try:
        result = await asyncio.to_thread(
            _run_workflow_with_progress,
            user_input,
            diagram_style,
            preferred_language,
            operation_id,
            DESIGN_NODE_TO_STAGE,
            "scope",
        )
        result.setdefault("requirements", {})["preferred_language"] = preferred_language
        result.setdefault("critic_run_limit", _CRITIC_MAX_RUNS_PER_SESSION)
        result.setdefault("critic_runs_used", 0)
        result["diagram_style"] = diagram_style
        result = _attach_mermaid_metadata(result, source="design_async")
        critic_feedback = result.get("critic_feedback", [])
        critic_summary, system_design_doc, non_technical_doc = await _run_postprocessors(result)
        validate_delivery_payload(result, system_design_doc, non_technical_doc)

        result["system_design_doc"] = system_design_doc
        result["non_technical_doc"] = non_technical_doc
        session_id = str(uuid.uuid4())
        chat_history = [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": _assistant_message(result)},
        ]
        session_memory = init_session_memory(user_input, repo_context=build_repo_context_snapshot())
        session_memory = update_memory_after_run(
            session_memory,
            result,
            warnings=warnings,
        )
        session_state = init_session_state()
        session_state = mark_session_status(session_state, "completed")
        session_payload = {
            "session_id": session_id,
            "initial_input": user_input,
            "diagram_style": diagram_style,
            "preferred_language": preferred_language,
            "chat_history": chat_history,
            "latest_result": result,
            "critic_runs": 0,
            "memory": session_memory,
            "state": session_state,
        }
        SESSION_STORE.set(session_id, session_payload)
        _persist_conversation(session_id, session_payload)
        response = DesignResponse(
            session_id=session_id,
            diagram_style=diagram_style,
            preferred_language=preferred_language,
            chat_history=chat_history,
            requirements=result.get("requirements", {}),
            architectures=result.get("architectures", []),
            critic_feedback=critic_feedback,
            critic_summary=critic_summary,
            final_architecture=result.get("revised_architecture", {}),
            system_design_doc=system_design_doc,
            non_technical_doc=non_technical_doc,
            mermaid_code=result.get("mermaid_code", ""),
            excalidraw_diagram=result.get("excalidraw_diagram", {}),
            hld_report=result.get("hld_report", {}),
            lld_report=result.get("lld_report", {}),
            tech_stack=result.get("tech_stack", {}),
            cloud_infrastructure=result.get("cloud_infrastructure", {}),
            warnings=warnings,
            execution_mode="full" if llm_available else "fallback",
        ).model_dump()
        _operation_complete(operation_id, response)
    except Exception as exc:
        logger.exception("Async design operation failed")
        _operation_fail(operation_id, f"Design execution failed: {exc}")


async def _run_followup_async_operation(
    operation_id: str,
    request: FollowUpRequest,
) -> None:
    session = _ensure_live_session(request.session_id)
    if not session:
        _operation_fail(operation_id, "Session not found. Start with POST /design.")
        return

    message = request.message.strip()
    preferred_language = request.preferred_language.strip() or "Python"
    diagram_style = request.diagram_style.strip().lower()

    followup_prompt = build_followup_prompt(session, message)

    llm_available = is_llm_available()
    warnings: list[str] = []
    if not llm_available:
        llm_config = get_llm_config()
        warnings.append(
            f"{llm_config.provider} is unreachable at "
            f"{llm_config.base_url}. The workflow may fail or return incomplete outputs until the provider is reachable."
        )

    try:
        state = dict(session.get("state", {}))
        state = mark_session_status(state, "running")
        SESSION_STORE.set(request.session_id, {**session, "state": state})

        result = await asyncio.to_thread(
            _run_workflow_with_progress,
            followup_prompt,
            diagram_style,
            preferred_language,
            operation_id,
            FOLLOWUP_NODE_TO_STAGE,
            "context",
        )
        previous_result = dict(session.get("latest_result", {}))
        if request.preserve_core_diagram:
            result["mermaid_code"] = stabilize_followup_mermaid(
                str(previous_result.get("mermaid_code", "")),
                str(result.get("mermaid_code", "")),
                message,
            )
        result.setdefault("requirements", {})["preferred_language"] = preferred_language
        result.setdefault("critic_run_limit", _CRITIC_MAX_RUNS_PER_SESSION)
        result.setdefault("critic_runs_used", int(session.get("critic_runs", 0)))
        result["diagram_style"] = diagram_style
        result = _attach_mermaid_metadata(result, source="followup_async", previous_result=previous_result)
        critic_feedback = result.get("critic_feedback", [])
        critic_summary, system_design_doc, non_technical_doc = await _run_postprocessors(result)
        validate_delivery_payload(result, system_design_doc, non_technical_doc)

        result["system_design_doc"] = system_design_doc
        result["non_technical_doc"] = non_technical_doc
        updated_history = list(session.get("chat_history", []))
        updated_history.append({"role": "user", "content": message})
        updated_history.append({"role": "assistant", "content": _assistant_message(result)})
        updated_memory = update_memory_after_run(
            dict(session.get("memory", {})),
            result,
            followup_message=message,
            warnings=warnings,
        )
        compacted_history = compact_chat_history(updated_history, updated_memory)
        updated_state = mark_session_status(
            dict(session.get("state", {})),
            "completed",
            correction="Applied follow-up request and regenerated outputs.",
        )
        SESSION_STORE.set(
            request.session_id,
            {
                **session,
                "diagram_style": diagram_style,
                "preferred_language": preferred_language,
                "chat_history": compacted_history,
                "latest_result": result,
                "memory": updated_memory,
                "state": updated_state,
            },
        )
        refreshed = SESSION_STORE.get(request.session_id)
        if refreshed:
            _persist_conversation(request.session_id, refreshed)
        response = FollowUpResponse(
            session_id=request.session_id,
            diagram_style=diagram_style,
            preferred_language=preferred_language,
            chat_history=compacted_history,
            requirements=result.get("requirements", {}),
            architectures=result.get("architectures", []),
            critic_feedback=critic_feedback,
            critic_summary=critic_summary,
            final_architecture=result.get("revised_architecture", {}),
            system_design_doc=system_design_doc,
            non_technical_doc=non_technical_doc,
            mermaid_code=result.get("mermaid_code", ""),
            excalidraw_diagram=result.get("excalidraw_diagram", {}),
            hld_report=result.get("hld_report", {}),
            lld_report=result.get("lld_report", {}),
            tech_stack=result.get("tech_stack", {}),
            cloud_infrastructure=result.get("cloud_infrastructure", {}),
            warnings=warnings,
            execution_mode="full" if llm_available else "fallback",
        ).model_dump()
        _operation_complete(operation_id, response)
    except Exception as exc:
        logger.exception("Async follow-up operation failed")
        existing = _ensure_live_session(request.session_id)
        if existing:
            updated_memory = record_error_and_correction(
                dict(existing.get("memory", {})),
                error=str(exc),
                correction="Retry follow-up with compacted session memory prompt.",
            )
            updated_state = mark_session_status(
                dict(existing.get("state", {})),
                "failed",
                error=str(exc),
            )
            SESSION_STORE.set(
                request.session_id,
                {
                    **existing,
                    "memory": updated_memory,
                    "state": updated_state,
                },
            )
            refreshed = SESSION_STORE.get(request.session_id)
            if refreshed:
                _persist_conversation(request.session_id, refreshed)
        _operation_fail(operation_id, f"Follow-up execution failed: {exc}")


@router.post("/design/async")
async def design_system_async(request: DesignRequest) -> Dict[str, Any]:
    """Start async design orchestration and return operation id for progress polling."""
    user_input = request.input.strip()
    user_input = _append_workspace_preferences(
        user_input,
        role=request.role,
        report_style=request.report_style,
        cloud_target=request.cloud_target,
        search_mode=request.search_mode,
    )
    preferred_language = request.preferred_language.strip() or "Python"
    diagram_style = request.diagram_style.strip().lower()
    if diagram_style not in {"minimal", "balanced", "detailed"}:
        raise HTTPException(status_code=400, detail="diagram_style must be one of: minimal, balanced, detailed")
    if not user_input:
        raise HTTPException(status_code=400, detail="Input must not be empty")

    _apply_request_model_override(
        provider=request.provider.strip().lower(),
        model=request.model.strip(),
        api_key=request.api_key.strip(),
        base_url=request.base_url.strip(),
    )

    try:
        operation_id = _create_operation("design", list(DESIGN_PROGRESS_STEPS))
        asyncio.create_task(
            _run_design_async_operation(
                operation_id=operation_id,
                user_input=user_input,
                preferred_language=preferred_language,
                diagram_style=diagram_style,
            )
        )
        return {"operation_id": operation_id, "status": "running"}
    finally:
        clear_request_model_override()


@router.post("/design/followup/async")
async def design_followup_async(request: FollowUpRequest) -> Dict[str, Any]:
    """Start async follow-up orchestration and return operation id for progress polling."""
    message = request.message.strip()
    message = _append_workspace_preferences(
        message,
        role=request.role,
        report_style=request.report_style,
        cloud_target=request.cloud_target,
        search_mode=request.search_mode,
    )
    diagram_style = request.diagram_style.strip().lower()
    if diagram_style not in {"minimal", "balanced", "detailed"}:
        raise HTTPException(status_code=400, detail="diagram_style must be one of: minimal, balanced, detailed")
    if not message:
        raise HTTPException(status_code=400, detail="Follow-up message must not be empty")
    request.message = message

    _apply_request_model_override(
        provider=request.provider.strip().lower(),
        model=request.model.strip(),
        api_key=request.api_key.strip(),
        base_url=request.base_url.strip(),
    )

    try:
        operation_id = _create_operation("followup", list(FOLLOWUP_PROGRESS_STEPS))
        asyncio.create_task(_run_followup_async_operation(operation_id=operation_id, request=request))
        return {"operation_id": operation_id, "status": "running"}
    finally:
        clear_request_model_override()


@router.post("/design", response_model=DesignResponse)
async def design_system(request: DesignRequest) -> DesignResponse:
    """Run the full system-design agent workflow.

    Accepts a free-text design prompt and returns structured architecture
    recommendations produced by the multi-step LangGraph pipeline.
    """
    user_input = request.input.strip()
    user_input = _append_workspace_preferences(
        user_input,
        role=request.role,
        report_style=request.report_style,
        cloud_target=request.cloud_target,
        search_mode=request.search_mode,
    )
    preferred_language = request.preferred_language.strip() or "Python"
    diagram_style = request.diagram_style.strip().lower()
    if diagram_style not in {"minimal", "balanced", "detailed"}:
        raise HTTPException(status_code=400, detail="diagram_style must be one of: minimal, balanced, detailed")
    if not user_input:
        raise HTTPException(status_code=400, detail="Input must not be empty")

    _apply_request_model_override(
        provider=request.provider.strip().lower(),
        model=request.model.strip(),
        api_key=request.api_key.strip(),
        base_url=request.base_url.strip(),
    )

    logger.info("POST /design — input: %s", user_input[:120])
    llm_available = is_llm_available()
    llm_config = get_llm_config()
    warnings: list[str] = []

    if not llm_available:
        warnings.append(
            f"{llm_config.provider} is unreachable at "
            f"{llm_config.base_url}. The workflow may fail or return incomplete outputs until the provider is reachable."
        )

    try:
        # Run blocking workflow in a thread to avoid blocking the event loop
        result = await asyncio.to_thread(run_workflow, user_input, diagram_style, preferred_language)
        result.setdefault("requirements", {})["preferred_language"] = preferred_language
        result.setdefault("critic_run_limit", _CRITIC_MAX_RUNS_PER_SESSION)
        result.setdefault("critic_runs_used", 0)
        result["diagram_style"] = diagram_style
        result = _attach_mermaid_metadata(result, source="design")
        critic_feedback = result.get("critic_feedback", [])
        critic_summary, system_design_doc, non_technical_doc = await _run_postprocessors(result)
        validate_delivery_payload(result, system_design_doc, non_technical_doc)

        result["system_design_doc"] = system_design_doc
        result["non_technical_doc"] = non_technical_doc
        session_id = str(uuid.uuid4())
        chat_history = [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": _assistant_message(result)},
        ]
        session_memory = init_session_memory(user_input, repo_context=build_repo_context_snapshot())
        session_memory = update_memory_after_run(
            session_memory,
            result,
            warnings=warnings,
        )
        session_state = init_session_state()
        session_state = mark_session_status(session_state, "completed")
        session_payload = {
            "session_id": session_id,
            "initial_input": user_input,
            "diagram_style": diagram_style,
            "preferred_language": preferred_language,
            "chat_history": chat_history,
            "latest_result": result,
            "critic_runs": 0,
            "memory": session_memory,
            "state": session_state,
        }
        SESSION_STORE.set(session_id, session_payload)
        _persist_conversation(session_id, session_payload)
        return DesignResponse(
            session_id=session_id,
            diagram_style=diagram_style,
            preferred_language=preferred_language,
            chat_history=chat_history,
            requirements=result.get("requirements", {}),
            architectures=result.get("architectures", []),
            critic_feedback=critic_feedback,
            critic_summary=critic_summary,
            final_architecture=result.get("revised_architecture", {}),
            system_design_doc=system_design_doc,
            non_technical_doc=non_technical_doc,
            mermaid_code=result.get("mermaid_code", ""),
            excalidraw_diagram=result.get("excalidraw_diagram", {}),
            hld_report=result.get("hld_report", {}),
            lld_report=result.get("lld_report", {}),
            tech_stack=result.get("tech_stack", {}),
            cloud_infrastructure=result.get("cloud_infrastructure", {}),
            warnings=warnings,
            execution_mode="full" if llm_available else "fallback",
        )

    except Exception as exc:
        logger.exception("Workflow failed")
        raise HTTPException(
            status_code=500,
            detail=f"Workflow execution failed: {exc}",
        )
    finally:
        clear_request_model_override()


@router.post("/design/critic", response_model=DesignCriticResponse)
async def run_design_critic(request: DesignCriticRequest) -> DesignCriticResponse:
    """Run premium/limited on-demand critic loop (judge + revise) for an existing session."""
    session = _ensure_live_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Start with POST /design.")

    current_runs = int(session.get("critic_runs", 0))
    if _CRITIC_MAX_RUNS_PER_SESSION > 0 and current_runs >= _CRITIC_MAX_RUNS_PER_SESSION:
        raise HTTPException(
            status_code=429,
            detail=(
                "Critic premium limit reached for this session. "
                "Upgrade plan or start a new session for additional critic runs."
            ),
        )

    latest_result = dict(session.get("latest_result", {}) or {})
    session_memory = session.get("memory", {}) or {}
    memory_summary = memory_to_markdown(session_memory)
    if len(memory_summary) > 1800:
        memory_summary = f"{memory_summary[:1800]}..."
    working_latest = dict(latest_result)
    iteration_limit = max(1, _CRITIC_ITERATION_LIMIT)
    iterations_used = 0
    judge_output: Dict[str, Any] = {}

    for idx in range(iteration_limit):
        iterations_used = idx + 1
        design_doc = build_system_design_doc(working_latest)
        markdown_payload = _build_design_markdown(session, working_latest, design_doc)
        if memory_summary.strip():
            markdown_payload = f"{markdown_payload}\n\n## Session Memory Summary\n{memory_summary}"
        payload = {
            "system_design_markdown": markdown_payload,
            "chat_history": session.get("chat_history", []),
            "focus": request.focus,
        }
        judge_output = await asyncio.to_thread(run_design_judge, payload, request.focus, request.search_mode)
        findings = judge_output.get("findings", [])
        critic_feedback = [str(item.get("text", "")) for item in findings if isinstance(item, dict)]

        if _critic_passed(judge_output) or idx == iteration_limit - 1:
            break

        revised = await asyncio.to_thread(
            revision_agent,
            _build_reviser_state(session, working_latest, critic_feedback),
        )
        revised_architecture = revised.get("revised_architecture", {})
        if isinstance(revised_architecture, dict) and revised_architecture:
            working_latest["revised_architecture"] = revised_architecture
            architectures = working_latest.get("architectures", []) or []
            if architectures:
                working_latest["architectures"] = [revised_architecture, *architectures[1:]]
            else:
                working_latest["architectures"] = [revised_architecture]

    final_findings = judge_output.get("findings", [])
    critic_feedback = [str(item.get("text", "")) for item in final_findings if isinstance(item, dict)]
    critic_summary = build_critic_summary(critic_feedback)

    # Preserve judge-provided categories/severity for richer UI.
    if isinstance(critic_summary.get("items"), list):
        for idx, item in enumerate(critic_summary["items"]):
            if idx < len(final_findings) and isinstance(final_findings[idx], dict):
                if "severity" in final_findings[idx]:
                    item["severity"] = str(final_findings[idx]["severity"])
                if "category" in final_findings[idx]:
                    item["category"] = str(final_findings[idx]["category"])
        # Recompute counts after applying judge-provided severity/category.
        severity_counts = {"critical": 0, "warning": 0, "info": 0}
        category_counts: dict[str, int] = {}
        for item in critic_summary["items"]:
            severity = str(item.get("severity", "info")).lower()
            if severity not in severity_counts:
                severity = "info"
            category = str(item.get("category", "general")).lower() or "general"
            severity_counts[severity] += 1
            category_counts[category] = category_counts.get(category, 0) + 1
        critic_summary["counts"] = {
            "severity": severity_counts,
            "category": category_counts,
            "total": len(critic_summary["items"]),
        }

    # Regenerate artifacts from revised architecture after the critic loop.
    regen_state = _build_reviser_state(session, working_latest, critic_feedback)
    diagram_out, report_out, cloud_out = await asyncio.gather(
        asyncio.to_thread(diagram_generator, regen_state),
        asyncio.to_thread(report_generator, regen_state),
        asyncio.to_thread(cloud_infra_agent, regen_state),
    )
    quality_state = {**regen_state, **(diagram_out or {})}
    quality_out = await asyncio.to_thread(diagram_quality_agent, quality_state)
    working_latest.update(diagram_out or {})
    working_latest.update(quality_out or {})
    working_latest.update(report_out or {})
    working_latest.update(cloud_out or {})
    working_latest["diagram_style"] = str(session.get("diagram_style", "balanced"))
    working_latest = _attach_mermaid_metadata(
        working_latest,
        source="critic_loop",
        previous_result=latest_result,
    )
    working_latest["system_design_doc"] = build_system_design_doc(working_latest)

    updated_latest = {
        **working_latest,
        "critic_feedback": critic_feedback,
        "critic_summary": critic_summary,
        "critic_suggested_improvements": judge_output.get("suggested_improvements", [])[:12],
        "critic_verdict": judge_output.get("overall_verdict", "major_rework_required"),
        "critic_risk_score": int(judge_output.get("risk_score", 70)),
        "critic_reasoning_summary": judge_output.get("reasoning_summary", ""),
        "critic_iterations_used": iterations_used,
        "critic_iteration_limit": iteration_limit,
        "critic_run_limit": _CRITIC_MAX_RUNS_PER_SESSION,
        "critic_runs_used": current_runs + 1,
    }
    updated_history = list(session.get("chat_history", []))
    focus = (request.focus or "").strip()
    if focus:
        updated_history.append({"role": "user", "content": f"Critic focus: {focus}"})
    updated_history.append(
        {
            "role": "assistant",
            "content": f"Critic verdict: {updated_latest.get('critic_verdict', 'major_rework_required')} "
            f"(risk {updated_latest.get('critic_risk_score', 70)}/100, "
            f"iterations {iterations_used}/{iteration_limit}).",
        }
    )
    updated_payload = {
        **session,
        "latest_result": updated_latest,
        "chat_history": updated_history,
        "critic_runs": current_runs + 1,
    }
    SESSION_STORE.set(request.session_id, updated_payload)
    _persist_conversation(request.session_id, updated_payload)
    return DesignCriticResponse(
        session_id=request.session_id,
        critic_feedback=critic_feedback,
        critic_summary=critic_summary,
        suggested_improvements=updated_latest.get("critic_suggested_improvements", []),
        overall_verdict=updated_latest.get("critic_verdict", "major_rework_required"),
        risk_score=updated_latest.get("critic_risk_score", 70),
        reasoning_summary=updated_latest.get("critic_reasoning_summary", ""),
    )


@router.post("/design/followup", response_model=FollowUpResponse)
async def design_followup(request: FollowUpRequest) -> FollowUpResponse:
    """Run a context-aware follow-up iteration for an existing session."""
    message = request.message.strip()
    message = _append_workspace_preferences(
        message,
        role=request.role,
        report_style=request.report_style,
        cloud_target=request.cloud_target,
        search_mode=request.search_mode,
    )
    preferred_language = request.preferred_language.strip() or "Python"
    diagram_style = request.diagram_style.strip().lower()
    if diagram_style not in {"minimal", "balanced", "detailed"}:
        raise HTTPException(status_code=400, detail="diagram_style must be one of: minimal, balanced, detailed")
    if not message:
        raise HTTPException(status_code=400, detail="Follow-up message must not be empty")
    _apply_request_model_override(
        provider=request.provider.strip().lower(),
        model=request.model.strip(),
        api_key=request.api_key.strip(),
        base_url=request.base_url.strip(),
    )

    session = _ensure_live_session(request.session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Start with POST /design.")

    logger.info("POST /design/followup — session: %s", request.session_id)

    followup_prompt = build_followup_prompt(session, message)

    llm_available = is_llm_available()
    warnings: list[str] = []
    if not llm_available:
        llm_config = get_llm_config()
        warnings.append(
            f"{llm_config.provider} is unreachable at "
            f"{llm_config.base_url}. The workflow may fail or return incomplete outputs until the provider is reachable."
        )

    try:
        state = dict(session.get("state", {}))
        state = mark_session_status(state, "running")
        SESSION_STORE.set(request.session_id, {**session, "state": state})

        result = await asyncio.to_thread(run_workflow, followup_prompt, diagram_style, preferred_language)
        previous_result = dict(session.get("latest_result", {}))
        if request.preserve_core_diagram:
            result["mermaid_code"] = stabilize_followup_mermaid(
                str(previous_result.get("mermaid_code", "")),
                str(result.get("mermaid_code", "")),
                message,
            )
        result.setdefault("requirements", {})["preferred_language"] = preferred_language
        result.setdefault("critic_run_limit", _CRITIC_MAX_RUNS_PER_SESSION)
        result.setdefault("critic_runs_used", int(session.get("critic_runs", 0)))
        result["diagram_style"] = diagram_style
        result = _attach_mermaid_metadata(result, source="followup", previous_result=previous_result)
        critic_feedback = result.get("critic_feedback", [])
        critic_summary, system_design_doc, non_technical_doc = await _run_postprocessors(result)
        validate_delivery_payload(result, system_design_doc, non_technical_doc)

        result["system_design_doc"] = system_design_doc
        result["non_technical_doc"] = non_technical_doc
        updated_history = list(session.get("chat_history", []))
        updated_history.append({"role": "user", "content": message})
        updated_history.append({"role": "assistant", "content": _assistant_message(result)})
        updated_memory = update_memory_after_run(
            dict(session.get("memory", {})),
            result,
            followup_message=message,
            warnings=warnings,
        )
        compacted_history = compact_chat_history(updated_history, updated_memory)
        updated_state = mark_session_status(
            dict(session.get("state", {})),
            "completed",
            correction="Applied follow-up request and regenerated outputs.",
        )
        SESSION_STORE.set(
            request.session_id,
            {
                **session,
                "diagram_style": diagram_style,
                "preferred_language": preferred_language,
                "chat_history": compacted_history,
                "latest_result": result,
                "memory": updated_memory,
                "state": updated_state,
            },
        )
        refreshed = SESSION_STORE.get(request.session_id)
        if refreshed:
            _persist_conversation(request.session_id, refreshed)
        return FollowUpResponse(
            session_id=request.session_id,
            diagram_style=diagram_style,
            preferred_language=preferred_language,
            chat_history=compacted_history,
            requirements=result.get("requirements", {}),
            architectures=result.get("architectures", []),
            critic_feedback=critic_feedback,
            critic_summary=critic_summary,
            final_architecture=result.get("revised_architecture", {}),
            system_design_doc=system_design_doc,
            non_technical_doc=non_technical_doc,
            mermaid_code=result.get("mermaid_code", ""),
            excalidraw_diagram=result.get("excalidraw_diagram", {}),
            hld_report=result.get("hld_report", {}),
            lld_report=result.get("lld_report", {}),
            tech_stack=result.get("tech_stack", {}),
            cloud_infrastructure=result.get("cloud_infrastructure", {}),
            warnings=warnings,
            execution_mode="full" if llm_available else "fallback",
        )
    except Exception as exc:
        logger.exception("Follow-up workflow failed")
        existing = _ensure_live_session(request.session_id)
        if existing:
            updated_memory = record_error_and_correction(
                dict(existing.get("memory", {})),
                error=str(exc),
                correction="Retry follow-up with compacted session memory prompt.",
            )
            updated_state = mark_session_status(
                dict(existing.get("state", {})),
                "failed",
                error=str(exc),
            )
            SESSION_STORE.set(
                request.session_id,
                {
                    **existing,
                    "memory": updated_memory,
                    "state": updated_state,
                },
            )
            refreshed = SESSION_STORE.get(request.session_id)
            if refreshed:
                _persist_conversation(request.session_id, refreshed)
        raise HTTPException(
            status_code=500,
            detail=f"Follow-up execution failed: {exc}",
        )
    finally:
        clear_request_model_override()


@router.post("/review", response_model=ReviewResponse)
async def review_architecture(request: ReviewRequest) -> ReviewResponse:
    """Run the critic agent on a provided architecture JSON.

    Returns structured feedback and improvement suggestions.
    """
    if not request.architecture:
        raise HTTPException(status_code=400, detail="Architecture must not be empty")

    logger.info("POST /review — reviewing architecture")

    try:
        result = run_critic_standalone(request.architecture)

        return ReviewResponse(
            critic_feedback=result.get("critic_feedback", []),
            suggested_improvements=result.get("suggested_improvements", []),
        )

    except Exception as exc:
        logger.exception("Review failed")
        raise HTTPException(
            status_code=500,
            detail=f"Review execution failed: {exc}",
        )


_VALID_PROVIDERS = {"aws", "gcp", "azure", "digitalocean", "on_prem", "local"}


@router.post("/design/cloud-redesign", response_model=CloudRedesignResponse)
async def cloud_redesign(request: CloudRedesignRequest) -> CloudRedesignResponse:
    """Re-generate diagram and reports for a specific cloud provider.

    This is a lighter-weight operation than the full /design pipeline:
    it only re-runs diagram generation and report generation with
    cloud-provider-specific context.
    """
    provider = request.provider.strip().lower()
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{provider}'. Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}",
        )

    logger.info("POST /design/cloud-redesign — provider: %s", provider)

    try:
        # Run in threads to avoid blocking
        mermaid_code, reports = await asyncio.gather(
            asyncio.to_thread(
                generate_cloud_diagram,
                request.architecture,
                provider,
                request.requirements,
            ),
            asyncio.to_thread(
                generate_cloud_reports,
                request.architecture,
                provider,
                request.requirements,
                request.user_input,
            ),
        )

        cloud_services = {
            provider: (request.cloud_infrastructure or {}).get(provider, {})
        }

        return CloudRedesignResponse(
            mermaid_code=mermaid_code,
            hld_report=reports.get("hld_report", {}),
            lld_report=reports.get("lld_report", {}),
            cloud_services=cloud_services,
        )

    except Exception as exc:
        logger.exception("Cloud redesign failed")
        raise HTTPException(
            status_code=500,
            detail=f"Cloud redesign failed: {exc}",
        )
