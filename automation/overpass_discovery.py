"""
overpass_discovery.py
---------------------
Logan v8.9: OpenStreetMap discovery for real local businesses.

Two outbound HTTPS calls per discover():
  1. Nominatim  → resolves "Hot Springs, AR" to an OSM relation_id.
                  (Needed because multiple US cities share names —
                  Hot Springs exists in AR, SD, MT, NC, VA, … so
                  nested area-by-name filters in Overpass alone are
                  ambiguous and cross-state matches leak through.)
  2. Overpass   → category queries scoped to that exact relation_id.

Both endpoints are part of the OpenStreetMap project. Free, public,
no auth, no key, no paid plan, no scraping. Strict rate limits but
plenty of headroom for one-click-per-search human use.

What flows outbound: a category word + city + US state. No PII, no
user identity, no cookies.

What flows back: a JSON list of matching businesses with whatever tags
OSM contributors entered — typically name, sometimes phone / website /
opening_hours / address. We never invent fields. If OSM doesn't have
a phone number, the candidate lands with phone="".

Honest about coverage: OSM is community-mapped. Well-mapped US metros
have dozens of small businesses; rural/thin areas may have a handful
or none. discover() returns whatever OSM actually had; never pads.

NO scraping. NO paid APIs. NO outbound contact. The discovered rows
land in the Logan candidate queue as 'pending'; the user reviews and
approves each before any conversion to a Logan lead.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request


OVERPASS_URL = "https://overpass-api.de/api/interpreter"  # primary (kept for back-compat reads)
# v13.0.12: mirror list, tried in order on connection-refused / 5xx.
# Some mirrors don't support area queries (the FR mirror returns
# "area_tags_local.bin not found"); we skip those by retrying the
# next one if the first response is empty AND carries a "remark" of
# "open64" or "runtime error". Kept short and trusted — these are the
# documented Overpass alternates.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]
# Cache of the last-known-good mirror for this process. None until we
# probe; once set we try this first on every call. Reset on hard 5xx
# from the cached mirror so a flaky host doesn't pin us forever.
_LAST_GOOD_MIRROR: str | None = None
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_HTTP_TIMEOUT_S = 30      # client-side socket timeout
NOMINATIM_HTTP_TIMEOUT_S = 15
OVERPASS_QUERY_TIMEOUT_S = 25     # server-side QL [timeout:N];
OVERPASS_MAX_RESULTS = 50         # hard cap on `out` count

# Sent on every OSM HTTP request. Nominatim TOS asks for a
# meaningful UA; Overpass is laxer but identifying is courteous.
# No PII in the UA — just the tool name + version.
_USER_AGENT = "PartnerDeskAI/8.9 (local single-user Hub; Logan lead discovery)"


class OverpassError(Exception):
    """Raised for transport / server / parse failures talking to OSM endpoints."""


# --- Category → OSM tag pairs -----------------------------------------
# Each entry maps a user-typed category word to one or more OSM
# (key, value) tag pairs. The query unions all nodes+ways matching ANY
# of the listed pairs within the resolved city area.
#
# Keys are normalized (lowercased, singular/plural collapsed) at
# lookup time. Unknown categories fall back to trying shop=<word> and
# amenity=<word>.
CATEGORY_TO_OSM: dict[str, list[tuple[str, str]]] = {
    "coffee":           [("amenity", "cafe"), ("shop", "coffee")],
    "coffee shop":      [("amenity", "cafe"), ("shop", "coffee")],
    "cafe":             [("amenity", "cafe")],
    "restaurant":       [("amenity", "restaurant")],
    "diner":            [("amenity", "restaurant")],
    "bakery":           [("shop", "bakery"), ("craft", "bakery")],
    "bar":              [("amenity", "bar"), ("amenity", "pub")],
    "pub":              [("amenity", "pub")],
    "brewery":          [("craft", "brewery"), ("industrial", "brewery")],
    "ice cream":        [("amenity", "ice_cream"), ("shop", "ice_cream")],
    "florist":          [("shop", "florist")],
    "salon":            [("shop", "hairdresser"), ("shop", "beauty")],
    "hair salon":       [("shop", "hairdresser")],
    "barber":           [("shop", "hairdresser")],
    "nails":            [("shop", "beauty")],
    "spa":              [("leisure", "spa"), ("shop", "beauty")],
    "tattoo":           [("shop", "tattoo")],
    # v13.0.7: trade categories — broadened tag coverage. OSM real-world
    # tagging is inconsistent; widening per-category to 3-5 likely tag
    # forms typically doubles or triples raw OSM hits per query without
    # any false positives (each tag form is still narrow). Same shape as
    # before — just more pairs per category.
    "landscaping":      [("shop", "garden_centre"), ("craft", "gardener"),
                         ("landuse", "grass"), ("office", "garden")],
    "landscaper":       [("shop", "garden_centre"), ("craft", "gardener"),
                         ("landuse", "grass"), ("office", "garden")],
    "lawn care":        [("craft", "gardener"), ("shop", "garden_centre")],
    "tree service":     [("craft", "gardener")],
    "plumber":          [("craft", "plumber"), ("shop", "plumber"),
                         ("office", "plumber")],
    "plumbing":         [("craft", "plumber"), ("shop", "plumber"),
                         ("office", "plumber")],
    "electrician":      [("craft", "electrician"), ("shop", "electrical"),
                         ("office", "electrician")],
    "electrical":       [("craft", "electrician"), ("shop", "electrical")],
    "handyman":         [("craft", "handyman"), ("office", "handyman"),
                         ("craft", "carpenter")],
    "hardware":         [("shop", "hardware"), ("shop", "doityourself")],
    "hardware store":   [("shop", "hardware"), ("shop", "doityourself")],
    "carpenter":        [("craft", "carpenter"), ("shop", "carpenter"),
                         ("craft", "cabinet_maker")],
    "carpentry":        [("craft", "carpenter"), ("craft", "cabinet_maker")],
    "roofer":           [("craft", "roofer"), ("shop", "roofing")],
    "roofing":          [("craft", "roofer"), ("shop", "roofing")],
    "hvac":             [("craft", "heating_engineer"), ("craft", "hvac"),
                         ("shop", "hvac"), ("office", "hvac")],
    "heating":          [("craft", "heating_engineer"), ("office", "hvac")],
    "air conditioning": [("craft", "heating_engineer"), ("office", "hvac")],
    "contractor":       [("office", "construction"), ("craft", "builder"),
                         ("craft", "handyman")],
    "general contractor": [("office", "construction"), ("craft", "builder")],
    "builder":          [("craft", "builder"), ("office", "construction")],
    "construction":     [("office", "construction"), ("craft", "builder")],
    "painter":          [("craft", "painter"), ("shop", "paint")],
    "painting":         [("craft", "painter")],
    "flooring":         [("shop", "flooring"), ("craft", "tiler")],
    "tiler":            [("craft", "tiler"), ("shop", "flooring")],
    "tile":             [("craft", "tiler"), ("shop", "flooring")],
    "auto repair":      [("shop", "car_repair")],
    "mechanic":         [("shop", "car_repair")],
    "car wash":         [("amenity", "car_wash")],
    "tire shop":        [("shop", "tyres")],
    "tires":            [("shop", "tyres")],
    "gym":              [("leisure", "fitness_centre")],
    "yoga":             [("leisure", "fitness_centre")],
    "yoga studio":      [("leisure", "fitness_centre")],
    "fitness":          [("leisure", "fitness_centre")],
    "dentist":          [("amenity", "dentist"), ("healthcare", "dentist")],
    "doctor":           [("amenity", "doctors")],
    "chiropractor":     [("healthcare", "chiropractor")],
    "veterinarian":     [("amenity", "veterinary")],
    "vet":              [("amenity", "veterinary")],
    "pet store":        [("shop", "pet")],
    "pet groomer":      [("shop", "pet_grooming"), ("shop", "pet")],
    "boutique":         [("shop", "clothes"), ("shop", "boutique")],
    "clothing":         [("shop", "clothes")],
    "clothing store":   [("shop", "clothes")],
    "jeweler":          [("shop", "jewelry")],
    "jewelry":          [("shop", "jewelry")],
    "bookstore":        [("shop", "books")],
    "bookshop":         [("shop", "books")],
    "thrift":           [("shop", "second_hand"), ("shop", "charity")],
    "antiques":         [("shop", "antiques")],
    "real estate":      [("office", "estate_agent")],
    "realtor":          [("office", "estate_agent")],
    "lawyer":           [("office", "lawyer")],
    "law office":       [("office", "lawyer")],
    "law firm":         [("office", "lawyer")],
    "accountant":       [("office", "accountant")],
    "insurance":        [("office", "insurance")],
    "photographer":     [("craft", "photographer"), ("shop", "photo")],
    "photography":      [("craft", "photographer")],
    "videographer":     [("craft", "photographer")],
    "hotel":            [("tourism", "hotel")],
    "motel":            [("tourism", "motel")],
    "bed and breakfast":[("tourism", "guest_house")],
    "guest house":      [("tourism", "guest_house")],
    "daycare":          [("amenity", "childcare")],
    "childcare":        [("amenity", "childcare")],
    "preschool":        [("amenity", "kindergarten")],
    "art gallery":      [("tourism", "gallery"), ("shop", "art")],
    "art studio":       [("shop", "art")],
    "framing":          [("shop", "frame")],
    "dry cleaner":      [("shop", "dry_cleaning")],
    "laundromat":       [("shop", "laundry")],
    "tailor":           [("shop", "tailor")],
    "shoe repair":      [("shop", "shoe_repair")],
    "locksmith":        [("shop", "locksmith"), ("craft", "key_cutter")],
    "music store":      [("shop", "musical_instrument")],
}


# --- US state name resolution -----------------------------------------
# OSM admin_level=4 in the US carries the full state name as `name`,
# never the postal abbreviation. We accept either input and resolve to
# the full name for the query.
US_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",        "AK": "Alaska",         "AZ": "Arizona",
    "AR": "Arkansas",       "CA": "California",     "CO": "Colorado",
    "CT": "Connecticut",    "DE": "Delaware",       "FL": "Florida",
    "GA": "Georgia",        "HI": "Hawaii",         "ID": "Idaho",
    "IL": "Illinois",       "IN": "Indiana",        "IA": "Iowa",
    "KS": "Kansas",         "KY": "Kentucky",       "LA": "Louisiana",
    "ME": "Maine",          "MD": "Maryland",       "MA": "Massachusetts",
    "MI": "Michigan",       "MN": "Minnesota",      "MS": "Mississippi",
    "MO": "Missouri",       "MT": "Montana",        "NE": "Nebraska",
    "NV": "Nevada",         "NH": "New Hampshire",  "NJ": "New Jersey",
    "NM": "New Mexico",     "NY": "New York",       "NC": "North Carolina",
    "ND": "North Dakota",   "OH": "Ohio",           "OK": "Oklahoma",
    "OR": "Oregon",         "PA": "Pennsylvania",   "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota",   "TN": "Tennessee",
    "TX": "Texas",          "UT": "Utah",           "VT": "Vermont",
    "VA": "Virginia",       "WA": "Washington",     "WV": "West Virginia",
    "WI": "Wisconsin",      "WY": "Wyoming",        "DC": "District of Columbia",
}

_STATE_NAMES_LOWER = {v.lower(): v for v in US_STATE_NAMES.values()}


# --- Public helpers ---------------------------------------------------

def _normalize_category(category: str) -> str:
    s = (category or "").strip().lower()
    # crude plural collapse: trailing 's' if 4+ chars and not 'ss'
    if len(s) >= 4 and s.endswith("s") and not s.endswith("ss"):
        # 'salons' → 'salon', 'cafes' → 'cafe', 'lawyers' → 'lawyer'
        s_singular = s[:-1]
        if s_singular in CATEGORY_TO_OSM:
            return s_singular
    return s


def _category_tags(category: str) -> list[tuple[str, str]]:
    key = _normalize_category(category)
    if key in CATEGORY_TO_OSM:
        return CATEGORY_TO_OSM[key]
    # Fallback for unknown words: try as both shop=<word> and amenity=<word>.
    # OSM tag values are lowercase with underscores; replace spaces.
    val = key.replace(" ", "_")
    return [("shop", val), ("amenity", val)]


def _parse_city_state(s: str) -> tuple[str, str]:
    """
    Accept 'City, ST' / 'City, State' / 'City ST'. Return (city, full_state).
    Raises ValueError on unparseable / unknown state.
    """
    raw = (s or "").strip()
    if not raw:
        raise ValueError("city_state required")
    city = state = ""
    if "," in raw:
        city_part, state_part = raw.rsplit(",", 1)
        city, state = city_part.strip(), state_part.strip()
    else:
        # Try "City ST" — split off the last whitespace token if it
        # looks like a 2-letter state code OR a full state name match.
        parts = raw.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].upper() in US_STATE_NAMES:
            city, state = parts[0].strip(), parts[1].strip()
        else:
            # Try matching multi-word state names at the tail.
            lower = raw.lower()
            match = None
            for name_l, name in _STATE_NAMES_LOWER.items():
                if lower.endswith(" " + name_l):
                    match = (raw[: -len(name_l) - 1].strip(), name)
                    break
            if not match:
                raise ValueError(
                    "city_state must be 'City, State' or 'City ST' "
                    "(e.g. 'Hot Springs, AR'). Got: " + repr(raw)
                )
            city, state = match
    if not city:
        raise ValueError("city is empty")
    if not state:
        raise ValueError("state is empty")
    state_upper = state.upper()
    if state_upper in US_STATE_NAMES:
        return city, US_STATE_NAMES[state_upper]
    full = _STATE_NAMES_LOWER.get(state.lower())
    if full:
        return city, full
    raise ValueError(f"unknown US state {state!r} — try the 2-letter code")


# --- Nominatim geocoding -----------------------------------------------
# Resolves a "City, State" string to a single OSM relation (the city
# administrative boundary). Used to scope the subsequent Overpass query
# unambiguously — querying Overpass for areas by name alone collides
# across same-named cities in different states.

def _call_nominatim(city: str, state: str) -> dict:
    """
    GET https://nominatim.openstreetmap.org/search?...
    Returns the first matching place's metadata. Filtered to US + city.
    Raises OverpassError on transport / parse / no-match.
    """
    params = {
        "q":            f"{city}, {state}, USA",
        "format":       "json",
        "limit":        "1",
        "countrycodes": "us",
        "addressdetails": "1",
    }
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept":     "application/json",
            "Accept-Language": "en",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=NOMINATIM_HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise OverpassError(
                "Nominatim rate-limited (429). Wait a minute and try again."
            ) from e
        raise OverpassError(f"Nominatim HTTP {e.code}: {e.reason}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise OverpassError(f"Nominatim unreachable: {e}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise OverpassError(f"Nominatim returned invalid JSON: {e}") from e
    if not isinstance(data, list) or not data:
        raise OverpassError(
            f"Nominatim found no city named {city!r} in {state}. "
            f"Try a larger nearby city or check spelling."
        )
    place = data[0]
    osm_type = (place.get("osm_type") or "").strip()
    osm_id   = place.get("osm_id")
    if not osm_type or not isinstance(osm_id, int):
        raise OverpassError(
            f"Nominatim result for {city}, {state} has no usable osm_id."
        )
    return {
        "osm_type":     osm_type,    # 'relation' | 'way' | 'node'
        "osm_id":       osm_id,
        "display_name": place.get("display_name") or f"{city}, {state}",
        "lat":          place.get("lat"),
        "lon":          place.get("lon"),
    }


def _overpass_area_id(osm_type: str, osm_id: int) -> int | None:
    """
    Overpass area IDs are derived from OSM IDs:
      relation N → 3600000000 + N
      way      N → 2400000000 + N
      node     N → no area (only relations/ways become areas)
    Returns None if the type can't be promoted to an area.
    """
    if osm_type == "relation":
        return 3_600_000_000 + osm_id
    if osm_type == "way":
        return 2_400_000_000 + osm_id
    return None


# --- Query construction -----------------------------------------------

def _qstr(s: str) -> str:
    """Escape a value for embedding in an Overpass QL double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _build_overpass_query_by_area_id(
    category: str, area_id: int, max_results: int = OVERPASS_MAX_RESULTS,
) -> str:
    """
    Build a category-filtered Overpass QL query scoped to a specific
    pre-resolved area_id (typically a Nominatim-resolved city relation).
    This is unambiguous — no name collision across same-named cities.
    """
    if max_results < 1 or max_results > OVERPASS_MAX_RESULTS:
        max_results = OVERPASS_MAX_RESULTS
    pair_lines: list[str] = []
    for k, v in _category_tags(category):
        ek, ev = _qstr(k), _qstr(v)
        pair_lines.append(f'  node["{ek}"="{ev}"](area.searchArea);')
        pair_lines.append(f'  way["{ek}"="{ev}"](area.searchArea);')
        pair_lines.append(f'  relation["{ek}"="{ev}"](area.searchArea);')
    body = "\n".join(pair_lines)
    return (
        f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_S}];\n"
        f"area({area_id})->.searchArea;\n"
        f"(\n{body}\n);\n"
        f"out tags center {max_results};\n"
    )


def _build_overpass_query_by_bbox(
    category: str, lat: float, lon: float,
    radius_m: int = 8000, max_results: int = OVERPASS_MAX_RESULTS,
) -> str:
    """
    Fallback when Nominatim returns a node (no area) — query by radius
    around the node's lat/lon instead. Default 8 km covers most small
    US cities.
    """
    if max_results < 1 or max_results > OVERPASS_MAX_RESULTS:
        max_results = OVERPASS_MAX_RESULTS
    pair_lines: list[str] = []
    for k, v in _category_tags(category):
        ek, ev = _qstr(k), _qstr(v)
        pair_lines.append(
            f'  node["{ek}"="{ev}"](around:{radius_m},{lat},{lon});'
        )
        pair_lines.append(
            f'  way["{ek}"="{ev}"](around:{radius_m},{lat},{lon});'
        )
        pair_lines.append(
            f'  relation["{ek}"="{ev}"](around:{radius_m},{lat},{lon});'
        )
    body = "\n".join(pair_lines)
    return (
        f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_S}];\n"
        f"(\n{body}\n);\n"
        f"out tags center {max_results};\n"
    )


# Kept for backward-compat with the v8.9.0 standalone tests that
# exercise the name-based query shape. New code should prefer the
# area-id path above.
def _build_overpass_query(
    category: str, city: str, state: str, max_results: int = OVERPASS_MAX_RESULTS,
) -> str:
    if max_results < 1 or max_results > OVERPASS_MAX_RESULTS:
        max_results = OVERPASS_MAX_RESULTS
    state_q = _qstr(state)
    city_q = _qstr(city)
    pair_lines: list[str] = []
    for k, v in _category_tags(category):
        ek, ev = _qstr(k), _qstr(v)
        pair_lines.append(f'  node["{ek}"="{ev}"](area.searchArea);')
        pair_lines.append(f'  way["{ek}"="{ev}"](area.searchArea);')
        pair_lines.append(f'  relation["{ek}"="{ev}"](area.searchArea);')
    body = "\n".join(pair_lines)
    return (
        f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_S}];\n"
        f'area["name"="{state_q}"]["admin_level"="4"]'
        f'["boundary"="administrative"]->.state;\n'
        f'area["name"="{city_q}"]["boundary"="administrative"]'
        f"(area.state)->.searchArea;\n"
        f"(\n{body}\n);\n"
        f"out tags center {max_results};\n"
    )


# --- Outbound call ----------------------------------------------------

def _call_overpass_one(url: str, data: bytes) -> dict:
    """Single attempt against one mirror. Raises OverpassError on any
    failure (HTTP non-2xx, transport error, JSON parse error, or a
    "remark" body indicating the mirror lacks area data)."""
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent":   _USER_AGENT,
            "Accept":       "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OVERPASS_HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise OverpassError(f"Overpass rate-limited (429) at {url}.") from e
        if e.code in (504, 408):
            raise OverpassError(f"Overpass timeout at {url}.") from e
        raise OverpassError(f"Overpass HTTP {e.code} at {url}: {e.reason}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise OverpassError(f"Overpass unreachable at {url}: {e}") from e
    try:
        result = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise OverpassError(f"Overpass invalid JSON from {url}: {e}") from e
    # Some mirrors return 200 but with a "remark" indicating a runtime
    # error (e.g. FR mirror lacks the area tags database). Treat empty
    # elements + a runtime-error remark as a failure so we try the next.
    remark = str(result.get("remark") or "").lower()
    if not result.get("elements") and any(
        s in remark for s in ("runtime error", "open64", "file_blocks", "no such file")
    ):
        raise OverpassError(f"Overpass mirror {url} lacks area data: {remark[:80]}")
    return result


def _call_overpass(query: str) -> dict:
    """Read-only HTTPS POST with multi-mirror fallback.

    v13.0.12: tries OVERPASS_MIRRORS in order. Caches the last-known-
    good mirror for the process so subsequent calls go straight there.
    On hard failure of the cached mirror, falls back through the rest.
    Raises OverpassError only if every mirror fails.
    """
    global _LAST_GOOD_MIRROR
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")

    # Build try-order: cached good mirror first (if any), then the rest.
    mirrors: list[str] = []
    if _LAST_GOOD_MIRROR and _LAST_GOOD_MIRROR in OVERPASS_MIRRORS:
        mirrors.append(_LAST_GOOD_MIRROR)
    for m in OVERPASS_MIRRORS:
        if m not in mirrors:
            mirrors.append(m)

    last_err: OverpassError | None = None
    for url in mirrors:
        try:
            result = _call_overpass_one(url, data)
            _LAST_GOOD_MIRROR = url
            return result
        except OverpassError as e:
            last_err = e
            # If the cached mirror failed, clear it so the next call
            # re-probes from the top.
            if url == _LAST_GOOD_MIRROR:
                _LAST_GOOD_MIRROR = None
            continue
    # All mirrors exhausted
    if last_err is None:
        last_err = OverpassError("All Overpass mirrors exhausted (none reachable).")
    raise last_err


# --- Element → candidate dict -----------------------------------------

def _map_to_candidate(el: dict, category: str, city_state: str) -> dict | None:
    """
    Map one OSM element to a lead_candidates row dict. Returns None
    for unnamed elements (we don't queue businesses with no name).

    Heuristics:
      - is_corporate := True iff 'brand' tag is present (chain/franchise indicator)
      - is_active    := False iff any tag has 'disused:' / 'abandoned:' / 'closed:' prefix
      - website_status := 'has website but needs cleanup' if website present, else 'no website found'
    """
    tags = el.get("tags") or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None

    # v13.0.8: pull more contact tags. OSM has contact:* and bare forms.
    phone   = (tags.get("contact:phone") or tags.get("phone")
               or tags.get("contact:mobile") or tags.get("mobile") or "").strip()
    email   = (tags.get("contact:email") or tags.get("email") or "").strip()
    website = (tags.get("contact:website") or tags.get("website") or "").strip()
    facebook  = (tags.get("contact:facebook") or tags.get("facebook")
                 or tags.get("contact:fb") or "").strip()
    instagram = (tags.get("contact:instagram") or tags.get("instagram") or "").strip()
    # Sometimes the value is "@handle" or "page-name" rather than a full
    # URL — wrap them so the kid-mode action buttons can open them.
    if facebook and not facebook.lower().startswith(("http://", "https://")):
        fb_handle = facebook.lstrip("@").strip("/")
        facebook = f"https://www.facebook.com/{fb_handle}" if fb_handle else ""
    if instagram and not instagram.lower().startswith(("http://", "https://")):
        ig_handle = instagram.lstrip("@").strip("/")
        instagram = f"https://www.instagram.com/{ig_handle}" if ig_handle else ""

    street     = (tags.get("addr:street") or "").strip()
    house      = (tags.get("addr:housenumber") or "").strip()
    addr_city  = (tags.get("addr:city") or "").strip()
    addr_state = (tags.get("addr:state") or "").strip()
    addr_zip   = (tags.get("addr:postcode") or "").strip()
    parts: list[str] = []
    if house and street:
        parts.append(f"{house} {street}")
    elif street:
        parts.append(street)
    if addr_city:  parts.append(addr_city)
    if addr_state: parts.append(addr_state)
    if addr_zip:   parts.append(addr_zip)
    address = ", ".join(parts)

    el_type = el.get("type") or ""
    el_id   = el.get("id")
    if el_type and el_id is not None:
        source_url = f"https://www.openstreetmap.org/{el_type}/{el_id}"
    else:
        source_url = ""

    search_url = (
        "https://www.google.com/search?q="
        + urllib.parse.quote_plus(f'"{name}" "{city_state}"')
    )

    if website:
        website_status = "has website but needs cleanup"
    else:
        website_status = "no website found"

    is_corporate = bool(
        tags.get("brand") or tags.get("brand:wikidata") or tags.get("brand:wikipedia")
    )
    is_active = not any(
        k.startswith(("disused:", "abandoned:", "closed:", "demolished:"))
        for k in tags
    )

    evidence_lines = ["Source: OpenStreetMap."]
    if address:
        evidence_lines.append(f"Address: {address}.")
    opening = (tags.get("opening_hours") or "").strip()
    if opening:
        evidence_lines.append(f"Hours: {opening}.")
    if tags.get("brand"):
        evidence_lines.append(f"Brand: {tags['brand']} (may be a franchise — verify).")
    evidence_lines.append(
        "Verify name + contact via Google before any outreach. "
        "OSM data is community-contributed and may be outdated."
    )
    evidence = " ".join(evidence_lines)

    return {
        "business_name":   name,
        "category":        category,
        "city_state":      city_state,
        "website_url":     website,
        "website_status":  website_status,
        "email":           email,
        "phone":           phone,
        "facebook_url":    facebook,
        "instagram_url":   instagram,
        "source_url":      source_url,
        "search_url":      search_url,
        "evidence_notes":  evidence,
        "is_local_service": True,
        "is_active":       is_active,
        "is_corporate":    is_corporate,
    }


# --- Public discover() entry point ------------------------------------

def discover(
    category: str,
    city_state: str,
    count: int = 10,
    website_status_target: str = "any local business",
) -> dict:
    """
    Two-step OSM discovery:
      1. Nominatim resolves "City, State" to a specific OSM relation
         (or way / node) — disambiguating against same-named cities
         in other states.
      2. Overpass returns category-matching businesses scoped to that
         exact relation's area (or a radius around the node, when
         the resolved place isn't a polygon).

    Returns:
      {
        "candidates":    [list of candidate dicts],
        "total_found":   N (raw OSM matches before dedupe),
        "message":       human-readable summary,
        "resolved_city":  parsed city,
        "resolved_state": parsed state (full name),
        "display_name":   Nominatim's full label for the resolved place,
      }

    Honest about coverage: returns as many as OSM had, up to `count`.
    Never pads with stubs. Never invents fields.
    """
    if not category or not category.strip():
        raise ValueError("category is required")
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if count > OVERPASS_MAX_RESULTS:
        count = OVERPASS_MAX_RESULTS

    city, state = _parse_city_state(city_state)

    # Step 1: resolve city to an unambiguous OSM place.
    place = _call_nominatim(city, state)
    area_id = _overpass_area_id(place["osm_type"], place["osm_id"])

    # Step 2: scope Overpass to that area, or fall back to a radius
    # query if the resolved place is a node (no polygon).
    if area_id is not None:
        query = _build_overpass_query_by_area_id(
            category, area_id, max_results=count * 2,
        )
    else:
        try:
            lat = float(place.get("lat") or 0.0)
            lon = float(place.get("lon") or 0.0)
        except (TypeError, ValueError):
            raise OverpassError(
                f"Nominatim returned a node without usable coordinates for "
                f"{city}, {state}."
            )
        query = _build_overpass_query_by_bbox(
            category, lat, lon, radius_m=8000, max_results=count * 2,
        )

    data = _call_overpass(query)
    elements = data.get("elements") or []

    candidates: list[dict] = []
    seen_names: set[str] = set()
    for el in elements:
        cand = _map_to_candidate(el, category, city_state)
        if not cand:
            continue
        key = cand["business_name"].lower().strip()
        if key in seen_names:
            continue
        seen_names.add(key)
        candidates.append(cand)
        if len(candidates) >= count:
            break

    if elements:
        msg = (
            f"OSM returned {len(elements)} matches for "
            f"{category} in {place['display_name']}; "
            f"yielded {len(candidates)} unique-named candidates."
        )
    else:
        msg = (
            f"OSM found no matches for {category} in {place['display_name']}. "
            f"Try a broader category, a larger city, or check spelling."
        )

    return {
        "candidates":    candidates,
        "total_found":   len(elements),
        "message":       msg,
        "resolved_city":  city,
        "resolved_state": state,
        "display_name":   place["display_name"],
        "website_status_target": website_status_target,
    }
