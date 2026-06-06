"""
automation.discovery
--------------------
Logan v9.3: pluggable discovery provider system.

Logan was hardwired to OpenStreetMap. v9.3 introduces a registry so
discovery sources are first-class objects the lead engine doesn't need
to know about individually. Adding a CSV importer, a chamber-of-
commerce scrape, or a paid directory means dropping in a new provider
module and registering it here — nothing in `lead_candidates.py`
changes.

Provider interface (duck-typed; each provider is a module):

    NAME              str  — kebab-case slug, e.g. "osm"
    DISPLAY_NAME      str  — human label for the UI
    DESCRIPTION       str  — one-line capability summary
    REQUIRES_NETWORK  bool — does discover() make outbound HTTP calls?
    ERROR_CLASS       type — exception type the provider may raise

    def is_available() -> bool:        # optional
        '''True if the provider can be used right now.'''

    def discover(category, city_state, count, **opts) -> ProviderResult:
        '''Returns a normalized ProviderResult dict (see below).'''

ProviderResult shape (every provider must return this):

    {
      "candidates":  list[dict],   # candidate row dicts ready for _clean()
      "total_found": int,          # raw matches before dedup/cap
      "provider":    str,          # echo of NAME
      "message":     str,          # human-readable status line
      # optional extras passed through to the caller (display_name,
      # resolved_city, resolved_state, …)
    }

Each candidate dict in `candidates` should be the same shape
`lead_candidates._clean()` accepts: business_name, category, city_state,
website_url, website_status, email, phone, source_url, search_url,
search_phrase, search_urls, evidence_notes, suggested_offer_angle,
is_local_service, is_active, is_corporate, discovery_source (the
provider sets this so the UI knows which source the row came from).
"""

from __future__ import annotations

from typing import Iterable


# Populated by side-effect during module import below.
PROVIDERS: dict = {}

# Reserved name for the chain default. Resolves to DEFAULT_CHAIN.
AUTO_NAME = "auto"

# v9.3 default chain — preserves the v8.9.1 "OSM first, top up with
# research missions when OSM is thin" behavior. Adding a CSV or chamber
# provider later means adding its NAME here OR exposing a different
# chain via the UI.
DEFAULT_CHAIN = ("osm", "research_missions")


class DiscoveryError(Exception):
    """Generic provider error. Concrete providers may raise subclasses
    (e.g. OverpassError); the registry catches both."""


def register(provider_module) -> None:
    """Register a provider module by its NAME constant. Idempotent — a
    second register() with the same NAME replaces the prior entry, so
    tests can swap providers cleanly."""
    name = getattr(provider_module, "NAME", None)
    if not isinstance(name, str) or not name:
        raise ValueError(
            f"provider {provider_module!r} has no usable NAME constant"
        )
    PROVIDERS[name] = provider_module


def get_provider(name: str):
    """Return the registered provider module. Raises KeyError if not
    registered (callers should surface a 404)."""
    if name not in PROVIDERS:
        raise KeyError(
            f"unknown discovery provider {name!r}; "
            f"registered: {sorted(PROVIDERS)}"
        )
    return PROVIDERS[name]


def list_providers() -> list[dict]:
    """UI-facing summary of available providers. Stable order: the
    DEFAULT_CHAIN order first, then everything else alphabetically."""
    out: list[dict] = []
    for nm in DEFAULT_CHAIN:
        if nm in PROVIDERS:
            out.append(_describe(PROVIDERS[nm]))
    others = sorted(
        (p for nm, p in PROVIDERS.items() if nm not in DEFAULT_CHAIN),
        key=lambda p: getattr(p, "NAME", ""),
    )
    out.extend(_describe(p) for p in others)
    return out


def _describe(p) -> dict:
    available = True
    try:
        if hasattr(p, "is_available"):
            available = bool(p.is_available())
    except Exception:
        available = False
    return {
        "name":             getattr(p, "NAME", ""),
        "display_name":     getattr(p, "DISPLAY_NAME", ""),
        "description":      getattr(p, "DESCRIPTION", ""),
        "requires_network": bool(getattr(p, "REQUIRES_NETWORK", False)),
        "available":        available,
    }


def discover_one(
    name: str,
    category: str,
    city_state: str,
    count: int,
    **opts,
) -> dict:
    """Run a single named provider. Returns the provider's
    ProviderResult dict (with the standard four keys guaranteed)."""
    provider = get_provider(name)
    result = provider.discover(
        category=category,
        city_state=city_state,
        count=count,
        **opts,
    )
    # Defensive normalization — even if a provider returns extra keys,
    # the lead engine only depends on these four.
    result.setdefault("candidates", [])
    result.setdefault("total_found", len(result["candidates"]))
    result.setdefault("provider", name)
    result.setdefault("message", "")
    return result


def discover_chain(
    names: Iterable[str],
    category: str,
    city_state: str,
    count: int,
    **opts,
) -> dict:
    """
    Run providers in order, accumulating candidates until we reach
    `count` or run out of providers. Each provider sees a reduced
    request reflecting the remaining gap.

    Per-provider errors don't abort the chain — they're recorded in the
    `errors` list and the chain moves on. This is how v8.9.1's "OSM
    failed; fall back to research missions" behavior survives.

    Returns:
        {
          "candidates":  [all candidates, in chain order],
          "total_found": sum of provider total_found counts,
          "providers":   [{name, contributed, total_found, message, error?}, ...],
          "message":     composed human-readable summary,
          "primary":     name of the first provider that contributed,
          "extras":      dict of passthroughs from the first contributing provider
                          (display_name, resolved_city, etc.)
        }
    """
    candidates: list[dict] = []
    per_provider: list[dict] = []
    total_found = 0
    extras: dict = {}
    primary: str | None = None
    seen_names: set[str] = set()

    for name in names:
        remaining = count - len(candidates)
        if remaining <= 0:
            break
        try:
            result = discover_one(
                name=name,
                category=category,
                city_state=city_state,
                count=remaining,
                **opts,
            )
        except KeyError as e:
            per_provider.append({
                "name": name, "contributed": 0, "total_found": 0,
                "message": str(e), "error": "unknown_provider",
            })
            continue
        except Exception as e:
            # Any provider-specific error (OverpassError, IOError,
            # ValueError on bad input). Surface but don't abort.
            per_provider.append({
                "name": name, "contributed": 0, "total_found": 0,
                "message": str(e), "error": type(e).__name__,
            })
            continue
        provider_candidates = result.get("candidates") or []
        # Per-chain dedup: skip names we've already added from earlier
        # providers (case-insensitive, whitespace-collapsed).
        added_here = 0
        for cand in provider_candidates:
            if len(candidates) >= count:
                break
            key = _dedup_key(cand)
            if key in seen_names:
                continue
            seen_names.add(key)
            # Tag the candidate with the provider name so the UI can
            # show which source it came from. Providers should already
            # set discovery_source, but we enforce it here.
            cand.setdefault("discovery_source", _provider_to_source(name))
            candidates.append(cand)
            added_here += 1
        total_found += int(result.get("total_found") or 0)
        per_provider.append({
            "name":         name,
            "contributed":  added_here,
            "total_found":  int(result.get("total_found") or 0),
            "message":      result.get("message") or "",
        })
        if added_here and primary is None:
            primary = name
            # Capture passthrough extras from the first contributing
            # provider so the response carries display_name, etc.
            extras = {
                k: v for k, v in result.items()
                if k not in ("candidates", "total_found", "provider", "message")
            }

    # Build the chain message.
    chain_msg_bits: list[str] = []
    for entry in per_provider:
        if entry.get("error"):
            chain_msg_bits.append(
                f"{entry['name']} failed: {entry['message']}"
            )
        elif entry["contributed"] > 0:
            chain_msg_bits.append(
                f"{entry['name']} added {entry['contributed']}"
            )
        else:
            chain_msg_bits.append(f"{entry['name']} added 0")
    chain_message = "; ".join(chain_msg_bits) if chain_msg_bits else "no providers run"

    return {
        "candidates":  candidates,
        "total_found": total_found,
        "providers":   per_provider,
        "message":     chain_message,
        "primary":     primary,
        "extras":      extras,
    }


def _dedup_key(c: dict) -> str:
    """
    Build a per-candidate dedup key for the within-chain pass.
    Named candidates collapse on (name, city). Empty-name candidates
    (research missions) collapse on (phrase, city) instead — otherwise
    every research-mission stub would collide with every other one and
    only the first would survive.
    """
    name = (c.get("business_name") or "").strip().lower()
    city = (c.get("city_state") or "").strip().lower()
    if name:
        return f"name:{name}|{city}"
    phrase = (c.get("search_phrase") or "").strip().lower()
    return f"phrase:{phrase}|{city}"


def _provider_to_source(name: str) -> str:
    """Map provider NAME to candidate.discovery_source enum slot.
    Keeps backward compatibility with the v8.9.1 enum
    ('osm' | 'research_mission' | 'manual') while leaving room for
    future providers to use their own slot."""
    if name == "research_missions":
        return "research_mission"
    if name == "osm":
        return "osm"
    return name  # CSV providers, etc., will be added with new slots.


# ---------------------------------------------------------------------
# Eager registration. Providers register themselves as a side-effect of
# being imported. Add a new line here per new provider module.

from . import osm as _osm                          # noqa: E402,F401
from . import research_missions as _research       # noqa: E402,F401

register(_osm)
register(_research)
