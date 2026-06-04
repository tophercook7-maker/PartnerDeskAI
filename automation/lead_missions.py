"""
lead_missions.py
----------------
Logan Auto Lead Generator (v8.1). Produces local search MISSIONS —
not actual web fetches. Each mission carries a Google search query
string + URL that Topher opens manually; Logan never browses the web.

NO scraping. NO HTTP calls (outbound). NO OpenAI. NO browser
automation. Mirrors the scout_queue.py atomic-write + whitelist
pattern. Backed by data/lead_missions.json (gitignored).

Schema per row:
    {
      "id":                    "<timestamp string>",
      "category":              str (required),
      "city_state":            str (required),
      "search_query":          str (required),
      "search_url":            str (the rendered Google search URL),
      "look_for":              str (what to scan the SERP for),
      "offer_angle":           str (suggested pitch if a candidate is found),
      "priority":              "low" | "medium" | "high",
      "status":                "new" | "researching" | "found_lead" |
                               "skipped" | "done",
      "notes":                 str (free-form, set by the user),
      "website_status_target": str (the website-status signal the user is hunting for),
      "created_at":            "YYYY-MM-DD HH:MM:SS",
      "updated_at":            "YYYY-MM-DD HH:MM:SS",
    }
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
import json
import os
import re
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
MISSIONS_PATH = ROOT / "data" / "lead_missions.json"

ALLOWED_STATUSES = ("new", "researching", "found_lead", "outreach_ready", "skipped", "done")
ALLOWED_PRIORITIES = ("low", "medium", "high")
DEFAULT_STATUS = "new"
DEFAULT_PRIORITY = "medium"

MAX_CATEGORY    = 100
MAX_CITY_LEN    = 100
MAX_QUERY_LEN   = 500
MAX_URL_LEN     = 1000
MAX_LOOK_LEN    = 1000
MAX_OFFER_LEN   = 500
MAX_NOTES_LEN   = 4000
MAX_TARGET_LEN  = 200

MAX_GENERATE_COUNT = 25  # one form submit can't create more than this

# Template families. Each is a Python format string with {cat} and
# {city} placeholders, plus optional context. The generator picks
# templates in order, cycling if count > len(templates).
_QUERY_TEMPLATES = [
    '"{cat}" "gmail.com" "{city}"',
    '"{cat}" "gmail.com" "{city}" "facebook"',
    '"{cat}" "{city}" "no website"',
    '"{cat}" "{city}" -site:yelp.com -site:angi.com',
    '"{cat}" "{city}" "facebook.com/" -site:yelp.com',
    '"no website" "{cat}" "{city}"',
    '"{cat}" "{city}" "call or text"',
    '"{cat}" "{city}" "find us on facebook"',
    '"{cat}" "{city}" "instagram.com/" -site:yelp.com',
    '"{cat}" "{city}" "free estimate" "gmail.com"',
    '"local {cat}" "{city}" "phone"',
    '"{cat}" "{city}" inurl:facebook.com',
]

# What to scan the SERP for, keyed by website-status target. Falls back
# to the generic phrase when the target isn't recognised.
_LOOK_FOR = {
    "no website found":
        "Listings that show a business name + phone/email but NO website link. "
        "Facebook page, Google Maps card, or directory entry only.",
    "old or weak website":
        "Sites that load slow, look like a 2010 template, no mobile layout, "
        "expired SSL, or stale dates in the footer.",
    "facebook-only":
        "Businesses whose only web presence is a Facebook page. No domain, "
        "no Linktree, no own website.",
    "google listing only":
        "Businesses with a Google Maps card but no separate website. "
        "Often have an email but no domain.",
    "has email address":
        "Listings that expose a contact email (often gmail.com) but no website.",
}
_GENERIC_LOOK = (
    "Local service businesses that match the category and lack a real website "
    "or have a weak/outdated one. Capture name + email if visible."
)

# Suggested offer angles for each website-status target.
_OFFER_ANGLES = {
    "no website found":
        "Simple one-page site + Google Business Profile setup. Pay-once, no subscription.",
    "old or weak website":
        "Website cleanup pass: faster load, mobile layout, refreshed copy, "
        "still pay-once.",
    "facebook-only":
        "Lightweight website that backs up their Facebook presence with a "
        "real domain. Tap hub or digital business card for in-person handoffs.",
    "google listing only":
        "Real website to anchor their Google Maps card. Optional tap hub for "
        "service vehicle / counter use.",
    "has email address":
        "Tap hub + digital business card so the business looks more credible "
        "next time the email lands.",
}
_GENERIC_OFFER = "Tap hub + simple one-page website. Pay once, no subscription."

# Priority hints by template / target combination. Defaults to medium.
_HIGH_PRIO_TARGETS = ("no website found", "facebook-only")
_HIGH_PRIO_HINTS   = ("no website", "facebook")  # in the query


# --- v8.7: richer mission content -------------------------------------
# Each mission gets a long-form Target line, an evidence-collection
# checklist, a suggested first-message angle, and a "next action"
# instruction. Templates substitute {category} and {city_state}.

_TARGET_TMPL = "{category} in {city_state} with weak or missing websites."

_EVIDENCE_TMPL = """- Gmail/Yahoo/Outlook email instead of a domain email
- Facebook page but no website link
- Google listing with phone but no website
- Directory listing only
- Recent reviews/photos showing the business is active
- No clear online menu, order link, booking/contact page, or hours page"""

_FIRST_MESSAGE_TMPL = (
    "I noticed your shop shows up locally, but it looks like customers "
    "may not have a simple website link to check hours, menu, photos, "
    "and contact info from their phone."
)

_NEXT_ACTION_TMPL = (
    "Open the search, find one qualified business, collect business "
    "name + contact info + evidence, then convert it into a Logan lead."
)

# Category → emoji-style badge. Falls back to a generic icon when the
# category isn't in the map. Keeps the UI scannable without an image
# asset pipeline.
CATEGORY_ICONS = {
    "coffee shops":     "☕",
    "cafe":             "☕",
    "restaurant":       "🍽️",
    "food truck":       "🌮",
    "landscaping":      "🌿",
    "lawn care":        "🌱",
    "pressure washing": "💦",
    "handyman":         "🔧",
    "auto detailing":   "🚗",
    "cleaners":         "🧹",
    "plumber":          "🚰",
    "salon":            "✂️",
    "barber":           "✂️",
    "pet groomer":      "🐾",
    "church":           "⛪",
    "photographer":     "📷",
    "roofing":          "🏠",
}


def _category_icon(category: str) -> str:
    if not category:
        return "📋"
    cat = category.strip().lower()
    if cat in CATEGORY_ICONS:
        return CATEGORY_ICONS[cat]
    # Try a loose contains-match for plurals / variations.
    for key, icon in CATEGORY_ICONS.items():
        if key in cat or cat in key:
            return icon
    return "📋"


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


def _clean(raw: dict, existing: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("mission must be a dict")
    ex = existing or {}
    category = str(raw.get("category") or ex.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    city = str(raw.get("city_state") or ex.get("city_state") or "").strip()
    if not city:
        raise ValueError("city_state is required")
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
    # v8.7: richer-content fields. Captured_lead is the mini-form data
    # snapshot from the Lead Found stage; preserved through PUT updates
    # via _pick so explicit None clears it.
    def _pick(key):
        if key in raw:
            return raw[key]
        return ex.get(key)
    captured = _pick("captured_lead")
    if captured is not None and not isinstance(captured, dict):
        captured = None
    return {
        "id":              ex.get("id") or raw.get("id"),
        "category":        category[:MAX_CATEGORY],
        "city_state":      city[:MAX_CITY_LEN],
        "search_query":    str(raw.get("search_query") or ex.get("search_query") or "")[:MAX_QUERY_LEN],
        "search_url":      str(raw.get("search_url")   or ex.get("search_url")   or "")[:MAX_URL_LEN],
        "look_for":        str(raw.get("look_for")     or ex.get("look_for")     or "")[:MAX_LOOK_LEN],
        "offer_angle":     str(raw.get("offer_angle")  or ex.get("offer_angle")  or "")[:MAX_OFFER_LEN],
        "priority":        priority,
        "status":          status,
        "notes":           str(raw.get("notes")        or ex.get("notes")        or "")[:MAX_NOTES_LEN],
        "website_status_target": str(raw.get("website_status_target") or ex.get("website_status_target") or "")[:MAX_TARGET_LEN],
        # v8.7 richer fields
        "target":          str(raw.get("target")               or ex.get("target")               or "")[:500],
        "evidence_template":str(raw.get("evidence_template")    or ex.get("evidence_template")    or "")[:2000],
        "first_message_angle":str(raw.get("first_message_angle") or ex.get("first_message_angle") or "")[:1000],
        "next_action":     str(raw.get("next_action")          or ex.get("next_action")          or "")[:500],
        "captured_lead":   captured,
        "created_at":      ex.get("created_at") or _now(),
        "updated_at":      _now(),
    }


def load() -> list[dict]:
    if not MISSIONS_PATH.is_file():
        return []
    try:
        data = json.loads(MISSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    # v8.7: setdefault the new richer fields on legacy rows so the
    # frontend can read them without crashes.
    for item in items:
        if isinstance(item, dict):
            item.setdefault("target",              "")
            item.setdefault("evidence_template",   "")
            item.setdefault("first_message_angle", "")
            item.setdefault("next_action",         "")
            item.setdefault("captured_lead",       None)
    return items


def _save(items: list[dict]) -> None:
    MISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".lead_missions.", suffix=".tmp", dir=str(MISSIONS_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"items": items}, f, indent=2)
            f.write("\n")
        os.replace(tmp, MISSIONS_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def update(mission_id: str, raw: dict) -> dict:
    items = load()
    for i, it in enumerate(items):
        if it.get("id") == mission_id:
            merged = _clean(raw, existing=it)
            merged["id"] = mission_id
            items[i] = merged
            _save(items)
            return merged
    raise KeyError(mission_id)


def delete(mission_id: str) -> bool:
    items = load()
    before = len(items)
    items = [it for it in items if it.get("id") != mission_id]
    if len(items) == before:
        return False
    _save(items)
    return True


# --- v8.1: generation -------------------------------------------------

def _pick_priority(query: str, target: str) -> str:
    """High-priority signals: explicit 'no website' in the query or
    targets we know convert better."""
    if target in _HIGH_PRIO_TARGETS:
        return "high"
    q = query.lower()
    if any(h in q for h in _HIGH_PRIO_HINTS):
        return "high"
    return DEFAULT_PRIORITY


def generate(
    category: str,
    city_state: str,
    count: int = 5,
    website_status_target: str = "no website found",
) -> list[dict]:
    """
    Generate `count` search missions for (category, city_state). Each
    mission gets a search query, a Google search URL, a "look for" tip,
    and a suggested offer angle. Saved atomically; returns the new rows.

    NO outbound network. NO scraping. Pure string formatting + URL
    encoding.
    """
    category = (category or "").strip()
    city_state = (city_state or "").strip()
    if not category or not city_state:
        raise ValueError("category and city_state are required")
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > MAX_GENERATE_COUNT:
        raise ValueError(
            f"count {count} exceeds limit of {MAX_GENERATE_COUNT}"
        )
    target = (website_status_target or "").strip() or "no website found"

    items = load()
    look_for    = _LOOK_FOR.get(target, _GENERIC_LOOK)
    offer_angle = _OFFER_ANGLES.get(target, _GENERIC_OFFER)
    # v8.7: each mission now carries a long-form Target line, a multi-
    # bullet evidence template, a suggested first-message angle, and a
    # next-action instruction. All editable per-row via PUT.
    target_line     = _TARGET_TMPL.format(category=category, city_state=city_state)
    evidence_tmpl   = _EVIDENCE_TMPL
    first_message   = _FIRST_MESSAGE_TMPL
    next_action     = _NEXT_ACTION_TMPL
    new_rows: list[dict] = []
    for i in range(count):
        tmpl = _QUERY_TEMPLATES[i % len(_QUERY_TEMPLATES)]
        query = tmpl.format(cat=category, city=city_state)
        url   = "https://www.google.com/search?q=" + quote_plus(query)
        cleaned = _clean({
            "category":              category,
            "city_state":            city_state,
            "search_query":          query,
            "search_url":            url,
            "look_for":              look_for,
            "offer_angle":           offer_angle,
            "priority":              _pick_priority(query, target),
            "status":                DEFAULT_STATUS,
            "website_status_target": target,
            "target":                target_line,
            "evidence_template":     evidence_tmpl,
            "first_message_angle":   first_message,
            "next_action":           next_action,
        })
        cleaned["id"] = _next_id(items + new_rows)
        cleaned["created_at"] = _now()
        cleaned["updated_at"] = cleaned["created_at"]
        new_rows.append(cleaned)

    if new_rows:
        items.extend(new_rows)
        _save(items)
    return new_rows


# --- v8.7: convert mission → Logan lead --------------------------------

import leads as _leads_mod  # local-only; no network


def _find(mission_id: str) -> dict:
    for it in load():
        if it.get("id") == mission_id:
            return it
    raise KeyError(mission_id)


def convert_to_lead(mission_id: str, captured: dict | None = None) -> dict:
    """
    Promote a mission into a Logan lead. The captured payload (from the
    Lead Found mini-form) overrides any previously-stored capture on
    the mission. After creating the lead, the mission status flips to
    'outreach_ready' so the user knows it's ready for the v8.4 outreach
    pipeline. Returns {mission, lead}.

    Local-only — writes to data/lead_missions.json + data/leads.json.
    NO external calls.
    """
    mission = _find(mission_id)
    # Use the just-passed capture if provided, else fall back to the
    # row's stored captured_lead. business_name is required either way.
    cap = captured if isinstance(captured, dict) else (mission.get("captured_lead") or {})
    if not isinstance(cap, dict):
        cap = {}
    business_name = (cap.get("business_name") or "").strip()
    if not business_name:
        raise ValueError(
            "captured business_name is required to convert mission to a lead"
        )

    # Map mission + capture → leads.add() shape (v8.4 schema).
    notes_lines = []
    if cap.get("evidence_notes"):     notes_lines.append(cap["evidence_notes"])
    if cap.get("phone"):              notes_lines.append(f"Phone: {cap['phone']}")
    if cap.get("current_web_presence"): notes_lines.append(f"Web presence: {cap['current_web_presence']}")
    notes = "\n\n".join(notes_lines)

    new_lead = _leads_mod.add({
        "name":           business_name[:200],
        "company":        f"{mission.get('category','')} — {mission.get('city_state','')}".strip(" —"),
        "email":          (cap.get("contact_email") or "")[:200],
        "source":         "Logan",
        "source_url":     (cap.get("source_url") or mission.get("search_url") or "")[:1000],
        "status":         "cold",
        "notes":          notes[:4000],
        "evidence":       (cap.get("evidence_notes") or "")[:2000],
        "offer_angle":    (mission.get("offer_angle") or "")[:500],
        "website_status": (cap.get("website_status") or mission.get("website_status_target") or "")[:200],
        # v8.4 outreach pipeline: leave at default not_started so the
        # user explicitly clicks Prepare Outreach when ready.
    })

    # Stash the capture back on the mission and bump its status.
    updated_mission = update(mission_id, {
        "captured_lead":   cap,
        "status":          "outreach_ready",
        "notes":           f"Converted to lead {new_lead['id']}",
    })
    return {"mission": updated_mission, "lead": new_lead}
