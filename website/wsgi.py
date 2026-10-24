"""Production entry point for the Pike website / account server.

Used by WSGI hosts (Render, Railway, Fly, gunicorn, etc.). Locally you can keep
using ``python app.py``.

    gunicorn wsgi:app
"""
from __future__ import annotations

import os

from app import app

if __name__ == "__main__":  # pragma: no cover - convenience for `python wsgi.py`
    port = int(os.environ.get("PORT") or os.environ.get("PIKE_WEB_PORT") or "5000")
    app.run(host="0.0.0.0", port=port, threaded=True)