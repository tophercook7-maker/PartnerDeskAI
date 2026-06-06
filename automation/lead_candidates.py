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

# v8.9.1: track how each candidate landed so the UI can show the right
# affordances (research-mission cards get Google/FB/Maps + Mark Researched;
# OSM cards already have a verifiable business; manual cards are bare).
ALLOWED_DISCOVERY_SOURCES = ("osm", "research_mission", "csv_import", "manual")
DEFAULT_DISCOVERY_SOURCE = "manual"

# v9.0 Lead Enrichment Engine.
#
# Honest framing: "enrich" here means derivation + scaffolding, not
# external data fetching. We don't scrape, we don't pay any APIs, and
# we don't crawl a business's website to extract their email. What we
# CAN do is: compute structured weakness flags + opportunity reasons
# from what's already on the row, build per-field search URLs for what's
# still missing, generate the four outreach drafts (email / Facebook /
# SMS / phone notes), and compute whether the row is ready for outreach.
ALLOWED_ENRICHMENT_STATUS = (
    "not_started", "enriched", "partial", "needs_research", "failed",
)
DEFAULT_ENRICHMENT_STATUS = "not_started"

# The 5 missing-data indicator chips per the spec. Each chip carries
# one of: "found" | "missing" | "needs_check". We never silently fill
# a field — if a status is "missing" or "needs_check", the UI surfaces
# it so the user knows what to research.
MISSING_FIELD_KEYS = ("website", "phone", "email", "facebook", "contact_form")

# Spec-verbatim offer + message angle wording. The user is the source
# of truth on this — DO NOT drift to "3 free fixes" language; only
# "free homepage mockup" + "$150 starter website fix".
FREE_OFFER_TEXT = "Free homepage mockup"
PAID_OFFER_TEXT = "Starter website fix from $150"
MESSAGE_ANGLE_TEXT = (
    "Make it easier for customers to call, message, and trust the "
    "business from their phone."
)

MAX_DRAFT      = 4000  # per-draft cap
MAX_REASONS    = 12    # max items in opportunity_reasons / score_reasons
MAX_FLAGS      = 16    # max items in weak_presence_flags
MAX_ROUTES     = 8     # max items in contact_routes

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

MAX_FIND_COUNT = 25  # per "Find Leads For Me" / "Discover" call
MAX_PHRASE     = 500
MAX_URL_LIST   = 8   # max search URLs we'll store per candidate

# v8.9.1: research-mission phrase templates. Spec verbatim examples
# are folded in. The discover path rotates through these to give the
# user varied SERP angles for the same category/city.
_RESEARCH_PHRASE_TMPL = [
    '{cat} {city} email',
    '{cat} {city} gmail.com',
    '{cat} {city} contact',
    '{cat} {city} phone',
    '{cat} {city} "call or text"',
    '{cat} {city} "free estimate"',
    'site:facebook.com {cat} {city}',
    '{cat} {city} "find us on facebook"',
    '{cat} {city} instagram.com',
    'inurl:facebook.com {cat} {city}',
]

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
            # v8.9.1 fields:
            it.setdefault("search_phrase", "")
            it.setdefault("discovery_source", DEFAULT_DISCOVERY_SOURCE)
            it.setdefault("search_urls", [])
            # v9.0 enrichment fields:
            it.setdefault("enrichment_status", DEFAULT_ENRICHMENT_STATUS)
            it.setdefault("enrichment_notes", "")
            it.setdefault("missing_fields", [])
            it.setdefault("opportunity_reasons", [])
            it.setdefault("weak_presence_flags", [])
            it.setdefault("score_reasons", [])
            it.setdefault("ready_for_outreach", False)
            it.setdefault("outreach_drafts", {})
            it.setdefault("contact_routes", [])
            it.setdefault("last_enriched_at", None)
            it.setdefault("facebook_url", "")
            it.setdefault("instagram_url", "")
            it.setdefault("contact_form_url", "")
            it.setdefault("service_area", "")
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

    # v8.9.1: discovery_source enum. Default 'manual' (legacy / direct
    # adds), set explicitly by OSM + research-mission paths.
    ds_raw = _pick("discovery_source") or DEFAULT_DISCOVERY_SOURCE
    ds = str(ds_raw).strip().lower()
    if ds not in ALLOWED_DISCOVERY_SOURCES:
        ds = DEFAULT_DISCOVERY_SOURCE

    # v8.9.1: search_urls list of {label, url} dicts. Sanitized + clamped.
    raw_urls = _pick("search_urls") or []
    if not isinstance(raw_urls, list):
        raw_urls = []
    search_urls: list[dict] = []
    for item in raw_urls[:MAX_URL_LIST]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:60]
        url = str(item.get("url") or "").strip()[:MAX_URL]
        if not url:
            continue
        search_urls.append({"label": label or "Search", "url": url})

    # v9.0: enrichment_status enum.
    es_raw = _pick("enrichment_status") or DEFAULT_ENRICHMENT_STATUS
    es = str(es_raw).strip().lower()
    if es not in ALLOWED_ENRICHMENT_STATUS:
        es = DEFAULT_ENRICHMENT_STATUS

    # v9.0: missing_fields list of {field, status} — strict shape.
    raw_mf = _pick("missing_fields") or []
    if not isinstance(raw_mf, list):
        raw_mf = []
    missing_fields: list[dict] = []
    for item in raw_mf:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()[:60]
        st = str(item.get("status") or "").strip().lower()
        if not field or st not in ("found", "missing", "needs_check"):
            continue
        missing_fields.append({"field": field, "status": st})

    # v9.0: simple list-of-strings fields, clamped + truncated.
    def _list_of_str(key, cap):
        raw_v = _pick(key) or []
        if not isinstance(raw_v, list):
            return []
        out = []
        for s in raw_v[:cap]:
            if isinstance(s, str) and s.strip():
                out.append(s.strip()[:500])
        return out

    opportunity_reasons = _list_of_str("opportunity_reasons", MAX_REASONS)
    weak_presence_flags = _list_of_str("weak_presence_flags", MAX_FLAGS)
    score_reasons       = _list_of_str("score_reasons",       MAX_REASONS)
    contact_routes      = _list_of_str("contact_routes",      MAX_ROUTES)

    # v9.0: outreach_drafts dict with 5 fixed string keys, clamped.
    raw_drafts = _pick("outreach_drafts") or {}
    if not isinstance(raw_drafts, dict):
        raw_drafts = {}
    drafts_clean: dict = {}
    for k in ("email_subject", "email_body", "fb_message", "sms_message", "phone_notes"):
        v = raw_drafts.get(k)
        if isinstance(v, str) and v.strip():
            drafts_clean[k] = v[:MAX_DRAFT]

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
        # v8.9.1:
        "search_phrase":     str(_pick("search_phrase") or "").strip()[:MAX_PHRASE],
        "search_urls":       search_urls,
        "discovery_source":  ds,
        # v9.0 enrichment fields:
        "enrichment_status":  es,
        "enrichment_notes":   str(_pick("enrichment_notes") or "")[:MAX_NOTES],
        "missing_fields":     missing_fields,
        "opportunity_reasons": opportunity_reasons,
        "weak_presence_flags": weak_presence_flags,
        "score_reasons":      score_reasons,
        "ready_for_outreach": bool(_pick("ready_for_outreach")),
        "outreach_drafts":    drafts_clean,
        "contact_routes":     contact_routes,
        "last_enriched_at":   _pick("last_enriched_at"),
        "facebook_url":       str(_pick("facebook_url") or "").strip()[:MAX_URL],
        "instagram_url":      str(_pick("instagram_url") or "").strip()[:MAX_URL],
        "contact_form_url":   str(_pick("contact_form_url") or "").strip()[:MAX_URL],
        "service_area":       str(_pick("service_area") or "").strip()[:MAX_CITY],
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


# --- v9.3: Pluggable discovery via the discovery registry --------------
# The lead engine no longer imports OSM directly. It talks to the
# discovery package, which lets any provider (OSM today; CSV / chamber /
# directory tomorrow) feed the candidate queue.

import discovery as _discovery_mod
import discovery.research_missions as _rm_provider


def _search_urls_for(category: str, city_state: str, phrase: str) -> list[dict]:
    """
    Build the three search-platform URLs the spec asks for. Pure string
    construction — no outbound calls. Kept here (not just in the
    research_missions provider) because the OSM post-processing step
    also needs to attach them to OSM rows.
    """
    base_q = f"{category} {city_state}".strip()
    return [
        {
            "label": "Google",
            "url":   "https://www.google.com/search?q=" + quote_plus(phrase or base_q),
        },
        {
            "label": "Facebook",
            "url":   "https://www.facebook.com/search/top?q=" + quote_plus(base_q),
        },
        {
            "label": "Maps",
            "url":   "https://www.google.com/maps/search/" + quote_plus(base_q),
        },
    ]


def generate_research_missions(
    category: str,
    city_state: str,
    count: int,
    phrase_offset: int = 0,
) -> list[dict]:
    """
    'Find More Anyway' entry point. Delegates stub generation to the
    research_missions provider, then persists. The provider stays
    stateless — persistence + id assignment belongs to the lead engine.
    """
    category = (category or "").strip()
    city_state = (city_state or "").strip()
    if not category or not city_state:
        raise ValueError("category and city_state are required")
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > MAX_FIND_COUNT:
        raise ValueError(f"count {count} exceeds limit of {MAX_FIND_COUNT}")
    result = _rm_provider.discover(
        category=category,
        city_state=city_state,
        count=count,
        phrase_offset=phrase_offset,
    )
    items = load()
    new_rows: list[dict] = []
    for cand in result["candidates"]:
        cleaned = _clean(cand)
        cleaned["id"] = _next_id(items + new_rows)
        cleaned["created_at"] = _now()
        cleaned["updated_at"] = cleaned["created_at"]
        new_rows.append(cleaned)
    if new_rows:
        items.extend(new_rows)
        _save(items)
    return new_rows


def discover_via_overpass(
    category: str,
    city_state: str,
    count: int = 10,
    website_status_target: str = "any local business",
    provider: str | None = None,
) -> dict:
    """
    v9.3: same public signature + return shape as before — the chain
    behavior is preserved verbatim — but routing now goes through the
    discovery registry.

    The `provider` argument is new:
      - None / "auto" → run the default chain (OSM + research_missions)
        with the same v8.9.1 fallback semantics.
      - any registered NAME → run only that provider.

    Backward-compatible return shape:
      {added, added_count, osm_added, research_missions_added,
       fallback_triggered, found, skipped_duplicates, message,
       resolved_city, resolved_state, display_name, provider}
    """
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > MAX_FIND_COUNT:
        raise ValueError(f"count {count} exceeds limit of {MAX_FIND_COUNT}")

    requested = (provider or _discovery_mod.AUTO_NAME).strip().lower()
    if requested == _discovery_mod.AUTO_NAME:
        chain_names = list(_discovery_mod.DEFAULT_CHAIN)
    else:
        # Validate the name before we run anything.
        _discovery_mod.get_provider(requested)
        chain_names = [requested]

    chain_result = _discovery_mod.discover_chain(
        names=chain_names,
        category=category,
        city_state=city_state,
        count=count,
        website_status_target=website_status_target,
    )

    # Persist the candidates with cross-queue dedup (vs existing rows).
    items = load()
    existing_keys = {
        ((it.get("business_name") or "").strip().lower(),
         (it.get("city_state") or "").strip().lower())
        for it in items
    }
    added: list[dict] = []
    skipped_duplicates = 0
    per_provider_added: dict[str, int] = {}
    for cand in chain_result["candidates"]:
        name_key = (cand.get("business_name") or "").strip().lower()
        city_key = (cand.get("city_state") or "").strip().lower()
        # Empty-name candidates (research missions) can't collide on
        # name — dedup them on phrase instead so re-running doesn't
        # produce duplicates of the same SERP angle.
        if not name_key:
            phrase = (cand.get("search_phrase") or "").strip().lower()
            key = (f"_phrase:{phrase}", city_key)
        else:
            key = (name_key, city_key)
        if key in existing_keys:
            skipped_duplicates += 1
            continue
        existing_keys.add(key)
        # Make sure every persisted candidate carries search_urls so
        # the UI's per-card search strip works regardless of provider.
        if not cand.get("search_urls"):
            cand["search_urls"] = _search_urls_for(
                cand.get("category") or category,
                cand.get("city_state") or city_state,
                (cand.get("business_name") or "")
                  or (cand.get("search_phrase") or "")
                  or (cand.get("category") or category),
            )
        cleaned = _clean(cand)
        cleaned["id"] = _next_id(items + added)
        cleaned["created_at"] = _now()
        cleaned["updated_at"] = cleaned["created_at"]
        added.append(cleaned)
        ds = cleaned.get("discovery_source") or "manual"
        per_provider_added[ds] = per_provider_added.get(ds, 0) + 1
    if added:
        items.extend(added)
        _save(items)

    osm_added = per_provider_added.get("osm", 0)
    research_missions_added = per_provider_added.get("research_mission", 0)
    fallback_triggered = (
        "research_missions" in chain_names and research_missions_added > 0
    )

    extras = chain_result.get("extras") or {}
    display_name = extras.get("display_name", "")
    resolved_city = extras.get("resolved_city", "")
    resolved_state = extras.get("resolved_state", "")

    # Spec-verbatim messaging preserved.
    if fallback_triggered and osm_added == 0:
        msg = (
            "OSM did not have enough businesses for this search, so "
            "Logan created research missions instead."
        )
    elif fallback_triggered and osm_added > 0:
        msg = (
            f"OSM returned {osm_added} business{'es' if osm_added != 1 else ''} for "
            f"{category} in {display_name or city_state}; "
            f"Logan added {research_missions_added} research mission"
            f"{'s' if research_missions_added != 1 else ''} so you have "
            f"{len(added)} total to work."
        )
    else:
        msg = chain_result.get("message") or ""

    return {
        "added":                   added,
        "added_count":             len(added),
        "osm_added":               osm_added,
        "research_missions_added": research_missions_added,
        "fallback_triggered":      fallback_triggered,
        "found":                   int(chain_result.get("total_found") or 0),
        "skipped_duplicates":      skipped_duplicates,
        "resolved_city":           resolved_city,
        "resolved_state":          resolved_state,
        "display_name":            display_name,
        "message":                 msg,
        "provider":                chain_result.get("primary") or requested,
        "providers":               chain_result.get("providers") or [],
    }


# --- Approval / conversion --------------------------------------------

import leads as _leads_mod  # local-only, no network


def approve(cid: str) -> dict:
    return update(cid, {"approval_status": "approved"})


def reject(cid: str) -> dict:
    return update(cid, {"approval_status": "rejected"})


def needs_research(cid: str) -> dict:
    return update(cid, {"approval_status": "needs_research"})


def mark_researched(cid: str) -> dict:
    """
    v8.9.1: flip a research-mission candidate from 'needs_research'
    back to 'pending' once the user has filled in business_name +
    contact info. The user can then Approve → Convert as usual.

    Refuses to flip rows that aren't currently 'needs_research' — those
    are already in the review/convert/reject flow.
    """
    cand = _find(cid)
    cur = (cand.get("approval_status") or "").strip()
    if cur != "needs_research":
        raise ValueError(
            f"candidate {cid!r} is not in 'needs_research' state "
            f"(current: {cur!r}); nothing to mark"
        )
    return update(cid, {"approval_status": "pending"})


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


# ======================================================================
# v9.0 Lead Enrichment Engine
# ----------------------------------------------------------------------
# enrich(cid) is the public entry point. It derives structured weakness
# signals + opportunity reasons, builds per-field search URLs for what's
# still missing, generates the four outreach drafts (free homepage
# mockup CTA — never "3 free fixes"), computes ready_for_outreach, and
# persists. ZERO outbound calls — pure local derivation.
# ======================================================================

# ---- Pure helpers (no I/O) ------------------------------------------

_GENERIC_EMAIL_HOSTS = (
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "aol.com", "icloud.com", "live.com", "msn.com", "comcast.net",
)

_DIRECTORY_DOMAINS = (
    "yelp.com", "yellowpages.com", "angi.com", "angieslist.com",
    "bbb.org", "manta.com", "superpages.com", "citysearch.com",
    "tripadvisor.com", "foursquare.com",
)


def _is_email_generic(email: str) -> bool:
    """True if the email uses a free consumer host (gmail/yahoo/etc.).
    A non-generic email implies a business domain, which is a stronger
    signal of an established web presence."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    host = e.rsplit("@", 1)[-1]
    return host in _GENERIC_EMAIL_HOSTS


def _source_is_directory(source_url: str) -> bool:
    """True if the lead's source_url is a directory site (Yelp/YP/etc.)."""
    s = (source_url or "").strip().lower()
    if not s:
        return False
    return any(d in s for d in _DIRECTORY_DOMAINS)


def _source_is_facebook(*urls: str) -> bool:
    """True if any of the given URLs points at facebook.com."""
    for u in urls:
        if "facebook.com" in (u or "").lower():
            return True
    return False


def _detect_weak_presence_flags(c: dict) -> list[str]:
    """
    Compute the spec's 11 weak-presence flags from the row's existing
    fields. Internal flags only; never insulting copy — they're
    Logan's notes for the user, not text we'd ever send anywhere.

    Mapping is intentionally conservative — we only flag what we can
    actually see, never guess.
    """
    flags: list[str] = []
    website = (c.get("website_url") or "").strip()
    website_status = (c.get("website_status") or "").strip().lower()
    email = (c.get("email") or "").strip()
    phone = (c.get("phone") or "").strip()
    source_url = (c.get("source_url") or "").strip()
    fb_url = (c.get("facebook_url") or "").strip()
    contact_form_url = (c.get("contact_form_url") or "").strip()

    has_fb = bool(fb_url) or _source_is_facebook(source_url)

    if not website:
        flags.append("No website found")
    elif "weak" in website_status or "cleanup" in website_status:
        flags.append("Old or weak website")
    if has_fb and not website:
        flags.append("Facebook only")
    if _source_is_directory(source_url) and not website:
        flags.append("Directory only")
    if _is_email_generic(email):
        flags.append("Gmail/Yahoo/Outlook email")
    if phone and not email and not website:
        flags.append("Phone only")
    if website and not contact_form_url:
        flags.append("No contact form found")
    if website and "weak" in website_status:
        flags.append("Needs mobile-friendly landing page")
    if not website or "weak" in website_status:
        flags.append("No booking/contact hub")
    # "Good candidate for free homepage mockup" — fires when there's a
    # legible opportunity but the row isn't a corporate/franchise outright.
    if (not website or "weak" in website_status) and not c.get("is_corporate"):
        flags.append("Good candidate for free homepage mockup")
    # "No clear call to action" — only flag when we have a website but
    # status hints it's weak. We can't actually see the page; this is a
    # heuristic to surface to the user, not a definitive judgement.
    if website and ("weak" in website_status or "cleanup" in website_status):
        flags.append("No clear call to action")

    # Dedup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out[:MAX_FLAGS]


def _build_opportunity_reasons(c: dict, flags: list[str]) -> list[str]:
    """
    Convert weak-presence flags + score signals into human-readable
    bullets the user sees in the 'Why this score' block.

    Reads from the row + the flags list (already computed). Returns
    the most useful subset, ordered most-actionable first.
    """
    reasons: list[str] = []
    if "No website found" in flags:
        reasons.append("No website found — ideal for a free homepage mockup pitch")
    if "Facebook only" in flags:
        reasons.append("Customers find them on Facebook only — easy to upgrade")
    if "Directory only" in flags:
        reasons.append("Visible on directories only — could own their own page")
    if "Old or weak website" in flags:
        reasons.append("Existing site is dated or thin — good candidate for refresh")
    if "Gmail/Yahoo/Outlook email" in flags:
        reasons.append("Uses a free consumer email — likely no business domain yet")
    if (c.get("phone") or "").strip():
        reasons.append("Phone is available — direct outreach channel")
    if (c.get("email") or "").strip():
        reasons.append("Email is available — written-outreach channel")
    if c.get("is_local_service") is True:
        reasons.append("Local service business — fits the partner-style offer")
    if c.get("is_active") is True:
        reasons.append("Currently active — worth the time to research")
    if c.get("is_corporate") is True:
        reasons.append("Brand / franchise — usually a no-go for the small-shop offer")
    if "Phone only" in flags:
        reasons.append("Phone only — strong fit for the starter website fix")
    return reasons[:MAX_REASONS]


def _compute_score_reasons(c: dict) -> list[str]:
    """
    Per-row score breakdown matching compute_score()'s rule set. The UI
    renders this as the 'Why' bullets next to the score.
    """
    reasons: list[str] = []
    ws = (c.get("website_status") or "").strip().lower()
    if ws == "no website found":
        reasons.append("+3 No website found")
    if ws == "weak web presence":
        reasons.append("+2 Weak web presence")
    if (c.get("email") or "").strip():
        reasons.append("+2 Email available")
    if (c.get("phone") or "").strip():
        reasons.append("+1 Phone available")
    if c.get("is_local_service") is True:
        reasons.append("+1 Local service business")
    if c.get("is_active") is True:
        reasons.append("+1 Active recent presence")
    if c.get("is_corporate") is True:
        reasons.append("-3 Looks corporate / franchise")
    if not (c.get("email") or "").strip() and not (c.get("phone") or "").strip():
        reasons.append("-2 No contact info on file")
    if c.get("is_active") is False:
        reasons.append("-2 Marked inactive / closed")
    return reasons[:MAX_REASONS]


def _has_facebook(c: dict) -> bool:
    return bool((c.get("facebook_url") or "").strip()) or _source_is_facebook(
        c.get("source_url") or "",
    )


def _build_missing_fields(c: dict) -> list[dict]:
    """
    Build the five missing-data chips per spec:
      website / phone / email / facebook / contact_form
    Each chip = {"field": <key>, "status": "found" | "missing" | "needs_check"}.

    "needs_check" is used for research_mission rows (we haven't verified
    anything) and for fields whose website_status hints at a problem.
    """
    chips: list[dict] = []
    discovery_source = (c.get("discovery_source") or "manual").strip()
    is_research = discovery_source == "research_mission"

    def _chip(field: str, value: str, has: bool) -> dict:
        if has:
            return {"field": field, "status": "found"}
        # If the row was never enriched + is a research mission, the
        # field hasn't been checked yet — flag for follow-up.
        if is_research and (c.get("enrichment_status") or DEFAULT_ENRICHMENT_STATUS) == DEFAULT_ENRICHMENT_STATUS:
            return {"field": field, "status": "needs_check"}
        return {"field": field, "status": "missing"}

    website = (c.get("website_url") or "").strip()
    phone   = (c.get("phone") or "").strip()
    email   = (c.get("email") or "").strip()
    fb      = _has_facebook(c)
    contact = (c.get("contact_form_url") or "").strip()

    chips.append(_chip("website", website, bool(website)))
    chips.append(_chip("phone",   phone,   bool(phone)))
    chips.append(_chip("email",   email,   bool(email)))
    chips.append(_chip("facebook", "fb",   fb))
    # contact_form: if no website, mark missing; if website but no
    # contact_form_url, mark needs_check (we'd need to visit the site).
    if not website:
        chips.append({"field": "contact_form", "status": "missing"})
    elif contact:
        chips.append({"field": "contact_form", "status": "found"})
    else:
        chips.append({"field": "contact_form", "status": "needs_check"})
    return chips


def _build_contact_routes(c: dict) -> list[str]:
    """Inventory of outbound channels usable for this lead today."""
    routes: list[str] = []
    if (c.get("phone") or "").strip():            routes.append("phone")
    if (c.get("email") or "").strip():            routes.append("email")
    if (c.get("website_url") or "").strip():      routes.append("website")
    if _has_facebook(c):                          routes.append("facebook")
    if (c.get("contact_form_url") or "").strip(): routes.append("contact_form")
    return routes[:MAX_ROUTES]


def _build_per_field_search_urls(c: dict, missing_fields: list[dict]) -> list[dict]:
    """
    Generate targeted search URLs for fields that are missing or
    needs-check, so the user can click straight to a useful SERP.
    Returned as the same {label, url} shape used elsewhere — these
    augment the existing Google/Facebook/Maps strip.
    """
    name = (c.get("business_name") or "").strip()
    category = (c.get("category") or "").strip()
    city = (c.get("city_state") or "").strip()
    out: list[dict] = []
    # Seed term: business name when known, else category.
    base = name or category
    if not base or not city:
        return out

    def _g(label: str, query: str):
        out.append({
            "label": label,
            "url":   "https://www.google.com/search?q=" + quote_plus(query),
        })

    by_field = {it["field"]: it["status"] for it in (missing_fields or [])}
    if by_field.get("email") in ("missing", "needs_check"):
        _g("Find email", f'"{base}" "{city}" email')
    if by_field.get("phone") in ("missing", "needs_check"):
        _g("Find phone", f'"{base}" "{city}" phone OR "call or text"')
    if by_field.get("facebook") in ("missing", "needs_check"):
        _g("Find Facebook", f'site:facebook.com "{base}" "{city}"')
    if by_field.get("contact_form") in ("missing", "needs_check"):
        _g("Find contact form", f'"{base}" "{city}" contact')
    if by_field.get("website") in ("missing", "needs_check"):
        _g("Find website", f'"{base}" "{city}" official site')
    # Instagram is implied by the spec list of contact routes; include
    # it when the row has no IG and we have a name.
    if not (c.get("instagram_url") or "").strip() and name:
        _g("Find Instagram", f'site:instagram.com "{base}" "{city}"')
    return out[:MAX_URL_LIST]


def _is_ready_for_outreach(c: dict) -> bool:
    """
    A candidate is Ready for Outreach when it has the minimum the spec
    requires:
      - business_name + category + city_state
      - at least one contact route
      - a positive opportunity score (>= 1, i.e. not Reject)
      - an offer angle attached
      - outreach drafts generated
    """
    if not (c.get("business_name") or "").strip():
        return False
    if not (c.get("category") or "").strip():
        return False
    if not (c.get("city_state") or "").strip():
        return False
    routes = c.get("contact_routes") or _build_contact_routes(c)
    if not routes:
        return False
    if (c.get("score") or 0) < 1:
        return False
    if not (c.get("suggested_offer_angle") or "").strip():
        return False
    drafts = c.get("outreach_drafts") or {}
    if not drafts.get("email_body"):
        return False
    return True


# ---- Outreach draft generator (spec section 7) ----------------------

def _greeting_for(name: str) -> str:
    """Friendly, non-presumptuous greeting that works for a business
    name (we don't know the owner's first name)."""
    n = (name or "").strip()
    if not n:
        return "Hi there,"
    # If the name looks like "Joe's Coffee", keep it; if it's an LLC
    # or capitalized brand, "team" is friendlier than guessing.
    if any(tok in n.lower() for tok in (" llc", " inc", " co.", " corp", " co ")):
        return f"Hi {n} team,"
    return f"Hi {n} team,"


def _generate_outreach_drafts(c: dict) -> dict:
    """
    Produce the four outreach drafts the spec asks for. CTA is
    "free homepage mockup" verbatim. The paid offer is "$150 starter
    website fix". ZERO "3 free fixes" language anywhere in this file.

    Drafts are friendly, brief, and never insult the business. They
    use placeholders only for fields we have on the row — never invent
    a name or a quote.
    """
    name = (c.get("business_name") or "").strip()
    category = (c.get("category") or "your kind of business").strip()
    city = (c.get("city_state") or "").strip()
    label = name or "your business"
    where = f" in {city}" if city else ""
    greet = _greeting_for(name)

    email_subject = (
        f"Quick idea for {label}" if name else f"Quick idea for a local {category}"
    )
    email_body = (
        f"{greet}\n\n"
        f"I help local {category} make it easier for customers to call, "
        f"message, and trust the business straight from a phone.\n\n"
        f"If you'd like, I can put together a free homepage mockup for "
        f"{label}{where} — just one clean, phone-first page that shows "
        f"what a simple modern site could look like. No commitment, "
        f"just a visual you can keep.\n\n"
        f"If you want to take it further after, I do a starter website "
        f"fix from $150 — pay once, no subscription.\n\n"
        f"Want me to put a free mockup together so you can see what I mean?\n\n"
        f"— Topher"
    )

    fb_message = (
        f"Hi! I help local {category} build simple, phone-first websites "
        f"and tap hubs (pay once, no subscription). "
        f"Happy to put together a free homepage mockup for {label} so you "
        f"can see what a clean, modern page might look like — no pressure. "
        f"Want me to make one?"
    )

    sms_message = (
        f"Hi! I help local businesses with simple websites. "
        f"I'd love to make {label} a free homepage mockup so you can see "
        f"what I mean — no commitment. Interested?"
    )

    phone_notes = (
        "Talking points (not a script):\n"
        f"  • Who: local partner helping {category} with simple, "
        f"phone-first websites — pay once, no subscription.\n"
        f"  • What I noticed: limited / weak web presence (be specific, "
        f"don't insult).\n"
        f"  • Free offer: I can put together a free homepage mockup for "
        f"{label}{where} so you can see what a clean modern page would "
        f"look like. No commitment.\n"
        "  • Paid offer (only if asked): starter website fix from $150.\n"
        "  • Ask: 'Would it help if I put one together for you to look at?'\n"
        "  • Listen first. If they're busy, offer to text or email.\n"
    )

    return {
        "email_subject": email_subject[:MAX_DRAFT],
        "email_body":    email_body[:MAX_DRAFT],
        "fb_message":    fb_message[:MAX_DRAFT],
        "sms_message":   sms_message[:MAX_DRAFT],
        "phone_notes":   phone_notes[:MAX_DRAFT],
    }


# ---- enrich() + bulk_enrich() ---------------------------------------

def enrich(cid: str) -> dict:
    """
    Run the full v9.0 enrichment pass against one candidate. Pure-local;
    no outbound calls. Sets enrichment_status to one of:
      - 'enriched'      — has business_name + at least one signal worth using
      - 'partial'       — derived what we could but core fields missing
      - 'needs_research' — empty row that needs the user to research first
    """
    items = load()
    cand = None
    idx = -1
    for i, it in enumerate(items):
        if it.get("id") == cid:
            cand = dict(it)
            idx = i
            break
    if cand is None:
        raise KeyError(cid)

    # Derive everything in one pass.
    flags = _detect_weak_presence_flags(cand)
    cand["weak_presence_flags"] = flags
    cand["opportunity_reasons"] = _build_opportunity_reasons(cand, flags)
    cand["score_reasons"] = _compute_score_reasons(cand)
    missing = _build_missing_fields(cand)
    cand["missing_fields"] = missing
    cand["contact_routes"] = _build_contact_routes(cand)

    # Always attach the standardized offer + message angle so the UI
    # has spec-verbatim copy to show. Only overwrite the offer_angle
    # if it was empty — preserve user-set offers.
    if not (cand.get("suggested_offer_angle") or "").strip():
        cand["suggested_offer_angle"] = (
            f"{FREE_OFFER_TEXT}. {PAID_OFFER_TEXT}. {MESSAGE_ANGLE_TEXT}"
        )

    # Augment the per-card search URL strip with targeted "find <field>"
    # links. Preserve any existing Google/Facebook/Maps entries the
    # discovery path put on the row.
    base_urls = list(cand.get("search_urls") or [])
    extra = _build_per_field_search_urls(cand, missing)
    existing_urls = {(u.get("url") or "") for u in base_urls if isinstance(u, dict)}
    for item in extra:
        if item["url"] not in existing_urls:
            base_urls.append(item)
            existing_urls.add(item["url"])
    cand["search_urls"] = base_urls[:MAX_URL_LIST]

    # Generate the four outreach drafts. Always — even for empty rows
    # the drafts use placeholders so the user has something to copy.
    cand["outreach_drafts"] = _generate_outreach_drafts(cand)

    # Compute ready_for_outreach AFTER all derivations land. The
    # function reads score / contact_routes / drafts.
    cand["ready_for_outreach"] = _is_ready_for_outreach(cand)

    # Status decision:
    name = (cand.get("business_name") or "").strip()
    if not name and (cand.get("discovery_source") or "") == "research_mission":
        # Empty research mission — needs the user to fill basics first.
        cand["enrichment_status"] = "needs_research"
        notes = (
            "Logan could not confirm more details yet. "
            "Use the search links below or mark this as Needs Research."
        )
    elif not name:
        cand["enrichment_status"] = "partial"
        notes = (
            "Partial enrichment — Logan derived opportunity + offer info, "
            "but the business name is missing. Add it to keep going."
        )
    elif not cand["contact_routes"]:
        cand["enrichment_status"] = "partial"
        notes = (
            "Partial enrichment — no contact route on file yet "
            "(phone / email / website / Facebook). Click a search link "
            "below to find one."
        )
    else:
        cand["enrichment_status"] = "enriched"
        notes = (
            f"Enriched. {len(flags)} weak-presence flag"
            f"{'s' if len(flags) != 1 else ''} · "
            f"{len(cand['contact_routes'])} contact route"
            f"{'s' if len(cand['contact_routes']) != 1 else ''} · "
            f"ready_for_outreach={cand['ready_for_outreach']}."
        )
    cand["enrichment_notes"] = notes
    cand["last_enriched_at"] = _now()

    # Persist via _clean (re-computes score from current fields).
    cleaned = _clean(cand, existing=items[idx])
    cleaned["id"] = cid
    items[idx] = cleaned
    _save(items)
    return cleaned


def bulk_enrich(ids: list[str]) -> dict:
    """
    Run enrich() against every id. Returns:
      {enriched: [row, ...], failed: [{id, reason}, ...]}
    Per-row errors don't abort the batch.
    """
    if not isinstance(ids, list) or not ids:
        raise ValueError("ids must be a non-empty list")
    enriched: list[dict] = []
    failed: list[dict] = []
    for cid in ids:
        try:
            enriched.append(enrich(cid))
        except KeyError:
            failed.append({"id": cid, "reason": "not found"})
        except (ValueError, OSError) as e:
            failed.append({"id": cid, "reason": str(e)})
    return {"enriched": enriched, "failed": failed}


# ======================================================================
# v9.1 One-Click Lead Desk
# ----------------------------------------------------------------------
# do_it_all() is the single end-to-end entry point: discover → enrich →
# rank → return server-computed picks. The frontend can drive the whole
# workflow with one call.
#
# Honest framing (still): no scraping, no paid APIs, no auto-contact.
# This is the same Discover + bulk-enrich pipeline as before, just
# bundled so the UI shows one progress state instead of three.
# ======================================================================

def _pick_reason(c: dict) -> str:
    """
    Build the one-sentence rationale shown under each Logan's Pick.
    Pulls from opportunity_reasons first (most actionable), falls back
    to weak_presence_flags or score_reasons. Never invents content.
    """
    opps = c.get("opportunity_reasons") or []
    if opps:
        # First opportunity is already most-actionable.
        return opps[0]
    flags = c.get("weak_presence_flags") or []
    if flags:
        return f"Weak presence: {flags[0]}"
    reasons = c.get("score_reasons") or []
    if reasons:
        return reasons[0]
    return "Scored " + str(c.get("score") or 0) + " — review the card."


def _best_contact_route(c: dict) -> str:
    """One-line summary of the best contact route on file."""
    routes = c.get("contact_routes") or []
    parts: list[str] = []
    if "phone" in routes and (c.get("phone") or "").strip():
        parts.append(f"📞 {c.get('phone')}")
    if "email" in routes and (c.get("email") or "").strip():
        parts.append(f"✉  {c.get('email')}")
    if "facebook" in routes and ((c.get("facebook_url") or "").strip()
                                  or "facebook.com" in (c.get("source_url") or "").lower()):
        parts.append("📘 Facebook")
    if "website" in routes and (c.get("website_url") or "").strip():
        parts.append("🌐 Website")
    if not parts:
        return "No contact route yet — research first"
    return " · ".join(parts)


def compute_picks(items: list[dict] | None = None, k: int = 5) -> list[dict]:
    """
    Server-side Logan's Picks computation. Returns up to k candidate
    rows ranked by ready_for_outreach first, then score desc, excluding
    converted/rejected.

    Each pick is the original row dict augmented with two keys:
      - pick_reason:        the one-line rationale
      - best_contact_route: the one-line contact summary
    so the frontend doesn't have to compute them.
    """
    if k < 1:
        k = 1
    if items is None:
        items = load()
    candidates = [
        c for c in items
        if c.get("approval_status") not in ("converted", "rejected")
        and (c.get("confidence") or "") != "Reject"
    ]
    # Sort: ready_for_outreach first, then by score desc.
    candidates.sort(
        key=lambda c: (
            0 if c.get("ready_for_outreach") else 1,
            -1 * (c.get("score") or 0),
        )
    )
    picks: list[dict] = []
    for c in candidates[:k]:
        enriched_pick = dict(c)
        enriched_pick["pick_reason"] = _pick_reason(c)
        enriched_pick["best_contact_route"] = _best_contact_route(c)
        picks.append(enriched_pick)
    return picks


def do_it_all(
    category: str,
    city_state: str,
    count: int = 10,
    website_status_target: str = "any local business",
    provider: str | None = None,
) -> dict:
    """
    The v9.1 one-click pipeline:
      1. discover_via_overpass (which v9.3 routes through the discovery
         registry — default chain is OSM + research_missions; honors an
         explicit provider name)
      2. bulk_enrich the just-added candidates — same local-only
         derivation as v9.0
      3. compute Logan's Picks (top 5) from the WHOLE current queue,
         not just the newly added rows — so re-running picks up
         previously-discovered candidates the user hasn't acted on yet.

    Returns:
      {
        ok, discover: {...}, enrichment: {enriched_count, failed_count, failed},
        picks: [top 5 with pick_reason + best_contact_route],
        message: one-line summary,
      }
    """
    discover_result = discover_via_overpass(
        category=category,
        city_state=city_state,
        count=count,
        website_status_target=website_status_target,
        provider=provider,
    )
    new_ids = [r["id"] for r in discover_result["added"] if r.get("id")]
    enrichment_result = {"enriched_count": 0, "failed_count": 0, "failed": []}
    if new_ids:
        br = bulk_enrich(new_ids)
        enrichment_result = {
            "enriched_count": len(br["enriched"]),
            "failed_count":   len(br["failed"]),
            "failed":         br["failed"],
        }

    picks = compute_picks(k=5)

    parts = [discover_result["message"]]
    if enrichment_result["enriched_count"]:
        parts.append(
            f"Enriched {enrichment_result['enriched_count']} candidate"
            f"{'s' if enrichment_result['enriched_count'] != 1 else ''}."
        )
    if picks:
        ready_n = sum(1 for p in picks if p.get("ready_for_outreach"))
        parts.append(
            f"Logan's Picks: {len(picks)} (top by score)"
            + (f" — {ready_n} ready to send" if ready_n else "")
            + "."
        )
    else:
        parts.append("No picks yet — fill in business name + contact on a card and re-enrich.")
    message = " ".join(parts)

    return {
        "ok":         True,
        "discover":   {
            "osm_added":              discover_result["osm_added"],
            "research_missions_added": discover_result["research_missions_added"],
            "fallback_triggered":     discover_result["fallback_triggered"],
            "added_count":            discover_result["added_count"],
            "found":                  discover_result["found"],
            "skipped_duplicates":     discover_result["skipped_duplicates"],
            "display_name":           discover_result.get("display_name", ""),
            "provider":               discover_result.get("provider", ""),
            "providers":              discover_result.get("providers", []),
        },
        "enrichment": enrichment_result,
        "picks":      picks,
        "picks_count": len(picks),
        "message":    message,
    }
