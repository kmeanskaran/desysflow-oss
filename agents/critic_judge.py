"""
On-demand LLM-as-a-Judge critic for full-system design review.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from services.llm import get_critic_llm
from services.search import format_search_results, search_web, should_use_web_search
from utils.parser import extract_json_block, normalize_llm_text

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """You are an elite Principal Architect acting as an LLM-as-a-Judge.
You must rigorously evaluate the entire design package, not just one component.

Review dimensions:
1) Requirement coverage and correctness
2) Scalability and performance
3) Reliability and failure handling
4) Security and privacy
5) Observability and operations
6) Cost and complexity trade-offs
7) Cloud portability and vendor lock-in

Return ONLY valid JSON with this schema:
{
  "overall_verdict": "approve_with_changes | major_rework_required | unsafe_for_production",
  "risk_score": <integer 0-100>,
  "reasoning_summary": "<concise summary>",
  "findings": [
    {
      "severity": "critical | warning | info",
      "category": "scalability | security | reliability | observability | cost | requirements | operations | architecture",
      "title": "<short title>",
      "detail": "<specific issue and why it matters>"
    }
  ],
  "suggested_improvements": ["<concrete action>", "..."]
}

Rules:
- Be strict and specific.
- Findings must be actionable and evidence-based from provided payload.
- Do not include markdown or prose outside JSON."""


def run_design_judge(payload: Dict[str, Any], focus: str = "", search_mode: str = "on") -> Dict[str, Any]:
    """Run strong on-demand critic over full design payload."""
    llm = get_critic_llm()
    search_context = _build_search_context(payload, focus, search_mode)
    user_content = (
        "Evaluate this full system-design package:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        f"Reviewer focus (optional): {focus or 'none'}"
    )
    if search_context:
        user_content += (
            "\n\nExternally grounded search notes were retrieved because the task appears to "
            "need current/external information. Use them carefully and do not invent facts.\n\n"
            f"{search_context}"
        )

    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        response = llm.invoke(messages)
        raw = normalize_llm_text(
            response.content if hasattr(response, "content") else response
        )
        parsed = json.loads(extract_json_block(raw))
        return _normalize_judge_output(parsed)
    except Exception as exc:
        logger.exception("On-demand design judge failed")
        return {
            "overall_verdict": "major_rework_required",
            "risk_score": 85,
            "reasoning_summary": "Judge failed; manual architecture review required.",
            "findings": [
                {
                    "severity": "warning",
                    "category": "operations",
                    "title": "Judge execution failed",
                    "detail": str(exc),
                }
            ],
            "suggested_improvements": [
                "Retry on-demand critic with a stable Ollama reasoning model.",
                "Run manual principal engineer review before implementation.",
            ],
        }


def _build_search_context(payload: Dict[str, Any], focus: str, search_mode: str) -> str:
    if str(search_mode).strip().lower() == "off":
        return ""
    markdown = str(payload.get("system_design_markdown", ""))
    query_source = f"{focus}\n{markdown[:2500]}".strip()
    if not should_use_web_search(query_source):
        return ""

    query = _build_search_query(markdown, focus)
    results = search_web(query)
    return format_search_results(results)


def _build_search_query(markdown: str, focus: str) -> str:
    title = _extract_heading(markdown) or "system design"
    focus_text = focus.strip() or "architecture best practices and current documentation"
    return f"{title} {focus_text}"


def _extract_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _normalize_judge_output(parsed: Dict[str, Any]) -> Dict[str, Any]:
    findings = parsed.get("findings", [])
    normalized_findings: List[Dict[str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "info")).lower().strip()
        if severity not in {"critical", "warning", "info"}:
            severity = "info"
        category = str(item.get("category", "architecture")).lower().strip()
        title = str(item.get("title", "Untitled finding")).strip()
        detail = str(item.get("detail", "")).strip()
        text = f"{title}: {detail}".strip(": ").strip()
        normalized_findings.append(
            {
                "severity": severity,
                "category": category or "architecture",
                "title": title or "Untitled finding",
                "detail": detail,
                "text": text or title or detail or "No detail provided",
            }
        )

    improvements = parsed.get("suggested_improvements", [])
    if not isinstance(improvements, list):
        improvements = []

    verdict = str(parsed.get("overall_verdict", "major_rework_required")).strip()
    if verdict not in {"approve_with_changes", "major_rework_required", "unsafe_for_production"}:
        verdict = "major_rework_required"

    try:
        risk_score = int(parsed.get("risk_score", 70))
    except Exception:
        risk_score = 70
    risk_score = max(0, min(100, risk_score))

    reasoning_summary = str(parsed.get("reasoning_summary", "")).strip()
    if not reasoning_summary:
        reasoning_summary = "Judge completed with actionable findings."

    return {
        "overall_verdict": verdict,
        "risk_score": risk_score,
        "reasoning_summary": reasoning_summary,
        "findings": normalized_findings,
        "suggested_improvements": [str(x) for x in improvements[:12]],
    }
