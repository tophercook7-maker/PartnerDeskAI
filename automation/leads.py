"""
leads.py
--------
Outbound prospect tracker (CRM-lite). Pure local storage — no network
calls, no LinkedIn API, no auto-sync. Backed by data/leads.json with
atomic writes via tempfile + os.replace.

Schema for a single lead:
    {
      "id":         "<numeric string, monotonic>",
      "name":       "...",                # required, ≤200 chars
      "company":    "...",                # optional, ≤200 chars
      "handle":     "...",                # optional, ≤500 chars (URL etc.)
      "source":     "...",                # optional, ≤500 chars
      "status":     "cold|warm|hot|closed|dropped",
      "notes":      "...",                # optional, ≤MAX_NOTES_LEN chars
      "created_at": "YYYY-MM-DD HH:MM:SS",
      "updated_at": "YYYY-MM-DD HH:MM:SS",
    }

Safety:
    - data/leads.json is GITIGNORED — never leaves the local machine
      via git.
    - No tokens / credentials stored. Field whitelist + length caps
      enforced on every write.
    - Unknown fields silently dropped on save (defense against schema
      drift / malicious input).
    - Status whitelisted to a known enum.
"""

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
LEADS_PATH = ROOT / "data" / "leads.json"

ALLOWED_STATUSES = ("cold", "warm", "hot", "closed", "dropped")
DEFAULT_STATUS = "cold"

MAX_NAME_LEN    = 200
MAX_COMPANY_LEN = 200
MAX_HANDLE_LEN  = 500
MAX_SOURCE_LEN  = 500
MAX_NOTES_LEN   = 4000


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(leads: list[dict]) -> str:
    """Monotonic timestamp-based id. Single-user app — collisions are
    effectively impossible at millisecond resolution; we still guard
    with a deduplication check against existing ids."""
    base = str(int(time.time() * 1000))
    existing = {l.get("id") for l in leads}
    cand = base
    n = 0
    while cand in existing:
        n += 1
        cand = f"{base}-{n}"
    return cand


def _clean_lead(raw: dict, existing: dict | None = None) -> dict:
    """
    Whitelist + clamp a single lead dict. `existing` is the prior
    state of the row (for updates) so we can preserve created_at /
    id when the user doesn't supply them. Unknown keys are dropped.
    """
    if not isinstance(raw, dict):
        raise ValueError("lead must be a dict")
    name = str(raw.get("name") or (existing or {}).get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    status = (raw.get("status") or (existing or {}).get("status") or DEFAULT_STATUS).strip()
    if status not in ALLOWED_STATUSES:
        raise ValueError(
            f"status must be one of {ALLOWED_STATUSES}, got {status!r}"
        )
    return {
        "id":         (existing or {}).get("id") or raw.get("id"),
        "name":       name[:MAX_NAME_LEN],
        "company":    str(raw.get("company") or (existing or {}).get("company") or "").strip()[:MAX_COMPANY_LEN],
        "handle":     str(raw.get("handle")  or (existing or {}).get("handle")  or "").strip()[:MAX_HANDLE_LEN],
        "source":     str(raw.get("source")  or (existing or {}).get("source")  or "").strip()[:MAX_SOURCE_LEN],
        "status":     status,
        "notes":      str(raw.get("notes")   or (existing or {}).get("notes")   or "")[:MAX_NOTES_LEN],
        "created_at": (existing or {}).get("created_at") or _now(),
        "updated_at": _now(),
    }


def load() -> list[dict]:
    """Return the full leads list, or [] if file missing/corrupt."""
    if not LEADS_PATH.is_file():
        return []
    try:
        data = json.loads(LEADS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("leads")
    return items if isinstance(items, list) else []


def _save(leads: list[dict]) -> None:
    """Atomic write of the full leads list."""
    LEADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".leads.", suffix=".tmp", dir=str(LEADS_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"leads": leads}, f, indent=2)
            f.write("\n")
        os.replace(tmp, LEADS_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(raw: dict) -> dict:
    """Append a new lead. Returns the saved row (with id, timestamps)."""
    cleaned = _clean_lead(raw)
    cleaned["id"] = _next_id(load())
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    leads = load()
    leads.append(cleaned)
    _save(leads)
    return cleaned


def update(lead_id: str, raw: dict) -> dict:
    """Update one lead. Raises KeyError if not found."""
    leads = load()
    for i, l in enumerate(leads):
        if l.get("id") == lead_id:
            merged = _clean_lead(raw, existing=l)
            merged["id"] = lead_id  # never let the caller change the id
            leads[i] = merged
            _save(leads)
            return merged
    raise KeyError(lead_id)


def delete(lead_id: str) -> bool:
    """Remove a lead. Returns True iff something was removed."""
    leads = load()
    before = len(leads)
    leads = [l for l in leads if l.get("id") != lead_id]
    if len(leads) == before:
        return False
    _save(leads)
    return True
