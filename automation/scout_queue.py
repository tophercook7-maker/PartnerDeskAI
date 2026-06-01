"""
scout_queue.py
--------------
Logan Lead Scout Queue (v7.28). Local-only capture + qualification
queue for businesses Topher spots that may need a website, web
cleanup, digital business card, tap hub, or AI/business systems.

Mirrors the leads.py pattern: backed by data/scout_queue.json, atomic
writes via tempfile + os.replace, whitelist + clamp on every save,
unknown fields silently dropped.

NO scraping. NO outreach. NO OpenAI. The "convert" helper just copies
a row into the existing leads.py registry — it does not send anything.

Schema per row:
    {
      "id":              "<timestamp string>",
      "business_name":   str (required),
      "category":        str,
      "city_state":      str,
      "contact_email":   str,
      "contact_source":  str,
      "website_status":  str,
      "evidence":        str,
      "offer_angle":     str,
      "priority":        "low" | "medium" | "high",
      "status":          "new" | "qualified" | "contacted" |
                         "follow_up" | "converted" | "rejected",
      "notes":           str,
      "converted_lead_id": str | None,  # set when convert() runs
      "created_at":      "YYYY-MM-DD HH:MM:SS",
      "updated_at":      "YYYY-MM-DD HH:MM:SS",
    }
"""

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile
import time

import leads as leads_mod


ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = ROOT / "data" / "scout_queue.json"

ALLOWED_STATUSES = (
    "new", "qualified", "contacted", "follow_up", "converted", "rejected",
)
ALLOWED_PRIORITIES = ("low", "medium", "high")
DEFAULT_STATUS = "new"
DEFAULT_PRIORITY = "medium"
DEFAULT_WEBSITE_STATUS = "no website found"

MAX_NAME_LEN    = 200
MAX_CATEGORY    = 100
MAX_CITY_LEN    = 100
MAX_EMAIL_LEN   = 200
MAX_SOURCE_LEN  = 500
MAX_STATUS_LEN  = 200
MAX_EVIDENCE    = 2000
MAX_OFFER_LEN   = 500
MAX_NOTES_LEN   = 4000


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(items: list[dict]) -> str:
    """Same monotonic-timestamp pattern as leads._next_id."""
    base = str(int(time.time() * 1000))
    existing = {it.get("id") for it in items}
    cand = base
    n = 0
    while cand in existing:
        n += 1
        cand = f"{base}-{n}"
    return cand


def _clean(raw: dict, existing: dict | None = None) -> dict:
    """Whitelist + clamp + validate. Unknown keys dropped."""
    if not isinstance(raw, dict):
        raise ValueError("scout lead must be a dict")
    ex = existing or {}
    name = str(raw.get("business_name") or ex.get("business_name") or "").strip()
    if not name:
        raise ValueError("business_name is required")

    status = (raw.get("status") or ex.get("status") or DEFAULT_STATUS).strip()
    if status not in ALLOWED_STATUSES:
        raise ValueError(
            f"status must be one of {ALLOWED_STATUSES}, got {status!r}"
        )
    priority = (raw.get("priority") or ex.get("priority") or DEFAULT_PRIORITY).strip()
    if priority not in ALLOWED_PRIORITIES:
        raise ValueError(
            f"priority must be one of {ALLOWED_PRIORITIES}, got {priority!r}"
        )

    # Distinguish "not in raw" vs "explicit None" for converted_lead_id
    # (cleared on un-convert), mirroring the v7.0 _pick pattern.
    def _pick(key):
        if key in raw:
            return raw[key]
        return ex.get(key)

    return {
        "id":              ex.get("id") or raw.get("id"),
        "business_name":   name[:MAX_NAME_LEN],
        "category":        str(raw.get("category")       or ex.get("category")       or "").strip()[:MAX_CATEGORY],
        "city_state":      str(raw.get("city_state")     or ex.get("city_state")     or "").strip()[:MAX_CITY_LEN],
        "contact_email":   str(raw.get("contact_email")  or ex.get("contact_email")  or "").strip()[:MAX_EMAIL_LEN],
        "contact_source":  str(raw.get("contact_source") or ex.get("contact_source") or "").strip()[:MAX_SOURCE_LEN],
        "website_status":  str(raw.get("website_status") or ex.get("website_status") or DEFAULT_WEBSITE_STATUS).strip()[:MAX_STATUS_LEN],
        "evidence":        str(raw.get("evidence")       or ex.get("evidence")       or "")[:MAX_EVIDENCE],
        "offer_angle":     str(raw.get("offer_angle")    or ex.get("offer_angle")    or "").strip()[:MAX_OFFER_LEN],
        "priority":        priority,
        "status":          status,
        "notes":           str(raw.get("notes")          or ex.get("notes")          or "")[:MAX_NOTES_LEN],
        "converted_lead_id": _pick("converted_lead_id"),
        "created_at":      ex.get("created_at") or _now(),
        "updated_at":      _now(),
    }


def load() -> list[dict]:
    """Read the queue. Returns [] on missing/corrupt file. Defensively
    setdefaults the converted_lead_id field on pre-v7.28 rows (there
    won't be any, but the pattern keeps load() resilient to future
    field additions)."""
    if not QUEUE_PATH.is_file():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, dict):
            item.setdefault("converted_lead_id", None)
    return items


def _save(items: list[dict]) -> None:
    """Atomic write of the full queue."""
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".scout_queue.", suffix=".tmp", dir=str(QUEUE_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"items": items}, f, indent=2)
            f.write("\n")
        os.replace(tmp, QUEUE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(raw: dict) -> dict:
    """Append a new scout lead."""
    cleaned = _clean(raw)
    items = load()
    cleaned["id"] = _next_id(items)
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    items.append(cleaned)
    _save(items)
    return cleaned


def update(scout_id: str, raw: dict) -> dict:
    """Update an existing scout lead. KeyError if not found."""
    items = load()
    for i, it in enumerate(items):
        if it.get("id") == scout_id:
            merged = _clean(raw, existing=it)
            merged["id"] = scout_id
            items[i] = merged
            _save(items)
            return merged
    raise KeyError(scout_id)


def delete(scout_id: str) -> bool:
    """Remove a scout lead. Returns True iff something was removed."""
    items = load()
    before = len(items)
    items = [it for it in items if it.get("id") != scout_id]
    if len(items) == before:
        return False
    _save(items)
    return True


def _find(scout_id: str) -> dict:
    for it in load():
        if it.get("id") == scout_id:
            return it
    raise KeyError(scout_id)


def convert(scout_id: str) -> dict:
    """
    Copy a scout lead into the existing leads.py registry as a normal
    cold lead, then mark the scout row as 'converted' with a back-
    reference to the new lead id. Returns {scout, lead}.

    Local-only: writes to data/leads.json and data/scout_queue.json.
    NO external calls, NO outreach.
    """
    scout = _find(scout_id)
    if scout.get("status") == "converted":
        raise ValueError(
            f"scout lead {scout_id!r} is already converted "
            f"(see converted_lead_id={scout.get('converted_lead_id')!r})"
        )
    # Build the Logan-lead row. Compose company from category + city
    # so the lead card carries the most useful contextual hint without
    # cramming everything into one field.
    bits = [scout.get("category"), scout.get("city_state")]
    company = " — ".join(b for b in bits if b)
    # Notes carry the scout evidence + offer angle so the Logan card
    # has the full pitch context attached.
    notes_lines = []
    if scout.get("notes"):
        notes_lines.append(scout["notes"])
    if scout.get("evidence"):
        notes_lines.append(f"Scout evidence: {scout['evidence']}")
    if scout.get("offer_angle"):
        notes_lines.append(f"Offer angle: {scout['offer_angle']}")
    if scout.get("website_status"):
        notes_lines.append(f"Website status: {scout['website_status']}")
    composed_notes = "\n\n".join(notes_lines)
    source_bits = ["scout_queue"]
    if scout.get("contact_source"):
        source_bits.append(scout["contact_source"])
    source = ": ".join(source_bits)
    # contact_email isn't a LinkedIn handle but stash it in the handle
    # field if no other handle source is available — preserves the
    # contact info on the converted lead.
    new_lead = leads_mod.add({
        "name":    scout.get("business_name") or "Unnamed business",
        "company": company,
        "handle":  scout.get("contact_email") or "",
        "source":  source,
        "status":  "cold",
        "notes":   composed_notes,
    })
    # Mark the scout row converted with a back-reference.
    updated_scout = update(scout_id, {
        "status": "converted",
        "converted_lead_id": new_lead["id"],
    })
    return {"scout": updated_scout, "lead": new_lead}
