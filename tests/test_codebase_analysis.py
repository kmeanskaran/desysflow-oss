from pathlib import Path

from desysflow_cli.__main__ import AnalysisContext, RunConfig, build_user_request
from utils.codebase_analysis import extract_codebase_context, format_codebase_context


def test_extract_codebase_context_reads_python_symbols_and_routes(tmp_path: Path) -> None:
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "routes.py").write_text(
        """
from fastapi import APIRouter

router = APIRouter()

class HealthService:
    def check(self):
        return {"ok": True}

@router.get("/health")
def health():
    return {"ok": True}

@router.post("/design")
async def design():
    return {"status": "accepted"}
""".strip(),
        encoding="utf-8",
    )

    ctx = extract_codebase_context(tmp_path, skip_dirs={"node_modules", ".git"})

    assert ctx["files_scanned"] == 1
    assert ctx["symbol_files"] == 1
    file_info = ctx["files"][0]
    assert file_info["path"] == "api/routes.py"
    assert "HealthService" in file_info["classes"]
    assert "health" in file_info["functions"]
    assert "design" in file_info["functions"]
    assert file_info["class_methods"]["HealthService"] == ["check"]
    assert {"method": "GET", "path": "/health", "handler": "health"} in file_info["routes"]
    assert {"method": "POST", "path": "/design", "handler": "design"} in file_info["routes"]


def test_extract_codebase_context_reads_javascript_symbols(tmp_path: Path) -> None:
    web_dir = tmp_path / "studio" / "src"
    web_dir.mkdir(parents=True)
    (web_dir / "App.jsx").write_text(
        """
export default function App() {
  return null
}

export function buildArtifacts() {
  return []
}

class ViewModel {
  render() {
    return null
  }
}

const loadState = async () => {
  return {}
}
""".strip(),
        encoding="utf-8",
    )

    ctx = extract_codebase_context(tmp_path, skip_dirs={"node_modules", ".git"})

    assert ctx["files_scanned"] == 1
    file_info = ctx["files"][0]
    assert "App" in file_info["functions"]
    assert "buildArtifacts" in file_info["functions"]
    assert "loadState" in file_info["functions"]
    assert "ViewModel" in file_info["classes"]


def test_build_user_request_includes_observed_codebase_symbols() -> None:
    cfg = RunConfig(
        command="/design",
        source=Path("."),
        output_root=Path("./desysflow"),
        project="demo",
        language="Python",
        style="balanced",
        cloud="local",
        web_search="off",
        mode="smart",
        effective_mode="fresh",
        focus="",
        role="architect",
        prompt="document the repo",
        non_interactive=True,
    )
    codebase = {
        "files_scanned": 2,
        "symbol_files": 2,
        "files": [
            {
                "path": "api/routes.py",
                "language": "python",
                "classes": ["DesignResponse"],
                "class_methods": {},
                "functions": ["create_design", "get_status"],
                "routes": [{"method": "POST", "path": "/design", "handler": "create_design"}],
            }
        ],
        "routes": [{"method": "POST", "path": "/design", "handler": "create_design", "file": "api/routes.py"}],
    }
    ctx = AnalysisContext(
        inventory={"total_files": 2, "extensions": {".py": 2}, "modules": [], "top_files": []},
        stack={"language": ["Python"], "frameworks": ["FastAPI"], "storage": ["SQLite"], "runtime": ["Uvicorn"]},
        module_map={"api": "API layer"},
        key_paths=["api/routes.py"],
        codebase=codebase,
        web_enabled=False,
        references=[],
        latest_design=None,
    )

    prompt = build_user_request(cfg, ctx)

    assert "Observed codebase structure" in prompt
    assert "api/routes.py" in prompt
    assert "create_design" in prompt
    assert "POST /design" in prompt


def test_format_codebase_context_handles_empty_result() -> None:
    rendered = format_codebase_context({"files": [], "routes": [], "files_scanned": 0, "symbol_files": 0})

    assert "No code symbols were extracted" in rendered
