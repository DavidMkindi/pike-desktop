"""Pike's self-updater.

Pike ships as a GitHub Release: each tagged build publishes ``Pike.exe`` and a
``Pike-<version>-Setup.exe`` installer. This module talks to the GitHub
Releases API, compares the running version, downloads the newest build and
launches the installer to replace the app in place.

The repository is **private**, so every request is authenticated. The token is
resolved in this order (first hit wins):

1. ``PIKE_GITHUB_TOKEN`` environment variable (or a local ``.env`` file).
2. ``GITHUB_TOKEN`` / ``GH_TOKEN`` environment variables.
3. A token saved from the app's Settings ▸ About page (``github_token``).
4. The ``gh`` command-line tool, when it is installed and signed in.

Nothing is sent anywhere except to ``api.github.com`` and the signed asset
download URL GitHub returns.

The public surface is small:

* :func:`check` - look for a newer release and describe it.
* :func:`start_download` - download it in the background.
* :func:`progress` - poll the background download.
* :func:`apply_update` - run the installer / swap the exe.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests

import config

GITHUB_API = "https://api.github.com"
REPO = "DavidMkindi/pike-desktop"

# Where downloaded builds are staged. Lives next to settings/history in the
# per-user data directory so it survives across runs and needs no admin rights.
UPDATES_DIR: Path = config.DATA_DIR / "updates"

USER_AGENT = f"{config.APP_NAME}-Updater/{config.APP_VERSION}"

# A tiny state machine shared between the download thread and the HTTP API.
_STATE: dict[str, Any] = {
    "phase": "idle",       # idle | downloading | ready | applying | error
    "active": False,
    "cancelled": False,
    "version": "",
    "asset": "",
    "path": "",
    "downloaded": 0,
    "total": 0,
    "percent": 0.0,
    "speed": 0.0,
    "error": "",
    "message": "",
}
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None


# --------------------------------------------------------------------------- #
#  Version helpers                                                            #
# --------------------------------------------------------------------------- #
def normalize_version(text: str) -> str:
    """Turn a release tag such as ``v1.2.0`` into ``1.2.0``."""
    value = str(text or "").strip()
    if value[:1] in ("v", "V"):
        value = value[1:]
    return value.strip()


def version_tuple(text: str) -> tuple[int, ...]:
    """Return a comparable tuple of ints for a version string.

    ``"1.2.0"`` -> ``(1, 2, 0)``; anything without digits sorts as ``(0,)``.
    """
    parts = re.findall(r"\d+", str(text) or "")
    return tuple(int(part) for part in parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    """True when *candidate* is a strictly newer version than *current*."""
    return version_tuple(candidate) > version_tuple(current)


# --------------------------------------------------------------------------- #
#  Authentication                                                             #
# --------------------------------------------------------------------------- #
def _gh_cli_token() -> str:
    """Ask the GitHub CLI for its token, when it is signed in."""
    exe = shutil.which("gh")
    if not exe:
        return ""
    try:
        result = subprocess.run(
            [exe, "auth", "token"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_token() -> str:
    """Resolve a GitHub token from the environment, settings or ``gh``."""
    for env_name in ("PIKE_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    stored = config.get_github_token()
    if stored:
        return stored
    return _gh_cli_token()


def _headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _repo() -> str:
    return config.get_update_repo() or REPO


# --------------------------------------------------------------------------- #
#  Release lookup                                                             #
# --------------------------------------------------------------------------- #
class UpdaterError(RuntimeError):
    """Raised for any recoverable updater failure."""


def _pick_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose the best asset to install.

    Preference: the Inno Setup installer (it replaces the app cleanly), then
    any ``Pike*.exe``, then any ``.exe``.
    """
    def score(asset: dict[str, Any]) -> tuple[int, str]:
        name = str(asset.get("name") or "").lower()
        if "setup" in name:
            return (0, name)
        if name.endswith(".exe") and "pike" in name:
            return (1, name)
        if name.endswith(".exe"):
            return (2, name)
        return (9, name)

    candidates = [a for a in assets if isinstance(a, dict) and a.get("name")]
    if not candidates:
        return None
    return sorted(candidates, key=score)[0]


def _asset_payload(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": asset.get("name") or "",
        "size": int(asset.get("size") or 0),
        "content_type": asset.get("content_type") or "",
        "url": asset.get("url") or "",
        "browser_url": asset.get("browser_download_url") or "",
        "digest": asset.get("digest") or "",
        "is_installer": "setup" in str(asset.get("name") or "").lower(),
    }


def _fetch_json(url: str, timeout: int = 12) -> Any:
    response = requests.get(url, headers=_headers(), timeout=timeout)
    return response


def _release_from(raw: dict[str, Any]) -> dict[str, Any]:
    tag = str(raw.get("tag_name") or raw.get("name") or "")
    version = normalize_version(tag)
    assets = raw.get("assets") or []
    chosen = _pick_asset(assets)
    return {
        "tag": tag,
        "version": version,
        "name": raw.get("name") or f"Pike {version}",
        "notes": raw.get("body") or "",
        "published_at": raw.get("published_at") or "",
        "prerelease": bool(raw.get("prerelease")),
        "html_url": raw.get("html_url") or "",
        "asset": _asset_payload(chosen) if chosen else None,
        "assets": [_asset_payload(a) for a in assets if isinstance(a, dict)],
    }


def latest_release(include_prerelease: bool = False) -> dict[str, Any]:
    """Return the newest release, or raise :class:`UpdaterError`."""
    repo = _repo()
    if include_prerelease:
        url = f"{GITHUB_API}/repos/{repo}/releases?per_page=20"
    else:
        url = f"{GITHUB_API}/repos/{repo}/releases/latest"

    response = _fetch_json(url)
    if response.status_code == 404:
        # ``/latest`` 404s when the only releases are prereleases or drafts.
        if not include_prerelease:
            return latest_release(include_prerelease=True)
        raise UpdaterError(
            f"No releases were found for {repo}. If the repository is private, "
            "make sure your GitHub token has access to it."
        )
    if response.status_code in (401, 403):
        raise UpdaterError(
            "GitHub rejected the request. Add a token with 'repo' access in "
            "Settings, or sign in with the 'gh' CLI."
        )
    if not response.ok:
        raise UpdaterError(
            f"GitHub request failed ({response.status_code}): {response.reason}"
        )

    data = response.json()
    if isinstance(data, list):
        if not data:
            raise UpdaterError("No releases have been published yet.")
        # Prefer the newest non-prerelease when one exists.
        stable = [r for r in data if not r.get("prerelease")]
        data = (stable or data)[0]
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise UpdaterError("The latest release could not be read.")
    return _release_from(data)


def check(include_prerelease: bool = False) -> dict[str, Any]:
    """Check for an update and describe what is available."""
    current = config.APP_VERSION
    release = latest_release(include_prerelease=include_prerelease)
    latest = release["version"] or current
    asset = release.get("asset")
    update_available = is_newer(latest, current)
    return {
        "ok": True,
        "configured": True,
        "authenticated": bool(get_token()),
        "repo": _repo(),
        "current": current,
        "latest": latest,
        "tag": release["tag"],
        "name": release["name"],
        "update_available": update_available,
        "prerelease": release["prerelease"],
        "notes": release["notes"],
        "published_at": release["published_at"],
        "html_url": release["html_url"],
        "asset": asset,
        "assets": release["assets"],
        # Backwards-compatible fields for older clients.
        "url": release["html_url"],
        "size": (asset or {}).get("size", 0),
    }


# --------------------------------------------------------------------------- #
#  Download                                                                   #
# --------------------------------------------------------------------------- #
def _set_state(**changes: Any) -> None:
    with _LOCK:
        _STATE.update(changes)


def _snapshot() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def progress() -> dict[str, Any]:
    """Return a copy of the current download state."""
    state = _snapshot()
    state["ok"] = state["phase"] != "error"
    return state


def _reset_state(version: str, asset_name: str, total: int) -> None:
    with _LOCK:
        _STATE.update(
            {
                "phase": "downloading",
                "active": True,
                "cancelled": False,
                "version": version,
                "asset": asset_name,
                "path": "",
                "downloaded": 0,
                "total": total,
                "percent": 0.0,
                "speed": 0.0,
                "error": "",
                "message": "Contacting GitHub...",
            }
        )


def cancel_download() -> dict[str, Any]:
    """Request cancellation of the in-flight download."""
    with _LOCK:
        if _STATE["active"]:
            _STATE["cancelled"] = True
            _STATE["message"] = "Cancelling..."
    return progress()


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "update.exe").strip("._")
    return cleaned or "update.exe"


def start_download(version: str = "", include_prerelease: bool = False) -> dict[str, Any]:
    """Begin downloading the newest release in a background thread.

    Safe to call twice: while a download is active the current state is
    returned instead of starting another.
    """
    global _THREAD
    with _LOCK:
        if _STATE["active"]:
            return dict(_STATE)

    release = latest_release(include_prerelease=include_prerelease)
    asset = release.get("asset")
    if not asset or not (asset.get("url") or asset.get("browser_url")):
        raise UpdaterError("The release does not include a downloadable file.")

    _reset_state(
        version=release["version"],
        asset_name=asset["name"],
        total=int(asset.get("size") or 0),
    )

    _THREAD = threading.Thread(
        target=_download_worker,
        args=(release, asset),
        name="pike-update-download",
        daemon=True,
    )
    _THREAD.start()
    return progress()


def _download_worker(release: dict[str, Any], asset: dict[str, Any]) -> None:
    version = release["version"] or "latest"
    target_dir = UPDATES_DIR / _safe_name(version)
    target = target_dir / _safe_name(asset["name"])
    part = target.with_name(target.name + ".part")

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # Clean up leftovers from a previous interrupted attempt.
        for stale in (part, target):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass

        url = asset.get("url") or asset.get("browser_url")
        headers = _headers("application/octet-stream")
        started = time.time()
        last_mark = started
        last_bytes = 0
        digest = hashlib.sha256()
        downloaded = 0
        total = int(asset.get("size") or 0)

        with requests.get(url, headers=headers, stream=True, timeout=(15, 120)) as response:
            if response.status_code in (401, 403):
                raise UpdaterError(
                    "GitHub refused the download. Check that your token can "
                    "read this repository's releases."
                )
            response.raise_for_status()
            if not total:
                total = int(response.headers.get("Content-Length") or 0)

            with part.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    if _snapshot().get("cancelled"):
                        raise UpdaterError("Download cancelled.")
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if now - last_mark >= 0.4:
                        speed = (downloaded - last_bytes) / max(now - last_mark, 1e-6)
                        last_mark, last_bytes = now, downloaded
                        percent = (downloaded / total * 100) if total else 0.0
                        _set_state(
                            downloaded=downloaded,
                            total=total,
                            percent=round(percent, 1),
                            speed=round(speed, 1),
                            message=f"Downloading {asset['name']}...",
                        )

        # Validate what we received before trusting it.
        if total and downloaded != total:
            raise UpdaterError(
                f"Download incomplete ({downloaded} of {total} bytes)."
            )
        expected = str(asset.get("digest") or "")
        if expected.startswith("sha256:"):
            actual = digest.hexdigest()
            if actual.lower() != expected.split(":", 1)[1].lower():
                raise UpdaterError("Downloaded file failed its checksum check.")

        part.replace(target)

        # Drop older staged builds so the updates folder does not grow forever.
        for old in UPDATES_DIR.iterdir():
            if old.is_dir() and old != target_dir:
                shutil.rmtree(old, ignore_errors=True)

        _set_state(
            phase="ready",
            active=False,
            path=str(target),
            downloaded=downloaded,
            total=total or downloaded,
            percent=100.0,
            message=f"Pike {version} is ready to install.",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI as text
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        _set_state(
            phase="error",
            active=False,
            error=str(exc),
            message=str(exc),
        )


# --------------------------------------------------------------------------- #
#  Apply                                                                      #
# --------------------------------------------------------------------------- #
def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _spawn_detached(command: list[str]) -> None:
    """Start a process that outlives Pike (the installer replaces our exe)."""
    kwargs: dict[str, Any] = {"close_fds": True}
    if os.name == "nt":  # pragma: no cover - Windows only
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(command, **kwargs)


def _schedule_self_replace(new_exe: Path) -> None:
    """Fallback for builds without an installer: swap the exe after we exit."""
    current = Path(sys.executable)
    script = UPDATES_DIR / "apply_update.bat"
    pid = os.getpid()
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                ":wait",
                f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
                "if not errorlevel 1 (",
                "  timeout /t 1 /nobreak >nul",
                "  goto wait",
                ")",
                f'copy /Y "{new_exe}" "{current}" >nul',
                f'start "" "{current}"',
                'del "%~f0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    _spawn_detached(["cmd", "/c", str(script)])


def apply_update() -> dict[str, Any]:
    """Install the downloaded build.

    Prefers the Inno Setup installer (silent, closes and relaunches Pike).
    Falls back to swapping the running executable on the next start.
    """
    state = _snapshot()
    path = state.get("path") or ""
    if state.get("phase") != "ready" or not path:
        return {"ok": False, "error": "No update has been downloaded yet."}

    target = Path(path)
    if not target.is_file():
        return {"ok": False, "error": "The downloaded update is missing."}

    is_installer = "setup" in target.name.lower()

    if not os.name == "nt":
        return {
            "ok": False,
            "error": f"Automatic install is only supported on Windows. The update is saved at {target}.",
            "path": str(target),
        }

    try:
        if is_installer:
            _set_state(phase="applying", message="Starting the installer...")
            _spawn_detached(
                [
                    str(target),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/CLOSEAPPLICATIONS",
                    "/RESTARTAPPLICATIONS",
                    "/SP-",
                ]
            )
            return {"ok": True, "mode": "installer", "path": str(target)}

        if _is_frozen():
            _set_state(phase="applying", message="Replacing Pike and restarting...")
            _schedule_self_replace(target)
            return {"ok": True, "mode": "replace", "path": str(target)}

        # Running from source: there is nothing to overwrite.
        return {
            "ok": True,
            "mode": "manual",
            "path": str(target),
            "message": "Update downloaded. Pike is running from source, so install it manually.",
        }
    except Exception as exc:  # noqa: BLE001
        _set_state(phase="ready", error=str(exc), message=str(exc))
        return {"ok": False, "error": f"Could not start the installer: {exc}"}
