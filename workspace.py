"""Workspace tools — a Cursor-style local file reader/writer for Pike.

A *workspace* is a folder the user opens in the composer. Once open, Pike can
read and write files inside it (and only inside it) so it can help with coding
tasks. This module is deliberately small and dependency-free.

Safety
------
Every path is resolved and checked against the workspace root, so a request can
never escape the opened folder (``..`` traversal, absolute paths or symlinks).
Files larger than :data:`MAX_READ_BYTES` are truncated when read.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

MAX_READ_BYTES = 512 * 1024  # 512 KB of text returned per read


class WorkspaceError(Exception):
    """A user-facing workspace error."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# Directories that are never worth listing or searching inside a project.
PRUNED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", "dist", "build", ".next", ".nuxt", ".cache", ".idea", ".vscode",
    "target", "vendor", ".gradle", ".mypy_cache", ".pytest_cache", ".tox",
}

# Text file extensions we are happy to read. Anything else is treated as binary.
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json",
    ".jsonc", ".json5", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".env", ".properties", ".xml", ".html", ".htm", ".css", ".scss", ".sass",
    ".less", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".py", ".pyi", ".rb", ".go", ".rs", ".java", ".kt", ".kts", ".c", ".h",
    ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".php", ".swift", ".m", ".mm",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd", ".sql", ".graphql",
    ".gql", ".proto", ".dockerfile", ".makefile", ".mk", ".gitignore",
    ".gitattributes", ".editorconfig", ".lock", ".patch", ".diff",
}


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    name = path.name.lower()
    if name in {"dockerfile", "makefile", "procfile", "license", "readme"}:
        return True
    # Fall back to sniffing for a NUL byte in the first chunk.
    try:
        with path.open("rb") as handle:
            chunk = handle.read(2048)
        return b"\x00" not in chunk
    except OSError:
        return False


def resolve(root: Path, relative: str | None) -> Path:
    """Resolve ``relative`` inside ``root``, refusing escapes.

    Raises :class:`WorkspaceError` when the target is outside the workspace.
    """
    base = root.resolve()
    target = (base / (relative or "")).resolve() if not os.path.isabs(relative or "") else Path(relative).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise WorkspaceError("That path is outside the opened folder.") from exc
    return target


def tree(root: Path, *, max_entries: int = 3000, max_depth: int = 12) -> list[dict[str, Any]]:
    """Return a flat, depth-tagged listing of the workspace.

    Each entry is ``{"path", "name", "type": "file"|"dir", "depth"}``. Heavy
    directories (``node_modules`` etc.) are skipped. Hidden files are included
    but sorted after visible ones.
    """
    base = root.resolve()
    if not base.is_dir():
        raise WorkspaceError("The opened folder no longer exists.", 404)

    entries: list[dict[str, Any]] = []

    def walk(directory: Path, depth: int) -> None:
        if len(entries) >= max_entries or depth > max_depth:
            return
        try:
            children = sorted(
                directory.iterdir(),
                key=lambda item: (item.is_file(), item.name.lower()),
            )
        except (OSError, PermissionError):
            return
        for child in children:
            if len(entries) >= max_entries:
                return
            name = child.name
            if child.is_dir():
                if name in PRUNED_DIRS or name.startswith("."):
                    continue
                entries.append({"path": _rel(base, child), "name": name, "type": "dir", "depth": depth})
                walk(child, depth + 1)
            elif child.is_file():
                entries.append({"path": _rel(base, child), "name": name, "type": "file", "depth": depth})

    walk(base, 0)
    return entries


def _rel(base: Path, target: Path) -> str:
    try:
        return target.relative_to(base).as_posix()
    except ValueError:
        return target.name


def read_file(root: Path, relative: str) -> dict[str, Any]:
    """Read a text file inside the workspace, truncating huge files."""
    path = resolve(root, relative)
    if not path.is_file():
        raise WorkspaceError(f"File not found: {relative}", 404)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise WorkspaceError("That file is too large to open (limit 8 MB).", 413)
    if not _is_text_file(path):
        raise WorkspaceError(f"{relative} looks like a binary file.", 415)
    try:
        text = path.read_text("utf-8", errors="replace")
    except OSError as exc:
        raise WorkspaceError(f"Could not read {relative}: {exc}") from exc
    truncated = len(text) > MAX_READ_BYTES
    if truncated:
        text = text[:MAX_READ_BYTES]
    return {
        "path": _rel(root.resolve(), path),
        "size": path.stat().st_size,
        "truncated": truncated,
        "content": text,
    }


def write_file(root: Path, relative: str, content: str) -> dict[str, Any]:
    """Create or overwrite a text file inside the workspace."""
    if not isinstance(content, str):
        raise WorkspaceError("File content must be text.")
    path = resolve(root, relative)
    if path.is_dir():
        raise WorkspaceError("That path is a folder, not a file.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
    except OSError as exc:
        raise WorkspaceError(f"Could not write {relative}: {exc}") from exc
    return {"path": _rel(root.resolve(), path), "size": path.stat().st_size, "written": True}


def make_dir(root: Path, relative: str) -> dict[str, Any]:
    path = resolve(root, relative)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkspaceError(f"Could not create folder: {exc}") from exc
    return {"path": _rel(root.resolve(), path), "created": True}


def delete_path(root: Path, relative: str, *, recursive: bool = True) -> dict[str, Any]:
    path = resolve(root, relative)
    if path == root.resolve():
        raise WorkspaceError("Refusing to delete the workspace root.")
    if not path.exists():
        raise WorkspaceError(f"Not found: {relative}", 404)
    try:
        if path.is_dir():
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()
        else:
            path.unlink()
    except OSError as exc:
        raise WorkspaceError(f"Could not delete {relative}: {exc}") from exc
    return {"path": _rel(root.resolve(), path), "deleted": True}


def rename_path(root: Path, source: str, destination: str) -> dict[str, Any]:
    """Rename or move a file/folder inside the workspace."""
    src = resolve(root, source)
    dst = resolve(root, destination)
    if not src.exists():
        raise WorkspaceError(f"Not found: {source}", 404)
    if src == root.resolve():
        raise WorkspaceError("Refusing to move the workspace root.")
    if not destination.strip():
        raise WorkspaceError("Enter a new name.")
    if dst.exists() and dst != src:
        raise WorkspaceError(f"Already exists: {destination}")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
    except OSError as exc:
        raise WorkspaceError(f"Could not rename {source}: {exc}") from exc
    return {"from": _rel(root.resolve(), src), "path": _rel(root.resolve(), dst), "renamed": True}


def search(root: Path, query: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """Find files whose name or text contains ``query`` (case-insensitive)."""
    query = (query or "").strip()
    if not query:
        raise WorkspaceError("Enter something to search for.")
    needle = query.lower()
    base = root.resolve()
    results: list[dict[str, Any]] = []

    for entry in tree(base):
        if len(results) >= limit:
            break
        if entry["type"] != "file":
            continue
        if needle in entry["name"].lower():
            results.append({"path": entry["path"], "line": 0, "text": entry["name"], "match": "name"})
            continue
        path = resolve(base, entry["path"])
        if not _is_text_file(path):
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, start=1):
                    if needle in line.lower():
                        results.append({
                            "path": entry["path"],
                            "line": number,
                            "text": line.rstrip("\n")[:240],
                            "match": "content",
                        })
                        if len(results) >= limit:
                            break
        except OSError:
            continue
    return results


def index_files(root: Path, *, limit: int = 60) -> list[str]:
    """Return a short list of likely-important files for prompt context."""
    interesting = (
        "readme", "package.json", "requirements.txt", "pyproject.toml", "cargo.toml",
        "go.mod", "pom.xml", "build.gradle", "composer.json", "gemfile",
        "makefile", "dockerfile", "tsconfig.json", "vite.config", "next.config",
        ".env.example",
    )
    found: list[str] = []
    for entry in tree(root):
        if len(found) >= limit:
            break
        if entry["type"] != "file":
            continue
        name = entry["name"].lower()
        if any(marker in name for marker in interesting):
            found.append(entry["path"])
    return found


def describe(root: Path) -> dict[str, Any]:
    """Summarise a workspace root for the UI header."""
    base = root.resolve()
    if not base.is_dir():
        raise WorkspaceError("The opened folder no longer exists.", 404)
    return {
        "path": str(base),
        "name": base.name or str(base),
    }