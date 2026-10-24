"""Pike account client for the desktop app.

This is the bridge between the desktop app and the Pike website's account
system. It lets a user sign in *through the website* using an OAuth-style
device-authorization flow, then keeps the device registered and reports
activity/usage so the web dashboard can show everything.

Design
------
* The account token + server URL live in ``account.json`` inside the same
  per-user data directory as the rest of Pike's settings.
* Nothing here is required for the app to work: if the user never signs in,
  every call is a no-op and Pike stays fully local.
* Network calls use a short timeout and never raise into the UI - callers get
  a ``{"ok": False, "error": ...}`` dict instead.

Configuration
-------------
* ``PIKE_ACCOUNT_URL``  - override the account server (default below).
* The URL can also be changed at runtime from the app's Settings ▸ Account tab.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

import config

APP_NAME = config.APP_NAME
APP_VERSION = config.APP_VERSION

ACCOUNT_FILE: Path = config.DATA_DIR / "account.json"
DEFAULT_ACCOUNT_URL = os.environ.get(
    "PIKE_ACCOUNT_URL", "https://website-seven-wine-40.vercel.app"
).rstrip("/")
REQUEST_TIMEOUT = 12
DEVICE_KIND = "desktop"

# The approval page for the sign-in that is currently in progress. It is kept
# in memory only (never sent to the desktop UI) so the account server address
# is never exposed to the frontend.
_pending_verification_url = ""

# Website pages the desktop app can open without knowing the server address.
_PAGE_PATHS = {
    "register": "/account/register",
    "dashboard": "/dashboard",
}

# Older builds pointed at the retired Render host. Treat those (and other
# previous defaults) as "not configured" so existing installs migrate to the
# current website automatically instead of silently hitting a dead server.
_LEGACY_DEFAULT_URLS = {
    "https://pike-web.onrender.com",
    "https://pike-web.onrender.com/",
}


# --------------------------------------------------------------------------- #
#  Local persistence                                                           #
# --------------------------------------------------------------------------- #
def _read() -> dict[str, Any]:
    if not ACCOUNT_FILE.is_file():
        return {}
    try:
        data = json.loads(ACCOUNT_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict[str, Any]) -> None:
    try:
        ACCOUNT_FILE.write_text(json.dumps(data, indent=2), "utf-8")
        try:
            os.chmod(ACCOUNT_FILE, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def get_server_url() -> str:
    stored = _read().get("server_url")
    if isinstance(stored, str) and stored.strip():
        value = stored.strip().rstrip("/")
        if value not in _LEGACY_DEFAULT_URLS:
            return value
    return DEFAULT_ACCOUNT_URL


def set_server_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    if not value:
        value = DEFAULT_ACCOUNT_URL
    data = _read()
    data["server_url"] = value
    _write(data)
    return value


def _token() -> str:
    value = _read().get("token")
    return value.strip() if isinstance(value, str) else ""


def is_signed_in() -> bool:
    return bool(_token())


def current_user() -> dict[str, Any] | None:
    user = _read().get("user")
    return user if isinstance(user, dict) else None


def sign_out() -> None:
    data = _read()
    data.pop("token", None)
    data.pop("user", None)
    _write(data)


# --------------------------------------------------------------------------- #
#  HTTP helper                                                                 #
# --------------------------------------------------------------------------- #
def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    auth: bool = True,
    server_url: str | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    base = (server_url or get_server_url()).rstrip("/")
    url = f"{base}{path}"
    headers = {"Accept": "application/json"}
    if auth and _token():
        headers["Authorization"] = f"Bearer {_token()}"
    try:
        response = requests.request(
            method, url, json=body, headers=headers, timeout=timeout
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Could not reach the Pike account server: {exc}"}

    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if response.status_code == 401 and auth:
        # Token no longer valid - drop it so the UI offers sign-in again.
        sign_out()
        data.setdefault("ok", False)
        data.setdefault("error", "Your session expired. Please sign in again.")
        data["signed_out"] = True
    return data


# --------------------------------------------------------------------------- #
#  Device-authorization login flow                                             #
# --------------------------------------------------------------------------- #
def start_login(device_name: str = "") -> dict[str, Any]:
    """Ask the server for a code the user enters on the website."""
    name = (device_name or _device_name()).strip()
    result = _request(
        "POST",
        "/api/account/device/start",
        body={"kind": DEVICE_KIND, "name": name},
        auth=False,
    )
    if result.get("ok"):
        result["device_name"] = name
        remember_verification(
            result.get("verification_uri_complete") or result.get("verification_uri") or ""
        )
    return result


def poll_login(device_code: str) -> dict[str, Any]:
    """Check whether the user approved the code yet; store the token when done."""
    result = _request(
        "POST",
        "/api/account/device/poll",
        body={
            "device_code": device_code,
            "platform": _platform(),
            "app_version": APP_VERSION,
        },
        auth=False,
    )
    if result.get("ok") and result.get("status") == "approved" and result.get("token"):
        data = _read()
        previous = data.get("token")
        data["token"] = result["token"]
        data["user"] = result.get("user") or {}
        if result.get("device_name"):
            data["device_name"] = result["device_name"]
        _write(data)
        # Only report the sign-in once, even if the client polls again after
        # approval (the server hands back the same token for retry safety).
        if previous != result["token"]:
            log_activity("account.signed_in", "Signed in through the website", source=DEVICE_KIND)
        clear_pending_verification()
    return result


# --------------------------------------------------------------------------- #
#  Activity / usage reporting                                                  #
# --------------------------------------------------------------------------- #
def log_activity(kind: str, detail: str = "", source: str = DEVICE_KIND) -> None:
    if not is_signed_in():
        return
    _request(
        "POST",
        "/api/account/activity",
        body={"kind": kind, "detail": detail, "source": source},
    )


def record_usage(model: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
    if not is_signed_in():
        return
    _request(
        "POST",
        "/api/account/usage",
        body={
            "source": DEVICE_KIND,
            "model": model,
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
        },
    )


def heartbeat() -> dict[str, Any]:
    if not is_signed_in():
        return {"ok": False, "error": "Not signed in."}
    return _request(
        "POST",
        "/api/account/heartbeat",
        body={
            "name": _device_name(),
            "platform": _platform(),
            "app_version": APP_VERSION,
        },
    )


# --------------------------------------------------------------------------- #
#  Settings sync                                                               #
# --------------------------------------------------------------------------- #
def pull_settings() -> dict[str, Any]:
    """Fetch account-synced settings from the server."""
    if not is_signed_in():
        return {}
    result = _request("GET", "/api/account/settings")
    settings = result.get("settings")
    return settings if isinstance(settings, dict) else {}


def push_settings(values: dict[str, Any]) -> dict[str, Any]:
    if not is_signed_in():
        return {"ok": False, "error": "Not signed in."}
    return _request("POST", "/api/account/settings", body={"settings": values})


def sync_now() -> dict[str, Any]:
    """Push the local preferences and pull the account's copy back.

    The server is the source of truth for values that already exist there;
    otherwise the local value is uploaded. This keeps two machines converging
    without a full conflict-resolution engine.
    """
    if not is_signed_in():
        return {"ok": False, "error": "Not signed in."}

    local = {
        "model": config.get_default_model(),
        "reasoning_effort": config.get_reasoning_effort(),
        "provider": config.get_active_provider(),
        "theme": config.get_theme() if hasattr(config, "get_theme") else "dark",
    }
    remote = pull_settings()

    # Fill gaps locally, upload anything the server does not have yet.
    missing = {k: v for k, v in local.items() if k not in remote and v}
    if missing:
        push_settings(missing)

    applied = list(missing.keys())
    if remote.get("model") and remote["model"] != local.get("model"):
        try:
            config.set_default_model(remote["model"])
            applied.append("model")
        except Exception:
            pass
    if remote.get("reasoning_effort") and remote["reasoning_effort"] != local.get("reasoning_effort"):
        try:
            config.set_reasoning_effort(remote["reasoning_effort"])
            applied.append("reasoning_effort")
        except Exception:
            pass

    log_activity("account.synced", "Synced settings for this device")
    return {"ok": True, "applied": applied, "settings": {**remote, **missing}}


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _device_name() -> str:
    stored = _read().get("device_name")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    import platform
    node = platform.node() or "Desktop"
    return f"{node} ({_platform() or APP_NAME})"


def _platform() -> str:
    import platform
    system = platform.system() or ""
    release = platform.release() or ""
    return f"{system} {release}".strip()


def status() -> dict[str, Any]:
    """Everything the UI needs to render the Account tab.

    Deliberately omits the server URL: the frontend only ever opens account
    pages through :func:`open_page`, so the address stays server-side.
    """
    return {
        "signed_in": is_signed_in(),
        "user": current_user(),
        "device_name": _device_name(),
        "app_version": APP_VERSION,
        "platform": _platform(),
    }


# --------------------------------------------------------------------------- #
#  Account pages (opened by the backend, never exposed to the UI)              #
# --------------------------------------------------------------------------- #
def remember_verification(url: str) -> None:
    """Stash the pending device-approval page for this sign-in attempt."""
    global _pending_verification_url
    _pending_verification_url = (url or "").strip()


def clear_pending_verification() -> None:
    global _pending_verification_url
    _pending_verification_url = ""


def page_url(target: str) -> str:
    """Resolve a UI link target to a URL without handing the UI the base URL."""
    target = (target or "").strip().lower()
    if target == "device":
        return _pending_verification_url
    path = _PAGE_PATHS.get(target)
    if not path:
        return ""
    return f"{get_server_url()}{path}"


def open_page(target: str) -> bool:
    """Open an account page in the user's browser. False for unknown targets."""
    url = page_url(target)
    if not url.startswith(("http://", "https://")):
        return False
    import webbrowser

    webbrowser.open(url)
    return True


def ensure_heartbeat_thread(interval: int = 300) -> None:
    """Start a background thread that keeps this device marked as active."""
    import threading

    if getattr(ensure_heartbeat_thread, "_started", False):
        return
    ensure_heartbeat_thread._started = True  # type: ignore[attr-defined]

    def loop() -> None:
        while True:
            try:
                if is_signed_in():
                    heartbeat()
            except Exception:
                pass
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="pike-account-heartbeat", daemon=True)
    thread.start()