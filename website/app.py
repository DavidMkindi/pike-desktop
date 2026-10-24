"""Pike website - the public marketing/docs site for the Pike app.

This is a standalone Flask application, separate from the desktop app in the
project root. It serves the landing page, downloads, documentation, changelog
and a few supporting pages.

Run it
------
    python website/app.py                 # http://127.0.0.1:5000
    python website/app.py --port 8000     # custom port
    python website/app.py --debug         # Flask debug + auto-reload

Or with the Flask CLI from inside the ``website`` folder::

    flask --app app run --port 5000
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, url_for

import account_routes

# --------------------------------------------------------------------------- #
#  App setup                                                                   #
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "static"),
    template_folder=str(BASE_DIR / "templates"),
)
app.config["JSON_SORT_KEYS"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.secret_key = os.environ.get("PIKE_SECRET_KEY", "pike-dev-secret-change-me")

# Accounts, the dashboard and the device-authorization flow.
account_routes.register(app)

# Product metadata (kept in one place so templates stay clean).
PRODUCT = {
    "name": "Pike",
    "tagline": "A focused AI workspace for your desktop.",
    "version": "1.0.0",
    "python": "3.9+",
    "license": "Free to use and modify",
    "github": "https://github.com/pike-ai/pike",
    "releases": "https://github.com/pike-ai/pike/releases",
    "year": datetime.now(timezone.utc).year,
}

# Providers shown on the landing page / docs. Mirrors ``config.PROVIDERS`` in
# the desktop app, but this site stays independent so it can be deployed alone.
PROVIDERS = [
    {"name": "OpenAI", "hint": "GPT-4o, GPT-4.1, o-series", "local": False},
    {"name": "Anthropic", "hint": "Claude 3.5 / 4 family", "local": False},
    {"name": "Google Gemini", "hint": "Gemini 1.5 / 2.x", "local": False},
    {"name": "xAI", "hint": "Grok", "local": False},
    {"name": "DeepSeek", "hint": "DeepSeek V4.1 Flash", "local": False},
    {"name": "Mistral AI", "hint": "Mistral / Codestral", "local": False},
    {"name": "Groq", "hint": "Fast LPU inference", "local": False},
    {"name": "Together AI", "hint": "Open models at scale", "local": False},
    {"name": "OpenRouter", "hint": "One key, many models", "local": False},
    {"name": "Perplexity", "hint": "Search-grounded answers", "local": False},
    {"name": "Moonshot", "hint": "Kimi", "local": False},
    {"name": "Z.ai", "hint": "GLM", "local": False},
    {"name": "Qwen", "hint": "Alibaba Qwen", "local": False},
    {"name": "Amazon Nova", "hint": "AWS Bedrock models", "local": False},
    {"name": "Cohere", "hint": "Command family", "local": False},
    {"name": "Cerebras", "hint": "Wafer-scale speed", "local": False},
    {"name": "Ollama", "hint": "Run models on your machine", "local": True},
    {"name": "LM Studio", "hint": "Local GGUF server", "local": True},
    {"name": "Custom", "hint": "Any OpenAI-compatible API", "local": False},
]

FEATURES = [
    {
        "icon": "bolt",
        "title": "Token-by-token streaming",
        "body": "Answers arrive as they are written over Server-Sent Events, so the "
        "first word lands in milliseconds - no waiting for the whole reply.",
    },
    {
        "icon": "brain",
        "title": "Thinking traces",
        "body": "Reasoning models expose a collapsible Thinking section. Watch the "
        "model work, then collapse it and keep the thread clean.",
    },
    {
        "icon": "sparkles",
        "title": "Bring any provider",
        "body": "One OpenAI-compatible client works with 19+ providers. Add a key "
        "for one and every model from the others stays available.",
    },
    {
        "icon": "code",
        "title": "A real coding agent",
        "body": "Open a workspace and Pike can read, write, search and run commands "
        "with your permission - it knows the files it is allowed to touch.",
    },
    {
        "icon": "history",
        "title": "History that stays local",
        "body": "Conversations live in a local SQLite file you own. Search, rename, "
        "archive and delete them - nothing leaves your machine.",
    },
    {
        "icon": "terminal",
        "title": "Built-in terminal",
        "body": "Spin up interactive shells next to the chat and let the assistant "
        "run the commands it just wrote, without switching windows.",
    },
]


# --------------------------------------------------------------------------- #
#  Context processors & helpers                                                #
# --------------------------------------------------------------------------- #
@app.context_processor
def inject_globals() -> dict:
    return {
        "product": PRODUCT,
        "providers": PROVIDERS,
        "current_year": datetime.now(timezone.utc).year,
        "nav_links": [
            {"endpoint": "index", "label": "Home"},
            {"endpoint": "features", "label": "Features"},
            {"endpoint": "download", "label": "Download"},
            {"endpoint": "docs", "label": "Docs"},
            {"endpoint": "changelog", "label": "Changelog"},
        ],
        # Available on every page so the nav can show Sign in / Dashboard.
        "account_user": _current_user(),
    }


def _current_user():
    """Resolve the signed-in user without importing the request too early."""
    try:
        return account_routes.current_user()
    except Exception:  # pragma: no cover - never break public pages
        return None


# --------------------------------------------------------------------------- #
#  Template filters (used by the dashboard)                                    #
# ---------------------------------------------------------------------------
def human_tokens(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    for unit, size in (("M", 1_000_000), ("K", 1_000)):
        if number >= size:
            return f"{number / size:.1f}{unit}".replace(".0", "")
    return str(int(number))


def time_ago(value) -> str:
    if not value:
        return "never"
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 60:
        return "just now"
    for label, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {label}{'s' if count != 1 else ''} ago"
    return "just now"


app.jinja_env.filters["human_tokens"] = human_tokens
app.jinja_env.filters["time_ago"] = time_ago


@app.after_request
def add_security_headers(response):
    """A few sensible defaults for a public site."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


# --------------------------------------------------------------------------- #
#  Pages                                                                       #
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return render_template(
        "index.html",
        page="home",
        title="Pike - A focused AI workspace for your desktop",
        description=PRODUCT["tagline"],
        features=FEATURES,
    )


@app.get("/features")
def features():
    return render_template(
        "features.html",
        page="features",
        title="Features - Pike",
        description="Streaming answers, thinking traces, workspace tools, a local "
        "terminal and history you own.",
        features=FEATURES,
    )


@app.get("/download")
def download():
    platforms = [
        {
            "name": "Windows",
            "icon": "windows",
            "file": "Pike.exe",
            "detail": "Windows 10 (1809+) and Windows 11, 64-bit",
            "primary": True,
        },
        {
            "name": "macOS",
            "icon": "apple",
            "file": "Pike",
            "detail": "macOS 12+ (Intel and Apple silicon)",
            "primary": False,
        },
        {
            "name": "Linux",
            "icon": "linux",
            "file": "Pike",
            "detail": "glibc 2.31+ (Ubuntu 20.04+, Fedora 33+)",
            "primary": False,
        },
    ]
    return render_template(
        "download.html",
        page="download",
        title="Download - Pike",
        description="Download Pike for Windows, macOS or Linux, or run it from source.",
        platforms=platforms,
    )


@app.get("/docs")
def docs():
    return render_template(
        "docs.html",
        page="docs",
        title="Documentation - Pike",
        description="Install Pike, connect a provider, learn the keyboard shortcuts "
        "and browse the API reference.",
    )


@app.get("/changelog")
def changelog():
    releases = [
        {
            "version": "1.0.0",
            "date": "2026-10-12",
            "badge": "Latest",
            "notes": [
                "Desktop app with a native pywebview window and browser fallback.",
                "Streaming chat with Markdown, code blocks and one-click copy.",
                "Workspace tools: read, write, search and run commands in a folder.",
                "Built-in interactive terminal manager.",
                "Per-provider API keys for 19+ OpenAI-compatible services.",
                "Collapsible thinking traces with elapsed-time badges.",
                "Local SQLite history with search, rename and delete.",
            ],
        },
        {
            "version": "0.9.0",
            "date": "2026-09-28",
            "badge": "",
            "notes": [
                "Introduced the connected-provider model catalogue.",
                "Added the reasoning-level picker for thinking models.",
                "Refreshed the dark design system and light theme.",
            ],
        },
    ]
    return render_template(
        "changelog.html",
        page="changelog",
        title="Changelog - Pike",
        description="Every notable change in the Pike desktop app.",
        releases=releases,
    )


@app.get("/about")
def about():
    return render_template(
        "about.html",
        page="about",
        title="About - Pike",
        description="Why Pike exists and what it stands for.",
    )


@app.get("/contact")
def contact():
    return render_template(
        "contact.html",
        page="contact",
        title="Contact - Pike",
        description="Get in touch with the Pike project.",
    )


# --------------------------------------------------------------------------- #
#  Small JSON API (handy for the status pill / release tooling)                 #
# --------------------------------------------------------------------------- #
@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "pike-website"})


@app.get("/api/product")
def api_product():
    return jsonify({"product": PRODUCT, "providers": PROVIDERS, "features": FEATURES})


# --------------------------------------------------------------------------- #
#  Error handlers                                                              #
# --------------------------------------------------------------------------- #
@app.errorhandler(404)
def not_found(_error):
    return render_template(
        "error.html",
        page="error",
        title="Page not found - Pike",
        code=404,
        message="We could not find that page.",
        detail="The link may be old or mistyped. Try heading back home.",
    ), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template(
        "error.html",
        page="error",
        title="Something went wrong - Pike",
        code=500,
        message="Something went wrong on our side.",
        detail="Please try again in a moment.",
    ), 500


# --------------------------------------------------------------------------- #
#  CLI                                                                         #
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Pike website.")
    # Hosting platforms set PORT and expect a 0.0.0.0 bind; local runs keep 127.0.0.1.
    default_host = os.environ.get("PIKE_WEB_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    default_port = int(os.environ.get("PIKE_WEB_PORT") or os.environ.get("PORT") or "5000")
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--debug", action="store_true", help="Enable debug + auto-reload")
    args = parser.parse_args()

    print(f"Pike website running at http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()