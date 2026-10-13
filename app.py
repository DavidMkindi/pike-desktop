"""Pike - a polished AI desktop app powered by Flask + pywebview.

Run options
-----------
    python app.py                 # open in the desktop window
    python app.py --browser       # open in your default browser
    python app.py --port 9000     # choose a port

The Flask backend serves the frontend and exposes a small JSON/SSE API.
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
import requests

import ai_client
import config
import database
import terminal as terminal_manager
import workspace

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

database.init_db()

logger = logging.getLogger("pike")

atexit.register(terminal_manager.manager.shutdown)


def _with_workspace_context(messages: Any) -> Any:
    """Prepend a system prompt describing the open workspace, if any.

    This is what lets Pike act like a coding agent: it knows the folder it is
    allowed to read and write, and is told to use the workspace tools.
    """
    root = config.get_workspace()
    if not root:
        return messages
    if not isinstance(messages, list):
        return messages
    try:
        files = workspace.index_files(workspace.Path(root))
    except workspace.WorkspaceError:
        files = []
    listing = "\n".join(f"- {path}" for path in files[:40]) if files else "(none detected)"
    context = (
        f"You are working inside the user's open project folder: {root}\n"
        "You can read and write files in this folder using the workspace tools "
        "provided by the app. You have full access: read, write, edit, delete, "
        "rename and move files, create folders, and run any shell/terminal "
        "command in the folder. Prefer reading files before editing them, keep "
        "changes minimal and focused, and preserve existing formatting.\n"
        "Use the tools to inspect the project — never invent file contents.\n"
        f"Notable files:\n{listing}"
    )
    return [{"role": "system", "content": context}, *messages]


# --------------------------------------------------------------------------- #
#  Workspace tools (real function calling, scoped to the open folder)         #
# --------------------------------------------------------------------------- #
WORKSPACE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the files and folders in the opened workspace, optionally under a subfolder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Folder path relative to the workspace root. Omit for the root.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the text content of a file in the opened workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace root.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a text file in the opened workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full new content of the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search files by name or text content inside the opened workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for (case-insensitive).",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": (
                "Delete a file or folder inside the opened workspace. "
                "Set recursive to true to delete a non-empty folder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File or folder path relative to the workspace root.",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Delete folders and all their contents. Defaults to true.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "Rename or move a file or folder inside the opened workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {
                        "type": "string",
                        "description": "Current path relative to the workspace root.",
                    },
                    "to": {
                        "type": "string",
                        "description": "New path relative to the workspace root.",
                    },
                },
                "required": ["from", "to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_directory",
            "description": "Create a folder (including parents) inside the opened workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Folder path relative to the workspace root.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command in the opened workspace and return its output. "
                "Any command is allowed (installs, builds, tests, git, etc.). "
                "Commands run non-interactively; set cwd to run from a subfolder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The full shell command to execute.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional subfolder (relative to the workspace root) to run in.",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Max seconds to wait before giving up (default 120, max 600).",
                    },
                },
                "required": ["command"],
            },
        },
    },
]


def _run_shell_command(command: str, cwd: str | None = None, timeout: float = 120.0) -> dict[str, Any]:
    """Run a shell command and capture its output. Any command is allowed."""
    command = (command or "").strip()
    if not command:
        raise workspace.WorkspaceError("Enter a command to run.")
    timeout = max(1.0, min(float(timeout or 120), 600.0))
    workdir = cwd or str(_workspace_root())
    try:
        completed = subprocess.run(  # noqa: S602 - deliberate shell access
            command,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"command": command, "error": f"Timed out after {int(timeout)}s.", "timed_out": True}
    except OSError as exc:
        raise workspace.WorkspaceError(f"Could not run the command: {exc}") from exc
    return {
        "command": command,
        "cwd": workdir,
        "exit_code": completed.returncode,
        "stdout": (completed.stdout or "")[-20000:],
        "stderr": (completed.stderr or "")[-8000:],
    }


def _run_workspace_tool(name: str, args: dict[str, Any]) -> str:
    """Execute one workspace tool and return a JSON string result."""
    try:
        root = _workspace_root()
        if name == "list_directory":
            entries = workspace.tree(root)
            folder = str(args.get("path") or "").strip().strip("/\\")
            if folder:
                prefix = folder.replace("\\", "/") + "/"
                entries = [entry for entry in entries if entry["path"].startswith(prefix)]
            return json.dumps({"entries": entries[:400]})
        if name == "read_file":
            result = workspace.read_file(root, str(args.get("path") or ""))
            return json.dumps(result)
        if name == "write_file":
            result = workspace.write_file(
                root, str(args.get("path") or ""), str(args.get("content") or "")
            )
            return json.dumps(result)
        if name == "search":
            results = workspace.search(root, str(args.get("query") or ""))
            return json.dumps({"results": results[:80]})
        if name == "delete_path":
            recursive = args.get("recursive", True)
            result = workspace.delete_path(
                root, str(args.get("path") or ""), recursive=bool(recursive)
            )
            return json.dumps(result)
        if name == "rename_path":
            result = workspace.rename_path(
                root, str(args.get("from") or ""), str(args.get("to") or "")
            )
            return json.dumps(result)
        if name == "make_directory":
            result = workspace.make_dir(root, str(args.get("path") or ""))
            return json.dumps(result)
        if name == "run_command":
            sub = str(args.get("cwd") or "").strip().strip("/\\")
            workdir = str(workspace.resolve(root, sub)) if sub else str(root)
            return json.dumps(
                _run_shell_command(
                    str(args.get("command") or ""),
                    cwd=workdir,
                    timeout=float(args.get("timeout") or 120),
                )
            )
        return json.dumps({"error": f"Unknown tool: {name}"})
    except workspace.WorkspaceError as exc:
        return json.dumps({"error": exc.message})
    except Exception as exc:  # pragma: no cover - defensive
        return json.dumps({"error": f"Tool {name} failed: {exc}"})


def _primary_work_area() -> tuple[int, int] | None:
    """Return the primary monitor's usable (taskbar-excluded) size in pixels.

    Used to keep the initial window from opening larger than the screen, which
    would push content below the bottom edge. Returns ``None`` when the size
    cannot be determined (non-Windows or unexpected failure).
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        SPI_GETWORKAREA = 0x0030
        rect = _RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if ok:
            return rect.right - rect.left, rect.bottom - rect.top
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Could not determine work area: %s", exc)
    return None


def _initial_window_size() -> tuple[int, int]:
    """Pick a sensible starting size that always fits inside the monitor."""
    default_w, default_h = 1440, 920
    min_w, min_h = 860, 620
    work = _primary_work_area()
    if not work:
        return default_w, default_h
    # Leave a small margin so the window does not touch the screen edges.
    margin = 60
    width = min(default_w, max(min_w, work[0] - margin))
    height = min(default_h, max(min_h, work[1] - margin))
    return width, height


def _resource_path(*parts: str) -> str:
    """Locate a bundled resource both in source and in a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None) or str(config.ROOT)
    return os.path.join(base, *parts)


def _icon_path() -> str | None:
    """Return the path to the app icon (``static/pike.ico``) if it exists."""
    for candidate in (
        _resource_path("static", "pike.ico"),
        _resource_path("pike.ico"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def _set_app_user_model_id() -> None:
    """Give the process its own Windows AppUserModelID.

    Without this, Windows groups the taskbar button under ``python.exe`` and
    shows the Python icon instead of Pike's. A distinct AppUserModelID makes
    Windows treat Pike as its own application and use the window icon set in
    :func:`_apply_window_icon`.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"Pike.App.{config.APP_VERSION}"
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Could not set AppUserModelID: %s", exc)


def _apply_window_icon(window: Any) -> None:
    """Force the native window to use the bundled Pike icon.

    pywebview's WinForms backend derives the window icon from
    ``sys.executable`` (i.e. ``python.exe`` when running from source), so we
    override it here with our own ``.ico``.
    """
    native = getattr(window, "native", None)
    if native is None:  # Unknown backend/version - nothing to do.
        return
    path = _icon_path()
    if not path:
        logger.debug("No app icon found to apply")
        return
    try:
        from System import Action
        from System.Drawing import Icon
    except Exception:  # pragma: no cover - non-Windows or pythonnet missing
        return

    def apply() -> None:
        # Ask .NET for the best-matching large frame so the taskbar and
        # Alt-Tab views stay crisp (the default constructor grabs 16x16).
        try:
            native.Icon = Icon(path, 256, 256)
        except Exception:
            native.Icon = Icon(path)

    try:
        if native.InvokeRequired:
            native.Invoke(Action(apply))
        else:
            apply()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Could not apply window icon: %s", exc)


def _keep_inside_work_area(window: Any) -> None:
    """Constrain a frameless window's maximized size to the monitor work area.

    pywebview's WinForms backend maximizes frameless windows to the *full*
    monitor bounds, which hides the Windows taskbar. Setting ``MaximizedBounds``
    to the screen's working area keeps the taskbar (and any docked bars) visible
    while the window is maximized.
    """
    native = getattr(window, "native", None)
    if native is None:  # Unknown backend/version - nothing we can do safely.
        return
    try:
        import System.Windows.Forms as WinForms
        from System import Action
        from System.Drawing import Rectangle
    except Exception:  # pragma: no cover - non-Windows or pythonnet missing
        return

    def apply() -> None:
        screen = WinForms.Screen.FromHandle(native.Handle)
        work = screen.WorkingArea
        native.MaximizedBounds = Rectangle(work.X, work.Y, work.Width, work.Height)

    try:
        # The native form must be touched on its own (UI) thread.
        if native.InvokeRequired:
            native.Invoke(Action(apply))
        else:
            apply()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Could not adjust maximized bounds: %s", exc)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _json_error(message: str, status: int = 400) -> tuple[Response, int]:
    return jsonify({"ok": False, "error": message}), status


def _sse(event_type: str, data: dict[str, Any]) -> str:
    """Format one Server-Sent-Event frame."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _version_tuple(text: str) -> tuple[int, ...]:
    """Turn a version string into a comparable tuple of integers."""
    parts = re.findall(r"\d+", str(text) or "")
    return tuple(int(part) for part in parts) if parts else (0,)


@app.after_request
def _no_cache(response: Response) -> Response:
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> str:
    return render_template(
        "index.html",
        app_name=config.APP_NAME,
        app_version=config.APP_VERSION,
        desktop_mode=bool(app.config.get("DESKTOP_MODE")),
    )


@app.get("/healthz")
def healthz() -> Response:
    return jsonify({"ok": True, "app": config.APP_NAME, "version": config.APP_VERSION})


# --------------------------------------------------------------------------- #
#  Status & settings
# --------------------------------------------------------------------------- #
@app.get("/api/status")
def api_status() -> Response:
    info = ai_client.provider_info()
    return jsonify(
        {
            "ok": True,
            "app": config.APP_NAME,
            "version": config.APP_VERSION,
            **info,
        }
    )


@app.get("/api/update")
def api_update_check() -> Response:
    """Check whether a newer version is available.

    Looks at the update manifest configured via ``PIKE_UPDATE_URL`` (a small
    JSON document such as ``{"version": "1.2.0", "url": "...", "notes": "..."}``).
    When no manifest is configured the app simply reports that it is up to date
    and where to get new releases.
    """
    current = config.APP_VERSION
    manifest_url = config.get_update_url()
    latest = current
    download_url = ""
    notes = ""
    configured = bool(manifest_url)

    if configured:
        try:
            response = requests.get(manifest_url, timeout=8)
            response.raise_for_status()
            manifest = response.json()
            if isinstance(manifest, dict):
                latest = str(manifest.get("version") or current)
                download_url = str(manifest.get("url") or "")
                notes = str(manifest.get("notes") or "")
        except Exception as exc:
            return jsonify(
                {
                    "ok": False,
                    "error": f"Could not check for updates: {exc}",
                    "current": current,
                }
            ), 502

    return jsonify(
        {
            "ok": True,
            "configured": configured,
            "current": current,
            "latest": latest,
            "update_available": _version_tuple(latest) > _version_tuple(current),
            "url": download_url or config.RELEASES_URL,
            "notes": notes,
        }
    )


@app.get("/api/settings")
def api_get_settings() -> Response:
    settings = config.load_settings()
    provider = config.get_active_provider()
    return jsonify(
        {
            "ok": True,
            "settings": settings,
            "models": config.get_models(),
            "default_model": config.get_default_model(),
            "base_url": config.get_base_url(),
            "provider": provider,
            "providers": config.available_providers(),
            "has_api_key": config.provider_has_key(provider),
            "catalog_updated": config.CATALOG_UPDATED,
            "reasoning_levels": config.REASONING_LEVELS,
            "reasoning_effort": config.get_reasoning_effort(),
        }
    )


@app.post("/api/settings")
def api_save_settings() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        # Switching provider: set it first so the key/base URL land on the
        # right provider.
        if payload.get("provider"):
            config.set_active_provider(str(payload["provider"]))

        if "api_key" in payload:
            key = payload.get("api_key")
            config.save_api_key(key if isinstance(key, str) else None)
        if "base_url" in payload:
            base_url = payload.get("base_url")
            if base_url and not str(base_url).startswith(("http://", "https://")):
                return _json_error("Base URL must start with http:// or https://")
            config.set_base_url(str(base_url) if base_url else None)
        if "model" in payload and payload.get("model"):
            config.set_default_model(str(payload["model"]))
        if "reasoning_effort" in payload:
            config.set_reasoning_effort(str(payload.get("reasoning_effort") or ""))
    except Exception as exc:  # pragma: no cover - defensive
        return _json_error(f"Could not save settings: {exc}", 500)
    return api_get_settings()


@app.get("/api/providers")
def api_providers() -> Response:
    return jsonify(
        {
            "ok": True,
            "providers": config.available_providers(),
            "active": config.get_active_provider(),
            "catalog_updated": config.CATALOG_UPDATED,
        }
    )


@app.post("/api/providers/models")
def api_refresh_models() -> Response:
    """Pull the live model list from a provider and cache it."""
    payload = request.get_json(silent=True) or {}
    provider = payload.get("provider") or config.get_active_provider()
    if provider not in config.PROVIDERS:
        return _json_error("Unknown provider.", 404)
    try:
        models = ai_client.fetch_models(provider)
    except ai_client.AIError as exc:
        return _json_error(exc.message, exc.status)
    # Refresh the active model if it disappeared from the global catalogue.
    all_ids = {model["id"] for model in config.get_models()}
    if config.get_default_model() not in all_ids and models:
        config.set_default_model(models[0]["id"])
    return jsonify(
        {
            "ok": True,
            "provider": provider,
            "models": config.get_models(),
        }
    )


@app.post("/api/settings/test")
def api_test_connection() -> Response:
    payload = request.get_json(silent=True) or {}
    model = payload.get("model") or config.get_default_model()
    effort = payload.get("reasoning_effort") or config.get_reasoning_effort()
    try:
        result = ai_client.complete_chat(
            [{"role": "user", "content": "Reply with the single word: ready"}],
            model=model,
            reasoning_effort=effort,
        )
        return jsonify({
            "ok": True,
            "reply": result["reply"],
            "reasoning": result.get("reasoning", ""),
            "model": result["model"],
            "provider": result.get("provider", ""),
        })
    except ai_client.AIError as exc:
        return _json_error(exc.message, exc.status)


# --------------------------------------------------------------------------- #
#  Chat (streaming + classic)
# --------------------------------------------------------------------------- #
@app.post("/api/chat/stream")
def api_chat_stream() -> Response:
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    model = payload.get("model")
    conversation_id = payload.get("conversation_id")
    reasoning_effort = payload.get("reasoning_effort")

    def generate():
        started = time.time()
        collected: list[str] = []
        thinking: list[str] = []
        wire: list[dict[str, Any]] = list(
            _with_workspace_context(messages) if isinstance(messages, list) else []
        )
        tools = WORKSPACE_TOOLS if config.get_workspace() else None
        max_steps = 8
        try:
            yield _sse("start", {"model": model or config.get_default_model()})
            for _ in range(max_steps):
                tool_calls: list[dict[str, Any]] = []
                for delta in ai_client.stream_chat(
                    wire, model=model, reasoning_effort=reasoning_effort, tools=tools
                ):
                    if delta["type"] == "reasoning":
                        thinking.append(delta["text"])
                        yield _sse("reasoning", {"text": delta["text"]})
                    elif delta["type"] == "tool_calls":
                        tool_calls = delta["calls"]
                    else:
                        collected.append(delta["text"])
                        yield _sse("delta", {"text": delta["text"]})

                # No tools requested: the model produced its final answer.
                if not tool_calls:
                    break

                # Record the assistant's tool request, run the tools, feed the
                # results back and let the model continue in the next step.
                wire.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = function.get("name") or "tool"
                    raw = function.get("arguments") or "{}"
                    try:
                        args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                    except ValueError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    yield _sse("tool", {"name": name, "arguments": json.dumps(args)})
                    output = _run_workspace_tool(name, args)
                    try:
                        payload = json.loads(output)
                    except ValueError:
                        payload = {"output": output}
                    yield _sse("tool_output", {"name": name, "result": payload})
                    wire.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") or "",
                            "content": output,
                        }
                    )

            full_reply = "".join(collected)
            yield _sse(
                "done",
                {
                    "reply": full_reply,
                    "reasoning": "".join(thinking),
                    "elapsed": round(time.time() - started, 2),
                },
            )
        except ai_client.AIError as exc:
            yield _sse("error", {"error": exc.message})
        except Exception as exc:  # pragma: no cover - defensive
            yield _sse("error", {"error": f"Unexpected error: {exc}"})

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    return response


@app.post("/api/chat")
def api_chat() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        result = ai_client.complete_chat(
            _with_workspace_context(payload.get("messages")), model=payload.get("model")
        )
        return jsonify({"ok": True, **result})
    except ai_client.AIError as exc:
        return _json_error(exc.message, exc.status)


# --------------------------------------------------------------------------- #
#  Conversation history
# --------------------------------------------------------------------------- #
@app.get("/api/conversations")
def api_list_conversations() -> Response:
    query = request.args.get("q")
    return jsonify({"ok": True, "conversations": database.list_conversations(query)})


@app.post("/api/conversations")
def api_create_conversation() -> Response:
    payload = request.get_json(silent=True) or {}
    conversation = database.create_conversation(
        title=payload.get("title", "New conversation"), model=payload.get("model")
    )
    return jsonify({"ok": True, "conversation": conversation}), 201


@app.get("/api/conversations/<conversation_id>")
def api_get_conversation(conversation_id: str) -> Response:
    conversation = database.get_conversation(conversation_id)
    if conversation is None:
        return _json_error("Conversation not found.", 404)
    return jsonify({"ok": True, "conversation": conversation})


@app.put("/api/conversations/<conversation_id>")
def api_update_conversation(conversation_id: str) -> Response:
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return _json_error("'messages' must be a list.")
    saved = database.save_conversation(
        conversation_id,
        messages,
        title=payload.get("title"),
        model=payload.get("model"),
    )
    return jsonify({"ok": True, "conversation": saved})


@app.patch("/api/conversations/<conversation_id>")
def api_rename_conversation(conversation_id: str) -> Response:
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return _json_error("A title is required.")
    if not database.rename_conversation(conversation_id, title):
        return _json_error("Conversation not found.", 404)
    return jsonify({"ok": True, "id": conversation_id, "title": title})


@app.delete("/api/conversations/<conversation_id>")
def api_delete_conversation(conversation_id: str) -> Response:
    if not database.delete_conversation(conversation_id):
        return _json_error("Conversation not found.", 404)
    return jsonify({"ok": True})


@app.delete("/api/conversations")
def api_clear_conversations() -> Response:
    count = database.clear_conversations()
    return jsonify({"ok": True, "deleted": count})


# --------------------------------------------------------------------------- #
#  Workspace (folder opened for coding)                                       #
# --------------------------------------------------------------------------- #
def _workspace_root() -> Any:
    """Return the opened workspace as a ``Path`` or raise a 400 JSON error."""
    path = config.get_workspace()
    if not path:
        raise workspace.WorkspaceError("Open a folder first to use file tools.", 400)
    return workspace.Path(path)


def _workspace_error(exc: workspace.WorkspaceError) -> tuple[Response, int]:
    return _json_error(exc.message, exc.status)


@app.get("/api/workspace")
def api_get_workspace() -> Response:
    path = config.get_workspace()
    if not path:
        return jsonify({"ok": True, "workspace": None})
    try:
        return jsonify({"ok": True, "workspace": workspace.describe(workspace.Path(path))})
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)


@app.post("/api/workspace")
def api_set_workspace() -> Response:
    payload = request.get_json(silent=True) or {}
    path = payload.get("path")
    if path is None or (isinstance(path, str) and not path.strip()):
        try:
            config.set_workspace("")
        except ValueError as exc:
            return _json_error(str(exc))
        return jsonify({"ok": True, "workspace": None})
    try:
        resolved = config.set_workspace(str(path))
    except ValueError as exc:
        return _json_error(str(exc), 400)
    try:
        return jsonify({"ok": True, "workspace": workspace.describe(workspace.Path(resolved))})
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)


@app.get("/api/workspace/browse")
def api_browse() -> Response:
    """List sub-folders so the UI can offer an in-app folder picker."""
    raw = request.args.get("path") or os.path.expanduser("~")
    target = workspace.Path(raw).expanduser()
    if not target.is_dir():
        target = workspace.Path(raw).expanduser().parent
    target = target.resolve()
    dirs: list[dict[str, Any]] = []
    try:
        children = sorted(
            (child for child in target.iterdir() if child.is_dir() and not child.name.startswith(".")),
            key=lambda item: item.name.lower(),
        )
    except (OSError, PermissionError):
        children = []
    for child in children[:400]:
        dirs.append({"name": child.name, "path": str(child)})
    parent = str(target.parent) if target.parent != target else ""
    return jsonify({
        "ok": True,
        "path": str(target),
        "name": target.name or str(target),
        "parent": parent,
        "home": os.path.expanduser("~"),
        "drives": _list_drives(),
        "directories": dirs,
    })


def _list_drives() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    drives: list[dict[str, str]] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.isdir(root):
            drives.append({"name": root, "path": root})
    return drives


@app.get("/api/workspace/tree")
def api_workspace_tree() -> Response:
    root = config.get_workspace()
    if not root:
        return jsonify({"ok": True, "root": None, "entries": []})
    try:
        entries = workspace.tree(workspace.Path(root))
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)
    return jsonify({"ok": True, "root": root, "entries": entries})


@app.post("/api/workspace/read")
def api_workspace_read() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        root = _workspace_root()
        result = workspace.read_file(root, str(payload.get("path") or ""))
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)
    return jsonify({"ok": True, "file": result})


@app.post("/api/workspace/write")
def api_workspace_write() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        root = _workspace_root()
        result = workspace.write_file(
            root, str(payload.get("path") or ""), str(payload.get("content") or "")
        )
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)
    return jsonify({"ok": True, "file": result})


@app.post("/api/workspace/delete")
def api_workspace_delete() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        root = _workspace_root()
        result = workspace.delete_path(
            root,
            str(payload.get("path") or ""),
            recursive=bool(payload.get("recursive", True)),
        )
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)
    return jsonify({"ok": True, "result": result})


@app.post("/api/workspace/rename")
def api_workspace_rename() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        root = _workspace_root()
        result = workspace.rename_path(
            root, str(payload.get("from") or payload.get("path") or ""), str(payload.get("to") or "")
        )
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)
    return jsonify({"ok": True, "result": result})


@app.post("/api/workspace/mkdir")
def api_workspace_mkdir() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        root = _workspace_root()
        result = workspace.make_dir(root, str(payload.get("path") or ""))
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)
    return jsonify({"ok": True, "result": result})


@app.get("/api/workspace/search")
def api_workspace_search() -> Response:
    query = request.args.get("q") or ""
    try:
        root = _workspace_root()
        results = workspace.search(root, query)
    except workspace.WorkspaceError as exc:
        return _workspace_error(exc)
    return jsonify({"ok": True, "results": results})


# --------------------------------------------------------------------------- #
#  Terminal                                                                   #
# --------------------------------------------------------------------------- #
def _terminal_error(message: str, status: int = 400) -> tuple[Response, int]:
    return _json_error(message, status)


@app.get("/api/terminal")
def api_terminal_list() -> Response:
    return jsonify({"ok": True, "sessions": terminal_manager.manager.list()})


@app.post("/api/terminal")
def api_terminal_create() -> Response:
    payload = request.get_json(silent=True) or {}
    cwd = payload.get("cwd") or config.get_workspace() or os.getcwd()
    try:
        session = terminal_manager.manager.create(cwd=str(cwd))
    except Exception as exc:  # pragma: no cover - defensive
        return _terminal_error(f"Could not start a terminal: {exc}", 500)
    return jsonify({"ok": True, "session": session.info()}), 201


@app.get("/api/terminal/<session_id>")
def api_terminal_read(session_id: str) -> Response:
    try:
        session = terminal_manager.manager.get(session_id)
    except KeyError:
        return _terminal_error("That terminal is no longer open.", 404)
    return jsonify({"ok": True, "output": session.read(), "running": session.running})


@app.post("/api/terminal/<session_id>")
def api_terminal_write(session_id: str) -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        session = terminal_manager.manager.get(session_id)
    except KeyError:
        return _terminal_error("That terminal is no longer open.", 404)
    try:
        session.write(str(payload.get("input") or ""))
    except RuntimeError as exc:
        return _terminal_error(str(exc), 409)
    return jsonify({"ok": True})


@app.post("/api/terminal/<session_id>/interrupt")
def api_terminal_interrupt(session_id: str) -> Response:
    try:
        session = terminal_manager.manager.get(session_id)
    except KeyError:
        return _terminal_error("That terminal is no longer open.", 404)
    session.interrupt()
    return jsonify({"ok": True})


@app.delete("/api/terminal/<session_id>")
def api_terminal_close(session_id: str) -> Response:
    terminal_manager.manager.close(session_id)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  Saving a conversation through the chat endpoint's answer
# --------------------------------------------------------------------------- #
@app.post("/api/conversations/save")
def api_save_chat() -> Response:
    """Persist a conversation that may not exist yet, auto-titling it."""
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return _json_error("'messages' must be a list.")
    saved = database.save_conversation(
        payload.get("conversation_id"),
        messages,
        title=payload.get("title"),
        model=payload.get("model"),
    )
    return jsonify({"ok": True, "conversation": saved})


# --------------------------------------------------------------------------- #
#  Error handlers
# --------------------------------------------------------------------------- #
@app.errorhandler(404)
def handle_404(_: Any) -> tuple[Response, int]:
    if request.path.startswith("/api/"):
        return _json_error("API route not found.", 404)
    return jsonify({"ok": False, "error": "Page not found."}), 404


@app.errorhandler(500)
def handle_500(exc: Any) -> tuple[Response, int]:
    return _json_error(f"Internal server error: {exc}", 500)


# --------------------------------------------------------------------------- #
#  Launchers
# --------------------------------------------------------------------------- #
def run_desktop(host: str, port: int) -> None:
    """Serve Flask in a thread and open a native desktop window with pywebview."""
    import webview

    # Identify the process as Pike so Windows uses our icon in the taskbar
    # instead of grouping it under python.exe.
    _set_app_user_model_id()

    # Tell the frontend it is running inside the native window so the boot
    # sequence waits for the title-bar controls before hiding the preloader.
    app.config["DESKTOP_MODE"] = True

    url = f"http://{host}:{port}/"
    server_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True),
        daemon=True,
    )
    server_thread.start()

    # Give the server a moment to bind before the window requests the page.
    time.sleep(0.6)

    width, height = _initial_window_size()

    webview.create_window(
        config.APP_NAME,
        url,
        width=width,
        height=height,
        min_size=(860, 620),
        background_color="#141414",
        fullscreen=False,
        frameless=True,
        easy_drag=False,
        text_select=True,
    )
    window = webview.windows[0]
    window_state = {"maximized": False}

    # Replace pywebview's default (Python) window icon with Pike's own icon.
    # The native form only exists once the GUI starts, so apply it on show.
    window.events.before_show += lambda: _apply_window_icon(window)
    window.events.shown += lambda: _apply_window_icon(window)

    def _sync_maximized(maximized: bool) -> None:
        """Record the state and let the UI swap the maximize/restore glyph."""
        window_state["maximized"] = bool(maximized)
        try:
            window.evaluate_js(
                "window.__setWindowMaximized && window.__setWindowMaximized("
                f"{str(bool(maximized)).lower()})"
            )
        except Exception as exc:  # pragma: no cover - window may be gone
            logger.debug("Could not sync maximized state: %s", exc)

    window.events.maximized += lambda: _sync_maximized(True)
    window.events.restored += lambda: _sync_maximized(False)

    # Keep the frameless window within the monitor's working area so maximizing
    # it does not cover the Windows taskbar. Re-checked whenever the window is
    # shown or moved (e.g. dragged to another monitor).
    window.events.shown += lambda: _keep_inside_work_area(window)
    window.events.moved += lambda *_: _keep_inside_work_area(window)

    def minimize():
        window.minimize()

    def toggle_maximize():
        _keep_inside_work_area(window)
        if window_state["maximized"]:
            window.restore()
            window_state["maximized"] = False
        else:
            window.maximize()
            window_state["maximized"] = True
        # The maximize/restored events sync the glyph; also return the new
        # state so the click handler can update it immediately.
        return window_state["maximized"]

    def close():
        window.destroy()

    window.expose(minimize, toggle_maximize, close)
    webview.start(debug=config.DEBUG)


def run_server(host: str, port: int) -> None:
    """Serve in the browser (useful for development / packaging)."""
    app.run(host=host, port=port, debug=config.DEBUG, use_reloader=False, threaded=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{config.APP_NAME} desktop app")
    parser.add_argument("--host", default=config.HOST, help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=config.PORT, help="Port (default: 8765)")
    parser.add_argument("--browser", action="store_true", help="Open in the default browser instead of the desktop window")
    parser.add_argument("--server", action="store_true", help="Run the Flask server only (no window)")
    args = parser.parse_args()

    if args.server:
        run_server(args.host, args.port)
        return

    if args.browser or config.BROWSER_ONLY:
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()
        run_server(args.host, args.port)
        return

    try:
        run_desktop(args.host, args.port)
    except ImportError:
        print(
            "pywebview is not installed, falling back to the browser.\n"
            "Install the desktop window with:  pip install pywebview",
            file=sys.stderr,
        )
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()
        run_server(args.host, args.port)


if __name__ == "__main__":
    main()