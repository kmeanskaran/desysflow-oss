from pathlib import Path

import pytest

from desysflow_cli.__main__ import (
    _collect_prompt_text,
    _resolve_ollama_model_selection,
    collect_source_checkpoints,
    default_output_root,
    has_meaningful_source_files,
    infer_dominant_language,
    resolve_effective_mode,
    resolve_latest_design_baseline,
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
    assert checkpoints.has_existing_design is False
    assert checkpoints.latest_design_version == ""


def test_collect_source_checkpoints_detects_latest_desysflow_baseline(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    output_root = source / ".desysflow"
    latest = output_root / "repo" / "v2"
    latest.mkdir(parents=True)
    (latest / "SUMMARY.md").write_text("# Summary\n\ncurrent design", encoding="utf-8")
    (output_root / "repo" / "latest").write_text("v2\n", encoding="utf-8")

    checkpoints = collect_source_checkpoints(
        source,
        ["python", "typescript", "go", "java", "rust"],
        output_root=output_root,
        project="repo",
    )

    assert checkpoints.has_existing_design is True
    assert checkpoints.latest_design_version == "v2"


def test_resolve_latest_design_baseline_reads_latest_pointer(tmp_path: Path) -> None:
    output_root = tmp_path / ".desysflow"
    latest = output_root / "repo" / "v3"
    latest.mkdir(parents=True)
    (latest / "SUMMARY.md").write_text("# Summary\n\nBaseline summary", encoding="utf-8")
    (latest / "HLD.md").write_text("# HLD\n\nBaseline HLD", encoding="utf-8")
    (output_root / "repo" / "latest").write_text("v3\n", encoding="utf-8")

    baseline = resolve_latest_design_baseline(output_root, "repo")

    assert baseline is not None
    assert baseline.version == "v3"
    assert baseline.path == latest
    assert "SUMMARY.md" in baseline.files
    assert "Baseline summary" in baseline.excerpts["SUMMARY.md"]


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
        has_existing_design=True,
        latest_design_version="v4",
        prompt="",
    )

    assert mode == "vibe-now"
    assert prompt == ""


def test_collect_prompt_text_repo_without_baseline_forces_ask(monkeypatch) -> None:
    responses = iter(["design around the current codebase"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    prompt, mode = _collect_prompt_text(
        source_has_files=True,
        has_existing_design=False,
        prompt="",
    )

    assert mode == "ask"
    assert prompt == "design around the current codebase"


def test_resolve_effective_mode_smart_uses_refine_when_baseline_exists() -> None:
    mode = resolve_effective_mode("/design", "smart", True, "")

    assert mode == "refine"


def test_default_output_root_uses_hidden_dir_for_new_workspace(tmp_path: Path) -> None:
    assert default_output_root(tmp_path) == tmp_path / ".desysflow"
