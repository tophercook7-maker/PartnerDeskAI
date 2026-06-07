"""
team_office.py
--------------
v11.0 Team Office command system. The shared substrate that turns
PartnerDeskAI's 6 individual partner dashboards into one animated
agency office.

Three responsibilities:

1. Route — keyword-based command parser maps a plain-English user
   request to the right partner and returns a structured action plan.
   Pure local rules — no external AI, no API calls.

2. Reply — each partner has a one-personality reply template so the
   console produces conversational responses without an LLM.

3. Coordinate — work items + shared documents + a persistent console
   message log. Partners hand off work to each other through these.

Safety perimeter (mirrors v10.0):
    - No auto-sending outreach, no auto-publishing, no form submission
    - No OAuth, no paid APIs, no social posting
    - All major actions require user approval (we surface action cards
      with Approve/Reject buttons; nothing fires automatically)
    - No new Python dependencies (stdlib only)
    - All state is local JSON in data/

Data files (gitignored):
    data/team_work_items.json — list of cross-partner work items
    data/team_documents.json  — list of shared documents
    data/team_console.json    — chronological console message log
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
WORK_ITEMS_PATH = ROOT / "data" / "team_work_items.json"
DOCUMENTS_PATH  = ROOT / "data" / "team_documents.json"
CONSOLE_PATH    = ROOT / "data" / "team_console.json"


# ======================================================================
# Partner registry
# ----------------------------------------------------------------------
# Each partner gets: emoji avatar, role label, keywords that route
# commands to them, a default "do it for me" action label, and a
# one-line description for the Ask-partner UI.
# ======================================================================

PARTNERS: dict[str, dict] = {
    "olivia": {
        "name":        "Olivia Office",
        "emoji":       "🗂️",
        "role":        "Office manager / dispatcher",
        "description": "Routes work to the right partner and tracks what to do next.",
        "keywords":    (
            "task", "report", "admin", "follow-up", "follow up",
            "what next", "what should i do", "next", "show me",
            "everyone", "everyone is", "team", "summary", "status",
            "what's", "what is",
        ),
        "do_it_label": "Tell Me What To Do Next",
    },
    "logan": {
        "name":        "Logan Leads",
        "emoji":       "📍",
        "role":        "Lead generation",
        "description": "Finds local-business prospects, enriches them, scores fit, prepares outreach.",
        "keywords":    (
            "lead", "leads", "prospect", "prospects", "client",
            "clients", "discover", "find", "outreach", "csv",
            "import", "candidates",
        ),
        "do_it_label": "Find Leads For Me",
    },
    "sage": {
        "name":        "Sage SEO Partner",
        "emoji":       "🔎",
        "role":        "SEO + Local SEO manager",
        "description": "Generates audits, tracks fix tasks, prepares monthly reports for client SEO projects.",
        "keywords":    (
            "seo", "audit", "rank", "google", "local seo", "local",
            "title", "meta", "heading", "alt text", "gbp",
            "business profile", "monthly report", "report", "sage",
            "fix", "fixes", "approval",
        ),
        "do_it_label": "Start SEO Audit For Me",
    },
    "parker": {
        "name":        "Parker Promo",
        "emoji":       "📣",
        "role":        "Promotions / marketing",
        "description": "Drafts promo copy, social posts, and offer-driven announcements.",
        "keywords":    (
            "promo", "ad", "ads", "offer", "facebook", "post",
            "posts", "marketing", "campaign copy", "announcement",
            "parker", "promote",
        ),
        "do_it_label": "Make Promo For Me",
    },
    "video": {
        "name":        "Video Partner",
        "emoji":       "🎬",
        "role":        "Video / content campaigns",
        "description": "Generates short-form scripts, shot lists, captions, and full video campaigns.",
        "keywords":    (
            "video", "script", "caption", "captions", "shot list",
            "campaign", "reels", "tiktok", "short", "video partner",
            "ad script",
        ),
        "do_it_label": "Make Video Campaign For Me",
    },
    "youtube": {
        "name":        "YouTube Growth Partner",
        "emoji":       "▶️",
        "role":        "YouTube growth",
        "description": "Generates video ideas, titles, hooks, thumbnails, and channel concepts.",
        "keywords":    (
            "youtube", "channel", "title", "thumbnail", "outlier",
            "hook", "video ideas", "growth", "youtube growth",
            "shorts",
        ),
        "do_it_label": "Find Video Ideas For Me",
    },
}

# Stable display order in the UI: dispatcher first.
PARTNER_ORDER = ("olivia", "logan", "sage", "parker", "video", "youtube")


# ======================================================================
# v12.0 — Voices: per-partner personality so replies feel like coworkers.
# Pure local strings; no external AI. Choices rotate deterministically
# off the request length so the same prompt yields a stable reply but
# different prompts feel varied.
# ======================================================================

_VOICES: dict[str, dict] = {
    "olivia": {
        "openers":   ("Hey,", "OK,", "Got it,", "Right,"),
        "sign_offs": (
            "I'll keep watching the team.",
            "Holler when you need me.",
            "I'll stay on dispatch.",
        ),
        # How Olivia hands work off to another partner. {partner_first}
        # = first word of partner name; {user_text} = the user's request
        # cleaned for echoing.
        "handoffs":  (
            "Hey {partner_first}, Topher's asking about this — can you take it?",
            "{partner_first}, this one's yours. Topher wants {short_intent}.",
            "Looping {partner_first} in — Topher's request: {short_intent}.",
        ),
        # Friendly observational lines for the desk chatter.
        "idle_chatter":   ("watching the board", "sipping coffee", "on dispatch"),
        "active_chatter": ("routing {n} item{s}", "triaging the queue"),
    },
    "logan": {
        "openers":   ("Right —", "OK so,", "Looking at it,", "On it."),
        "sign_offs": (
            "I'll keep ranking.",
            "Holler when you've got a target.",
            "I'll be at my desk.",
        ),
        "ack_olivia": (
            "Got it, Olivia.",
            "On it, Olivia.",
            "Thanks, Olivia.",
        ),
        # Mentions of other partners — used occasionally for banter.
        "banter_about": {
            "parker": "Once I've ranked a few, Parker can draft the first outreach.",
            "sage":   "If you want SEO context on any of these, Sage can fold it in.",
        },
        "idle_chatter":   ("queue is quiet", "scanning OSM"),
        "active_chatter": ("ranking {n} candidate{s}", "lining up {n} lead{s}"),
    },
    "sage": {
        "openers":   ("OK,", "Let me think.", "Here's what I'd do —", "Got it."),
        "sign_offs": (
            "Ready when you are.",
            "Want me to lay out step one?",
            "Tell me when to start.",
        ),
        "ack_olivia": (
            "Got it, Olivia.",
            "On it, Olivia.",
            "Thanks, Olivia — taking this.",
        ),
        "banter_about": {
            "parker": "Once the audit's done, Parker can turn the wins into a promo.",
            "video":  "If you want a quick video angle from the SEO wins, Video Partner can scriptify.",
        },
        "idle_chatter":   ("reviewing the checklist", "watching for new projects"),
        "active_chatter": ("{n} fix{es} waiting approval", "auditing the checklist"),
    },
    "parker": {
        "openers":   ("Oh nice —", "Yeah —", "Love this.", "OK got it."),
        "sign_offs": (
            "I can riff on it more if you want.",
            "Want me to keep going?",
            "Tell me when to push it.",
        ),
        "ack_olivia": (
            "On it, Olivia!",
            "Got it, O — drafting.",
            "Yep — thanks, Olivia.",
        ),
        "banter_about": {
            "video":   "If you want this as a short clip too, Video Partner can scriptify.",
            "logan":   "If Logan has a list ready, I'll draft outreach off it.",
        },
        "idle_chatter":   ("noodling on hooks", "watching the deck"),
        "active_chatter": ("{n} draft{s} ready for you", "polishing the angle"),
    },
    "video": {
        "openers":   ("Hmm,", "OK so picture this —", "Got it.", "Right."),
        "sign_offs": (
            "Want a shot list too?",
            "Let me know the vibe.",
            "I'll be in the edit bay.",
        ),
        "ack_olivia": (
            "On it, Olivia.",
            "Got it, O.",
            "Thanks, Olivia.",
        ),
        "banter_about": {
            "youtube": "YouTube Growth can pull title ideas from the same angle.",
            "parker":  "If Parker already has the promo, I'll script straight off it.",
        },
        "idle_chatter":   ("storyboarding in my head", "watching for a topic"),
        "active_chatter": ("{n} script{s} on the desk", "drafting the shot list"),
    },
    "youtube": {
        "openers":   ("Right.", "Looking at it,", "Here's the angle —", "Got it."),
        "sign_offs": (
            "Want me to draft three titles?",
            "Let me know the hook.",
            "I'll keep an eye on the channel.",
        ),
        "ack_olivia": (
            "Got it, Olivia.",
            "On it, Olivia.",
            "Thanks, O.",
        ),
        "banter_about": {
            "video":  "If you want one made into a short, Video Partner can take it from here.",
            "parker": "Parker can repurpose the title for promo copy if you want.",
        },
        "idle_chatter":   ("watching for video ideas", "scanning hooks"),
        "active_chatter": ("{n} package{s} drafted", "noodling on titles"),
    },
}


def _pick(seq, key: str) -> str:
    """Deterministic pick from a sequence given a hash-friendly key.
    Identical keys produce identical picks (so the same prompt feels
    consistent), different keys feel varied."""
    if not seq:
        return ""
    idx = sum(ord(c) for c in (key or "x")) % len(seq)
    return seq[idx]


def _partner_first(partner_id: str) -> str:
    name = PARTNERS.get(partner_id, {}).get("name", partner_id)
    return name.split(" ", 1)[0]


def _short_intent(text: str, max_words: int = 8) -> str:
    """Compress the user's request to a short echo for handoffs.
    Lowercases the leading verb so the embedded line reads naturally
    (e.g. "Topher wants leads on lawn care" not "Topher wants Find me")."""
    words = (text or "").strip().split()
    if not words:
        return "something"
    trimmed_words = list(words[:max_words])
    if trimmed_words:
        first = trimmed_words[0]
        # Lowercase the first word unless it's clearly a proper noun
        # (starts with a capital AND its rest already has a capital).
        if first[0].isupper() and not any(c.isupper() for c in first[1:]):
            trimmed_words[0] = first.lower()
    trimmed = " ".join(trimmed_words)
    return trimmed.rstrip(".!?")


# ======================================================================
# Enums + caps
# ======================================================================

WORK_ITEM_STATUSES = (
    "new", "assigned", "in_progress", "waiting_approval",
    "completed", "rejected",
)
DEFAULT_WORK_ITEM_STATUS = "new"

WORK_ITEM_PRIORITIES = ("low", "medium", "high", "urgent")
DEFAULT_WORK_ITEM_PRIORITY = "medium"

DOCUMENT_TYPES = (
    "lead_list", "seo_audit", "seo_report", "promo_copy",
    "outreach_draft", "video_script", "campaign_package",
    "monthly_report", "notes", "next_actions",
)
DOCUMENT_STATUSES = ("draft", "ready", "shared", "archived")
DEFAULT_DOCUMENT_STATUS = "draft"

MESSAGE_ROLES = ("user", "olivia", "logan", "sage", "parker", "video", "youtube", "system")

MAX_TITLE       = 200
MAX_SUMMARY     = 2000
MAX_BODY        = 16000
MAX_TEXT        = 4000
MAX_PAYLOAD     = 16000
MAX_MESSAGES    = 200    # console message ring buffer
MAX_WORK_ITEMS  = 500
MAX_DOCUMENTS   = 500


# ======================================================================
# Time + ID + IO helpers
# ======================================================================

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(items: list[dict] | None) -> str:
    base = str(int(time.time() * 1000))
    existing = {it.get("id") for it in (items or [])}
    cand = base
    n = 0
    while cand in existing:
        n += 1
        cand = f"{base}-{n}"
    return cand


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
# Console message log
# ======================================================================

def _clean_message(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("message must be a dict")
    role = str(raw.get("role") or "system").strip().lower()
    if role not in MESSAGE_ROLES:
        role = "system"
    return {
        "id":        raw.get("id"),
        "role":      role,
        "partner":   str(raw.get("partner") or role)[:50],
        "text":      str(raw.get("text") or "")[:MAX_TEXT],
        "actions":   raw.get("actions") if isinstance(raw.get("actions"), list) else [],
        "work_item_ids": list(raw.get("work_item_ids") or []),
        "document_ids":  list(raw.get("document_ids") or []),
        "created_at": raw.get("created_at") or _now(),
    }


def load_messages() -> list[dict]:
    data = _safe_load(CONSOLE_PATH, None)
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return list(items) if isinstance(items, list) else []


def _save_messages(items: list[dict]) -> None:
    # Ring buffer — keep at most MAX_MESSAGES.
    if len(items) > MAX_MESSAGES:
        items = items[-MAX_MESSAGES:]
    _atomic_write(CONSOLE_PATH, {"items": items})


def append_message(raw: dict) -> dict:
    items = load_messages()
    cleaned = _clean_message(raw)
    cleaned["id"] = _next_id(items)
    items.append(cleaned)
    _save_messages(items)
    return cleaned


def clear_console() -> dict:
    """v11.0 spec section 14: clears ONLY the console state. Leads,
    SEO projects, reports, documents, work items, partner data are
    all preserved."""
    _atomic_write(CONSOLE_PATH, {"items": []})
    return {"ok": True, "cleared": "console"}


# ======================================================================
# Work items
# ======================================================================

def _clean_work_item(raw: dict, existing: dict | None = None) -> dict:
    ex = existing or {}
    if not isinstance(raw, dict):
        raise ValueError("work item must be a dict")
    def _pick(k):
        return raw.get(k, ex.get(k))
    title = str(_pick("title") or "").strip()[:MAX_TITLE]
    if not title:
        raise ValueError("work_item.title is required")
    status = str(_pick("status") or DEFAULT_WORK_ITEM_STATUS).strip().lower()
    if status not in WORK_ITEM_STATUSES:
        raise ValueError(
            f"work_item.status must be one of {WORK_ITEM_STATUSES}"
        )
    priority = str(_pick("priority") or DEFAULT_WORK_ITEM_PRIORITY).strip().lower()
    if priority not in WORK_ITEM_PRIORITIES:
        priority = DEFAULT_WORK_ITEM_PRIORITY
    type_ = str(_pick("type") or "task").strip()[:50]
    source = str(_pick("source_partner") or "").strip().lower()
    assigned = str(_pick("assigned_partner") or "").strip().lower()
    related = _pick("related_partner_ids") or []
    if not isinstance(related, list):
        related = []
    payload = _pick("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "id":                  ex.get("id") or raw.get("id"),
        "title":               title,
        "type":                type_,
        "source_partner":      source,
        "assigned_partner":    assigned,
        "related_partner_ids": [str(p)[:50] for p in related[:10]],
        "related_project_id":  str(_pick("related_project_id") or "")[:100] or None,
        "related_lead_id":     str(_pick("related_lead_id") or "")[:100] or None,
        "status":              status,
        "priority":            priority,
        "summary":             str(_pick("summary") or "")[:MAX_SUMMARY],
        "payload":             {k: str(v)[:MAX_PAYLOAD] if isinstance(v, str) else v
                                  for k, v in payload.items()},
        "needs_approval":      bool(_pick("needs_approval")),
        "created_at":          ex.get("created_at") or _now(),
        "updated_at":          _now(),
    }


def load_work_items() -> list[dict]:
    data = _safe_load(WORK_ITEMS_PATH, None)
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return list(items) if isinstance(items, list) else []


def _save_work_items(items: list[dict]) -> None:
    if len(items) > MAX_WORK_ITEMS:
        items = items[-MAX_WORK_ITEMS:]
    _atomic_write(WORK_ITEMS_PATH, {"items": items})


def create_work_item(raw: dict) -> dict:
    items = load_work_items()
    cleaned = _clean_work_item(raw)
    cleaned["id"] = _next_id(items)
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    items.append(cleaned)
    _save_work_items(items)
    return cleaned


def list_work_items(
    status: str | None = None,
    partner: str | None = None,
) -> list[dict]:
    items = load_work_items()
    if status:
        items = [it for it in items if (it.get("status") or "") == status]
    if partner:
        items = [it for it in items
                 if (it.get("assigned_partner") == partner
                     or it.get("source_partner") == partner
                     or partner in (it.get("related_partner_ids") or []))]
    return items


def update_work_item(wid: str, raw: dict) -> dict:
    items = load_work_items()
    for i, it in enumerate(items):
        if it.get("id") == wid:
            merged = _clean_work_item(raw, existing=it)
            merged["id"] = wid
            items[i] = merged
            _save_work_items(items)
            return merged
    raise KeyError(wid)


def update_work_item_status(wid: str, status: str) -> dict:
    return update_work_item(wid, {"status": status})


# ======================================================================
# Shared documents
# ======================================================================

def _clean_document(raw: dict, existing: dict | None = None) -> dict:
    ex = existing or {}
    if not isinstance(raw, dict):
        raise ValueError("document must be a dict")
    def _pick(k):
        return raw.get(k, ex.get(k))
    title = str(_pick("title") or "").strip()[:MAX_TITLE]
    if not title:
        raise ValueError("document.title is required")
    type_ = str(_pick("type") or "notes").strip().lower()
    if type_ not in DOCUMENT_TYPES:
        type_ = "notes"
    status = str(_pick("status") or DEFAULT_DOCUMENT_STATUS).strip().lower()
    if status not in DOCUMENT_STATUSES:
        status = DEFAULT_DOCUMENT_STATUS
    created_by = str(_pick("created_by") or "").strip().lower()
    shared_with = _pick("shared_with") or []
    if not isinstance(shared_with, list):
        shared_with = []
    return {
        "id":                  ex.get("id") or raw.get("id"),
        "title":               title,
        "type":                type_,
        "created_by":          created_by[:50],
        "shared_with":         [str(p).strip().lower()[:50] for p in shared_with[:10] if p],
        "related_work_item_id": str(_pick("related_work_item_id") or "")[:100] or None,
        "related_project_id":  str(_pick("related_project_id") or "")[:100] or None,
        "related_lead_id":     str(_pick("related_lead_id") or "")[:100] or None,
        "body":                str(_pick("body") or "")[:MAX_BODY],
        "status":              status,
        "created_at":          ex.get("created_at") or _now(),
        "updated_at":          _now(),
    }


def load_documents() -> list[dict]:
    data = _safe_load(DOCUMENTS_PATH, None)
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return list(items) if isinstance(items, list) else []


def _save_documents(items: list[dict]) -> None:
    if len(items) > MAX_DOCUMENTS:
        items = items[-MAX_DOCUMENTS:]
    _atomic_write(DOCUMENTS_PATH, {"items": items})


def create_document(raw: dict) -> dict:
    items = load_documents()
    cleaned = _clean_document(raw)
    cleaned["id"] = _next_id(items)
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    items.append(cleaned)
    _save_documents(items)
    return cleaned


def list_documents(
    partner: str | None = None,
    type_: str | None = None,
) -> list[dict]:
    items = load_documents()
    if partner:
        items = [it for it in items
                 if it.get("created_by") == partner
                    or partner in (it.get("shared_with") or [])]
    if type_:
        items = [it for it in items if it.get("type") == type_]
    return items


def share_document(doc_id: str, partner_id: str) -> dict:
    partner_id = (partner_id or "").strip().lower()
    if partner_id not in PARTNERS:
        raise ValueError(f"unknown partner {partner_id!r}")
    items = load_documents()
    for i, it in enumerate(items):
        if it.get("id") == doc_id:
            shared = list(it.get("shared_with") or [])
            if partner_id not in shared:
                shared.append(partner_id)
            it["shared_with"] = shared
            it["status"] = "shared"
            it["updated_at"] = _now()
            items[i] = it
            _save_documents(items)
            return it
    raise KeyError(doc_id)


# ======================================================================
# Command router
# ======================================================================

def _detect_partner(text: str) -> tuple[str, list[str]]:
    """
    Score keyword hits per partner, return (best_partner, all_partners_hit).
    Default to 'olivia' as the dispatcher when no keywords match.
    Returns the secondary partners list when 2+ score above threshold
    (used to build multi-partner workflows).
    """
    t = (text or "").lower()
    hits: dict[str, int] = {}
    for pid, meta in PARTNERS.items():
        score = 0
        for kw in meta["keywords"]:
            if kw in t:
                # Weight longer phrases higher so "monthly report" beats "report"
                score += max(1, len(kw.split()))
        if score:
            hits[pid] = score
    if not hits:
        return "olivia", []
    # Sort descending by score.
    ordered = sorted(hits, key=lambda p: hits[p], reverse=True)
    primary = ordered[0]
    # Secondary = partners with at least half the top score (only if >1 partner).
    threshold = max(1, hits[primary] // 2)
    secondary = [p for p in ordered[1:] if hits[p] >= threshold]
    return primary, secondary


def _olivia_next_actions_text() -> tuple[str, list[dict]]:
    """
    Pull the spec-required signals across partners and return a ranked
    3-item next-actions list as text + action cards.

    Defensive: each subsystem is imported inside the function so the
    Team Office doesn't fail to load if a partner module is broken.
    """
    ranked: list[tuple[int, str, dict]] = []  # (priority_int, text, action_card)
    # Logan signals
    try:
        import leads as _leads
        all_leads = _leads.load()
        ready = [l for l in all_leads
                 if (l.get("outreach_status") or "") == "outreach_ready"]
        contacted_pending = [l for l in all_leads
                              if (l.get("outreach_status") or "") == "contacted"]
        if ready:
            ranked.append((10,
                f"Send outreach to {ready[0].get('name', 'your top lead')} — Logan already drafted it.",
                {"label": "Open Logan", "kind": "scroll", "target": "logan-details"}))
        elif contacted_pending:
            ranked.append((5,
                f"Follow up with {contacted_pending[0].get('name', 'your contacted lead')} — they're past their follow-up date.",
                {"label": "Open Logan", "kind": "scroll", "target": "logan-details"}))
    except Exception:
        pass
    # Sage signals
    try:
        import seo_partner as _sp
        queue = _sp.list_approval_queue()
        if queue:
            top = queue[0]
            ranked.append((9,
                f"Approve Sage's {top.get('severity', 'high')}-priority fix: "
                f"{top.get('issue', 'website fix')} in {top.get('project_name', 'MMS')}.",
                {"label": "Open Sage", "kind": "scroll", "target": "sage-details"}))
        # Reports due (no report this month)
        projects = _sp.load_projects()
        if projects:
            mms = projects[0]
            reports = _sp.list_reports(mms.get("id", ""))
            current_month = datetime.now().strftime("%Y-%m")
            has_this_month = any((r.get("month") or "") == current_month for r in reports)
            if not has_this_month:
                ranked.append((4,
                    f"Generate this month's SEO report for {mms.get('project_name', 'MMS')}.",
                    {"label": "Open Sage", "kind": "scroll", "target": "sage-details"}))
    except Exception:
        pass
    # Parker signals — drafts pending approval
    try:
        import youtube_partner as _yt
        packages = _yt.load_packages()
        drafts = [p for p in packages if (p.get("status") or "") == "draft"]
        if drafts:
            ranked.append((3,
                f"Review {len(drafts)} draft content package{'s' if len(drafts) != 1 else ''} waiting in YouTube Growth.",
                {"label": "Open YouTube", "kind": "scroll", "target": "youtube-details"}))
    except Exception:
        pass
    # Work items waiting approval
    try:
        waiting = list_work_items(status="waiting_approval")
        if waiting:
            ranked.append((7,
                f"{len(waiting)} team work item{'s' if len(waiting) != 1 else ''} waiting your approval.",
                {"label": "View work queue", "kind": "scroll", "target": "team-office-section"}))
    except Exception:
        pass

    ranked.sort(key=lambda r: -r[0])
    top = ranked[:3]
    if not top:
        text = (
            "Looks calm right now. Three things you could do:\n"
            "  1. Run Logan — Find Leads For Me — to bring in new prospects.\n"
            "  2. Have Sage start an SEO audit on MixedMakerShop.\n"
            "  3. Ask Parker to draft a promo for the free homepage mockup."
        )
        actions = [
            {"label": "Find Leads For Me",      "kind": "do_it_for_me", "partner": "logan"},
            {"label": "Start SEO Audit For Me", "kind": "do_it_for_me", "partner": "sage"},
            {"label": "Make Promo For Me",      "kind": "do_it_for_me", "partner": "parker"},
        ]
        return text, actions
    bullets = "\n".join(f"  {i+1}. {t[1]}" for i, t in enumerate(top))
    text = f"Top {len(top)} things to do next:\n{bullets}"
    return text, [t[2] for t in top]


def _voice(partner_id: str) -> dict:
    return _VOICES.get(partner_id, _VOICES["olivia"])


def _wrap_with_voice(
    partner_id: str,
    body: str,
    text: str,
    handoff_from: str | None = None,
    add_banter_for: str | None = None,
) -> str:
    """
    Wrap the partner's body text with their personality:
      - opener (or olivia-ack if this is a handoff reply)
      - body
      - optional banter mentioning another partner
      - sign-off

    This is what makes replies feel like coworkers instead of buttons.
    """
    v = _voice(partner_id)
    parts: list[str] = []
    if handoff_from == "olivia":
        # Receiving partner addresses Olivia first, then the user.
        ack = _pick(v.get("ack_olivia") or v.get("openers") or ("",), text or "x")
        if ack:
            parts.append(f"{ack} Topher — {body}")
        else:
            parts.append(body)
    else:
        opener = _pick(v.get("openers") or ("",), text or "x")
        if opener:
            parts.append(f"{opener} {body}")
        else:
            parts.append(body)
    # Banter: occasional mention of another partner. Triggered by a
    # context flag; the secondary-partner thread in route_command()
    # sets this for the primary partner so the conversation feels
    # collaborative.
    if add_banter_for:
        banter = (v.get("banter_about") or {}).get(add_banter_for)
        if banter:
            parts.append(banter)
    sign = _pick(v.get("sign_offs") or ("",), text or "x")
    if sign:
        parts.append(sign)
    return "\n\n".join(parts)


def partner_reply(
    partner_id: str,
    text: str,
    context: dict | None = None,
) -> dict:
    """
    Generate a personality-tuned reply from the named partner.
    Returns {partner, response_text, actions}.

    v12.0: replies pass through _wrap_with_voice() so each partner
    has their own opener, sign-off, and (when context indicates a
    handoff or collaboration) banter mentioning another partner.

    context (optional):
      handoff_from: partner_id of who's handing this off (typically
                    'olivia'); the receiving partner addresses them.
      banter_about: partner_id to mention in passing — usually the
                    secondary partner in a multi-partner workflow.
    """
    partner_id = (partner_id or "olivia").strip().lower()
    if partner_id not in PARTNERS:
        partner_id = "olivia"
    meta = PARTNERS[partner_id]
    ctx = context or {}
    t_low = (text or "").lower()

    actions: list[dict] = []
    body: str
    if partner_id == "olivia":
        if any(k in t_low for k in ("next", "what should", "what's up", "show me")):
            body, actions = _olivia_next_actions_text()
        elif ctx.get("greeting"):
            body = ctx["greeting"]
        else:
            primary, secondary = _detect_partner(text)
            if primary == "olivia":
                body = (
                    "if you tell me what you want done — find leads, "
                    "run an SEO audit, draft a promo — I'll point it at "
                    "the right partner."
                )
            else:
                # v12.0: Olivia's handoff is a true conversation move.
                handoff_tmpl = _pick(_voice("olivia").get("handoffs") or ("",), text or "x")
                body = handoff_tmpl.format(
                    partner_first=_partner_first(primary),
                    short_intent=_short_intent(text),
                )
                actions.append({
                    "label":  f"Send to {PARTNERS[primary]['name']}",
                    "kind":   "ask_partner",
                    "partner": primary,
                    "prompt":  text,
                })
    elif partner_id == "logan":
        try:
            import lead_candidates as _lc
            picks = _lc.compute_picks(k=3)
            count = len(picks)
        except Exception:
            count = 0
        if count > 0:
            top_name = (picks[0].get("business_name") or "your top lead")
            body = (
                f"I've got {count} ranked candidate{'s' if count != 1 else ''} "
                f"on my desk. Strongest is {top_name}. Want me to keep "
                f"finding more, or take action on one of these?"
            )
            actions.append({"label": "Open Logan", "kind": "scroll", "target": "logan-details"})
        else:
            body = (
                "queue is empty right now. Throw me a business type and a "
                "city and I'll go pull real businesses from OpenStreetMap "
                "— if coverage is thin in that area I'll top up with "
                "research missions so you're never staring at nothing."
            )
            actions.append({"label": "Find Leads For Me", "kind": "do_it_for_me", "partner": "logan"})
    elif partner_id == "sage":
        if "first" in t_low or "start" in t_low or "begin" in t_low:
            body = (
                "for MixedMakerShop, here's the order I'd take it:\n"
                "  1. Generate the SEO audit.\n"
                "  2. Walk the failed or unknown items.\n"
                "  3. Turn the important ones into fix tasks.\n"
                "  4. Approve the fixes you actually want done.\n"
                "  5. Spin up a monthly report when work is in."
            )
            actions.append({"label": "Start SEO Audit For Me", "kind": "do_it_for_me", "partner": "sage"})
        elif "audit" in t_low:
            body = (
                "I'll spin up a basic SEO audit — titles, headings, "
                "service clarity, local signals, and what needs your "
                "approval before it ships. Nothing touches the live site "
                "or Google Business Profile."
            )
            actions.append({"label": "Start SEO Audit For Me", "kind": "do_it_for_me", "partner": "sage"})
        elif "report" in t_low or "monthly" in t_low:
            body = (
                "I can pull a client-friendly monthly report from the "
                "current project — what we checked, what we fixed, the "
                "wins, what's still open, and what I'd do next."
            )
            actions.append({"label": "Open Sage", "kind": "scroll", "target": "sage-details"})
        else:
            body = (
                "I run SEO audits, local SEO, website fix tasks, the "
                "approval queue, and monthly reports. Ask me to start an "
                "audit or what to do first if you want a clean entry point."
            )
            actions.append({"label": "Open Sage", "kind": "scroll", "target": "sage-details"})
    elif partner_id == "parker":
        body = (
            "I can spin this into a friendly promo — the free offer "
            "stays as a homepage mockup, not free fixes. I'll draft you "
            "copy and you'll get to review it before it goes anywhere."
        )
        actions.append({"label": "Make Promo For Me", "kind": "do_it_for_me", "partner": "parker"})
        actions.append({"label": "Open Parker", "kind": "scroll", "target": "parker-details"})
    elif partner_id == "video":
        body = (
            "I can put together a short script from that offer and stage "
            "it for your review. Reels, TikTok, YouTube Shorts — pick the "
            "format. Nothing publishes automatically."
        )
        actions.append({"label": "Make Video Campaign For Me", "kind": "do_it_for_me", "partner": "video"})
        actions.append({"label": "Open Video Partner", "kind": "scroll", "target": "video-details"})
    elif partner_id == "youtube":
        body = (
            "I can spin this into title ideas, hooks, and a clean video "
            "concept. Approval-based — I prep, you decide what gets made."
        )
        actions.append({"label": "Find Video Ideas For Me", "kind": "do_it_for_me", "partner": "youtube"})
        actions.append({"label": "Open YouTube Growth", "kind": "scroll", "target": "youtube-details"})
    else:
        body = "(no reply template registered for this partner yet)"

    # v12.0: wrap the body in the partner's voice (opener + sign-off,
    # and a handoff ack when this is a routed message).
    response = _wrap_with_voice(
        partner_id,
        body,
        text,
        handoff_from=ctx.get("handoff_from"),
        add_banter_for=ctx.get("banter_about"),
    )

    return {
        "partner":       partner_id,
        "partner_name":  meta["name"],
        "partner_emoji": meta["emoji"],
        "response_text": response,
        "actions":       actions,
    }


def route_command(text: str) -> dict:
    """
    Main entry from POST /api/team-office/command.

    Pipeline:
        1. Append the user's message to the console log.
        2. Detect the primary partner via keyword scoring.
        3. Generate the primary partner's reply.
        4. If 2+ partners hit, also generate Olivia's routing note.
        5. Append every partner reply to the console log.
        6. Return the structured result.

    Returns:
        {
          chosen_partner,
          intent,
          response_text,
          suggested_actions,
          created_work_items,
          created_documents,
          messages,  # all appended messages, ready for UI render
        }
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("command text is required")

    # 1. User message
    user_msg = append_message({
        "role":    "user",
        "partner": "user",
        "text":    text,
    })

    # 2. Detect partner
    primary, secondary = _detect_partner(text)
    intent = _classify_intent(text)

    appended: list[dict] = [user_msg]
    has_handoff = bool(secondary) and primary != "olivia"

    # 3. v12.0 — visible delegation. Olivia speaks first as dispatcher
    # with a real handoff line ("Hey Logan, Topher's asking about ..."),
    # AND the primary partner addresses Olivia in their reply.
    if has_handoff:
        olivia_reply = partner_reply("olivia", text)
        msg = append_message({
            "role":    "olivia",
            "partner": "olivia",
            "text":    olivia_reply["response_text"],
            "actions": olivia_reply["actions"],
        })
        appended.append(msg)

    # 4. Primary partner reply — receives the handoff if Olivia spoke
    # first, and gets banter context so they mention the secondary.
    primary_ctx = {}
    if has_handoff:
        primary_ctx["handoff_from"] = "olivia"
    if secondary:
        primary_ctx["banter_about"] = secondary[0]
    primary_reply = partner_reply(primary, text, context=primary_ctx)
    msg = append_message({
        "role":    primary,
        "partner": primary,
        "text":    primary_reply["response_text"],
        "actions": primary_reply["actions"],
    })
    appended.append(msg)

    # 5. v12.0 — secondary partners chime in as natural collaborators,
    # not "I can help too." Use a single-line preview of their reply,
    # without the heavy opener/sign-off so it reads like a quick aside.
    for sec_id in secondary:
        if sec_id == primary:
            continue
        sec_reply = partner_reply(sec_id, text)
        # First non-empty line of the wrapped reply — keeps the voice.
        first_line = next(
            (ln.strip() for ln in sec_reply["response_text"].split("\n") if ln.strip()),
            sec_reply["response_text"],
        )
        msg = append_message({
            "role":    sec_id,
            "partner": sec_id,
            "text":    first_line,
            "actions": sec_reply["actions"][:1],  # one action only
        })
        appended.append(msg)

    return {
        "chosen_partner":     primary,
        "secondary_partners": secondary,
        "intent":             intent,
        "response_text":      primary_reply["response_text"],
        "suggested_actions":  primary_reply["actions"],
        "created_work_items": [],   # router doesn't auto-create — actions do
        "created_documents":  [],
        "messages":           appended,
    }


def _classify_intent(text: str) -> str:
    """Coarse intent label for the response payload (not used for
    routing — routing uses keyword scores)."""
    t = (text or "").lower()
    if any(k in t for k in ("what next", "what should", "show me", "status")):
        return "status_query"
    if any(k in t for k in ("find", "discover", "get me", "show me")):
        return "discover"
    if any(k in t for k in ("audit", "check", "review")):
        return "audit"
    if any(k in t for k in ("make", "create", "draft", "write", "generate")):
        return "create"
    if any(k in t for k in ("approve", "ship", "send")):
        return "approve"
    if any(k in t for k in ("report", "monthly")):
        return "report"
    return "question"


# ======================================================================
# Summary endpoint — desk states for the UI
# ======================================================================

def _desk_chatter(pid: str, task_count: int, status: str) -> str:
    """
    v12.0: a one-line ambient activity string under each desk.
    Empty string falls back to the partner's idle chatter list.
    """
    v = _voice(pid)
    if status == "idle" or task_count == 0:
        seq = v.get("idle_chatter") or ()
    else:
        seq = v.get("active_chatter") or ()
    if not seq:
        return ""
    # Stable per-day variation so the chatter feels fresh but not
    # frantic.
    key = f"{pid}-{datetime.now().strftime('%Y-%m-%d')}-{task_count}"
    tmpl = _pick(seq, key)
    s = "s" if task_count != 1 else ""
    # Some active-chatter templates use {es} for the {fix} plural.
    es = "es" if task_count != 1 else ""
    return tmpl.format(n=task_count, s=s, es=es)


def office_greeting() -> str:
    """v12.0: time-aware Olivia greeting for the empty console state.
    Pure text — no API calls."""
    hour = datetime.now().hour
    if hour < 5:
        time_word = "late night"
        opener = "still up?"
    elif hour < 12:
        time_word = "morning"
        opener = "morning."
    elif hour < 17:
        time_word = "afternoon"
        opener = "afternoon."
    elif hour < 22:
        time_word = "evening"
        opener = "evening."
    else:
        time_word = "late evening"
        opener = "evening."
    return (
        f"{opener.capitalize()} Topher — I'm watching the team. "
        f"Tell me what you want done and I'll point it at the right "
        f"partner. If you're not sure where to start, just say "
        f"\"what should I do next?\""
    )


def office_suggestion_chips() -> list[str]:
    """v12.0: a tiny set of one-tap suggestions for the empty console.
    Picks live next to the greeting."""
    return [
        "What should I do next?",
        "Find me leads",
        "Have Sage audit MixedMakerShop",
        "Show me what everyone is working on",
    ]


def summary() -> dict:
    """
    One-shot UI payload: every partner's desk status + task count.
    Lazy-imports each partner module so a broken partner doesn't crash
    the whole Team Office.

    v12.0: each desk also carries an ambient `chatter` line so the
    office feels alive. The response includes a top-level `greeting`
    and `suggestion_chips` so the UI can render the empty-state
    welcome without a second call.
    """
    desks: list[dict] = []
    for pid in PARTNER_ORDER:
        meta = PARTNERS[pid]
        # Compute task count per partner using a forgiving heuristic.
        task_count = 0
        status = "idle"
        try:
            if pid == "olivia":
                # Olivia owns the cross-partner queue.
                task_count = len(list_work_items(status="waiting_approval"))
                status = "thinking" if task_count else "idle"
            elif pid == "logan":
                import lead_candidates as _lc
                task_count = len(_lc.compute_picks(k=10))
                status = "active" if task_count else "idle"
            elif pid == "sage":
                import seo_partner as _sp
                task_count = len(_sp.list_approval_queue())
                status = "waiting" if task_count else "idle"
            elif pid == "parker":
                task_count = len(list_work_items(partner="parker"))
                status = "active" if task_count else "idle"
            elif pid == "youtube":
                import youtube_partner as _yt
                packages = _yt.load_packages()
                task_count = sum(1 for p in packages
                                 if (p.get("status") or "draft") == "draft")
                status = "active" if task_count else "idle"
            elif pid == "video":
                import video_partner as _vp
                packages = _vp.load_packages()
                task_count = sum(1 for p in packages
                                 if (p.get("status") or "draft") == "draft")
                status = "active" if task_count else "idle"
        except Exception:
            task_count = 0
            status = "idle"
        desks.append({
            "id":          pid,
            "name":        meta["name"],
            "emoji":       meta["emoji"],
            "role":        meta["role"],
            "description": meta["description"],
            "status":      status,
            "task_count":  task_count,
            "do_it_label": meta["do_it_label"],
            # v12.0 ambient activity line:
            "chatter":     _desk_chatter(pid, task_count, status),
        })
    return {
        "desks":           desks,
        "work_items":      len(load_work_items()),
        "documents":       len(load_documents()),
        "messages":        len(load_messages()),
        "waiting_approval": len(list_work_items(status="waiting_approval")),
        # v12.0 office atmosphere:
        "greeting":         office_greeting(),
        "suggestion_chips": office_suggestion_chips(),
    }
