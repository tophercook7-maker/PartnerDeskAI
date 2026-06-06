"""
automation.discovery.research_missions
--------------------------------------
v9.3 research-missions provider — generates candidate stubs scoped to
(category, city_state) when other providers come up empty (or as a
standalone source). Each stub is a research-mission: business_name is
blank, and the row carries Google + Facebook + Maps search URLs the
user opens manually to find a real business and fill in the row.

Honest framing: this provider does NOT find businesses. It builds the
scaffolding the user needs to find businesses themselves. Pure-local;
zero outbound calls. No scraping, no paid APIs.

Previously this logic lived inside lead_candidates.discover_via_overpass
as the v8.9.1 fallback. v9.3 promotes it to a first-class provider so
it can be invoked directly (the existing /research-missions endpoint)
or chained behind OSM (the default).
"""

from __future__ import annotations

from urllib.parse import quote_plus


NAME             = "research_missions"
DISPLAY_NAME     = "Research Missions"
DESCRIPTION      = (
    "Local-only fallback. Generates Google/Facebook/Maps search-link "
    "stubs for areas/categories where other providers are thin. No "
    "outbound calls."
)
REQUIRES_NETWORK = False
# Pure local — the only "error" is bad input.
ERROR_CLASS      = ValueError


# Spec-verbatim phrase templates, rotated per stub for SERP variety.
_RESEARCH_PHRASE_TMPL = (
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
)

_GENERIC_OFFER = "Tap hub + simple one-page website. Pay once, no subscription."

MAX_COUNT = 25  # safety cap; mirrors lead_candidates.MAX_FIND_COUNT


def is_available() -> bool:
    return True


def _search_urls_for(category: str, city_state: str, phrase: str) -> list[dict]:
    """Three platform search URLs per stub: Google (uses the rotating
    phrase), Facebook, Maps. Pure string construction — no outbound
    calls. Same shape returned by other providers."""
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


def _build_stub(
    category: str,
    city_state: str,
    phrase_idx: int,
) -> dict:
    """Return one candidate dict (NOT persisted). lead_candidates._clean
    accepts this shape directly."""
    tmpl = _RESEARCH_PHRASE_TMPL[phrase_idx % len(_RESEARCH_PHRASE_TMPL)]
    phrase = tmpl.format(cat=category, city=city_state)
    google_url = "https://www.google.com/search?q=" + quote_plus(phrase)
    return {
        "business_name":          "",  # blank — user fills after researching
        "category":               category,
        "city_state":             city_state,
        "website_status":         "",
        "search_url":             google_url,
        "source_url":             google_url,
        "search_phrase":          phrase,
        "search_urls":            _search_urls_for(category, city_state, phrase),
        "discovery_source":       "research_mission",
        "approval_status":        "needs_research",
        "is_local_service":       True,
        "suggested_offer_angle":  _GENERIC_OFFER,
    }


def discover(
    category: str,
    city_state: str,
    count: int,
    phrase_offset: int = 0,
    **opts,
) -> dict:
    """
    Build N research-mission candidate stubs. Caller is responsible for
    deduplication + persistence — this is a pure generator.

    Args:
        category, city_state: required.
        count: how many stubs to generate. Capped at MAX_COUNT.
        phrase_offset: skip the first N phrase templates so successive
            calls with the same (category, city_state) don't repeat.

    Returns:
        Standard ProviderResult shape.
    """
    category = (category or "").strip()
    city_state = (city_state or "").strip()
    if not category or not city_state:
        raise ValueError("category and city_state are required")
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > MAX_COUNT:
        count = MAX_COUNT
    rows: list[dict] = []
    for i in range(count):
        rows.append(_build_stub(category, city_state, phrase_offset + i))
    if rows:
        msg = (
            f"Logan added {len(rows)} research mission"
            f"{'s' if len(rows) != 1 else ''} for "
            f"{category} in {city_state}."
        )
    else:
        msg = "no research missions generated"
    return {
        "candidates":  rows,
        "total_found": len(rows),
        "provider":    NAME,
        "message":     msg,
    }
