"""
lead_candidates.py
------------------
Logan Lead Candidate Queue (v8.8). Reviewable possible-leads queue
sitting between missions and the Logan leads registry.

Honest framing: this is NOT a scraper. Logan generates candidate
*stubs* — one row per prospective business — pre-scoped to a
category/area/web-status target, each with its own targeted Google
search URL. The user opens the search, finds a real business, fills
the candidate's fields, and the score updates automatically. Once
the candidate scores Hot or Warm, it can be approved + converted
into a Logan lead.

Backed by data/lead_candidates.json (gitignored). Local-only writes.
NO scraping. NO paid APIs. NO automated outreach. The convert path
creates a v8.4 lead with outreach_status='not_started' so the user
still has to click Prepare Outreach manually.

Schema per row:
    {
      "id":                 "<timestamp string>",
      "business_name":      str,
      "category":           str (required),
      "city_state":         str (required),
      "website_url":        str,
      "website_status":     str (enum hint, freeform OK),
      "email":              str,
      "phone":              str,
      "source_url":         str,
      "search_url":         str,   # Google search seed for this stub
      "evidence_notes":     str,
      "suggested_offer_angle": str,
      "is_local_service":   bool | None,
      "is_active":          bool | None,
      "is_corporate":       bool | None,
      "score":              int,    # computed from the booleans + fields
      "confidence":         "Hot"|"Warm"|"Research"|"Reject",
      "approval_status":    "pending"|"approved"|"rejected"|"needs_research"|"converted",
      "converted_lead_id":  str | None,
      "notes":              str,
      "created_at":         "YYYY-MM-DD HH:MM:SS",
      "updated_at":         "YYYY-MM-DD HH:MM:SS",
    }
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
import json
import os
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "data" / "lead_candidates.json"

ALLOWED_APPROVAL = ("pending", "approved", "rejected", "needs_research", "converted")
ALLOWED_CONFIDENCE = ("Hot", "Warm", "Research", "Reject")
DEFAULT_APPROVAL = "pending"

ALLOWED_WEBSITE_STATUS = (
    "no website found", "weak web presence", "has website but needs cleanup",
    "has website (good)", "any local business",
)

MAX_NAME       = 200
MAX_CATEGORY   = 100
MAX_CITY       = 100
MAX_URL        = 1000
MAX_STATUS     = 200
MAX_EMAIL      = 200
MAX_PHONE      = 60
MAX_NOTES      = 4000
MAX_EVIDENCE   = 2000
MAX_OFFER      = 500

MAX_FIND_COUNT = 25  # per "Find Leads For Me" call

# Search-template variants — same shape as missions, one per candidate stub.
_QUERY_TEMPLATES = [
    '"{cat}" "{city}" "gmail.com"',
    '"{cat}" "{city}" "facebook.com/" -site:yelp.com',
    '"{cat}" "{city}" "no website"',
    '"{cat}" "{city}" -site:yelp.com -site:angi.com',
    '"{cat}" "{city}" "find us on facebook"',
    '"{cat}" "{city}" "call or text"',
    '"local {cat}" "{city}" "phone"',
    '"{cat}" "{city}" inurl:facebook.com',
    '"{cat}" "{city}" "free estimate" "gmail.com"',
    '"{cat}" "{city}" "instagram.com/" -site:yelp.com',
]

# Per-target offer-angle templates (reuse pattern from lead_missions.py).
_OFFER_FOR_TARGET = {
    "no website found":
        "Simple one-page site + Google Business Profile setup. Pay-once, no subscription.",
    "weak web presence":
        "Website cleanup pass — faster load, mobile layout, refreshed copy. Pay once.",
    "any local business":
        "Tap hub + simple one-page website. Pay once, no subscription.",
}
_GENERIC_OFFER = "Tap hub + simple one-page website. Pay once, no subscription."


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(items: list[dict]) -> str:
    base = str(int(time.time() * 1000))
    existing = {it.get("id") for it in items}
    cand = base
    n = 0
    while cand in existing:
        n += 1
        cand = f"{base}-{n}"
    return cand


# --- Scoring (spec rules verbatim) ------------------------------------

def compute_score(c: dict) -> tuple[int, str]:
    """
    Return (score, confidence) per the v8.8 spec rules.
      +3 no website found
      +2 weak web presence
      +2 email found
      +1 phone found
      +1 local service business
      +1 active recent posts/reviews
      -3 corporate/franchise
      -2 no contact info
      -2 inactive/closed

    Labels:
      8+   → Hot
      5–7  → Warm
      1–4  → Research
      ≤ 0  → Reject
    """
    s = 0
    ws = (c.get("website_status") or "").strip().lower()
    if ws == "no website found":
        s += 3
    if ws == "weak web presence":
        s += 2
    email = (c.get("email") or "").strip()
    phone = (c.get("phone") or "").strip()
    if email:
        s += 2
    if phone:
        s += 1
    if c.get("is_local_service") is True:
        s += 1
    if c.get("is_active") is True:
        s += 1
    if c.get("is_corporate") is True:
        s -= 3
    # "no contact info"  → no email AND no phone
    if not email and not phone:
        s -= 2
    # "inactive/closed"  → explicit is_active=False
    if c.get("is_active") is False:
        s -= 2

    if s >= 8:
        label = "Hot"
    elif s >= 5:
        label = "Warm"
    elif s >= 1:
        label = "Research"
    else:
        label = "Reject"
    return s, label


# --- CRUD -------------------------------------------------------------

def load() -> list[dict]:
    if not CANDIDATES_PATH.is_file():
        return []
    try:
        data = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    # Setdefault new-ish fields so legacy rows don't crash the renderer.
    for it in items:
        if isinstance(it, dict):
            it.setdefault("converted_lead_id", None)
    return items


def _save(items: list[dict]) -> None:
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".lead_candidates.", suffix=".tmp", dir=str(CANDIDATES_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"items": items}, f, indent=2)
            f.write("\n")
        os.replace(tmp, CANDIDATES_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def _norm_bool(v):
    """Accept JSON-ish truthy/falsey, return True/False/None."""
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "y", "1"):  return True
        if s in ("false", "no", "n", "0"):  return False
        if s == "":                         return None
    return None


def _clean(raw: dict, existing: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("candidate must be a dict")
    ex = existing or {}
    category = str(raw.get("category") or ex.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    city = str(raw.get("city_state") or ex.get("city_state") or "").strip()
    if not city:
        raise ValueError("city_state is required")
    approval = (raw.get("approval_status") or ex.get("approval_status") or DEFAULT_APPROVAL).strip()
    if approval not in ALLOWED_APPROVAL:
        raise ValueError(
            f"approval_status must be one of {ALLOWED_APPROVAL}, got {approval!r}"
        )

    # Picker that distinguishes "missing" from "explicit clear".
    def _pick(key):
        if key in raw:
            return raw[key]
        return ex.get(key)

    merged = {
        "id":                ex.get("id") or raw.get("id"),
        "business_name":     str(_pick("business_name") or "").strip()[:MAX_NAME],
        "category":          category[:MAX_CATEGORY],
        "city_state":        city[:MAX_CITY],
        "website_url":       str(_pick("website_url") or "").strip()[:MAX_URL],
        "website_status":    str(_pick("website_status") or "").strip()[:MAX_STATUS],
        "email":             str(_pick("email") or "").strip()[:MAX_EMAIL],
        "phone":             str(_pick("phone") or "").strip()[:MAX_PHONE],
        "source_url":        str(_pick("source_url") or "").strip()[:MAX_URL],
        "search_url":        str(_pick("search_url") or "").strip()[:MAX_URL],
        "evidence_notes":    str(_pick("evidence_notes") or "")[:MAX_EVIDENCE],
        "suggested_offer_angle": str(_pick("suggested_offer_angle") or "").strip()[:MAX_OFFER],
        "is_local_service":  _norm_bool(_pick("is_local_service")),
        "is_active":         _norm_bool(_pick("is_active")),
        "is_corporate":      _norm_bool(_pick("is_corporate")),
        "approval_status":   approval,
        "converted_lead_id": _pick("converted_lead_id"),
        "notes":             str(_pick("notes") or "")[:MAX_NOTES],
        "created_at":        ex.get("created_at") or _now(),
        "updated_at":        _now(),
    }
    score, label = compute_score(merged)
    merged["score"] = score
    merged["confidence"] = label
    return merged


def add(raw: dict) -> dict:
    items = load()
    cleaned = _clean(raw)
    cleaned["id"] = _next_id(items)
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    items.append(cleaned)
    _save(items)
    return cleaned


def update(cid: str, raw: dict) -> dict:
    items = load()
    for i, it in enumerate(items):
        if it.get("id") == cid:
            merged = _clean(raw, existing=it)
            merged["id"] = cid
            items[i] = merged
            _save(items)
            return merged
    raise KeyError(cid)


def delete(cid: str) -> bool:
    items = load()
    before = len(items)
    items = [it for it in items if it.get("id") != cid]
    if len(items) == before:
        return False
    _save(items)
    return True


def _find(cid: str) -> dict:
    for it in load():
        if it.get("id") == cid:
            return it
    raise KeyError(cid)


# --- "Find Leads For Me" — generate candidate stubs --------------------

def find_for_me(
    category: str,
    city_state: str,
    count: int = 10,
    website_status_target: str = "no website found",
) -> list[dict]:
    """
    Create N candidate stubs scoped to (category, city_state). Each
    stub is one prospective business slot, with its own targeted
    Google search URL the user opens to find a real business and
    fill the candidate's fields.

    NOT a scraper. NOT a paid API. The stubs are blank business-name
    slots, pre-scored as Research (no contact info yet), ready for
    the user to populate.
    """
    category = (category or "").strip()
    city_state = (city_state or "").strip()
    if not category or not city_state:
        raise ValueError("category and city_state are required")
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > MAX_FIND_COUNT:
        raise ValueError(
            f"count {count} exceeds limit of {MAX_FIND_COUNT}"
        )
    target = (website_status_target or "").strip() or "no website found"
    offer = _OFFER_FOR_TARGET.get(target, _GENERIC_OFFER)
    items = load()
    new_rows: list[dict] = []
    for i in range(count):
        tmpl = _QUERY_TEMPLATES[i % len(_QUERY_TEMPLATES)]
        query = tmpl.format(cat=category, city=city_state)
        url = "https://www.google.com/search?q=" + quote_plus(query)
        # The target hints at a starting website_status — Hot when no
        # site, Warm when weak — so freshly-generated stubs land in
        # the right bucket once the user fills the contact info.
        starting_ws = target if target in ALLOWED_WEBSITE_STATUS else ""
        cleaned = _clean({
            "business_name":          "",
            "category":               category,
            "city_state":             city_state,
            "website_status":         starting_ws,
            "search_url":             url,
            "source_url":             url,
            "suggested_offer_angle":  offer,
            "is_local_service":       True,  # generous default; user can flip
        })
        cleaned["id"] = _next_id(items + new_rows)
        cleaned["created_at"] = _now()
        cleaned["updated_at"] = cleaned["created_at"]
        new_rows.append(cleaned)
    if new_rows:
        items.extend(new_rows)
        _save(items)
    return new_rows


# --- v8.9: Discover via OpenStreetMap Overpass ------------------------

import overpass_discovery as _overpass_mod  # one outbound HTTPS POST per call


def discover_via_overpass(
    category: str,
    city_state: str,
    count: int = 10,
    website_status_target: str = "any local business",
) -> dict:
    """
    Logan asks OpenStreetMap (via the public Overpass API) for real
    local businesses matching (category, city_state) and queues them
    as pending candidates for Topher to review.

    - One read-only HTTPS POST to overpass-api.de per call.
    - No auth, no key, no paid plan, no scraping.
    - Dedupes against existing candidates by (lowered name, lowered city_state)
      so re-running the same query is idempotent.
    - Returns however many OSM actually had, up to count. Never pads.
    - Candidates land with approval_status='pending' — Topher still
      approves + converts manually before anything outbound happens.

    Returns: {added: [rows], added_count, found, skipped_duplicates, message}
    """
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > MAX_FIND_COUNT:
        raise ValueError(
            f"count {count} exceeds limit of {MAX_FIND_COUNT}"
        )
    result = _overpass_mod.discover(
        category=category,
        city_state=city_state,
        count=count,
        website_status_target=website_status_target,
    )
    items = load()
    existing_keys = {
        ((it.get("business_name") or "").strip().lower(),
         (it.get("city_state") or "").strip().lower())
        for it in items
    }
    added: list[dict] = []
    skipped_duplicates = 0
    for cand in result["candidates"]:
        key = (cand["business_name"].strip().lower(),
               cand["city_state"].strip().lower())
        if key in existing_keys:
            skipped_duplicates += 1
            continue
        existing_keys.add(key)
        cleaned = _clean(cand)
        cleaned["id"] = _next_id(items + added)
        cleaned["created_at"] = _now()
        cleaned["updated_at"] = cleaned["created_at"]
        added.append(cleaned)
    if added:
        items.extend(added)
        _save(items)
    return {
        "added":              added,
        "added_count":        len(added),
        "found":              result["total_found"],
        "skipped_duplicates": skipped_duplicates,
        "resolved_city":      result.get("resolved_city", ""),
        "resolved_state":     result.get("resolved_state", ""),
        "display_name":       result.get("display_name", ""),
        "message":            result["message"],
    }


# --- Approval / conversion --------------------------------------------

import leads as _leads_mod  # local-only, no network


def approve(cid: str) -> dict:
    return update(cid, {"approval_status": "approved"})


def reject(cid: str) -> dict:
    return update(cid, {"approval_status": "rejected"})


def needs_research(cid: str) -> dict:
    return update(cid, {"approval_status": "needs_research"})


def convert(cid: str) -> dict:
    """
    Convert an approved candidate into a Logan lead. The candidate
    must have business_name set (we don't create leads with empty
    names). Status flips to 'converted' with a back-reference. Returns
    {candidate, lead}.

    The new lead's outreach_status is 'not_started' so the user still
    has to click Prepare Outreach manually — no shortcuts to outbound.
    """
    cand = _find(cid)
    if (cand.get("approval_status") or "") == "converted":
        raise ValueError(
            f"candidate {cid!r} already converted to lead {cand.get('converted_lead_id')!r}"
        )
    business_name = (cand.get("business_name") or "").strip()
    if not business_name:
        raise ValueError("candidate has no business_name — cannot convert")

    notes_lines = []
    if cand.get("evidence_notes"): notes_lines.append(cand["evidence_notes"])
    if cand.get("phone"):          notes_lines.append(f"Phone: {cand['phone']}")
    if cand.get("website_url"):    notes_lines.append(f"Website: {cand['website_url']}")
    notes = "\n\n".join(notes_lines)

    new_lead = _leads_mod.add({
        "name":           business_name[:200],
        "company":        f"{cand['category']} — {cand['city_state']}".strip(" —"),
        "email":          (cand.get("email") or "")[:200],
        "source":         "Logan",
        "source_url":     (cand.get("source_url") or cand.get("search_url") or "")[:1000],
        "status":         "cold",
        "notes":          notes[:4000],
        "evidence":       (cand.get("evidence_notes") or "")[:2000],
        "offer_angle":    (cand.get("suggested_offer_angle") or "")[:500],
        "website_status": (cand.get("website_status") or "")[:200],
        # outreach_status stays at default 'not_started' — user clicks
        # Prepare Outreach manually after reviewing.
    })

    updated_cand = update(cid, {
        "approval_status":   "converted",
        "converted_lead_id": new_lead["id"],
    })
    return {"candidate": updated_cand, "lead": new_lead}


# --- Bulk actions -----------------------------------------------------

ALLOWED_BULK_ACTIONS = (
    "approve", "reject", "needs_research", "delete", "convert",
)


def bulk_action(action: str, ids: list[str]) -> dict:
    """
    Run `action` against a list of candidate ids. Returns
    {processed: [ids], skipped: [{id, reason}], leads: [new lead rows
    for convert action]}. Convert-action candidates without
    business_name are skipped with a reason.
    """
    if action not in ALLOWED_BULK_ACTIONS:
        raise ValueError(
            f"action must be one of {ALLOWED_BULK_ACTIONS}, got {action!r}"
        )
    if not isinstance(ids, list) or not ids:
        raise ValueError("ids must be a non-empty list")
    processed: list[str] = []
    skipped: list[dict] = []
    leads: list[dict] = []
    for cid in ids:
        try:
            if action == "approve":
                approve(cid); processed.append(cid)
            elif action == "reject":
                reject(cid); processed.append(cid)
            elif action == "needs_research":
                needs_research(cid); processed.append(cid)
            elif action == "delete":
                if delete(cid): processed.append(cid)
                else:          skipped.append({"id": cid, "reason": "not found"})
            elif action == "convert":
                result = convert(cid)
                processed.append(cid)
                leads.append(result["lead"])
        except (KeyError, ValueError) as e:
            skipped.append({"id": cid, "reason": str(e)})
    return {"processed": processed, "skipped": skipped, "leads": leads}
