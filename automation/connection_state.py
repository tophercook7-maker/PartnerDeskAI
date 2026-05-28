"""
connection_state.py
-------------------
Persistent 3-state verification cache for publishing platforms.

States:
    verified       — env keys present AND last verify probe succeeded
    configured     — env keys present, but verify never run OR last verify failed
    not_configured — env keys missing

Cache lives at data/connection_status.json. The file is created on first
write; if the directory is missing it's created too. The file is
.gitignored — only the empty data/.gitkeep placeholder ships in the repo.

Never stores token values. Only stores: state, last_verified_at, and
the human message returned by the verify helper.
"""

import json
import os
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "connection_status.json"

# Mirrors hub/app.py's _PLATFORM_ENV_REQUIREMENTS. Lowercase-with-
# underscores keys keep the wizard CLI, the Hub API, and this cache
# all using the same identifier shape.
PLATFORM_ENV_KEYS = {
    "linkedin":                ["LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_URN"],
    "facebook":                ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN"],
    "google_business_profile": ["GBP_ACCESS_TOKEN", "GBP_ACCOUNT_ID", "GBP_LOCATION_ID"],
    "instagram":               ["INSTAGRAM_BUSINESS_ACCOUNT_ID", "INSTAGRAM_ACCESS_TOKEN"],
}

_EMPTY_STATE = {"state": "not_configured", "last_verified_at": None, "last_message": None}


def env_present(platform_key: str) -> bool:
    """True iff every required env key for this platform is non-empty."""
    keys = PLATFORM_ENV_KEYS.get(platform_key, [])
    if not keys:
        return False
    return all((os.getenv(k) or "").strip() for k in keys)


def load_states() -> dict:
    """Read the on-disk cache. Returns {} if missing or unreadable."""
    if not CACHE_PATH.is_file():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        return {}


def save_states(states: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")


def compute_state(platform_key: str, cache: dict | None = None) -> dict:
    """
    Return the live trust state for `platform_key` as
        {state, last_verified_at, last_message}
    Read-only — never updates the cache.

    - env missing                                  -> not_configured
    - env present, cache says verified             -> verified
    - env present, cache says configured / missing -> configured
    """
    if cache is None:
        cache = load_states()
    if not env_present(platform_key):
        return dict(_EMPTY_STATE)
    entry = cache.get(platform_key) or {}
    if entry.get("state") == "verified":
        return {
            "state":            "verified",
            "last_verified_at": entry.get("last_verified_at"),
            "last_message":     entry.get("last_message"),
        }
    return {
        "state":            "configured",
        "last_verified_at": entry.get("last_verified_at"),
        "last_message":     entry.get("last_message"),
    }


def record_verification(platform_key: str, ok: bool, message: str) -> dict:
    """
    Persist the outcome of a verify probe and return the new state dict.

    Decision matrix:
        env missing      -> not_configured (clears any prior verify state)
        env present + ok -> verified
        env present + !ok -> configured (with the failure message)
    """
    cache = load_states()
    if not env_present(platform_key):
        cache[platform_key] = dict(_EMPTY_STATE)
    else:
        cache[platform_key] = {
            "state":            "verified" if ok else "configured",
            "last_verified_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_message":     message or "",
        }
    save_states(cache)
    return cache[platform_key]
