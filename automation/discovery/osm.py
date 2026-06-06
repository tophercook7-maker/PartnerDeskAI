"""
automation.discovery.osm
------------------------
v9.3 OSM discovery provider — thin adapter over the existing
overpass_discovery module so the migration is risk-free.

All the actual Nominatim + Overpass logic, the CATEGORY_TO_OSM table,
the US_STATE_NAMES map, the Overpass QL builders, the element →
candidate mapping — all of it stays in overpass_discovery.py. This
adapter exposes the standardized provider interface required by the
discovery registry.

Behavior is byte-for-byte the same as v9.2's discover_via_overpass:
two outbound HTTPS calls per discover (Nominatim → Overpass),
read-only, no auth, no key, no scraping.
"""

from __future__ import annotations

import overpass_discovery as _overpass


NAME             = "osm"
DISPLAY_NAME     = "OpenStreetMap"
DESCRIPTION      = (
    "Free public OSM data via Nominatim + Overpass. Real local "
    "businesses. ~5-15s per click. Coverage varies by area."
)
REQUIRES_NETWORK = True
ERROR_CLASS      = _overpass.OverpassError

# Re-export the constants the lead engine references so downstream
# code doesn't need to import overpass_discovery directly any more.
OVERPASS_URL  = _overpass.OVERPASS_URL
NOMINATIM_URL = _overpass.NOMINATIM_URL


def is_available() -> bool:
    """We don't ping the network here — that would defeat the purpose
    of a cheap availability check. OSM endpoints have been stable for
    years; we report available unconditionally and surface any actual
    failure as part of discover()."""
    return True


def discover(
    category: str,
    city_state: str,
    count: int,
    website_status_target: str = "any local business",
    **opts,
) -> dict:
    """
    Provider entry point. Adapts the existing discover() to the
    standardized ProviderResult shape.

    Args:
        category, city_state, count: standard provider args.
        website_status_target: provider-specific opt, passed through.

    Returns:
        {
          candidates, total_found, provider, message,
          # passthrough extras from overpass_discovery:
          resolved_city, resolved_state, display_name,
          website_status_target,
        }

    Raises:
        OverpassError on transport / parse / no-match failures from
        either Nominatim or Overpass. The discovery_chain catches this
        and moves to the next provider.
    """
    raw = _overpass.discover(
        category=category,
        city_state=city_state,
        count=count,
        website_status_target=website_status_target,
    )
    # raw already has candidates + total_found + message; just add the
    # provider tag and tag each candidate with discovery_source.
    candidates = raw.get("candidates") or []
    for cand in candidates:
        cand.setdefault("discovery_source", "osm")
    return {
        "candidates":             candidates,
        "total_found":            int(raw.get("total_found") or 0),
        "provider":               NAME,
        "message":                raw.get("message") or "",
        "resolved_city":          raw.get("resolved_city", ""),
        "resolved_state":         raw.get("resolved_state", ""),
        "display_name":           raw.get("display_name", ""),
        "website_status_target":  raw.get("website_status_target", website_status_target),
    }
