"""Pike account system - the shared identity layer for every Pike surface.

The desktop app, the VS Code extension and this website all talk to this module
through the account blueprint (:mod:`account_routes`). It is deliberately
dependency-free: it uses only the standard library (``sqlite3`` + ``hashlib``)
so the website stays a single ``pip install flask`` away from running.

What lives here
---------------
* **Users**          - email + PBKDF2-HMAC-SHA256 password hashes.
* **Sessions**       - short-lived browser sessions (cookie backed).
* **Access tokens**  - long-lived tokens held by the desktop app / VS Code.
* **Devices**        - one row per signed-in app, so users can see and revoke them.
* **Device codes**   - the OAuth-style *device authorization* flow used to sign
                      in to the apps "through the website".
* **Activity**       - a running log of what each device did, shown on the dashboard.
* **Synced settings**- a tiny key/value store so preferences follow the account.
* **Usage**          - per-request token counts for the dashboard charts.

Everything is stored in a single SQLite file (``instance/pike_accounts.sqlite3``)
so the whole account system is easy to back up, move or delete.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import string
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PIKE_ACCOUNT_DATA") or (BASE_DIR / "instance"))
DB_PATH = Path(os.environ.get("PIKE_ACCOUNT_DB") or (DATA_DIR / "pike_accounts.sqlite3"))

# --------------------------------------------------------------------------- #
#  Backend selection                                                           #
#                                                                              #
#  On a persistent host (Render/Railway/Fly, a local machine, Docker with a     #
#  volume) we use SQLite. On a serverless host where the filesystem is          #
#  ephemeral we use Postgres via ``DATABASE_URL`` so accounts actually persist. #
# --------------------------------------------------------------------------- #
DATABASE_URL = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("POSTGRES_URL")
    or os.environ.get("PIKE_DATABASE_URL")
    or ""
).strip()
USE_POSTGRES = bool(DATABASE_URL)

# Only create the on-disk SQLite directory when we actually need it. Serverless
# hosts (Vercel) mount the code read-only, so an unconditional mkdir would crash
# the whole app at import even when Postgres/Neon is configured.
if not USE_POSTGRES:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Read-only filesystem with no DATABASE_URL: let the real SQLite
        # connection raise a clear error when it is actually attempted.
        pass

if USE_POSTGRES:
    import psycopg
    import psycopg_pool
    from psycopg.rows import dict_row

    # A small pool so a warm serverless instance reuses its TCP/TLS connection
    # instead of paying a full Neon handshake on every query. ``min_size=0``
    # avoids holding a connection when the instance is idle.
    _pool = psycopg_pool.ConnectionPool(
        DATABASE_URL,
        min_size=0,
        max_size=4,
        open=True,
        kwargs={"row_factory": dict_row, "connect_timeout": 15},
    )
else:
    _pool = None

REQUIRED_TABLES = (
    "users",
    "sessions",
    "access_tokens",
    "devices",
    "device_codes",
    "activity",
    "usage_events",
    "user_settings",
)

_initialized = False


SESSION_TTL_DAYS = int(os.environ.get("PIKE_SESSION_TTL_DAYS", "30"))
DEVICE_CODE_TTL_MINUTES = int(os.environ.get("PIKE_DEVICE_CODE_TTL_MINUTES", "15"))
TOKEN_PREFIX = "pike_"
PBKDF2_ROUNDS = 210_000

# Unambiguous alphabet for the short user code (no O/0/I/1).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# --------------------------------------------------------------------------- #
#  Tiny helpers                                                                #
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _today_iso() -> str:
    """Today's date as ``YYYY-MM-DD`` (matches the stored ISO timestamps)."""
    return _now().date().isoformat()


def _days_ago_iso(days: int) -> str:
    """ISO timestamp ``days`` days ago, used for date-range filters."""
    return (_now() - timedelta(days=int(days))).isoformat(timespec="seconds")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _connect():
    """Open a database connection for the configured backend.

    Returns a connection whose ``cursor``-less ``execute`` helper yields
    mappings, so the rest of this module can use one SQL dialect-agnostic API.
    """
    if USE_POSTGRES:
        # The pool hands out a context manager that returns the connection on exit.
        handle = _pool.connection()
        return _CompatConnection(handle.__enter__(), USE_POSTGRES, pooled=True, handle=handle)
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return _CompatConnection(conn, USE_POSTGRES, pooled=False)


class _CompatResult:
    """Minimal cursor-like wrapper exposing ``fetchone``/``fetchall``/``lastrowid``."""

    def __init__(self, cursor, is_pg: bool):
        self._cursor = cursor
        self._is_pg = is_pg

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor.fetchall())

    @property
    def lastrowid(self):
        if not self._is_pg:
            return self._cursor.lastrowid
        row = self._cursor.fetchone()
        return dict(row).get("id") if row else None


class _CompatConnection:
    """Thin adapter that normalises SQLite and Postgres behaviour.

    * ``?`` placeholders are rewritten to ``%s`` for Postgres.
    * the ``AUTOINCREMENT`` keyword is stripped from Postgres DDL.
    * ``with conn`` commits/rolls back and closes like sqlite3 does.
    * a small set of SQLite-only functions are translated (``date('now')``,
      ``datetime('now', '-13 days')``, ``COALESCE(NULLIF(?, ''), col)``).
    """

    def __init__(self, conn, is_pg: bool, pooled: bool = False, handle=None):
        self._conn = conn
        self._is_pg = is_pg
        self._pooled = pooled
        self._handle = handle

    def _translate(self, sql: str) -> str:
        if not self._is_pg:
            return sql
        out = sql.replace("AUTOINCREMENT", "")
        # Emulate sqlite's cursor.lastrowid with a RETURNING clause.
        if SQLITE_ID_TABLES_RE.search(out) and "RETURNING" not in out.upper():
            out = out.rstrip() + " RETURNING id"
        # psycopg uses %s placeholders; our callers always write sqlite's ?.
        out = out.replace("?", "%s")
        return out

    def execute(self, sql: str, params=()):
        sql = self._translate(sql)
        try:
            if self._is_pg:
                cursor = self._conn.cursor()
                cursor.execute(sql, tuple(params))
            else:
                cursor = self._conn.execute(sql, tuple(params))
        except Exception as exc:
            _maybe_reset_schema(exc)
            raise
        return _CompatResult(cursor, self._is_pg)

    def executescript(self, script: str):
        if self._is_pg:
            cur = self._conn.cursor()
            statements = [s.strip() for s in script.split(";") if s.strip()]
            for statement in statements:
                cur.execute(self._translate(statement))
        else:
            self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        # Closing a pooled handle returns the connection to the pool; closing a
        # raw connection disposes it. Both use the same call.
        if self._handle is not None:
            self._handle.__exit__(exc_type, exc, tb)
        else:
            self._conn.close()
        return False


# Tables whose ``id`` column is a serial, so Postgres needs ``RETURNING id`` to
# emulate ``cursor.lastrowid``.
SQLITE_ID_TABLES_RE = __import__("re").compile(
    r"^\s*INSERT\s+INTO\s+(users|access_tokens|devices|activity|usage_events)\b",
    __import__("re").IGNORECASE,
)

def _maybe_reset_schema(exc: Exception) -> None:
    """If Postgres reports a missing relation, clear the init cache so the next
    call re-runs ``init_db`` (covers a cold start against a fresh database)."""
    global _initialized
    message = str(exc).lower()
    if "does not exist" in message or "undefinedtable" in message:
        _initialized = False


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


# --------------------------------------------------------------------------- #
#  Password + token primitives                                                 #
# --------------------------------------------------------------------------- #
def _normalize_password(password: str) -> str:
    """Return the canonical (NFC) form of a password.

    Visually identical strings can be encoded differently across operating
    systems and input methods (for example ``café`` as ``cafe`` + U+00E9 in
    NFC, or ``cafe`` + U+0065/U+0301 in NFD). Without this, an account created
    on one device could not be signed into from another even though the user
    typed exactly the same password. Normalising keeps the bytes we hash stable.
    """
    return unicodedata.normalize("NFC", password or "")


def hash_password(password: str) -> str:
    """Return a salted PBKDF2 hash in the form ``pbkdf2$rounds$salt$hash``."""
    salt = secrets.token_bytes(16)
    normalized = _normalize_password(password)
    digest = hashlib.pbkdf2_hmac("sha256", normalized.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        rounds = int(rounds)
        salt = bytes.fromhex(salt_hex)
        # Try every equivalent encoding, then the raw string. The raw fallback
        # keeps accounts created before normalisation working, and trying NFC
        # and NFD both ways means an existing account logs in regardless of the
        # form it was originally stored in.
        raw = password or ""
        candidates = []
        for form in ("NFC", "NFD"):
            value = unicodedata.normalize(form, raw)
            if value not in candidates:
                candidates.append(value)
        if raw not in candidates:
            candidates.append(raw)
        for candidate in candidates:
            digest = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"), salt, rounds)
            if hmac.compare_digest(digest.hex(), digest_hex):
                return True
        return False
    except Exception:
        return False


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def _new_user_code() -> str:
    part = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{part[:4]}-{part[4:]}"


def normalize_code(code: str | None) -> str:
    """Normalise a user-entered code: upper-case, no dashes/spaces."""
    cleaned = "".join(ch for ch in (code or "").upper() if ch is not None)
    return "".join(ch for ch in cleaned if ch.isalnum())


# --------------------------------------------------------------------------- #
#  Schema                                                                      #
# --------------------------------------------------------------------------- #
def init_db() -> None:
    with _connect() as conn:
        if USE_POSTGRES:
            _init_postgres(conn)
        else:
            conn.executescript(_SQLITE_SCHEMA_VALUE)
        for table in REQUIRED_TABLES:
            conn.execute(f"SELECT 1 FROM {table} LIMIT 1")
    global _initialized
    _initialized = True


def _init_postgres(conn) -> None:
    """Create tables if missing. Safe to call repeatedly."""
    for statement in _POSTGRES_SCHEMA:
        conn.execute(statement)


def ensure_schema() -> None:
    """Init the schema at most once per process; cheap no-op afterwards."""
    if _initialized:
        return
    init_db()


_SQLITE_SCHEMA_VALUE = """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT NOT NULL UNIQUE,
        name          TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        plan          TEXT NOT NULL DEFAULT 'free',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        last_login_at TEXT
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token      TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind       TEXT NOT NULL DEFAULT 'web',
        user_agent TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_seen  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS access_tokens (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name       TEXT NOT NULL DEFAULT 'Token',
        kind       TEXT NOT NULL DEFAULT 'desktop',
        token_hash TEXT NOT NULL UNIQUE,
        prefix     TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_used  TEXT,
        revoked    INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS devices (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_id    INTEGER REFERENCES access_tokens(id) ON DELETE SET NULL,
        name        TEXT NOT NULL DEFAULT 'Device',
        kind        TEXT NOT NULL DEFAULT 'desktop',
        platform    TEXT NOT NULL DEFAULT '',
        app_version TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        last_seen   TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS device_codes (
        code        TEXT PRIMARY KEY,
        device_code TEXT NOT NULL UNIQUE,
        user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
        kind        TEXT NOT NULL DEFAULT 'desktop',
        name        TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'pending',
        token       TEXT,
        created_at  TEXT NOT NULL,
        expires_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS activity (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind       TEXT NOT NULL DEFAULT 'event',
        detail     TEXT NOT NULL DEFAULT '',
        source     TEXT NOT NULL DEFAULT 'website',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS usage_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source      TEXT NOT NULL DEFAULT 'desktop',
        model       TEXT NOT NULL DEFAULT '',
        tokens_in   INTEGER NOT NULL DEFAULT 0,
        tokens_out  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS user_settings (
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key        TEXT NOT NULL,
        value      TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, key)
    );

    CREATE INDEX IF NOT EXISTS idx_activity_user ON activity(user_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_events(user_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
    """


# Postgres schema (SERIAL instead of AUTOINCREMENT).
_POSTGRES_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id            SERIAL PRIMARY KEY,
        email         TEXT NOT NULL UNIQUE,
        name          TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        plan          TEXT NOT NULL DEFAULT 'free',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        last_login_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token      TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind       TEXT NOT NULL DEFAULT 'web',
        user_agent TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_seen  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS access_tokens (
        id         SERIAL PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name       TEXT NOT NULL DEFAULT 'Token',
        kind       TEXT NOT NULL DEFAULT 'desktop',
        token_hash TEXT NOT NULL UNIQUE,
        prefix     TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_used  TEXT,
        revoked    INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS devices (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_id    INTEGER REFERENCES access_tokens(id) ON DELETE SET NULL,
        name        TEXT NOT NULL DEFAULT 'Device',
        kind        TEXT NOT NULL DEFAULT 'desktop',
        platform    TEXT NOT NULL DEFAULT '',
        app_version TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        last_seen   TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS device_codes (
        code        TEXT PRIMARY KEY,
        device_code TEXT NOT NULL UNIQUE,
        user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
        kind        TEXT NOT NULL DEFAULT 'desktop',
        name        TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'pending',
        token       TEXT,
        created_at  TEXT NOT NULL,
        expires_at  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS activity (
        id         SERIAL PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind       TEXT NOT NULL DEFAULT 'event',
        detail     TEXT NOT NULL DEFAULT '',
        source     TEXT NOT NULL DEFAULT 'website',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS usage_events (
        id          SERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source      TEXT NOT NULL DEFAULT 'desktop',
        model       TEXT NOT NULL DEFAULT '',
        tokens_in   INTEGER NOT NULL DEFAULT 0,
        tokens_out  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS user_settings (
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key        TEXT NOT NULL,
        value      TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_activity_user ON activity(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_events(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id)",
]

# --------------------------------------------------------------------------- #
#  Users                                                                       #
# --------------------------------------------------------------------------- #
def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data.get("id"),
        "email": data.get("email"),
        "name": data.get("name") or "",
        "plan": data.get("plan") or "free",
        "created_at": data.get("created_at"),
        "last_login_at": data.get("last_login_at"),
    }


def create_user(email: str, password: str, name: str = "") -> dict[str, Any]:
    email = (email or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("Enter a valid email address.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")

    now = _iso()
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            raise ValueError("An account with that email already exists.")
        cursor = conn.execute(
            "INSERT INTO users (email, name, password_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email, (name or "").strip(), hash_password(password), now, now),
        )
        user_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO activity (user_id, kind, detail, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, "account.created", "Account created", "website", now),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public_user(row)


def get_user(user_id: int | None) -> dict[str, Any] | None:
    if not user_id:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public_user(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)
        ).fetchone()
    return _public_user(row) if row else None


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    email = (email or "").strip().lower()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row or not verify_password(password or "", row["password_hash"]):
            return None
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_iso(), row["id"]))
    return _public_user(row)


def update_profile(user_id: int, name: str | None = None, password: str | None = None) -> dict[str, Any] | None:
    updates: list[str] = []
    params: list[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name.strip())
    if password:
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        updates.append("password_hash = ?")
        params.append(hash_password(password))
    if not updates:
        return get_user(user_id)
    updates.append("updated_at = ?")
    params.append(_iso())
    params.append(user_id)
    with _connect() as conn:
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
    return get_user(user_id)


# --------------------------------------------------------------------------- #
#  Browser sessions                                                            #
# --------------------------------------------------------------------------- #
def create_session(user_id: int, kind: str = "web", user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, kind, user_agent, created_at, expires_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user_id,
                kind,
                (user_agent or "")[:300],
                _iso(now),
                _iso(now + timedelta(days=SESSION_TTL_DAYS)),
                _iso(now),
            ),
        )
    return token


def session_user(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        if (_parse(row["expires_at"]) or _now()) < _now():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        conn.execute("UPDATE sessions SET last_seen = ? WHERE token = ?", (_iso(), token))
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    return _public_user(user) if user else None


def delete_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --------------------------------------------------------------------------- #
#  Access tokens + devices                                                     #
# --------------------------------------------------------------------------- #
def create_access_token(
    user_id: int,
    name: str = "Device",
    kind: str = "desktop",
    platform: str = "",
    app_version: str = "",
) -> dict[str, Any]:
    """Create a token AND register the device that owns it."""
    raw = _new_token()
    now = _iso()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO access_tokens (user_id, name, kind, token_hash, prefix, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, name.strip() or "Device", kind, _hash_token(raw), raw[:12], now),
        )
        token_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO devices (user_id, token_id, name, kind, platform, app_version, created_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, token_id, name.strip() or "Device", kind, platform, app_version, now, now),
        )
        conn.execute(
            "INSERT INTO activity (user_id, kind, detail, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, "device.connected", f"{name or kind} signed in", kind, now),
        )
        token_row = conn.execute("SELECT * FROM access_tokens WHERE id = ?", (token_id,)).fetchone()
    result = dict(token_row)
    result["token"] = raw  # only ever returned here
    return result


def verify_access_token(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM access_tokens WHERE token_hash = ? AND revoked = 0", (_hash_token(raw),)
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE access_tokens SET last_used = ? WHERE id = ?", (_iso(), row["id"]))
        conn.execute(
            "UPDATE devices SET last_seen = ? WHERE token_id = ?", (_iso(), row["id"])
        )
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if not user:
        return None
    return {"user": _public_user(user), "token": dict(row)}


def list_tokens(user_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        cursor = conn.execute(
            "SELECT id, name, kind, prefix, created_at, last_used, revoked "
            "FROM access_tokens WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return _rows(cursor)


def revoke_token(user_id: int, token_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM access_tokens WHERE id = ? AND user_id = ?", (token_id, user_id)
        ).fetchone()
        if not row:
            return False
        conn.execute("UPDATE access_tokens SET revoked = 1 WHERE id = ?", (token_id,))
        conn.execute("DELETE FROM devices WHERE token_id = ?", (token_id,))
        conn.execute(
            "INSERT INTO activity (user_id, kind, detail, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, "device.revoked", f"{row['name']} signed out", row["kind"], _iso()),
        )
    return True


def list_devices(user_id: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        cursor = conn.execute(
            "SELECT id, name, kind, platform, app_version, created_at, last_seen "
            "FROM devices WHERE user_id = ? ORDER BY last_seen DESC",
            (user_id,),
        )
        return _rows(cursor)


def touch_device(user_id: int, token_id: int | None, name: str = "", platform: str = "", app_version: str = "") -> None:
    now = _iso()
    with _connect() as conn:
        row = None
        if token_id:
            row = conn.execute("SELECT id, platform, app_version FROM devices WHERE token_id = ?", (token_id,)).fetchone()
        if row:
            # Resolve COALESCE/NULLIF in Python so this works on both backends.
            new_platform = platform or row["platform"] or ""
            new_version = app_version or row["app_version"] or ""
            conn.execute(
                "UPDATE devices SET last_seen = ?, platform = ?, app_version = ? WHERE id = ?",
                (now, new_platform, new_version, row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO devices (user_id, token_id, name, kind, platform, app_version, created_at, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, token_id, name or "Device", "desktop", platform, app_version, now, now),
            )


# --------------------------------------------------------------------------- #
#  Device authorization flow (sign in to the apps "through the website")       #
# --------------------------------------------------------------------------- #
def start_device_code(kind: str = "desktop", name: str = "") -> dict[str, Any]:
    device_code = secrets.token_urlsafe(32)
    code = _new_user_code()
    now = _now()
    with _connect() as conn:
        while conn.execute("SELECT 1 FROM device_codes WHERE code = ?", (code,)).fetchone():
            code = _new_user_code()
        conn.execute(
            "INSERT INTO device_codes (code, device_code, kind, name, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (code, device_code, kind, name, _iso(now), _iso(now + timedelta(minutes=DEVICE_CODE_TTL_MINUTES))),
        )
    return {
        "device_code": device_code,
        "user_code": code,
        "expires_in": DEVICE_CODE_TTL_MINUTES * 60,
        "interval": 3,
    }


def get_device_code_by_user_code(user_code: str) -> dict[str, Any] | None:
    normalized = normalize_code(user_code)
    with _connect() as conn:
        cursor = conn.execute("SELECT * FROM device_codes")
        for row in cursor.fetchall():
            if normalize_code(row["code"]) == normalized:
                return dict(row)
    return None


def approve_device_code(user_code: str, user_id: int) -> dict[str, Any]:
    entry = get_device_code_by_user_code(user_code)
    if not entry:
        raise ValueError("That code was not recognised. Check the app and try again.")
    if entry["status"] == "approved":
        raise ValueError("That code has already been used.")
    if entry["status"] == "denied":
        raise ValueError("That code was denied. Start again from the app.")
    if (_parse(entry["expires_at"]) or _now()) < _now():
        raise ValueError("That code has expired. Start again from the app.")

    with _connect() as conn:
        conn.execute(
            "UPDATE device_codes SET user_id = ?, status = 'approved' WHERE code = ?",
            (user_id, entry["code"]),
        )
        conn.execute(
            "INSERT INTO activity (user_id, kind, detail, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, "device.approved", f"Approved sign-in for {entry['name'] or entry['kind']}", "website", _iso()),
        )
    return {"user_code": entry["code"], "kind": entry["kind"], "name": entry["name"]}


def deny_device_code(user_code: str) -> bool:
    entry = get_device_code_by_user_code(user_code)
    if not entry or entry["status"] != "pending":
        return False
    with _connect() as conn:
        conn.execute("UPDATE device_codes SET status = 'denied' WHERE code = ?", (entry["code"],))
    return True


def poll_device_code(device_code: str, platform: str = "", app_version: str = "") -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM device_codes WHERE device_code = ?", (device_code,)
        ).fetchone()
        if not row:
            return {"status": "invalid"}
        if row["status"] != "approved":
            if (_parse(row["expires_at"]) or _now()) < _now():
                conn.execute("UPDATE device_codes SET status = 'expired' WHERE code = ?", (row["code"],))
                return {"status": "expired"}
            return {"status": row["status"]}
        if row["token"]:
            # Already redeemed on an earlier poll: hand back the same token.
            return {"status": "approved", "token": row["token"]}

        created = create_access_token(
            row["user_id"],
            name=row["name"] or row["kind"].title(),
            kind=row["kind"],
            platform=platform,
            app_version=app_version,
        )
        conn.execute(
            "UPDATE device_codes SET token = ? WHERE code = ?", (created["token"], row["code"])
        )
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    return {"status": "approved", "token": created["token"], "user": _public_user(user)}


# --------------------------------------------------------------------------- #
#  Activity + usage                                                            #
# --------------------------------------------------------------------------- #
def log_event(user_id: int, kind: str, detail: str = "", source: str = "website") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO activity (user_id, kind, detail, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, kind[:80], detail[:300], source[:40], _iso()),
        )


def list_activity(user_id: int, limit: int = 40) -> list[dict[str, Any]]:
    with _connect() as conn:
        cursor = conn.execute(
            "SELECT kind, detail, source, created_at FROM activity WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, int(limit)),
        )
        return _rows(cursor)


def record_usage(
    user_id: int, source: str, model: str, tokens_in: int = 0, tokens_out: int = 0
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage_events (user_id, source, model, tokens_in, tokens_out, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, source[:40], model[:120], int(tokens_in or 0), int(tokens_out or 0), _iso()),
        )


# --------------------------------------------------------------------------- #
#  Synced settings                                                             #
# --------------------------------------------------------------------------- #
def get_settings(user_id: int) -> dict[str, Any]:
    with _connect() as conn:
        cursor = conn.execute("SELECT key, value FROM user_settings WHERE user_id = ?", (user_id,))
        out: dict[str, Any] = {}
        for row in cursor.fetchall():
            try:
                out[row["key"]] = __import__("json").loads(row["value"])
            except Exception:
                out[row["key"]] = row["value"]
    return out


def set_settings(user_id: int, values: dict[str, Any]) -> dict[str, Any]:
    import json

    now = _iso()
    with _connect() as conn:
        for key, value in (values or {}).items():
            conn.execute(
                "INSERT INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (user_id, str(key)[:60], json.dumps(value), now),
            )
    return get_settings(user_id)


# --------------------------------------------------------------------------- #
#  Dashboard aggregate                                                         #
# --------------------------------------------------------------------------- #
def overview(user_id: int) -> dict[str, Any]:
    """Everything the dashboard needs in one call."""
    with _connect() as conn:
        totals = conn.execute(
            "SELECT COALESCE(SUM(tokens_in), 0) AS tokens_in, COALESCE(SUM(tokens_out), 0) AS tokens_out, "
            "COUNT(*) AS requests FROM usage_events WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        today = conn.execute(
            "SELECT COUNT(*) AS requests FROM usage_events WHERE user_id = ? "
            "AND substr(created_at, 1, 10) = ?",
            (user_id, _today_iso()),
        ).fetchone()
        by_source = _rows(
            conn.execute(
                "SELECT source, COUNT(*) AS requests, COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens "
                "FROM usage_events WHERE user_id = ? GROUP BY source ORDER BY requests DESC",
                (user_id,),
            )
        )
        by_model = _rows(
            conn.execute(
                "SELECT model, COUNT(*) AS requests, COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens "
                "FROM usage_events WHERE user_id = ? GROUP BY model ORDER BY requests DESC LIMIT 8",
                (user_id,),
            )
        )
        daily = _rows(
            conn.execute(
                "SELECT substr(created_at, 1, 10) AS day, COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens, "
                "COUNT(*) AS requests FROM usage_events WHERE user_id = ? "
                "AND created_at >= ? GROUP BY day ORDER BY day",
                (user_id, _days_ago_iso(13)),
            )
        )
    # Gap-fill the last 14 days so the dashboard chart always has a full axis.
    from datetime import date, timedelta

    by_day = {row["day"]: row for row in daily}
    today_date = date.today()
    daily_filled: list[dict[str, Any]] = []
    for offset in range(13, -1, -1):
        moment = today_date - timedelta(days=offset)
        key = moment.isoformat()
        row = by_day.get(key)
        daily_filled.append(
            {
                "day": key,
                "label": moment.strftime("%a"),
                "day_num": moment.day,
                "tokens": int((row or {}).get("tokens") or 0),
                "requests": int((row or {}).get("requests") or 0),
            }
        )

    return {
        "totals": dict(totals),
        "today": dict(today),
        "by_source": by_source,
        "by_model": by_model,
        "daily": daily,
        "daily_filled": daily_filled,
        "devices": list_devices(user_id),
        "activity": list_activity(user_id, 25),
        "tokens": list_tokens(user_id),
        "settings": get_settings(user_id),
    }