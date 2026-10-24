"""Resolve the newest Pike desktop release for the public website.

The download page must always offer the newest installers, and its buttons
should download the file directly instead of sending visitors to GitHub's HTML
pages. This module asks the GitHub Releases API for the latest release, maps
each platform/architecture to the right asset and returns that asset's direct
``browser_download_url``.

Only the standard library is used, so it runs on Vercel with no extra
dependencies. Lookups are cached in-process for a few minutes to stay well
inside GitHub's unauthenticated rate limit; if GitHub cannot be reached the
cached result is reused, and failing that the page falls back to the release
page.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

REPO = os.environ.get("PIKE_REPO", "DavidMkindi/pike-desktop")
GITHUB_API = "https://api.github.com"
USER_AGENT = f"Pike-Website (https://github.com/{REPO})"
CACHE_TTL = int(os.environ.get("PIKE_RELEASE_CACHE_TTL") or "600")

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "release": None}

# Public download slots. Each maps to a platform, an optional CPU architecture
# and the file extensions that make sense for it, in order of preference.
SLOTS: dict[str, dict[str, Any]] = {
    "windows": {"platform": "windows", "arch": "", "exts": (".exe",)},
    "macos-arm64": {"platform": "macos", "arch": "arm64", "exts": (".dmg", ".pkg")},
    "macos-x86_64": {"platform": "macos", "arch": "x86_64", "exts": (".dmg", ".pkg")},
    "linux-appimage": {"platform": "linux", "arch": "", "exts": (".appimage",)},
    "linux-deb": {"platform": "linux", "arch": "", "exts": (".deb",)},
}


def _normalize_version(tag: str) -> str:
    value = str(tag or "").strip()
    return value[1:].strip() if value[:1] in ("v", "V") else value


def human_size(num: Any) -> str:
    """Format a byte count for humans (``"18.2 MB"``)."""
    try:
        size = float(num or 0)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _arch_tokens(arch: str) -> tuple[str, ...]:
    if arch == "arm64":
        return ("arm64", "aarch64", "apple", "silicon")
    if arch == "x86_64":
        return ("x86_64", "amd64", "intel", "x64")
    return ()


def _score(name: str, slot: dict[str, Any]) -> tuple[Any, ...] | None:
    """Rank *name* for *slot*; ``None`` means the asset does not fit the slot."""
    lowered = str(name or "").lower()
    platform = slot["platform"]
    arch = slot.get("arch") or ""
    exts = slot["exts"]

    ext_rank = next((i for i, ext in enumerate(exts) if lowered.endswith(ext)), None)
    if ext_rank is None:
        return None

    if platform == "windows":
        kind = 0 if ("setup" in lowered or "installer" in lowered) else 1
    elif platform == "macos":
        kind = 0 if any(tag in lowered for tag in ("macos", "darwin", "osx", "mac-", "mac_")) else 1
    else:  # linux
        kind = 0 if "linux" in lowered else 1

    if arch:
        arch_rank = 0 if any(tag in lowered for tag in _arch_tokens(arch)) else 1
    else:
        arch_rank = 0

    return (kind, arch_rank, ext_rank, lowered)


def _pick(assets: list[dict[str, Any]], slot: dict[str, Any]) -> dict[str, Any] | None:
    scored: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for asset in assets:
        rank = _score(asset.get("name") or "", slot)
        if rank is not None:
            scored.append((rank, asset))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _asset_payload(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": asset.get("name") or "",
        "size": int(asset.get("size") or 0),
        "size_human": human_size(asset.get("size")),
        "url": asset.get("browser_download_url") or asset.get("url") or "",
    }


def _build(raw: dict[str, Any]) -> dict[str, Any]:
    tag = str(raw.get("tag_name") or raw.get("name") or "")
    version = _normalize_version(tag)
    assets = [a for a in (raw.get("assets") or []) if isinstance(a, dict) and a.get("name")]

    slots: dict[str, Any] = {}
    for slug, slot in SLOTS.items():
        best = _pick(assets, slot)
        if best and (best.get("browser_download_url") or best.get("url")):
            slots[slug] = _asset_payload(best)

    return {
        "tag": tag,
        "version": version or "latest",
        "name": raw.get("name") or (f"Pike {version}" if version else "Pike"),
        "published_at": raw.get("published_at") or "",
        "prerelease": bool(raw.get("prerelease")),
        "html_url": raw.get("html_url") or f"https://github.com/{REPO}/releases",
        "assets": [_asset_payload(a) for a in assets],
        "slots": slots,
    }


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("PIKE_GITHUB_TOKEN")
    )
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch() -> dict[str, Any] | None:
    try:
        data = _get_json(f"{GITHUB_API}/repos/{REPO}/releases/latest")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:  # 404 => every release is a prerelease or none exist
            return None
        try:
            data = _get_json(f"{GITHUB_API}/repos/{REPO}/releases?per_page=20")
        except Exception:
            return None
    except Exception:
        return None

    if isinstance(data, list):
        stable = [item for item in data if isinstance(item, dict) and not item.get("prerelease")]
        candidates = stable or [item for item in data if isinstance(item, dict)]
        data = candidates[0] if candidates else None
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    return _build(data)


def _empty() -> dict[str, Any]:
    return {
        "tag": "",
        "version": "",
        "name": "Pike",
        "published_at": "",
        "prerelease": False,
        "html_url": f"https://github.com/{REPO}/releases",
        "assets": [],
        "slots": {},
    }


def latest(force: bool = False) -> dict[str, Any]:
    """Return the newest release, using a short-lived in-process cache."""
    now = time.time()
    with _LOCK:
        cached = _CACHE["release"]
        if not force and cached and (now - _CACHE["at"]) < CACHE_TTL:
            return cached

    fetched = _fetch()
    with _LOCK:
        if fetched:
            _CACHE["release"] = fetched
            _CACHE["at"] = time.time()
            return fetched
        if _CACHE["release"]:
            return _CACHE["release"]
        # Negative cache so a GitHub outage does not trigger a request per hit.
        _CACHE["release"] = _empty()
        _CACHE["at"] = time.time()
        return _CACHE["release"]


def asset(slug: str) -> dict[str, Any] | None:
    """Return the resolved asset for a public *slug*, if one exists."""
    if slug not in SLOTS:
        return None
    return (latest().get("slots") or {}).get(slug)


def download_url(slug: str) -> str:
    """Return the direct download URL for *slug*, or an empty string."""
    payload = asset(slug)
    return str(payload.get("url") or "") if payload else ""
