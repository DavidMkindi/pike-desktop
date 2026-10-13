"""A tiny persistent-shell manager for Pike's pop-up terminal.

Each :class:`TerminalSession` owns one long-lived shell process whose stdin,
stdout and stderr are pumped by background threads into an output buffer. The
frontend polls :meth:`TerminalSession.read` for new output and posts commands
via :meth:`TerminalSession.write`.

The manager keeps sessions in memory keyed by id; they are reaped when the
process exits or the session is closed.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque

MAX_BUFFER_LINES = 4000
IDLE_TIMEOUT_SECONDS = 60 * 60  # reap sessions idle for an hour


def _default_shell() -> str:
    if os.name == "nt":
        return os.environ.get("COMSPEC") or "cmd.exe"
    return os.environ.get("SHELL") or "/bin/bash"


class TerminalSession:
    """One interactive shell process."""

    def __init__(self, cwd: str | None = None, shell: str | None = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.shell = shell or _default_shell()
        self.cwd = cwd if cwd and os.path.isdir(cwd) else os.getcwd()
        self.created = time.time()
        self.last_used = time.time()
        self._buffer: Deque[str] = deque(maxlen=MAX_BUFFER_LINES)
        self._lock = threading.Lock()
        self._closed = False

        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            # CREATE_NEW_PROCESS_GROUP lets us interrupt without killing the app.
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self._process = subprocess.Popen(  # noqa: S603 - deliberate shell
            [self.shell],
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **kwargs,
        )
        self._pump = threading.Thread(target=self._read_loop, daemon=True)
        self._pump.start()

    # -- output ------------------------------------------------------------- #
    def _emit(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._buffer.append(text)

    def _read_loop(self) -> None:
        stream = self._process.stdout
        if stream is None:
            return
        try:
            for chunk in iter(lambda: stream.read(1), ""):
                self._emit(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self._emit("\n[process exited]\n")

    def read(self) -> str:
        """Return and clear everything buffered since the last poll."""
        self.last_used = time.time()
        with self._lock:
            if not self._buffer:
                return ""
            text = "".join(self._buffer)
            self._buffer.clear()
            return text

    def write(self, command: str) -> None:
        """Send a line of input to the shell."""
        if self._closed or self._process.poll() is not None:
            raise RuntimeError("This terminal has closed.")
        self.last_used = time.time()
        data = command if command.endswith("\n") else command + "\n"
        stdin = self._process.stdin
        if stdin is None:
            raise RuntimeError("This terminal cannot accept input.")
        try:
            stdin.write(data)
            stdin.flush()
        except (OSError, ValueError) as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Could not write to the terminal: {exc}") from exc

    def interrupt(self) -> None:
        """Best-effort Ctrl-C equivalent."""
        if self._process.poll() is not None:
            return
        try:
            if os.name == "nt":
                self._process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self._process.send_signal(signal.SIGINT)
        except Exception:  # pragma: no cover - defensive
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._process.stdin:
                self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.terminate()
            self._process.wait(timeout=3)
        except Exception:  # pragma: no cover - defensive
            try:
                self._process.kill()
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return not self._closed and self._process.poll() is None

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "shell": self.shell,
            "running": self.running,
        }


class TerminalManager:
    """Thread-safe registry of terminal sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create(self, cwd: str | None = None, shell: str | None = None) -> TerminalSession:
        session = TerminalSession(cwd=cwd, shell=shell)
        with self._lock:
            self._reap_locked()
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> TerminalSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def close(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.close()
        return True

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            self._reap_locked()
            return [session.info() for session in self._sessions.values()]

    def _reap_locked(self) -> None:
        now = time.time()
        for session_id in list(self._sessions):
            session = self._sessions[session_id]
            if not session.running or now - session.last_used > IDLE_TIMEOUT_SECONDS:
                try:
                    session.close()
                except Exception:  # pragma: no cover - defensive
                    pass
                self._sessions.pop(session_id, None)

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:  # pragma: no cover - defensive
                pass


manager = TerminalManager()