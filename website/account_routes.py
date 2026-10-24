"""HTTP routes for the Pike account system (pages + JSON API).

Registered on the website Flask app in :mod:`app`. It provides:

* the marketing-facing **auth pages** (register / login / logout),
* the signed-in **dashboard** (devices, usage, activity, settings),
* the **device approval** page used by the desktop app & VS Code extension,
* and a JSON API that both apps and the dashboard call.

Auth model
----------
* Browsers use a signed-in **session cookie** (``pike_session``).
* Apps use a long-lived **Bearer token** issued by the device flow.

Both funnel through :func:`current_user` / :func:`token_user`, so routes can
accept either.
"""
from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable

from flask import (
    Blueprint,
    Response,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

import account

bp = Blueprint("account", __name__)

SESSION_COOKIE = "pike_session"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# --------------------------------------------------------------------------- #
#  Auth helpers                                                                #
# --------------------------------------------------------------------------- #
def current_user() -> dict[str, Any] | None:
    """Resolve the signed-in user from the session cookie, if any."""
    return account.session_user(request.cookies.get(SESSION_COOKIE))


def token_user() -> dict[str, Any] | None:
    """Resolve the user from an ``Authorization: Bearer <token>`` header."""
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    result = account.verify_access_token(header.split(None, 1)[1].strip())
    return result["user"] if result else None


def any_user() -> dict[str, Any] | None:
    return current_user() or token_user()


def _origin_ok() -> bool:
    """Reject cross-site state changes (belt-and-braces CSRF protection)."""
    if request.method in _SAFE_METHODS:
        return True
    origin = request.headers.get("Origin")
    if not origin:
        return True  # non-browser clients (the apps) send no Origin
    host = request.host_url.rstrip("/")
    return origin.rstrip("/") == host


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Not signed in."}), 401
            return redirect(url_for("account.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper


def token_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        user = any_user()
        if not user:
            return jsonify({"ok": False, "error": "Invalid or missing token."}), 401
        return view(*args, **kwargs)

    return wrapper


def _set_session_cookie(response: Response, token: str) -> Response:
    secure = os.environ.get("PIKE_COOKIE_SECURE", "0") == "1"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=account.SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="Lax",
        secure=secure,
        path="/",
    )
    return response


# --------------------------------------------------------------------------- #
#  Auth pages                                                                  #
# --------------------------------------------------------------------------- #
@bp.get("/account/login")
def login():
    if current_user():
        return redirect(url_for("account.dashboard"))
    return render_template(
        "account_login.html",
        page="login",
        title="Sign in - Pike",
        description="Sign in to your Pike account.",
        next=request.args.get("next", ""),
    )


@bp.get("/account/register")
def register():
    if current_user():
        return redirect(url_for("account.dashboard"))
    return render_template(
        "account_register.html",
        page="register",
        title="Create an account - Pike",
        description="Create a Pike account to sync your devices.",
        next=request.args.get("next", ""),
    )


@bp.get("/account/logout")
@bp.post("/account/logout")
def logout():
    account.delete_session(request.cookies.get(SESSION_COOKIE))
    target = request.args.get("next") or url_for("index")
    response = make_response(redirect(target))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@bp.get("/account")
def account_home():
    return redirect(url_for("account.dashboard") if current_user() else url_for("account.login"))


# --------------------------------------------------------------------------- #
#  Dashboard                                                                   #
# --------------------------------------------------------------------------- #
@bp.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    return render_template(
        "dashboard.html",
        page="dashboard",
        title="Dashboard - Pike",
        description="Monitor your Pike devices, usage and activity.",
        dashboard=account.overview(user["id"]),
        user=user,
    )


# --------------------------------------------------------------------------- #
#  Device authorization page (used by the desktop app / VS Code)               #
# --------------------------------------------------------------------------- #
@bp.get("/device")
def device_page():
    code = request.args.get("code", "")
    user = current_user()
    entry = account.get_device_code_by_user_code(code) if code else None
    return render_template(
        "device.html",
        page="device",
        title="Connect a device - Pike",
        description="Approve a desktop or editor sign-in for your Pike account.",
        code=code,
        entry=entry,
        user=user,
    )


# --------------------------------------------------------------------------- #
#  JSON API - auth                                                             #
# --------------------------------------------------------------------------- #
@bp.get("/api/account/session")
def api_session():
    user = current_user()
    return jsonify({"ok": True, "authenticated": bool(user), "user": user})


@bp.post("/api/account/register")
def api_register():
    if not _origin_ok():
        return jsonify({"ok": False, "error": "Cross-site request blocked."}), 403
    payload = request.get_json(silent=True) or request.form
    try:
        user = account.create_user(
            payload.get("email", ""), payload.get("password", ""), payload.get("name", "")
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    token = account.create_session(user["id"], user_agent=request.headers.get("User-Agent", ""))
    response = make_response(jsonify({"ok": True, "user": user}))
    return _set_session_cookie(response, token)


@bp.post("/api/account/login")
def api_login():
    if not _origin_ok():
        return jsonify({"ok": False, "error": "Cross-site request blocked."}), 403
    payload = request.get_json(silent=True) or request.form
    user = account.authenticate(payload.get("email", ""), payload.get("password", ""))
    if not user:
        return jsonify({"ok": False, "error": "Wrong email or password."}), 401
    token = account.create_session(user["id"], user_agent=request.headers.get("User-Agent", ""))
    account.log_event(user["id"], "account.login", "Signed in on the website", "website")
    response = make_response(jsonify({"ok": True, "user": user}))
    return _set_session_cookie(response, token)


@bp.post("/api/account/logout")
def api_logout():
    account.delete_session(request.cookies.get(SESSION_COOKIE))
    response = make_response(jsonify({"ok": True}))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@bp.route("/api/account/profile", methods=["GET", "POST", "PATCH"])
@login_required
def api_profile():
    if request.method == "GET":
        return jsonify({"ok": True, "user": current_user()})
    payload = request.get_json(silent=True) or {}
    try:
        user = account.update_profile(
            current_user()["id"], name=payload.get("name"), password=payload.get("password")
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "user": user})


# --------------------------------------------------------------------------- #
#  JSON API - device flow (called by the apps themselves)                      #
# --------------------------------------------------------------------------- #
@bp.post("/api/account/device/start")
def api_device_start():
    payload = request.get_json(silent=True) or {}
    info = account.start_device_code(
        kind=(payload.get("kind") or "desktop")[:20],
        name=(payload.get("name") or "")[:80],
    )
    verify_url = url_for("account.device_page", _external=True, code=info["user_code"])
    return jsonify(
        {
            "ok": True,
            "device_code": info["device_code"],
            "user_code": info["user_code"],
            "verification_uri": verify_url,
            "verification_uri_complete": verify_url,
            "expires_in": info["expires_in"],
            "interval": info["interval"],
        }
    )


@bp.post("/api/account/device/poll")
def api_device_poll():
    payload = request.get_json(silent=True) or {}
    result = account.poll_device_code(
        payload.get("device_code", ""),
        platform=(payload.get("platform") or "")[:80],
        app_version=(payload.get("app_version") or "")[:40],
    )
    if result.get("status") == "pending":
        return jsonify({"ok": True, **result}), 202
    if result.get("status") in {"invalid", "expired", "denied"}:
        return jsonify({"ok": False, **result}), 400
    return jsonify({"ok": True, **result})


@bp.post("/api/account/device/approve")
def api_device_approve():
    user = current_user()
    if not user:
        return jsonify({"ok": False, "error": "Sign in first.", "login": True}), 401
    payload = request.get_json(silent=True) or request.form
    try:
        result = account.approve_device_code(payload.get("user_code", ""), user["id"])
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **result})


@bp.post("/api/account/device/deny")
def api_device_deny():
    payload = request.get_json(silent=True) or request.form
    return jsonify({"ok": True, "denied": account.deny_device_code(payload.get("user_code", ""))})


# --------------------------------------------------------------------------- #
#  JSON API - dashboard data                                                   #
# --------------------------------------------------------------------------- #
@bp.get("/api/account/overview")
@login_required
def api_overview():
    return jsonify({"ok": True, "dashboard": account.overview(current_user()["id"])})


@bp.get("/api/account/devices")
@login_required
def api_devices():
    return jsonify({"ok": True, "devices": account.list_devices(current_user()["id"])})


@bp.delete("/api/account/devices/<int:token_id>")
@login_required
def api_revoke_device(token_id: int):
    ok = account.revoke_token(current_user()["id"], token_id)
    return jsonify({"ok": ok}), (200 if ok else 404)


@bp.get("/api/account/activity")
@login_required
def api_activity():
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify({"ok": True, "activity": account.list_activity(current_user()["id"], limit)})


@bp.route("/api/account/settings", methods=["GET", "POST", "PUT"])
@token_required
def api_settings():
    user = any_user()
    if request.method == "GET":
        return jsonify({"ok": True, "settings": account.get_settings(user["id"])})
    payload = request.get_json(silent=True) or {}
    values = payload.get("settings", payload)
    return jsonify({"ok": True, "settings": account.set_settings(user["id"], values)})


@bp.post("/api/account/heartbeat")
@token_required
def api_heartbeat():
    """Apps ping this so their device shows as recently active."""
    user = any_user()
    payload = request.get_json(silent=True) or {}
    token = account.verify_access_token(request.headers.get("Authorization", "")[7:].strip())
    token_id = token["token"]["id"] if token else None
    account.touch_device(
        user["id"],
        token_id,
        name=(payload.get("name") or "")[:80],
        platform=(payload.get("platform") or "")[:80],
        app_version=(payload.get("app_version") or "")[:40],
    )
    return jsonify({"ok": True})


@bp.post("/api/account/activity")
@token_required
def api_log_activity():
    user = any_user()
    payload = request.get_json(silent=True) or {}
    account.log_event(
        user["id"],
        payload.get("kind", "event"),
        payload.get("detail", ""),
        source=payload.get("source", "desktop"),
    )
    return jsonify({"ok": True})


@bp.post("/api/account/usage")
@token_required
def api_log_usage():
    user = any_user()
    payload = request.get_json(silent=True) or {}
    account.record_usage(
        user["id"],
        source=payload.get("source", "desktop"),
        model=payload.get("model", ""),
        tokens_in=payload.get("tokens_in", 0),
        tokens_out=payload.get("tokens_out", 0),
    )
    return jsonify({"ok": True})


@bp.get("/api/account/me")
@token_required
def api_me():
    """Lightweight token check used by the desktop app & extension on startup."""
    user = any_user()
    return jsonify({"ok": True, "user": user, "devices": account.list_devices(user["id"])})


def register(app: Any) -> None:
    # Create tables up front, but never let a transient database hiccup (for
    # example a Neon cold start) stop the whole site from importing. Existing
    # tables keep serving requests; a fresh database is retried next cold start.
    try:
        account.init_db()
    except Exception as exc:  # pragma: no cover - depends on live database
        app.logger.warning("Account schema init failed: %s", exc)
    app.register_blueprint(bp)