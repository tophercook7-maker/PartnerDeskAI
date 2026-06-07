"""
onboarding.py
-------------
v12.1 Easiest Automated Onboarding. First-time setup that turns an
empty Hub into a ready-to-use office in ~7 conversational steps.

What this module does:
    - Tracks whether onboarding is complete (data/onboarding_state.json)
    - Holds the user's first-pass answers in an agency profile
      (data/agency_profile.json)
    - Orchestrates partner-profile seeding when the user finishes the
      wizard:
        * Sage SEO agency profile + MMS - MixedMakerShop - SEO project
        * Video Partner business profile
        * YouTube Growth channel profile
        * Three starter work items (Audit / Find Leads / Make Promo)
        * One welcome note in the shared document library
    - Reset clears ONLY the completion flag (saved leads, projects,
      reports, documents, work items are all preserved).

Safety perimeter (mirrors every prior version):
    - No publishing. No auto-send. No connections. No live changes.
    - Everything created is draft / review-only.
    - All starter work items carry needs_approval=True so they're
      explicitly waiting on the user before any action.
    - Stdlib only. No new Python dependencies.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH   = ROOT / "data" / "onboarding_state.json"
PROFILE_PATH = ROOT / "data" / "agency_profile.json"


# ======================================================================
# Spec defaults — exactly what the wizard pre-fills each input with.
# Users can override every value.
# ======================================================================

DEFAULT_AGENCY_NAME       = "MixedMakerShop"
DEFAULT_FIRST_WEBSITE     = "https://mixedmakershop.com"
DEFAULT_FREE_OFFER        = "Free homepage mockup"
DEFAULT_PAID_OFFER        = "Starter website fix from $150"
DEFAULT_SEARCH_AREA       = "Hot Springs, AR"

DEFAULT_SERVICES: tuple[str, ...] = (
    "Websites",
    "SEO",
    "Local SEO",
    "Google Business Profile help",
    "Video/content help",
    "Lead generation",
    "Digital business cards / tap hubs",
    "AI systems",
)

DEFAULT_TARGET_CUSTOMERS: tuple[str, ...] = (
    "local service businesses",
    "small business owners",
    "solo operators",
    "churches",
    "makers",
)


def default_answers() -> dict:
    """The dict the UI pre-fills the wizard with. Equivalent to a
    user who clicked Next on every step."""
    return {
        "agency_name":         DEFAULT_AGENCY_NAME,
        "first_website":       DEFAULT_FIRST_WEBSITE,
        "services":            list(DEFAULT_SERVICES),
        "target_customers":    list(DEFAULT_TARGET_CUSTOMERS),
        "free_offer":          DEFAULT_FREE_OFFER,
        "paid_offer":          DEFAULT_PAID_OFFER,
        "default_search_area": DEFAULT_SEARCH_AREA,
    }


# ======================================================================
# IO helpers — atomic writes, defensive reads
# ======================================================================

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def _safe_load(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


# ======================================================================
# State (completion flag + last-saved answers)
# ======================================================================

def load_state() -> dict:
    state = _safe_load(STATE_PATH, None)
    if not isinstance(state, dict):
        return {"complete": False, "completed_at": None, "answers": None}
    state.setdefault("complete",     False)
    state.setdefault("completed_at", None)
    state.setdefault("answers",      None)
    return state


def is_complete() -> bool:
    return bool(load_state().get("complete"))


def save_state(state: dict) -> dict:
    _atomic_write(STATE_PATH, state)
    return state


def reset() -> dict:
    """v12.1: clears ONLY the onboarding completion flag. Saved leads,
    SEO projects, reports, documents, work items, partner profiles are
    all preserved. The next page load will show the wizard again with
    the user's last-saved answers pre-filled."""
    state = load_state()
    state["complete"]     = False
    state["completed_at"] = None
    # Keep the answers around so a re-run pre-fills with what they
    # had before.
    save_state(state)
    return state


# ======================================================================
# Agency profile (sticky — survives reset)
# ======================================================================

def load_agency_profile() -> dict:
    p = _safe_load(PROFILE_PATH, None)
    if not isinstance(p, dict):
        return {}
    return p


def save_agency_profile(answers: dict) -> dict:
    if not isinstance(answers, dict):
        raise ValueError("answers must be a dict")
    existing = load_agency_profile()

    def _str(key, default=""):
        v = answers.get(key, existing.get(key, default))
        return str(v or default).strip()[:1000]

    def _list_str(key, default):
        raw = answers.get(key)
        if not isinstance(raw, list):
            raw = existing.get(key) if isinstance(existing.get(key), list) else default
        out: list[str] = []
        for item in (raw or [])[:50]:
            if isinstance(item, str) and item.strip():
                out.append(item.strip()[:200])
        return out

    profile = {
        "agency_name":         _str("agency_name",         DEFAULT_AGENCY_NAME),
        "first_website":       _str("first_website",       DEFAULT_FIRST_WEBSITE),
        "services":            _list_str("services",       list(DEFAULT_SERVICES)),
        "target_customers":    _list_str("target_customers", list(DEFAULT_TARGET_CUSTOMERS)),
        "free_offer":          _str("free_offer",          DEFAULT_FREE_OFFER),
        "paid_offer":          _str("paid_offer",          DEFAULT_PAID_OFFER),
        "default_search_area": _str("default_search_area", DEFAULT_SEARCH_AREA),
        "created_at":          existing.get("created_at") or _now(),
        "updated_at":          _now(),
    }
    _atomic_write(PROFILE_PATH, profile)
    return profile


# ======================================================================
# Apply — orchestrates partner-profile seeding from answers
# ======================================================================

def _seed_sage(profile: dict) -> dict:
    """Save Sage agency name + ensure MMS project exists with updated
    business_type + website_url. Sage's load_projects() auto-bootstraps
    the MMS project on first call; we then patch it."""
    try:
        import seo_partner as sage
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Agency name
    sage.save_agency({
        "name":         profile["agency_name"],
        "website_url":  profile["first_website"],
        "service_area": profile["default_search_area"],
    })

    # Ensure MMS project exists (bootstrap happens on load).
    projects = sage.load_projects()
    if not projects:
        return {"ok": False, "error": "no SEO projects after bootstrap"}
    mms = projects[0]
    services_str = ", ".join(profile["services"]) or "Web design + SEO"
    sage.update_project(mms["id"], {
        "client_name":    profile["agency_name"],
        "website_url":    profile["first_website"],
        "business_type":  services_str[:200],
        "location":       profile["default_search_area"],
        "main_goal":      (
            "Get more local customers — "
            + ", ".join(profile["target_customers"])[:500]
        ),
    })
    return {"ok": True, "project_id": mms["id"], "project_name": mms["project_name"]}


def _seed_video(profile: dict) -> dict:
    try:
        import video_partner as vp
    except Exception as e:
        return {"ok": False, "error": str(e)}
    services_str = ", ".join(profile["services"]) or "local service business"
    customers_str = ", ".join(profile["target_customers"]) or "local customers"
    vp.save_profile({
        "business_name":   profile["agency_name"],
        "business_type":   services_str[:200],
        "target_customer": customers_str[:200],
        "main_service":    profile["services"][0] if profile["services"] else "Websites",
        "tone":            "friendly and helpful",
        "platforms":       "Facebook Instagram TikTok YouTube",
        "video_length":    "30-60 seconds",
        "call_to_action":  profile["free_offer"],
    })
    return {"ok": True}


def _seed_youtube(profile: dict) -> dict:
    try:
        import youtube_partner as yt
    except Exception as e:
        return {"ok": False, "error": str(e)}
    services_str = ", ".join(profile["services"]) or "small business help"
    customers_str = ", ".join(profile["target_customers"]) or "local customers"
    yt.save_channel({
        "channel_niche":    services_str[:200],
        "target_audience":  customers_str[:200],
        "video_style":      "friendly explainer",
        "tone":             "warm and direct",
        "main_offer_cta":   profile["free_offer"],
        "preferred_length": "5-8 minutes",
        "focus":            "shorts",
    })
    return {"ok": True}


def _seed_team_office(profile: dict, sage_result: dict) -> dict:
    """Create three starter work items + a welcome document so the
    Team Office has something to show day one."""
    try:
        import team_office as to
    except Exception as e:
        return {"ok": False, "error": str(e)}

    work_items: list[dict] = []
    sage_pid = sage_result.get("project_id") if sage_result.get("ok") else None

    # 1. Audit MMS website
    work_items.append(to.create_work_item({
        "title":            f"Run first SEO audit on {profile['agency_name']}",
        "type":             "audit",
        "source_partner":   "olivia",
        "assigned_partner": "sage",
        "related_project_id": sage_pid or "",
        "status":           "new",
        "priority":         "high",
        "summary":          (
            f"Run a structured SEO audit on {profile['first_website']}. "
            "Sage will produce the static-template checklist; you walk it manually."
        ),
        "needs_approval":   True,
    }))

    # 2. Find first local leads
    work_items.append(to.create_work_item({
        "title":            f"Find first local leads in {profile['default_search_area']}",
        "type":             "discover",
        "source_partner":   "olivia",
        "assigned_partner": "logan",
        "status":           "new",
        "priority":         "high",
        "summary":          (
            f"Have Logan discover local prospects in {profile['default_search_area']}. "
            "Real businesses via OSM, plus research missions if coverage is thin. "
            "No outreach until you approve a target."
        ),
        "needs_approval":   True,
    }))

    # 3. Make promo for free homepage mockup
    work_items.append(to.create_work_item({
        "title":            f"Draft promo for {profile['free_offer'].lower()}",
        "type":             "promo",
        "source_partner":   "olivia",
        "assigned_partner": "parker",
        "status":           "new",
        "priority":         "medium",
        "summary":          (
            f"Parker drafts promo copy with the free offer ({profile['free_offer']}) "
            f"and the paid offer ({profile['paid_offer']}) as the call to action. "
            "Review-only — nothing publishes."
        ),
        "needs_approval":   True,
    }))

    # Welcome document.
    doc = to.create_document({
        "title":      f"{profile['agency_name']} starter notes",
        "type":       "notes",
        "created_by": "olivia",
        "shared_with": ["sage", "logan", "parker"],
        "body":       (
            f"Office opened by {profile['agency_name']}.\n"
            f"First website: {profile['first_website']}\n"
            f"Services: {', '.join(profile['services'])}\n"
            f"Target customers: {', '.join(profile['target_customers'])}\n"
            f"Free offer: {profile['free_offer']}\n"
            f"Paid offer: {profile['paid_offer']}\n"
            f"First search area: {profile['default_search_area']}\n\n"
            "Sage, Logan, and Parker have starter work items in the queue.\n"
            "Nothing publishes automatically. Everything is review-only."
        ),
        "status":     "ready",
    })

    return {
        "ok":          True,
        "work_items":  [w["id"] for w in work_items],
        "document_id": doc["id"],
    }


def apply(answers: dict | None = None) -> dict:
    """
    Run the full onboarding pipeline. Idempotent enough that re-running
    overwrites the agency profile but doesn't create duplicate work
    items (we don't dedup work items — re-running creates fresh ones,
    by design; user can delete the old ones).

    Returns a structured summary the UI uses for the success screen.
    """
    answers = answers or {}
    # Fill missing values with defaults.
    merged: dict = default_answers()
    for k, v in answers.items():
        if v is None:
            continue
        merged[k] = v

    # Persist the agency profile first so partner seeders can read it.
    profile = save_agency_profile(merged)

    sage_result = _seed_sage(profile)
    video_result = _seed_video(profile)
    youtube_result = _seed_youtube(profile)
    team_result = _seed_team_office(profile, sage_result)

    state = {
        "complete":     True,
        "completed_at": _now(),
        "answers":      merged,
    }
    save_state(state)

    return {
        "ok":              True,
        "state":           state,
        "profile":         profile,
        "sage":            sage_result,
        "video":           video_result,
        "youtube":         youtube_result,
        "team_office":     team_result,
        # Spec section "Final screen" recommendations.
        "recommendations": [
            f"Have Sage audit {profile['agency_name']}.",
            "Have Logan find local leads.",
            f"Have Parker make a promo for the {profile['free_offer'].lower()}.",
        ],
        "actions": [
            {"label": "Start SEO Audit",    "kind": "do_it_for_me", "partner": "sage"},
            {"label": "Find Leads",         "kind": "do_it_for_me", "partner": "logan"},
            {"label": "Make Promo",         "kind": "do_it_for_me", "partner": "parker"},
            {"label": "Go to Office",       "kind": "scroll",       "target": "team-office-section"},
        ],
        "olivia_summary": (
            f"Your office is ready, Topher. I recommend starting with these three things:\n"
            f"  1. Have Sage audit {profile['agency_name']}.\n"
            f"  2. Have Logan find local leads.\n"
            f"  3. Have Parker make a promo for the {profile['free_offer'].lower()}."
        ),
    }
