"""Centralised LLM service with provider-aware runtime checks."""

from __future__ import annotations

import logging
import os
import socket
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = "ollama"
_DEFAULT_MODEL = "gpt-oss:20b-cloud"
_DEFAULT_TEMPERATURE = 0.2
_DEFAULT_TIMEOUT = 120
_DEFAULT_OLLAMA_NUM_PREDICT = 2048

# ── Request-scoped overrides (set by API routes before calling agent workflows) ──
_request_model_override: ContextVar[Optional[dict[str, str]]] = ContextVar(
    "request_model_override", default=None
)


def set_request_model_override(
    provider: str,
    model: str,
    api_key: str = "",
    base_url: str = "",
) -> None:
    if provider and model:
        _request_model_override.set(
            {
                "provider": provider.strip().lower(),
                "model": model.strip(),
                "api_key": api_key.strip(),
                "base_url": base_url.strip(),
            }
        )


def clear_request_model_override() -> None:
    _request_model_override.set(None)


def _get_override() -> Optional[dict[str, str]]:
    return _request_model_override.get()


@dataclass(frozen=True)
class LLMConfig:
    """Resolved runtime configuration for the selected LLM provider."""

    provider: str
    model: str
    temperature: float
    base_url: str
    timeout: int
    api_key: str


@dataclass(frozen=True)
class CriticLLMConfig:
    """Resolved runtime configuration for judge/critic LLM."""

    provider: str
    model: str
    temperature: float
    base_url: str
    timeout: int
    api_key: str


def _normalise_ollama_base_url(raw_base_url: str) -> str:
    value = raw_base_url.strip()
    if not value:
        return "http://localhost:11434"
    if "://" in value:
        return value.rstrip("/")
    host, sep, port = value.partition(":")
    if not host:
        return "http://localhost:11434"
    resolved_port = port if sep and port else "11434"
    return f"http://{host}:{resolved_port}"


def _ollama_num_predict() -> int:
    raw = os.getenv("OLLAMA_NUM_PREDICT", str(_DEFAULT_OLLAMA_NUM_PREDICT)).strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_OLLAMA_NUM_PREDICT
    return max(256, min(value, 8192))


def _build_llm_config(
    provider: str,
    model: str,
    api_key: str = "",
    base_url: str = "",
) -> LLMConfig:
    """Build LLMConfig for a given provider/model, ignoring env override."""
    provider = (provider or _DEFAULT_PROVIDER).strip().lower()
    model = model.strip()
    api_key = api_key.strip()
    base_url = base_url.strip()
    if provider == "openai":
        return LLMConfig(
            provider=provider,
            model=model or os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o",
            temperature=float(os.getenv("OPENAI_TEMPERATURE", str(_DEFAULT_TEMPERATURE))),
            base_url=base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            timeout=int(os.getenv("OPENAI_TIMEOUT", str(_DEFAULT_TIMEOUT))),
            api_key=api_key or os.getenv("OPENAI_API_KEY", "").strip(),
        )
    if provider == "anthropic":
        return LLMConfig(
            provider=provider,
            model=model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip() or "claude-sonnet-4-20250514",
            temperature=float(os.getenv("ANTHROPIC_TEMPERATURE", str(_DEFAULT_TEMPERATURE))),
            base_url=base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip(),
            timeout=int(os.getenv("ANTHROPIC_TIMEOUT", str(_DEFAULT_TIMEOUT))),
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY", "").strip(),
        )
    base_url = _normalise_ollama_base_url(base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip())
    return LLMConfig(
        provider="ollama",
        model=model or os.getenv("OLLAMA_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL,
        temperature=float(os.getenv("OLLAMA_TEMPERATURE", str(_DEFAULT_TEMPERATURE))),
        base_url=base_url,
        timeout=int(os.getenv("OLLAMA_TIMEOUT", str(_DEFAULT_TIMEOUT))),
        api_key="",
    )


def get_llm_config() -> LLMConfig:
    override = _get_override()
    if override:
        return _build_llm_config(
            override.get("provider", ""),
            override.get("model", ""),
            api_key=override.get("api_key", ""),
            base_url=override.get("base_url", ""),
        )
    provider = os.getenv("MODEL_PROVIDER", _DEFAULT_PROVIDER).strip().lower() or _DEFAULT_PROVIDER
    return _build_llm_config(provider, "")


def get_critic_llm_config() -> CriticLLMConfig:
    base = get_llm_config()
    if base.provider == "openai":
        return CriticLLMConfig(
            provider=base.provider,
            model=os.getenv("OPENAI_CRITIC_MODEL", base.model).strip() or base.model,
            temperature=float(os.getenv("OPENAI_CRITIC_TEMPERATURE", "0.1")),
            base_url=base.base_url,
            timeout=int(os.getenv("OPENAI_CRITIC_TIMEOUT", "300")),
            api_key=base.api_key,
        )
    if base.provider == "anthropic":
        return CriticLLMConfig(
            provider=base.provider,
            model=os.getenv("ANTHROPIC_CRITIC_MODEL", base.model).strip() or base.model,
            temperature=float(os.getenv("ANTHROPIC_CRITIC_TEMPERATURE", "0.1")),
            base_url=base.base_url,
            timeout=int(os.getenv("ANTHROPIC_CRITIC_TIMEOUT", "300")),
            api_key=base.api_key,
        )
    return CriticLLMConfig(
        provider="ollama",
        model=os.getenv("OLLAMA_CRITIC_MODEL", base.model).strip() or base.model,
        temperature=float(os.getenv("OLLAMA_CRITIC_TEMPERATURE", "0.1")),
        base_url=base.base_url,
        timeout=int(os.getenv("OLLAMA_CRITIC_TIMEOUT", "300")),
        api_key="",
    )


def check_llm_status(probe: bool = True) -> dict[str, str]:
    cfg = get_llm_config()
    if cfg.provider == "ollama":
        return _check_ollama_status(cfg, probe=probe)
    if cfg.provider == "openai":
        if not cfg.api_key:
            return _status(cfg, "unavailable", "OPENAI_API_KEY is not set.")
        return _check_openai_status(cfg, probe=probe)
    if cfg.provider == "anthropic":
        if not cfg.api_key:
            return _status(cfg, "unavailable", "ANTHROPIC_API_KEY is not set.")
        return _check_anthropic_status(cfg, probe=probe)
    return _status(cfg, "unavailable", f"Unsupported provider: {cfg.provider}")


def is_llm_available() -> bool:
    return check_llm_status().get("status") == "available"


def _build_llm(cfg: LLMConfig):
    if cfg.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.model,
            temperature=cfg.temperature,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            timeout=cfg.timeout,
        )
    if cfg.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=cfg.model,
            temperature=cfg.temperature,
            anthropic_api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout,
        )
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=cfg.model,
        temperature=cfg.temperature,
        base_url=cfg.base_url,
        num_predict=_ollama_num_predict(),
        timeout=cfg.timeout,
    )


def get_llm(provider: str = "", model: str = ""):
    """Return an LLM instance.

    Resolution order:
    1. Request-scoped context variable (set by API routes for per-request override)
    2. Explicit (provider, model) arguments passed here
    3. Environment / config defaults
    """
    override = _get_override()
    api_key = ""
    base_url = ""
    if override:
        provider = override.get("provider", "")
        model = override.get("model", "")
        api_key = override.get("api_key", "")
        base_url = override.get("base_url", "")
    elif not provider:
        cfg = get_llm_config()
        provider, model = cfg.provider, cfg.model

    cfg = _build_llm_config(provider, model, api_key=api_key, base_url=base_url)
    logger.info(
        "Initialising LLM provider=%s model=%s temperature=%s base_url=%s timeout=%ss",
        cfg.provider,
        cfg.model,
        cfg.temperature,
        cfg.base_url,
        cfg.timeout,
    )
    llm = _build_llm(cfg)

    if os.getenv("LLM_GUARDRAIL", "").lower() in ("1", "true"):
        from services.guardrails import with_secret_guardrail

        return with_secret_guardrail(llm)
    return llm


def _build_critic_llm(cfg: CriticLLMConfig):
    if cfg.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.model,
            temperature=cfg.temperature,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            timeout=cfg.timeout,
        )
    if cfg.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=cfg.model,
            temperature=cfg.temperature,
            anthropic_api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout,
        )
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=cfg.model,
        temperature=cfg.temperature,
        base_url=cfg.base_url,
        num_predict=_ollama_num_predict(),
        timeout=cfg.timeout,
    )


def get_critic_llm():
    cfg = get_critic_llm_config()
    logger.info(
        "Initialising critic LLM provider=%s model=%s temperature=%s base_url=%s timeout=%ss",
        cfg.provider,
        cfg.model,
        cfg.temperature,
        cfg.base_url,
        cfg.timeout,
    )
    llm = _build_critic_llm(cfg)

    if os.getenv("LLM_GUARDRAIL", "").lower() in ("1", "true"):
        from services.guardrails import with_secret_guardrail

        return with_secret_guardrail(llm)
    return llm


def list_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return list of installed Ollama model names."""
    resolved_base_url = _normalise_ollama_base_url(base_url)
    try:
        response = httpx.get(f"{resolved_base_url.rstrip('/')}/api/tags", timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        return [
            str(item.get("name", "")).strip()
            for item in payload.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]
    except Exception:
        return []


def _check_ollama_status(cfg: LLMConfig, probe: bool = True) -> dict[str, str]:
    if not probe:
        return _status(cfg, "unknown", "Ollama probe skipped.")

    parsed = urlparse(cfg.base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        with socket.create_connection((host, port), timeout=1.5):
            pass
    except OSError:
        return _status(cfg, "unavailable", f"Ollama is not reachable at {cfg.base_url}.")

    try:
        response = httpx.get(f"{cfg.base_url.rstrip('/')}/api/tags", timeout=5.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _status(cfg, "unavailable", f"Could not inspect Ollama models: {exc}")

    models = payload.get("models", [])
    names = {
        str(item.get("name", "")).strip()
        for item in models
        if isinstance(item, dict) and item.get("name")
    }
    if cfg.model not in names:
        return _status(cfg, "missing_model", f"Ollama model '{cfg.model}' is not installed.")
    return _status(cfg, "available", "Ollama model is installed and reachable.")


def _join_provider_endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def _check_openai_status(cfg: LLMConfig, probe: bool = True) -> dict[str, str]:
    if not probe:
        return _status(cfg, "unknown", "OpenAI probe skipped.")

    endpoint = _join_provider_endpoint(cfg.base_url, "/models")
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    try:
        response = httpx.get(endpoint, headers=headers, timeout=min(10.0, float(cfg.timeout)))
        if response.status_code in (401, 403):
            return _status(cfg, "unavailable", "OpenAI API key was rejected.")
        response.raise_for_status()
    except Exception as exc:
        return _status(cfg, "unavailable", f"Could not reach OpenAI endpoint: {exc}")
    return _status(cfg, "available", "OpenAI model endpoint is reachable and authenticated.")


def _check_anthropic_status(cfg: LLMConfig, probe: bool = True) -> dict[str, str]:
    if not probe:
        return _status(cfg, "unknown", "Anthropic probe skipped.")

    path = "/models" if cfg.base_url.rstrip("/").endswith("/v1") else "/v1/models"
    endpoint = _join_provider_endpoint(cfg.base_url, path)
    headers = {
        "x-api-key": cfg.api_key,
        "anthropic-version": "2023-06-01",
    }
    try:
        response = httpx.get(endpoint, headers=headers, timeout=min(10.0, float(cfg.timeout)))
        if response.status_code in (401, 403):
            return _status(cfg, "unavailable", "Anthropic API key was rejected.")
        response.raise_for_status()
    except Exception as exc:
        return _status(cfg, "unavailable", f"Could not reach Anthropic endpoint: {exc}")
    return _status(cfg, "available", "Anthropic model endpoint is reachable and authenticated.")


def _status(cfg: LLMConfig, status: str, message: str) -> dict[str, str]:
    return {
        "status": status,
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "message": message,
    }
