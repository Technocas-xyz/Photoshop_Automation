"""Central configuration for Design Studio Automation.

All runtime knobs live here. Environment variables override defaults so the
app can be driven differently per machine without code changes.
"""
from __future__ import annotations

import os
from pathlib import Path

# Load a .env file at the project root (if present) BEFORE reading any env vars
# so values there populate os.environ. python-dotenv is optional at runtime: if
# it is not installed we silently skip, keeping DEMO_MODE usable with zero extra
# dependencies.
try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
DEBUG_DIR = DATA_DIR / "debug"
STATIC_DIR = BASE_DIR / "app" / "static"
DB_PATH = DATA_DIR / "studio.sqlite"

# Legacy Playwright persistent profile (old "launch" default). Kept so earlier
# behaviour still resolves; the robust path now uses PS_PROFILE_DIR below.
PW_PROFILE_DIR = BASE_DIR / "pw_profile"

for _p in (DATA_DIR, UPLOAD_DIR, RESULT_DIR, DEBUG_DIR):
    _p.mkdir(parents=True, exist_ok=True)


def _default_downloads_dir() -> Path:
    """Best-effort path to the current user's Downloads folder."""
    home = Path.home()
    candidate = home / "Downloads"
    return candidate


# ---------------------------------------------------------------------------
# Behaviour flags
# ---------------------------------------------------------------------------
# DEMO_MODE skips Photoshop entirely and returns the Pillow result instead.
# Lets the UI + log streaming be exercised without an Adobe session.
DEMO_MODE = _env_bool("DEMO_MODE", False)

# Which engine performs the Blackout op: real Photoshop automation, or the
# local Pillow reference implementation. Lets you A/B the two outputs.
# One of: "photoshop" | "pillow"
BLACKOUT_ENGINE = os.environ.get("BLACKOUT_ENGINE", "photoshop").strip().lower()

# Hard timeout per job in seconds.
JOB_TIMEOUT_SECONDS = _env_int("JOB_TIMEOUT_SECONDS", 180)

# Upload constraints
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024)  # 10 MB
ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# ---------------------------------------------------------------------------
# Playwright / Photoshop
# ---------------------------------------------------------------------------
PHOTOSHOP_URL = "https://photoshop.adobe.com"
PW_CHANNEL = os.environ.get("PW_CHANNEL", "chrome")
PW_HEADLESS = _env_bool("PW_HEADLESS", False)

# ---------------------------------------------------------------------------
# Photoshop Web connection
# ---------------------------------------------------------------------------
# How Playwright reaches Chrome:
#   "cdp"    -> attach to a normal Chrome you started yourself (start_chrome.bat)
#               over the DevTools protocol. This is the robust default: Adobe
#               behaves far better in a real, user-launched Chrome than in the
#               bare browser Playwright launches itself.
#   "launch" -> fallback; Playwright launches its own persistent Chrome.
PS_CONNECT_MODE = os.environ.get("PS_CONNECT_MODE", "cdp").strip().lower()

# DevTools endpoint that start_chrome.bat exposes. Bound to localhost only.
PS_CDP_URL = os.environ.get("PS_CDP_URL", "http://127.0.0.1:9222").strip()

# Dedicated Chrome profile directory for the user-launched Chrome. A dedicated
# --user-data-dir is MANDATORY: Chrome 136+ ignores remote debugging on the
# default profile. Stored as an absolute path so the launcher scripts and the
# app agree on exactly one location.
PS_PROFILE_DIR = Path(
    os.environ.get("PS_PROFILE_DIR", str(BASE_DIR / "chrome_profile"))
).resolve()

# Where Chrome drops downloads when we cannot capture them via Playwright's
# download event (common in CDP mode). We watch this folder for the newest
# .png appearing after an export click.
PS_DOWNLOAD_DIR = Path(
    os.environ.get("PS_DOWNLOAD_DIR", str(_default_downloads_dir()))
).resolve()

# Minimum usable Photoshop window. Below this the layout gets cut off and
# menus overflow, so we warn the user to maximize / zoom out.
PS_MIN_WINDOW_WIDTH = _env_int("PS_MIN_WINDOW_WIDTH", 1280)
PS_MIN_WINDOW_HEIGHT = _env_int("PS_MIN_WINDOW_HEIGHT", 720)
