"""Codebase-aware symbol extraction for documentation grounding."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

ROUTE_DECORATORS = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "websocket",
}

SYMBOL_SUFFIX_LANGUAGE = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
}


def extract_codebase_context(
    source: Path,
    *,
    skip_dirs: set[str] | None = None,
    max_files: int = 80,
) -> dict[str, Any]:
    """Extract a compact symbol inventory from the local codebase."""
    skip = skip_dirs or set()
    files: list[dict[str, Any]] = []
    scanned_files = 0

    for root, dirs, names in os.walk(source):
        dirs[:] = [item for item in dirs if item not in skip and not item.startswith(".")]
        for name in sorted(names):
            path = Path(root) / name
            suffix = path.suffix.lower()
            language = SYMBOL_SUFFIX_LANGUAGE.get(suffix)
            if language is None:
                continue
            rel = path.relative_to(source)
            file_info = _extract_file_symbols(path, rel, language)
            scanned_files += 1
            if file_info["classes"] or file_info["functions"] or file_info["routes"]:
                files.append(file_info)
            if scanned_files >= max_files:
                break
        if scanned_files >= max_files:
            break

    files.sort(
        key=lambda item: (
            -(len(item["routes"]) * 10 + len(item["classes"]) * 3 + len(item["functions"])),
            item["path"],
        )
    )
    routes = [
        {**route, "file": file_info["path"]}
        for file_info in files
        for route in file_info["routes"]
    ]
    return {
        "files_scanned": scanned_files,
        "symbol_files": len(files),
        "files": files,
        "routes": routes,
    }


def format_codebase_context(ctx: dict[str, Any], *, file_limit: int = 8, route_limit: int = 8) -> str:
    """Render extracted symbol context into prompt-friendly markdown."""
    files = ctx.get("files", [])
    routes = ctx.get("routes", [])
    if not files:
        return "- No code symbols were extracted from the current source tree."

    lines = [
        f"- Files scanned for symbols: {ctx.get('files_scanned', 0)}",
        f"- Files with extracted symbols: {ctx.get('symbol_files', 0)}",
    ]

    top_files = files[:file_limit]
    if top_files:
        lines.append("- Representative symbol-bearing files:")
        for file_info in top_files:
            parts = [f"`{file_info['path']}` ({file_info['language']})"]
            if file_info["classes"]:
                parts.append("classes=" + ", ".join(file_info["classes"][:4]))
            if file_info["functions"]:
                parts.append("functions=" + ", ".join(file_info["functions"][:6]))
            if file_info["class_methods"]:
                method_items = []
                for class_name, methods in list(file_info["class_methods"].items())[:3]:
                    if methods:
                        method_items.append(f"{class_name}[{', '.join(methods[:4])}]")
                if method_items:
                    parts.append("methods=" + "; ".join(method_items))
            if file_info["routes"]:
                route_items = [f"{item['method']} {item['path']}" for item in file_info["routes"][:4]]
                parts.append("routes=" + ", ".join(route_items))
            lines.append(f"  - {' | '.join(parts)}")

    if routes:
        lines.append("- Detected API/web routes:")
        for route in routes[:route_limit]:
            handler = route.get("handler", "unknown")
            lines.append(f"  - `{route['method']} {route['path']}` -> `{handler}` in `{route['file']}`")

    return "\n".join(lines)


def _extract_file_symbols(path: Path, rel: Path, language: str) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    if language == "python":
        classes, class_methods, functions, routes = _extract_python_symbols(content)
    else:
        classes, class_methods, functions, routes = _extract_jsts_symbols(content)
    return {
        "path": str(rel),
        "language": language,
        "classes": classes,
        "class_methods": class_methods,
        "functions": functions,
        "routes": routes,
    }


def _extract_python_symbols(content: str) -> tuple[list[str], dict[str, list[str]], list[str], list[dict[str, str]]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [], {}, [], []

    classes: list[str] = []
    class_methods: dict[str, list[str]] = {}
    functions: list[str] = []
    routes: list[dict[str, str]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            routes.extend(_extract_python_routes(node))
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
            methods = [
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if methods:
                class_methods[node.name] = methods

    return classes, class_methods, functions, routes


def _extract_python_routes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in ROUTE_DECORATORS:
            continue
        path = "/"
        if decorator.args:
            first = decorator.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                path = first.value
        routes.append({
            "method": method.upper(),
            "path": path,
            "handler": node.name,
        })
    return routes


def _extract_jsts_symbols(content: str) -> tuple[list[str], dict[str, list[str]], list[str], list[dict[str, str]]]:
    classes = _unique_matches(
        re.findall(r"(?m)^\s*(?:export\s+default\s+|export\s+)?class\s+([A-Za-z_]\w*)", content)
    )
    named_functions = re.findall(
        r"(?m)^\s*(?:export\s+default\s+|export\s+)?function\s+([A-Za-z_]\w*)\s*\(",
        content,
    )
    arrow_functions = re.findall(
        r"(?m)^\s*(?:export\s+)?const\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^=\n]*\)|[A-Za-z_]\w*)\s*=>",
        content,
    )
    functions = _unique_matches(named_functions + arrow_functions)

    class_methods: dict[str, list[str]] = {}
    for class_name, body in re.findall(
        r"(?s)(?:export\s+default\s+|export\s+)?class\s+([A-Za-z_]\w*)[^{]*\{(.*?)\n\}",
        content,
    ):
        methods = _unique_matches(
            re.findall(r"(?m)^\s*(?:async\s+)?([A-Za-z_]\w*)\s*\([^;\n]*\)\s*\{", body)
        )
        methods = [name for name in methods if name != "constructor"]
        if methods:
            class_methods[class_name] = methods

    routes = []
    for method, path in re.findall(
        r"""(?m)^\s*(?:app|router)\.(get|post|put|patch|delete|options|head)\(\s*['"]([^'"]+)['"]""",
        content,
    ):
        routes.append({"method": method.upper(), "path": path, "handler": "anonymous"})

    return classes, class_methods, functions, routes


def _unique_matches(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
