from pathlib import Path

import pytest

from desysflow_cli.__main__ import (
    _collect_prompt_text,
    _resolve_ollama_model_selection,
    collect_source_checkpoints,
    has_meaningful_source_files,
    infer_dominant_language,
)


def test_has_meaningful_source_files_ignores_non_source_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("todo", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "diagram.png").write_bytes(b"png")

    assert has_meaningful_source_files(tmp_path) is False


def test_has_meaningful_source_files_accepts_markdown_and_code_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project", encoding="utf-8")
    (tmp_path / "script.sh").write_text("echo hi", encoding="utf-8")

    assert has_meaningful_source_files(tmp_path) is True


def test_resolve_ollama_model_selection_reprompts_when_model_missing(monkeypatch) -> None:
    responses = iter(["missing-model", "y", "gpt-oss:20b-cloud"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    selected = _resolve_ollama_model_selection(
        installed=["gpt-oss:20b-cloud"],
        base_url="http://localhost:11434",
        default="gpt-oss:20b-cloud",
    )

    assert selected == "gpt-oss:20b-cloud"


def test_resolve_ollama_model_selection_aborts_when_user_declines_retry(monkeypatch) -> None:
    responses = iter(["missing-model", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    with pytest.raises(SystemExit, match="Aborted"):
        _resolve_ollama_model_selection(
            installed=["gpt-oss:20b-cloud"],
            base_url="http://localhost:11434",
            default="gpt-oss:20b-cloud",
        )


def test_infer_dominant_language_prefers_majority_extensions(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / "worker.py").write_text("print('y')", encoding="utf-8")
    (tmp_path / "dashboard.ts").write_text("export {}", encoding="utf-8")

    language = infer_dominant_language(tmp_path, ["python", "typescript", "go", "java", "rust"])

    assert language == "python"


def test_collect_source_checkpoints_empty_repo_has_no_inferred_language(tmp_path: Path) -> None:
    checkpoints = collect_source_checkpoints(tmp_path, ["python", "typescript", "go", "java", "rust"])

    assert checkpoints.has_meaningful_files is False
    assert checkpoints.inferred_language == ""


def test_collect_prompt_text_empty_repo_skips_input_mode_and_requests_prompt(monkeypatch) -> None:
    responses = iter(["design an ai code review app"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    prompt, mode = _collect_prompt_text(source_has_files=False, has_existing_design=False)

    assert mode == "ask"
    assert prompt == "design an ai code review app"


def test_collect_prompt_text_non_empty_repo_keeps_vibe_now_default(monkeypatch) -> None:
    responses = iter([""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    prompt, mode = _collect_prompt_text(
        source_has_files=True,
        has_existing_design=False,
        prompt="",
    )

    assert mode == "vibe-now"
    assert prompt == ""
