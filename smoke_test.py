"""End-to-end smoke test for Pike.

Verifies that:
  1. The official provider catalogue is registered and models resolve to the
     provider that owns them.
  2. The full cross-provider model list is always exposed (no provider hides
     another provider's models).
  3. The Flask API endpoints expose the model + thinking level.

Run with:  python smoke_test.py
Network steps are skipped automatically when the provider is unreachable.
"""
from __future__ import annotations

import json
import sys

import config

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    mark = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"[{mark}] {name}{(' — ' + detail) if detail else ''}")


print("=" * 64)
print(f"{config.APP_NAME} smoke test")
print("=" * 64)

# --- 1. Registry ----------------------------------------------------------- #
models = config.get_models()
check("model list is non-empty", bool(models), f"{len(models)} models")

providers_present = {m.get("provider") for m in models}
check(
    "models come from multiple providers",
    len(providers_present) > 1,
    ", ".join(sorted(p for p in providers_present if p)),
)
check("no tokenharbor provider", "tokenharbor.ai" not in config.PROVIDERS)
check("all models tagged with a provider", all(m.get("provider") for m in models))

gpt = next((m for m in models if m.get("provider") == "openai" and str(m.get("id", "")).startswith("gpt")), None)
check("an OpenAI GPT model is registered", gpt is not None, gpt.get("id") if gpt else "")
check(
    "frontier GPT models support thinking",
    all(
        m.get("reasoning")
        for m in models
        if m.get("provider") == "openai"
        and str(m.get("id", "")).startswith("gpt-5")
    ),
)

# Resolution routes to the owning provider, regardless of the active one.
openai_model = next((m["id"] for m in models if m.get("provider") == "openai"), None)
if openai_model:
    connection = config.resolve_connection(openai_model)
    check(
        "openai model resolves to openai",
        connection["provider"] == "openai" and connection["base_url"] == "https://api.openai.com/v1",
        f"{connection['provider']} · {connection['base_url']}",
    )

groq_model = next((m["id"] for m in models if m.get("provider") == "groq"), None)
if groq_model:
    connection = config.resolve_connection(groq_model)
    check(
        "groq model resolves to groq",
        connection["provider"] == "groq" and connection["base_url"] == "https://api.groq.com/openai/v1",
        f"{connection['provider']} · {connection['base_url']}",
    )

levels = [level["id"] for level in config.REASONING_LEVELS]
check("thinking levels available", levels == ["off", "low", "medium", "high"], ", ".join(levels))

# --- 2. HTTP API ----------------------------------------------------------- #
try:
    import app as webapp

    client = webapp.app.test_client()

    status = client.get("/api/status").get_json()
    check("GET /api/status", status.get("ok") is True)
    check("status exposes thinking levels", bool(status.get("reasoning_levels")))
    check("status exposes the full catalogue", len(status.get("models", [])) == len(models))

    settings = client.get("/api/settings").get_json()
    check("GET /api/settings", settings.get("ok") is True)
    check("settings exposes the full catalogue", len(settings.get("models", [])) == len(models))
    check(
        "settings lists official providers",
        any(p.get("id") == "openai" for p in settings.get("providers", [])),
    )

    # --- Workspace API ----------------------------------------------------- #
    ws = client.get("/api/workspace").get_json()
    check("GET /api/workspace", ws.get("ok") is True)

    import os as _os
    import workspace as _workspace

    root = config.ROOT
    tree = _workspace.tree(root)
    check("workspace.tree lists project files", any(e["name"] == "app.py" for e in tree))
    read = _workspace.read_file(root, "app.py")
    check("workspace.read_file returns content", bool(read["content"]), f"{read['size']} bytes")
    found = _workspace.search(root, "def main", limit=5)
    check("workspace.search finds text", bool(found), f"{len(found)} hits")
    try:
        _workspace.read_file(root, "../config.py")
        check("workspace blocks path traversal", False)
    except _workspace.WorkspaceError:
        check("workspace blocks path traversal", True)

    # --- Terminal API ------------------------------------------------------ #
    created = client.post("/api/terminal", json={}).get_json()
    check("POST /api/terminal", created.get("ok") is True)
    session_id = (created.get("session") or {}).get("id")
    if session_id:
        client.post(f"/api/terminal/{session_id}", json={"input": "echo pike-terminal-ok"})
        import time as _time

        _time.sleep(1.2)
        out = client.get(f"/api/terminal/{session_id}").get_json()
        check("terminal echoes command output", "pike-terminal-ok" in (out.get("output") or ""))
        closed = client.delete(f"/api/terminal/{session_id}").get_json()
        check("DELETE /api/terminal", closed.get("ok") is True)
except Exception as exc:  # noqa: BLE001
    check("HTTP API smoke", False, str(exc))

print("=" * 64)
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)