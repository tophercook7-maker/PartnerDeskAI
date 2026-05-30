"""
meta_app_state.py
-----------------
Per-Meta-platform user-authored notes (app review status, approved
permissions, reviewer feedback, etc.). Tiny JSON file at
data/meta_app_state.json. Atomic writes via temp-file + rename.

Schema:
    {
      "facebook":  {"notes": "...", "updated_at": "YYYY-MM-DD HH:MM:SS"},
      "instagram": {"notes": "...", "updated_at": "..."},
    }

Safety:
    - Notes are USER-AUTHORED free text — never persist anything
      fetched from a Meta API here (don't want to accidentally store
      a token returned in an error message).
    - File is gitignored.
    - Length capped at 4000 chars per platform.
    - Atomic write: write to a temp file in the same directory, then
      os.replace into place, so a crash mid-write cannot corrupt the
      existing file.
"""

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "meta_app_state.json"
MAX_NOTES_LEN = 4000
_ALLOWED_PLATFORMS = ("facebook", "instagram")


def load() -> dict:
    """Return the full state dict, or {} if file missing/corrupt."""
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    """Validates + atomically writes the full state dict."""
    if not isinstance(data, dict):
        raise ValueError("data must be a dict")
    # Whitelist + length-cap each entry. Unknown platforms are dropped
    # silently so a stale schema can't crash readers.
    cleaned: dict[str, dict] = {}
    for platform, entry in data.items():
        if platform not in _ALLOWED_PLATFORMS:
            continue
        if not isinstance(entry, dict):
            continue
        notes = str(entry.get("notes") or "")[:MAX_NOTES_LEN]
        updated_at = str(entry.get("updated_at") or "")[:32]
        cleaned[platform] = {"notes": notes, "updated_at": updated_at}

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".meta_app_state.", suffix=".tmp",
        dir=str(STATE_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, STATE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get(platform: str) -> dict:
    """Return one platform's {notes, updated_at}, empty if not set."""
    return load().get(platform, {"notes": "", "updated_at": ""})


def set_notes(platform: str, notes: str) -> dict:
    """
    Replace the notes for one platform. Stamps updated_at. Returns
    the saved entry (no secrets — just notes + timestamp).
    """
    if platform not in _ALLOWED_PLATFORMS:
        raise ValueError(
            f"Unknown platform {platform!r}. Allowed: {_ALLOWED_PLATFORMS}"
        )
    data = load()
    data[platform] = {
        "notes":      (notes or "")[:MAX_NOTES_LEN],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save(data)
    return data[platform]
