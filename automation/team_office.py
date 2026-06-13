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
        "do_it_label": "Tell Me Next Step",
        # v12.3: 3 desk decor items rendered as a row under the desk's
        # role line so each partner's desk looks distinct.
        "desk_items":  ("📋", "✅", "☕"),
        # v12.3: short-form name (used in tighter UI surfaces)
        "short_name":  "Olivia",
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
        "do_it_label": "Find Clients",
        "desk_items":  ("🗺️", "📞", "📒"),
        "short_name":  "Logan",
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
            # v12.5: include the plain do_it_label phrasing so a user
            # typing "check my website" routes to Sage as expected.
            "website", "check website", "check my website",
            "my website", "check site",
        ),
        "do_it_label": "Check My Website",
        "desk_items":  ("📊", "📈", "💻"),
        "short_name":  "Sage",
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
        "do_it_label": "Make Promo",
        "desk_items":  ("🎨", "💡", "📌"),
        "short_name":  "Parker",
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
        "do_it_label": "Make Video",
        "desk_items":  ("📷", "🎞️", "💡"),
        "short_name":  "Video",
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
        "do_it_label": "Find Video Ideas",
        "desk_items":  ("🖼️", "📈", "🎯"),
        "short_name":  "YouTube",
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
        # v12.8: partner-is-waiting-for-an-answer flag.
        "pending":   bool(raw.get("pending")),
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
            picks = _lc.compute_picks(k=5)
            count = len(picks)
        except Exception:
            picks = []
            count = 0
        if count > 0:
            top_name = (picks[0].get("business_name") or "your top lead")
            # v12.3: richer reply mentions WHY top picks stand out —
            # pulls real opportunity_reasons / weak_presence_flags from
            # v9.0 enrichment data.
            standout = ""
            for p in picks[:3]:
                flags = p.get("weak_presence_flags") or []
                if "Facebook only" in flags:
                    standout = ("They rely heavily on Facebook and "
                                "don't have strong websites.")
                    break
                if "No website found" in flags:
                    standout = ("They have no website on file — "
                                "ideal for the free mockup pitch.")
                    break
                if "Old or weak website" in flags:
                    standout = "Their sites are dated or thin — fast wins."
                    break
                if "Gmail/Yahoo/Outlook email" in flags:
                    standout = ("They're using free consumer email — "
                                "no business domain yet.")
                    break
            if standout:
                body = (
                    f"I have {count} businesses worth looking at on the "
                    f"board. Top picks stand out because {standout} "
                    f"Strongest right now is {top_name}. Want me to show "
                    f"you those first?"
                )
            else:
                body = (
                    f"I have {count} ranked candidate"
                    f"{'s' if count != 1 else ''} on my desk. Strongest "
                    f"is {top_name}. Want me to keep finding more, or "
                    f"take action on one of these?"
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
            # v12.3: if there's an existing audit, surface the top open
            # checklist item by section so Sage's reply lands with
            # specific intel ("biggest opportunity I see right now is
            # local search visibility...") instead of a generic line.
            specific = ""
            try:
                import seo_partner as _sp
                projects = _sp.load_projects()
                if projects:
                    audits = _sp.list_audits(projects[0]["id"])
                    if audits:
                        latest = audits[-1]
                        # Count failing/pending items per section
                        sec_pending: dict[str, int] = {}
                        for sec_key, items in (latest.get("checklist") or {}).items():
                            if isinstance(items, list):
                                sec_pending[sec_key] = sum(
                                    1 for it in items
                                    if (it.get("status") or "") in ("pending", "failing")
                                )
                        if sec_pending:
                            top_sec = max(sec_pending, key=lambda k: sec_pending[k])
                            label = top_sec.replace("_", " ").title()
                            specific = (
                                f"The biggest opportunity I see right now "
                                f"is {label.lower()}. I count "
                                f"{sec_pending[top_sec]} item"
                                f"{'s' if sec_pending[top_sec] != 1 else ''} "
                                f"that could move the needle."
                            )
            except Exception:
                pass
            if specific:
                body = (
                    f"I just finished checking "
                    f"{projects[0].get('project_name', 'the project')}. "
                    f"{specific} Want me to walk through them with you?"
                )
            else:
                body = (
                    "I'll spin up a basic SEO audit — titles, headings, "
                    "service clarity, local signals, and what needs your "
                    "approval before it ships. Nothing touches the live "
                    "site or Google Business Profile."
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


# ======================================================================
# v12.8 — Chat-first: partners ASK before they act
# ----------------------------------------------------------------------
# Each partner has one clarifying question they ask before doing real
# work. The user's next message is treated as the answer and routed
# back to that partner with the answer as context.
#
# No new data files. Pending state lives in the existing console log
# as a `pending: true` flag on partner messages.
# ======================================================================

PARTNER_QUESTIONS: dict[str, str] = {
    "logan": (
        "Sure thing. What kind of business should I look for, and "
        "what city or area?"
    ),
    "sage": (
        "Got it. Should I do a full website check on {website}, "
        "or focus on something specific you've noticed?"
    ),
    "parker": (
        "Yes. Who's this promo for, and what's the main offer — "
        "the free homepage mockup, or something else?"
    ),
    "video": (
        "Sounds good. What's the topic, and is this for Reels, "
        "TikTok, or YouTube Shorts?"
    ),
    "youtube": (
        "Yeah. What angle do you want me to explore for the video ideas?"
    ),
}

# Olivia's brief handoff line — what she says before the partner asks.
_OLIVIA_HANDOFFS: dict[str, str] = {
    "logan":   "On it. Logan, take this one.",
    "sage":    "Got it. Sage, you're up.",
    "parker":  "On it. Parker, this one's yours.",
    "video":   "Sounds good. Video Partner, you got this.",
    "youtube": "Yep. YouTube Growth, take it.",
}


def _format_partner_question(partner_id: str, user_text: str = "") -> str:
    """
    v12.9: smart question — acknowledges what the user already said
    and asks only for what's missing. For Logan, this means parsing
    count/filters/location/category first, then asking only the gap.
    """
    if partner_id == "logan":
        return _logan_smart_question(user_text)
    tmpl = PARTNER_QUESTIONS.get(partner_id, "")
    if not tmpl:
        return ""
    try:
        import onboarding as _ob
        profile = _ob.load_agency_profile() or {}
        return tmpl.format(
            website=profile.get("first_website") or "your site",
        )
    except Exception:
        return tmpl


def _logan_smart_question(user_text: str) -> str:
    """
    Smart Logan question:
      - Parse the user's text for count/filters/location/category
      - Acknowledge what was understood
      - Ask only for what's actually missing
    Returns "" (empty string) if we have enough to run without asking —
    in that case the caller should fall through to running directly.
    """
    parsed = _parse_logan_full(user_text)

    # What do we have?
    # v12.10: umbrella categories ALSO count as having a category.
    have_category = bool(parsed["category"]) or bool(parsed.get("umbrella_subs"))
    have_location = bool(parsed["city"]) or bool(parsed["state"])

    # Build a human acknowledgement of what's pinned down.
    parts: list[str] = []
    if parsed["count"] != 10:
        parts.append(f"up to {parsed['count']}")
    nice_filter = {
        "no_website":      "no website",
        "has_email":       "has an email",
        "facebook_only":   "Facebook only",
        "weak_presence":   "weak web presence",
        "no_email":        "no email",
        "no_phone":        "no phone",
    }
    for f in parsed["filters"]:
        parts.append(nice_filter.get(f, f))
    if parsed["is_statewide"] and parsed["state"]:
        parts.append(f"statewide {parsed['state'].title()}")
    elif parsed["state"] and parsed["city"]:
        parts.append(f"{parsed['city']}, {parsed['state'].title()}")
    elif parsed["state"]:
        parts.append(parsed["state"].title())
    elif parsed["city"]:
        parts.append(parsed["city"])
    if parsed["category"]:
        parts.append(parsed["category"])

    ack = ", ".join(parts) if parts else ""

    if have_category and have_location:
        # Nothing missing — caller should run directly.
        return ""
    if not have_category and not have_location:
        # Nothing pinned — full question.
        if ack:
            return (f"Got it — {ack}. "
                    "What kind of business should I look for, and what city or area?")
        return ("Sure thing. What kind of business should I look for, "
                "and what city or area?")
    if not have_category:
        return (f"Got it — {ack}. What kind of business should I look for?")
    # Missing location only
    return (f"Got it — {ack}. What city or area?")


def _find_pending_partner() -> str | None:
    """
    Walk recent console messages newest-first. The most recent partner
    message marked pending=True (that hasn't been answered by a later
    user message) is the partner waiting for an answer.
    """
    msgs = load_messages()
    for m in reversed(msgs):
        if m.get("role") == "user":
            # User has already spoken after the question — answered.
            return None
        if m.get("pending"):
            return m.get("partner")
    return None


def _clear_pending_flags() -> None:
    """Mark every prior pending message as no longer pending."""
    items = load_messages()
    changed = False
    for m in items:
        if m.get("pending"):
            m["pending"] = False
            changed = True
    if changed:
        _save_messages(items)


def _user_intent_is_partner_switch(text: str, current_partner: str) -> bool:
    """
    Detect 'I changed my mind' — user replied with keywords for a
    DIFFERENT partner instead of answering the pending question.
    """
    primary, _ = _detect_partner(text)
    if primary == "olivia":
        return False
    return primary != current_partner


def _parse_logan_request(text: str) -> tuple[str | None, str | None]:
    """
    Heuristic parse of 'plumbers in hot springs ar' → ('plumbers',
    'hot springs ar'). Tries several common shapes. Returns
    (category, city) — either can be None if unparseable.
    """
    import re as _re
    s = (text or "").strip()
    if not s:
        return None, None
    # "X in Y" / "X near Y" / "X around Y" / "X at Y" / "X around the Y area"
    m = _re.search(
        r'^(.+?)\s+(?:in|near|around|at|throughout)\s+(.+)$',
        s, _re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # "X, City State"
    if "," in s:
        before, after = s.split(",", 1)
        if before.strip() and after.strip():
            return before.strip(), after.strip()
    # Single token — treat as category, use default city
    return s, None


# ----- v12.9: comprehensive Logan parser -------------------------------
# The v12.8 parser only handled "X in Y". The real complaint was that
# Logan ignored everything the user already said. v12.9 pulls structured
# fields from the user's free text so Logan only has to ask for what's
# actually missing.

# US state abbreviation + name → canonical lowercase full name.
US_STATE_LOOKUP: dict[str, str] = {
    "al": "alabama", "alabama": "alabama",
    "ak": "alaska", "alaska": "alaska",
    "az": "arizona", "arizona": "arizona",
    "ar": "arkansas", "arkansas": "arkansas",
    "ca": "california", "california": "california",
    "co": "colorado", "colorado": "colorado",
    "ct": "connecticut", "connecticut": "connecticut",
    "de": "delaware", "delaware": "delaware",
    "fl": "florida", "florida": "florida",
    "ga": "georgia", "georgia": "georgia",
    "hi": "hawaii", "hawaii": "hawaii",
    "id": "idaho", "idaho": "idaho",
    "il": "illinois", "illinois": "illinois",
    "in": "indiana", "indiana": "indiana",
    "ia": "iowa", "iowa": "iowa",
    "ks": "kansas", "kansas": "kansas",
    "ky": "kentucky", "kentucky": "kentucky",
    "la": "louisiana", "louisiana": "louisiana",
    "me": "maine", "maine": "maine",
    "md": "maryland", "maryland": "maryland",
    "ma": "massachusetts", "massachusetts": "massachusetts",
    "mi": "michigan", "michigan": "michigan",
    "mn": "minnesota", "minnesota": "minnesota",
    "ms": "mississippi", "mississippi": "mississippi",
    "mo": "missouri", "missouri": "missouri",
    "mt": "montana", "montana": "montana",
    "ne": "nebraska", "nebraska": "nebraska",
    "nv": "nevada", "nevada": "nevada",
    "nh": "new hampshire", "new hampshire": "new hampshire",
    "nj": "new jersey", "new jersey": "new jersey",
    "nm": "new mexico", "new mexico": "new mexico",
    "ny": "new york", "new york": "new york",
    "nc": "north carolina", "north carolina": "north carolina",
    "nd": "north dakota", "north dakota": "north dakota",
    "oh": "ohio", "ohio": "ohio",
    "ok": "oklahoma", "oklahoma": "oklahoma",
    "or": "oregon", "oregon": "oregon",
    "pa": "pennsylvania", "pennsylvania": "pennsylvania",
    "ri": "rhode island", "rhode island": "rhode island",
    "sc": "south carolina", "south carolina": "south carolina",
    "sd": "south dakota", "south dakota": "south dakota",
    "tn": "tennessee", "tennessee": "tennessee",
    "tx": "texas", "texas": "texas",
    "ut": "utah", "utah": "utah",
    "vt": "vermont", "vermont": "vermont",
    "va": "virginia", "virginia": "virginia",
    "wa": "washington", "washington": "washington",
    "wv": "west virginia", "west virginia": "west virginia",
    "wi": "wisconsin", "wisconsin": "wisconsin",
    "wy": "wyoming", "wyoming": "wyoming",
}

# Top anchor cities per state — for statewide aggregation Logan can
# fan OSM queries out across these. Picked for population + spread.
STATE_ANCHOR_CITIES: dict[str, list[str]] = {
    "arkansas":    ["Little Rock, AR", "Fayetteville, AR", "Fort Smith, AR", "Conway, AR",
                    "Hot Springs, AR", "Jonesboro, AR", "Springdale, AR", "Pine Bluff, AR"],
    "texas":       ["Houston, TX", "Dallas, TX", "Austin, TX", "San Antonio, TX"],
    "california":  ["Los Angeles, CA", "San Diego, CA", "San Jose, CA", "San Francisco, CA"],
    "florida":     ["Jacksonville, FL", "Miami, FL", "Tampa, FL", "Orlando, FL"],
    "new york":    ["New York, NY", "Buffalo, NY", "Rochester, NY", "Albany, NY"],
    "illinois":    ["Chicago, IL", "Aurora, IL", "Springfield, IL", "Rockford, IL"],
    "georgia":     ["Atlanta, GA", "Augusta, GA", "Columbus, GA", "Savannah, GA"],
    "tennessee":   ["Nashville, TN", "Memphis, TN", "Knoxville, TN", "Chattanooga, TN"],
    "missouri":    ["Kansas City, MO", "St. Louis, MO", "Springfield, MO", "Columbia, MO"],
    "oklahoma":    ["Oklahoma City, OK", "Tulsa, OK", "Norman, OK", "Broken Arrow, OK"],
    "louisiana":   ["New Orleans, LA", "Baton Rouge, LA", "Shreveport, LA", "Lafayette, LA"],
    "mississippi": ["Jackson, MS", "Gulfport, MS", "Hattiesburg, MS", "Tupelo, MS"],
    "alabama":     ["Birmingham, AL", "Montgomery, AL", "Mobile, AL", "Huntsville, AL"],
    "kentucky":    ["Louisville, KY", "Lexington, KY", "Bowling Green, KY", "Owensboro, KY"],
    "north carolina": ["Charlotte, NC", "Raleigh, NC", "Greensboro, NC", "Durham, NC"],
    "south carolina": ["Charleston, SC", "Columbia, SC", "Greenville, SC", "Myrtle Beach, SC"],
}

# v12.10: umbrella category terms — when the user says "trade
# business" instead of a specific trade, Logan expands the term into
# a list of sub-categories and runs them all, aggregating. Keys are
# matched longest-first so "trade business" wins over "trade".
CATEGORY_UMBRELLAS: dict[str, list[str]] = {
    "trade businesses":  ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter", "landscaper", "handyman", "contractor"],
    "trade business":    ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter", "landscaper", "handyman", "contractor"],
    "skilled trades":    ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter", "landscaper", "handyman", "contractor"],
    "service businesses":["plumber", "electrician", "hvac", "landscaper", "cleaners", "handyman"],
    "service business":  ["plumber", "electrician", "hvac", "landscaper", "cleaners", "handyman"],
    "local services":    ["plumber", "electrician", "hvac", "landscaper", "cleaners", "handyman"],
    "local service":     ["plumber", "electrician", "hvac", "landscaper", "cleaners", "handyman"],
    "home services":     ["plumber", "electrician", "hvac", "roofer", "painter", "landscaper"],
    "home service":      ["plumber", "electrician", "hvac", "roofer", "painter", "landscaper"],
    "contractors":       ["plumber", "electrician", "hvac", "roofer", "painter", "carpenter", "landscaper", "handyman", "contractor"],
    "contractor":        ["plumber", "electrician", "hvac", "roofer", "painter", "carpenter"],
    "blue collar":       ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter"],
    "tradesmen":         ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter", "landscaper", "handyman", "contractor"],
    "tradespeople":      ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter", "landscaper", "handyman", "contractor"],
    "trades":            ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter", "landscaper", "handyman", "contractor"],
    "trade":             ["plumber", "electrician", "hvac", "roofer", "carpenter", "painter"],
    "small businesses":  ["restaurant", "salon", "cafe", "shop", "boutique"],
    "small business":    ["restaurant", "salon", "cafe", "shop", "boutique"],
    "local businesses":  ["restaurant", "salon", "cafe", "shop", "plumber"],
    "local business":    ["restaurant", "salon", "cafe", "shop", "plumber"],
    "any":               ["restaurant", "salon", "plumber", "electrician", "shop"],
    "anything":          ["restaurant", "salon", "plumber", "electrician", "shop"],
}

# Common business categories for keyword detection.
_LOGAN_CATEGORY_WORDS = (
    "lawn care", "pressure washing", "pest control", "tree service",
    "hair salon", "beauty salon", "nail salon", "tattoo shop",
    "coffee shop", "ice cream shop", "convenience store",
    "personal trainer", "yoga studio",
    "plumbers", "plumber", "plumbing",
    "electricians", "electrician",
    "roofers", "roofer", "roofing",
    "landscapers", "landscaping", "landscaper",
    "lawn", "hvac", "heating", "cooling", "ac",
    "painters", "painter", "painting",
    "cleaners", "cleaning", "maid",
    "salons", "salon", "barbers", "barber",
    "restaurants", "restaurant", "cafes", "cafe",
    "gyms", "gym", "fitness",
    "dentists", "dentist", "doctors", "doctor",
    "chiropractors", "chiropractor",
    "lawyers", "lawyer", "attorneys", "attorney",
    "churches", "church",
    "florists", "florist",
    "photographers", "photographer",
    "bakeries", "bakery", "bakers", "baker",
    "auto repair", "mechanic", "mechanics",
    "tire shop", "car wash",
    "boutique", "clothing store",
    "jeweler", "jewelry",
    "bookstore", "books",
    "thrift store", "antiques",
    "real estate", "realtor",
    "accountants", "accountant",
    "insurance",
    "vets", "veterinarian", "vet",
    "pet groomer", "pet store",
    "daycare", "preschool",
    "movers", "moving company",
    "locksmiths", "locksmith",
)


def _parse_logan_full(text: str) -> dict:
    """
    v12.9: extract every parseable field from a Logan request.

    Returns a dict:
        {
          count:        int       (1-100, default 10),
          category:     str|None,
          city:         str|None  (best-guess single city),
          state:        str|None  (canonical lowercase full name),
          is_statewide: bool,
          filters:      list[str] (subset of: no_website, has_email,
                                   facebook_only, weak_presence,
                                   no_email, no_phone),
        }
    """
    import re as _re
    s = (text or "").strip()
    sl = s.lower()

    # Count — "100 leads" / "30 prospects" / "find me 5 clients"
    count = 10
    m = _re.search(
        r'\b(\d{1,3})\s*(?:leads?|prospects?|clients?|businesses?|results?)?\b',
        sl,
    )
    if m:
        try:
            count = max(1, min(100, int(m.group(1))))
        except ValueError:
            pass

    # Filters — order doesn't matter; multiple can be set.
    filters: list[str] = []
    if any(p in sl for p in ("no website", "without a website", "without website",
                              "no site", "without a site", "no web", "no online")):
        filters.append("no_website")
    if any(p in sl for p in ("with email", "with an email", "has email",
                              "have email", "have an email", "email address",
                              "email on file")):
        filters.append("has_email")
    if any(p in sl for p in ("facebook only", "just facebook", "fb only",
                              "facebook page only")):
        filters.append("facebook_only")
    if any(p in sl for p in ("weak web", "weak online", "weak presence",
                              "weak site", "thin website", "dated website",
                              "old website", "outdated website")):
        filters.append("weak_presence")
    if "no email" in sl or "without email" in sl:
        filters.append("no_email")
    if "no phone" in sl or "without phone" in sl:
        filters.append("no_phone")

    # Location — try statewide, city+state, then bare city.
    state = None
    is_statewide = False
    city = None

    # Statewide markers
    statewide_markers = (
        "all over", "all across", "throughout", "across",
        "anywhere in", "around the state", "statewide",
        "everywhere in",
    )
    for marker in statewide_markers:
        idx = sl.find(marker)
        if idx == -1:
            continue
        rest = sl[idx + len(marker):].strip()
        # The phrase right after should be a state name (one or two words)
        candidate1 = rest.split()[:1]
        candidate2 = " ".join(rest.split()[:2])
        for cand in (candidate2, " ".join(candidate1)):
            cand = cand.strip(".,?!").strip()
            if cand in US_STATE_LOOKUP:
                state = US_STATE_LOOKUP[cand]
                is_statewide = True
                break
        if is_statewide:
            break

    # Also catch bare "in Arkansas" with no city specified.
    if not is_statewide and not city:
        # Match "in X" / "across X" / "from X" where X is a state name
        for word in (statewide_markers + ("in", "from", "for")):
            patt = _re.compile(
                r'\b' + _re.escape(word) + r'\s+([a-z][a-z\s]+?)(?:\s+(?:with|having|that|who|but|and)|$|[.,?!])',
                _re.IGNORECASE,
            )
            mm = patt.search(sl)
            if not mm:
                continue
            candidate = mm.group(1).strip().lower()
            # Trim trailing "state" word
            if candidate.endswith(" state"):
                candidate = candidate[:-6].strip()
            if candidate in US_STATE_LOOKUP:
                state = US_STATE_LOOKUP[candidate]
                # If marker was "in X" with NO city before, treat as statewide
                is_statewide = True
                break

    # City+state: "X, ST" pattern
    if not is_statewide:
        cs = _re.search(
            r'(?:in|near|around|from|at)\s+([a-z][a-z\s]+?),\s*([a-z]{2,})\b',
            sl,
        )
        if cs:
            city = cs.group(1).strip().title()
            st_cand = cs.group(2).strip().lower()
            state = US_STATE_LOOKUP.get(st_cand)
        else:
            # Try "in <city> <ST>" without comma (e.g. "in austin tx")
            cs2 = _re.search(
                r'(?:in|near|around|from|at)\s+([a-z][a-z\s]+?)\s+(' +
                "|".join(_re.escape(k) for k in US_STATE_LOOKUP if len(k) == 2) +
                r')\b',
                sl,
            )
            if cs2:
                city = cs2.group(1).strip().title()
                state = US_STATE_LOOKUP.get(cs2.group(2).strip().lower())
            else:
                # Try bare "in <city>" (no state)
                cs3 = _re.search(
                    r'(?:in|near|around|from|at)\s+([a-z][a-z\s]+?)(?:\s+(?:with|having|that|who|but|and)|$|[.,?!])',
                    sl,
                )
                if cs3:
                    cand = cs3.group(1).strip()
                    # Only accept as city if it's not a state name
                    if cand.lower() not in US_STATE_LOOKUP:
                        city = cand.title()

    # v12.10: more permissive location detection. If we haven't found
    # a location yet, try several looser shapes.
    if not state and not city and not is_statewide:
        # "City, ST" anywhere in the message (no preposition needed)
        bare_cs = _re.search(
            r'\b([a-z][a-z\s]+?),\s*([a-z]{2})\b', sl,
        )
        if bare_cs:
            cand_city = bare_cs.group(1).strip()
            cand_state = bare_cs.group(2).strip().lower()
            if cand_state in US_STATE_LOOKUP and cand_city not in US_STATE_LOOKUP:
                city = cand_city.title()
                state = US_STATE_LOOKUP[cand_state]
        # "City ST" without comma — try a 2-or-3-word capitalized
        # sequence followed by a 2-letter state code at the end of the
        # message (or before a preposition like "with"/"that").
        if not state and not city:
            bare_no_comma = _re.search(
                r'\b([a-z][a-z\s]{2,30}?)\s+(' +
                "|".join(_re.escape(k) for k in US_STATE_LOOKUP if len(k) == 2) +
                r')\b(?!\w)',
                sl,
            )
            if bare_no_comma:
                cand_city = bare_no_comma.group(1).strip()
                cand_state = bare_no_comma.group(2).strip().lower()
                # Strip likely-noise leading words from city
                noise_prefixes = ("find me", "find", "me", "the", "a", "an",
                                  "near", "in", "at", "from", "for",
                                  "with", "but", "and", "all over",
                                  "leads with", "leads", "client", "clients",
                                  "businesses", "business", "prospect",
                                  "prospects")
                for noise in sorted(noise_prefixes, key=len, reverse=True):
                    if cand_city.startswith(noise + " "):
                        cand_city = cand_city[len(noise):].strip()
                if cand_city and cand_city not in US_STATE_LOOKUP:
                    city = cand_city.title()
                    state = US_STATE_LOOKUP[cand_state]
        # Bare state name anywhere in message (treat as statewide)
        if not state and not city:
            for word in sorted(US_STATE_LOOKUP, key=len, reverse=True):
                if len(word) < 4:  # skip 2-letter codes here
                    continue
                if _re.search(r'\b' + _re.escape(word) + r'\b', sl):
                    state = US_STATE_LOOKUP[word]
                    is_statewide = True
                    break
        # Region phrases — "northwest arkansas", "central texas" etc.
        # treat as statewide for the corresponding state.
        if not state:
            region_m = _re.search(
                r'\b(northwest|southwest|northeast|southeast|north|south|east|west|central|greater)\s+([a-z][a-z\s]+?)\b',
                sl,
            )
            if region_m:
                region_state = region_m.group(2).strip().lower()
                # Try to match a state name
                for word in sorted(US_STATE_LOOKUP, key=len, reverse=True):
                    if len(word) < 4:
                        continue
                    if region_state.startswith(word):
                        state = US_STATE_LOOKUP[word]
                        is_statewide = True
                        break

    # v12.10: post-process city to catch two common shapes that earlier
    # patterns mis-classify.
    if city:
        # (a) leading business category word — "Plumbers Little Rock"
        # should become "Little Rock" (the category will be parsed
        # separately a few lines down).
        for noise_cat in sorted(
            list(CATEGORY_UMBRELLAS.keys()) + list(_LOGAN_CATEGORY_WORDS),
            key=len, reverse=True,
        ):
            if city.lower().startswith(noise_cat + " "):
                city = city[len(noise_cat):].strip().title() or None
                break
        # (b) "region state" — "Central Texas" should be statewide TX,
        # not a city called "Central Texas".
        if city and not state:
            parts = city.lower().split()
            regions = {
                "northwest", "southwest", "northeast", "southeast",
                "north", "south", "east", "west", "central", "greater",
            }
            if len(parts) >= 2 and parts[0] in regions:
                rest = " ".join(parts[1:])
                if rest in US_STATE_LOOKUP:
                    state = US_STATE_LOOKUP[rest]
                    is_statewide = True
                    city = None

    # v12.10: Category — umbrellas first (longest match wins), then
    # specific terms. Umbrellas expand into a sub-category list that
    # _logan_run iterates over.
    category = None
    umbrella_subs: list[str] = []
    for term in sorted(CATEGORY_UMBRELLAS.keys(), key=len, reverse=True):
        if _re.search(r'\b' + _re.escape(term) + r'\b', sl):
            category = term
            umbrella_subs = list(CATEGORY_UMBRELLAS[term])
            break
    if not category:
        for cat in _LOGAN_CATEGORY_WORDS:
            if _re.search(r'\b' + _re.escape(cat) + r'\b', sl):
                category = cat
                break

    return {
        "count":         count,
        "category":      category,
        "umbrella_subs": umbrella_subs,
        "city":          city,
        "state":         state,
        "is_statewide":  is_statewide,
        "filters":       filters,
    }


def _parse_video_request(text: str) -> tuple[str | None, str | None]:
    """
    Heuristic parse of video request like 'free mockup for tiktok' →
    ('free mockup', 'tiktok'). Returns (topic, platform).
    """
    import re as _re
    s = (text or "").strip()
    if not s:
        return None, None
    # Detect platform keywords
    platform = None
    for kw, label in (
        ("reels", "Reels"), ("instagram reels", "Reels"),
        ("tiktok", "TikTok"), ("tik tok", "TikTok"),
        ("shorts", "YouTube Shorts"), ("youtube shorts", "YouTube Shorts"),
        ("youtube", "YouTube"), ("yt", "YouTube"),
    ):
        if kw in s.lower():
            platform = label
            break
    # Topic = whatever isn't the platform mention
    topic = s
    if platform:
        # Strip the platform phrase from the text
        topic = _re.sub(
            r'\b(for|on|to|as)?\s*(reels|instagram reels|tiktok|tik tok|youtube shorts|shorts|youtube|yt)\b',
            '', s, flags=_re.IGNORECASE,
        ).strip(' ,.')
    return (topic or None), platform


def _stitch_user_context(latest_answer: str, partner_id: str) -> str:
    """
    v12.9: when a partner asks a clarifying question and the user
    answers, the answer alone often loses context (e.g. user typed
    "find me 100 leads no website in arkansas" → partner asked
    "what business type?" → user typed "plumbers"). The partner
    needs both messages to honor what the user originally said.

    Walks back through console messages to find the most recent
    USER message before the partner's question, and concatenates it
    with the latest answer.
    """
    msgs = load_messages()
    # Walk backward. Skip the latest user message we just appended.
    # Find the partner's pending question, then the user message
    # immediately before that.
    found_partner_q = False
    original = ""
    for m in reversed(msgs[:-1]):  # exclude the new answer we just appended
        if not found_partner_q:
            if m.get("partner") == partner_id and m.get("pending"):
                found_partner_q = True
                continue
            # The most recent partner message MIGHT not be marked
            # pending anymore (cleared). Also accept if it's just
            # the partner's most recent message.
            if m.get("partner") == partner_id:
                found_partner_q = True
                continue
        else:
            if m.get("role") == "user":
                original = m.get("text") or ""
                break
    if original and original.lower().strip() != latest_answer.lower().strip():
        return f"{original}. {latest_answer}".strip()
    return latest_answer


def _ask_first_flow(user_msg: dict, primary: str, text: str) -> dict:
    """
    v12.8: Olivia briefly hands off, then the partner asks one
    clarifying question and marks itself pending. No work runs yet.
    v12.9: Logan can skip the question entirely if the user already
    specified everything (category + location). In that case we
    short-circuit to running directly.
    """
    # v12.9: smart question — Logan only. If Logan has enough to run,
    # _logan_smart_question returns "" and we run immediately with the
    # original text as context.
    question = _format_partner_question(primary, text)
    if not question and primary == "logan":
        # The user already told Logan everything they need. Run now.
        olivia_line = _OLIVIA_HANDOFFS.get(primary, "On it.")
        olivia_msg = append_message({
            "role": "olivia", "partner": "olivia", "text": olivia_line,
        })
        try:
            result = start_work(primary, context=text)
        except Exception as e:
            err_text = f"Hit a snag: {e}. Want to try again?"
            err_msg = append_message({
                "role": primary, "partner": primary, "text": err_text,
            })
            return {
                "chosen_partner":     primary,
                "secondary_partners": [],
                "intent":             "error",
                "messages":           [user_msg, olivia_msg, err_msg],
                "asked":              False,
            }
        return {
            "chosen_partner":     primary,
            "secondary_partners": [],
            "intent":             "follow_up",
            "messages":           [user_msg, olivia_msg] + list(result.get("messages", [])),
            "result_card":        result.get("result_card"),
            "documents":          result.get("documents", []),
            "asked":              False,
        }

    # Standard ask-first flow
    olivia_line = _OLIVIA_HANDOFFS.get(
        primary, f"On it. {PARTNERS[primary]['short_name']}, take this."
    )
    olivia_msg = append_message({
        "role":    "olivia",
        "partner": "olivia",
        "text":    olivia_line,
    })

    if not question:
        question = PARTNER_QUESTIONS.get(primary, "What do you want me to focus on?")

    # Wrap in the partner's voice so the opener + handoff ack land
    # naturally ("On it, Olivia. Topher — ...").
    voiced = _wrap_with_voice(
        primary, question, text, handoff_from="olivia",
    )
    partner_msg = append_message({
        "role":    primary,
        "partner": primary,
        "text":    voiced,
        "pending": True,  # this is the marker that drives v12.8 routing
    })

    return {
        "chosen_partner":     primary,
        "secondary_partners": [],
        "intent":             "clarify",
        "response_text":      voiced,
        "suggested_actions":  [],
        "created_work_items": [],
        "created_documents":  [],
        "messages":           [user_msg, olivia_msg, partner_msg],
        "asked":              True,
    }


def _handle_partner_clarification(partner_id: str, answer: str) -> dict:
    """
    v12.8: user answered a pending question. Clear the flag, run the
    real work with the user's answer as context, and return the
    partner's reply (with result_card so the UI can render bullets +
    next-step button inline).
    v12.9: combine the user's original request (last user message
    before the partner's question) with their answer so the partner
    has the full picture — count, filters, location, etc. that were
    in the original message.
    """
    user_msg = append_message({
        "role": "user", "partner": "user", "text": answer,
    })
    _clear_pending_flags()
    # v12.9: stitch the original request + answer for richer context
    full_context = _stitch_user_context(answer, partner_id)
    try:
        result = start_work(partner_id, context=full_context)
    except Exception as e:
        err_text = (
            f"Hm, I tried to start but hit a snag: {e}. Want to "
            "try again, or hand this to someone else?"
        )
        err_msg = append_message({
            "role": partner_id, "partner": partner_id, "text": err_text,
        })
        return {
            "chosen_partner":     partner_id,
            "secondary_partners": [],
            "intent":             "error",
            "messages":           [user_msg, err_msg],
            "asked":              False,
        }
    return {
        "chosen_partner":     partner_id,
        "secondary_partners": [],
        "intent":             "follow_up",
        "messages":           [user_msg] + list(result.get("messages", [])),
        "result_card":        result.get("result_card"),
        "documents":          result.get("documents", []),
        "asked":              False,
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

    # v12.8: if a partner is waiting for an answer and the user isn't
    # clearly switching topics, route to them with the answer.
    pending = _find_pending_partner()
    if pending and not _user_intent_is_partner_switch(text, pending):
        return _handle_partner_clarification(pending, text)
    # User explicitly switched — clear the pending flag and proceed
    # with normal routing.
    if pending:
        _clear_pending_flags()

    # v12.3: auto-delegation. Outcome phrases like "get me more clients"
    # kick off a real multi-partner workflow visibly in the console
    # instead of routing to a single partner.
    delegation = _detect_auto_delegation(text)
    if delegation:
        chain, intro = delegation
        return run_auto_delegation(text, chain, intro)

    # 1. User message
    user_msg = append_message({
        "role":    "user",
        "partner": "user",
        "text":    text,
    })

    # 2. Detect partner
    primary, secondary = _detect_partner(text)
    intent = _classify_intent(text)

    # v12.9: Logan affinity override. If the user clearly described a
    # lead search (category + location, or strong filters like
    # "no website" / "with email" alongside any business word),
    # route to Logan regardless of what keyword scoring picked.
    # This fixes "50 plumbers all over arkansas with no website"
    # getting hijacked to Sage because "website" matches Sage's
    # keyword list.
    if primary != "olivia":
        parsed_logan = _parse_logan_full(text)
        strong_signal = (
            (parsed_logan["category"] and (parsed_logan["city"] or
                                             parsed_logan["state"]))
            or
            (parsed_logan["filters"] and parsed_logan["category"])
            or
            ("leads" in text.lower() or "prospects" in text.lower()
             or "clients" in text.lower() or "businesses" in text.lower())
        )
        if strong_signal:
            primary = "logan"
            secondary = []

    # v12.8: if the primary partner has an ask-first question
    # registered and isn't already responding to a clarification,
    # short-circuit: Olivia hands off and the partner ASKS.
    if primary != "olivia" and primary in PARTNER_QUESTIONS:
        return _ask_first_flow(user_msg, primary, text)

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
    """v12.4: the 5 spec-mandated one-tap suggestions Olivia offers
    when the user opens the office. Plain words, action-shaped."""
    return [
        "Get me clients",
        "Improve my website",
        "Make a promo",
        "Make a video",
        "Tell me what to do next",
    ]


# ======================================================================
# v12.2 — start_work(partner_id)
# ----------------------------------------------------------------------
# The "Do It For Me" buttons (on the onboarding success screen AND on
# each partner desk in the Agency Office) used to scroll-and-status —
# Sage actually ran the audit, but everyone else just navigated.
# v12.2 makes Olivia actually start the work: each partner produces a
# real artifact (audit / lead picks / promo draft / video script /
# YouTube package), saves it to the shared document library, posts a
# message to the console showing what they made, and updates any
# related work item to status="waiting_approval".
#
# Safety: nothing publishes, nothing sends, nothing connects. Logan's
# discovery still uses the existing OSM client. Everything else is
# pure local generation.
# ======================================================================

def _agency_profile() -> dict:
    """Lazy-load v12.1 agency profile so missing onboarding doesn't
    crash start_work."""
    try:
        import onboarding as _ob
        return _ob.load_agency_profile() or {}
    except Exception:
        return {}


def _bump_work_item(partner: str, new_status: str = "waiting_approval") -> dict | None:
    """Find the most recent 'new' work item assigned to this partner
    and flip it to waiting_approval. If none, returns None silently."""
    items = list_work_items(partner=partner, status="new")
    if not items:
        return None
    # Most recently created first.
    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    target = items[0]
    try:
        return update_work_item_status(target["id"], new_status)
    except Exception:
        return None


def _start_olivia(context: str | None = None) -> dict:
    """Olivia's 'Tell me what to do next' — already worked in v11.0,
    just structures the response in the new start_work shape."""
    text, actions = _olivia_next_actions_text()
    msg = append_message({
        "role": "olivia", "partner": "olivia",
        "text": text, "actions": actions,
    })
    # v12.4: pull the top-3 lines out of Olivia's text as bullets for
    # the result card, then surface the first action as next-action.
    bullets: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith("•")
                     or line.startswith("-")):
            # Strip leading "1." / "2." / "•" / "-".
            cleaned = line.lstrip("0123456789.• -")
            if cleaned:
                bullets.append(cleaned.strip())
        if len(bullets) >= 3:
            break
    if not bullets:
        bullets = [text.split("\n", 1)[0]] if text else ["You're up to date."]
    next_action = actions[0] if actions else None
    return {
        "ok":          True,
        "partner":     "olivia",
        "messages":    [msg],
        "documents":   [],
        "work_item":   None,
        "summary":     "Olivia ranked the next 3 things to do.",
        "result_card": {
            "headline":    "Here's what I'd do next:",
            "bullets":     bullets,
            "next_action": next_action,
        },
    }


def _start_logan(context: str | None = None) -> dict:
    """Run the v9.1 do_it_all pipeline with the agency-profile defaults.
    Real OSM discovery + bulk-enrich + ranking in one round trip.

    v12.9: comprehensive parsing of `context` — count, category, city,
    state, statewide flag, filters. If statewide, fan out across
    state anchor cities and aggregate. Apply post-filters across
    aggregated results.
    """
    profile = _agency_profile()
    # Defaults
    category = "plumber"
    city = profile.get("default_search_area") or "Hot Springs, AR"
    state = None
    is_statewide = False
    count = 10
    filters: list[str] = []

    umbrella_subs: list[str] = []
    if context:
        parsed = _parse_logan_full(context)
        if parsed["category"]:       category = parsed["category"]
        if parsed.get("umbrella_subs"): umbrella_subs = parsed["umbrella_subs"]
        if parsed["city"]:           city = parsed["city"]
        if parsed["state"]:          state = parsed["state"]
        is_statewide = parsed["is_statewide"]
        count = parsed["count"]
        filters = parsed["filters"]
        # If state was parsed without an explicit city, treat as statewide
        if state and not parsed["city"] and not is_statewide:
            is_statewide = True
    return _logan_run(
        category=category, city=city, state=state,
        is_statewide=is_statewide, count=count, filters=filters,
        original_context=context, umbrella_subs=umbrella_subs,
    )


def _logan_run(
    category: str,
    city: str,
    state: str | None,
    is_statewide: bool,
    count: int,
    filters: list[str],
    original_context: str | None,
    umbrella_subs: list[str] | None = None,
) -> dict:
    """Execute discovery — single-city or statewide aggregation —
    apply filters, build result_card + console message.

    v12.10: if `umbrella_subs` is provided (e.g. user said "trade
    business" → ["plumber", "electrician", "hvac", ...]), Logan runs
    OSM for each sub-category and aggregates.
    """
    import lead_candidates as _lc

    per_call_cap = 25

    # Categories to actually query — list of one (specific) or many
    # (umbrella expansion).
    if umbrella_subs:
        query_categories = list(umbrella_subs)
    else:
        query_categories = [category]

    all_picks: list[dict] = []
    sources_run: list[tuple[str, str]] = []   # (place, category) pairs
    osm_total = 0
    rm_total = 0

    if is_statewide and state:
        anchors = STATE_ANCHOR_CITIES.get(state.lower())
        if not anchors:
            anchors = [city] if city else []
        # Budget split: per (anchor × sub-category) call.
        total_calls = max(1, len(anchors) * len(query_categories))
        per_call = max(3, min(per_call_cap, count // total_calls))
        if "has_email" in filters or "no_website" in filters:
            per_call = min(per_call_cap, per_call * 2)
        for anchor in anchors:
            for sub_cat in query_categories:
                try:
                    r = _lc.do_it_all(
                        category=sub_cat, city_state=anchor, count=per_call,
                    )
                    all_picks.extend(r.get("picks") or [])
                    disc = r.get("discover") or {}
                    osm_total += int(disc.get("osm_added") or 0)
                    rm_total  += int(disc.get("research_missions_added") or 0)
                    sources_run.append((anchor, sub_cat))
                except Exception:
                    continue
    else:
        # Single-place discovery; loop over sub-categories.
        per_call = min(per_call_cap, max(3, count // max(1, len(query_categories))))
        # v13.0.7: OSM's _parse_city_state requires "City, State" form.
        # Logan's parser splits these into city + state; re-join here so
        # the OSM call doesn't silently fail and we don't fall straight
        # through to research_mission stubs.
        place = f"{city}, {state.upper()}" if (city and state) else city
        for sub_cat in query_categories:
            try:
                r = _lc.do_it_all(
                    category=sub_cat, city_state=place, count=per_call,
                )
                all_picks.extend(r.get("picks") or [])
                disc = r.get("discover") or {}
                osm_total += int(disc.get("osm_added") or 0)
                rm_total  += int(disc.get("research_missions_added") or 0)
                sources_run.append((city, sub_cat))
            except Exception as e:
                # On hard failure of the FIRST sub-category, surface
                # the error. If later sub-cats fail, continue silently.
                if not all_picks and len(sources_run) == 0:
                    err = append_message({
                        "role": "logan", "partner": "logan",
                        "text": (
                            f"I tried to start in {city} but hit a snag: {e}. "
                            "Open my section and run Find Leads For Me manually."
                        ),
                        "actions": [{"label": "Open Logan", "kind": "scroll",
                                     "target": "logan-details"}],
                    })
                    return {"ok": False, "partner": "logan", "messages": [err],
                            "documents": [], "work_item": None,
                            "summary": f"Logan stalled: {e}"}
                continue

    # v12.10: dedupe aggregated picks — when umbrellas run multiple
    # sub-categories, the same business can come back more than once.
    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for p in all_picks:
        name = (p.get("business_name") or "").strip().lower()
        loc  = (p.get("city_state") or "").strip().lower()
        # Use phone or address as a tiebreaker when name is empty
        # (research-mission stubs).
        if not name:
            key = "phrase:" + (p.get("search_phrase") or "")[:80] + "|" + loc
        else:
            key = f"{name}|{loc}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(p)
    all_picks = deduped

    # Apply filters across the aggregated (deduped) picks.
    filtered = _apply_logan_filters(all_picks, filters)

    # Cap to the requested count (after filtering).
    final_picks = filtered[:count]

    # Build the document body — name list with WHY each stands out.
    body_lines: list[str] = []
    place_label = (
        f"statewide {state.title()}" if (is_statewide and state)
        else city
    )
    # Distinct places + sub-categories actually run
    distinct_places = list(dict.fromkeys(p for p, _ in sources_run))
    distinct_cats   = list(dict.fromkeys(c for _, c in sources_run))
    cat_label = category if not umbrella_subs else f"{category} ({', '.join(distinct_cats)})"
    body_lines.append(f"Search: category={cat_label}, place={place_label}, count_target={count}.")
    if filters:
        nice = {"no_website": "no website", "has_email": "has email",
                "facebook_only": "Facebook only", "weak_presence": "weak web presence",
                "no_email": "no email", "no_phone": "no phone"}
        body_lines.append("Filters: " + ", ".join(nice.get(f, f) for f in filters) + ".")
    body_lines.append(
        f"Scanned {len(distinct_places)} place"
        f"{'s' if len(distinct_places) != 1 else ''}: {', '.join(distinct_places)}."
    )
    if umbrella_subs:
        body_lines.append(
            f"Across {len(distinct_cats)} sub-categor"
            f"{'ies' if len(distinct_cats) != 1 else 'y'}: {', '.join(distinct_cats)}."
        )
    body_lines.append(
        f"OSM hits across all places: {osm_total}. "
        f"Research missions: {rm_total}. "
        f"Final after filtering: {len(final_picks)} of {len(all_picks)} unfiltered."
    )
    body_lines.append("")
    body_lines.append("Top picks:")
    for i, p in enumerate(final_picks[:25], 1):
        body_lines.append(
            f"  {i}. {p.get('business_name') or '(unnamed)'} — "
            f"score {p.get('score', 0)} ({p.get('confidence', '?')})"
        )
    doc = create_document({
        "title":      f"Lead picks — {place_label} {category}",
        "type":       "lead_list",
        "created_by": "logan",
        "shared_with": ["olivia", "parker"],
        "body":       "\n".join(body_lines),
        "status":     "ready",
    })

    # Build the Logan message + honest caveats.
    msg_lines: list[str] = []
    if is_statewide and state:
        cat_text = (
            f"**{category}** (covering {', '.join(distinct_cats)})"
            if umbrella_subs else f"**{category}**"
        )
        msg_lines.append(
            f"I scanned {len(distinct_places)} {state.title()} "
            f"{'cities' if len(distinct_places) != 1 else 'city'}"
            f"{' (' + ', '.join(distinct_places) + ')' if distinct_places else ''} "
            f"for {cat_text}."
        )
    else:
        cat_text = (
            f"**{category}** (covering {', '.join(distinct_cats)})"
            if umbrella_subs else f"**{category}**"
        )
        msg_lines.append(f"I ran a pass on {cat_text} in **{place_label}**.")

    if filters:
        nice = {"no_website": "no website", "has_email": "with email",
                "facebook_only": "Facebook only", "weak_presence": "weak web presence",
                "no_email": "no email yet", "no_phone": "no phone yet"}
        msg_lines.append(
            "Filters applied: " + ", ".join(nice.get(f, f) for f in filters) + "."
        )

    # Honest caveats
    caveats: list[str] = []
    if "has_email" in filters:
        with_email = sum(1 for p in final_picks if (p.get("email") or "").strip())
        caveats.append(
            f"Heads up — OSM rarely has email on file. "
            f"Of the {len(final_picks)} I'm showing, only {with_email} have an email confirmed; "
            f"the rest are good candidates by other signals (no website, contact route, local fit)."
        )
    if "no_website" in filters and not final_picks:
        caveats.append(
            "OSM didn't have many no-website businesses for this category here. "
            "The research missions I queued are search-link stubs — open them to research manually."
        )

    if caveats:
        msg_lines.append("")
        msg_lines.extend(caveats)

    # Picks summary
    msg_lines.append("")
    msg_lines.append(
        f"{len(final_picks)} ranked pick{'s' if len(final_picks) != 1 else ''} ready."
    )
    if final_picks:
        msg_lines.append("Top 3:")
        for i, p in enumerate(final_picks[:3], 1):
            why = ""
            flags = p.get("weak_presence_flags") or []
            if "No website found" in flags: why = "no website"
            elif "Facebook only" in flags:   why = "Facebook only"
            elif "Old or weak website" in flags: why = "dated website"
            name = p.get("business_name") or "(unnamed)"
            msg_lines.append(f"  {i}. {name}" + (f" — {why}" if why else ""))

    msg = append_message({
        "role": "logan", "partner": "logan",
        "text": _wrap_with_voice("logan", "\n".join(msg_lines), "start"),
        "actions": [
            {"label": "Open Logan", "kind": "scroll", "target": "logan-details"},
        ],
    })

    wi = _bump_work_item("logan")

    # Result card — plain bullets per pick
    rc_bullets: list[str] = []
    for p in final_picks[:3]:
        name = p.get("business_name") or "(unnamed)"
        flags = p.get("weak_presence_flags") or []
        why = ""
        if "No website found" in flags: why = "no website yet"
        elif "Facebook only" in flags:   why = "on Facebook only"
        elif "Old or weak website" in flags: why = "dated website"
        elif "Gmail/Yahoo/Outlook email" in flags: why = "uses a free email"
        rc_bullets.append(f"{name}{' — ' + why if why else ''}")
    if not rc_bullets:
        rc_bullets = [f"Scanned {place_label}. {len(all_picks)} candidates pre-filter; "
                      f"strict filters narrowed to {len(final_picks)}."]

    return {
        "ok":        True,
        "partner":   "logan",
        "messages":  [msg],
        "documents": [doc],
        "work_item": wi,
        "summary":   (f"Logan: {len(final_picks)} ranked clients in "
                      f"{place_label}{' (' + ', '.join(filters) + ')' if filters else ''}."),
        "result_card": {
            "headline":  (
                f"I found {len(final_picks)} possible client"
                f"{'s' if len(final_picks) != 1 else ''} in {place_label}."
            ),
            "bullets":   rc_bullets,
            "next_action": {
                "label":  "See the list",
                "kind":   "scroll",
                "target": "logan-details",
            },
        },
    }


def _apply_logan_filters(picks: list[dict], filters: list[str]) -> list[dict]:
    """Post-filter aggregated picks per the user's constraints."""
    if not filters:
        return list(picks)
    out: list[dict] = []
    for p in picks:
        ws_lower = (p.get("website_status") or "").lower()
        has_site = bool((p.get("website_url") or "").strip())
        has_email = bool((p.get("email") or "").strip())
        has_phone = bool((p.get("phone") or "").strip())
        flags = p.get("weak_presence_flags") or []

        if "no_website" in filters:
            # Strict: site URL must be empty
            if has_site:
                continue
        if "has_email" in filters:
            if not has_email:
                continue
        if "no_email" in filters:
            if has_email:
                continue
        if "no_phone" in filters:
            if has_phone:
                continue
        if "facebook_only" in filters:
            if "Facebook only" not in flags:
                continue
        if "weak_presence" in filters:
            # At least one weak-presence flag, but not strict no-website
            if not flags:
                continue
        out.append(p)
    # Sort filtered picks by score descending so best survives caps.
    out.sort(key=lambda p: (
        -(1 if p.get("ready_for_outreach") else 0),
        -(p.get("score") or 0),
    ))
    return out


def _start_sage(context: str | None = None) -> dict:
    """Generate the SEO audit on MMS — Sage's audit was already real in
    v12.1; v12.2 adds the visible console message + shared document so
    the user sees what Sage produced."""
    try:
        import seo_partner as _sp
        projects = _sp.load_projects()
        if not projects:
            raise RuntimeError("no SEO projects bootstrapped")
        mms = projects[0]
        # Generate fresh audit
        audit = _sp.generate_audit(mms["id"])
    except Exception as e:
        msg = append_message({
            "role": "sage", "partner": "sage",
            "text": (
                f"I couldn't start the audit — {e}. Open my section and "
                "try Generate Audit on the MixedMakerShop project."
            ),
            "actions": [{"label": "Open Sage", "kind": "scroll",
                         "target": "sage-details"}],
        })
        return {"ok": False, "partner": "sage", "messages": [msg],
                "documents": [], "work_item": None,
                "summary": f"Sage stalled: {e}"}

    sections = audit.get("checklist") or {}
    counts = {k: len(v) for k, v in sections.items() if isinstance(v, list)}
    proj_name = mms.get('project_name', 'your website')
    site_url = mms.get('website_url', '?')

    # v12.4: spec section 9 — plain-language recommendations, NOT
    # "technical SEO" as the headline. Lead with the most relatable
    # opportunity: clarity + local signals.
    plain_recommendations = [
        "Make it clearer what you sell and where you serve.",
        "Add local service terms (city + service) to titles and headings.",
        "Add clear calls to action on every page.",
        "Check page titles and meta descriptions are unique.",
    ]

    body_lines = [
        f"I checked {site_url}.",
        "",
        "The first thing I'd improve is making it clearer what you sell "
        "and where you serve.",
        "",
        "Other things I'd do, in order:",
    ]
    for rec in plain_recommendations[1:]:
        body_lines.append(f"  • {rec}")
    body_lines.append("")
    body_lines.append(
        "(Behind this list I built a full check covering "
        f"{sum(counts.values())} items — Technical, On-Page, and Local. "
        "Open my section if you want to walk it.)"
    )
    doc = create_document({
        "title":      f"Website check — {proj_name}",
        "type":       "seo_audit",
        "created_by": "sage",
        "shared_with": ["olivia", "parker"],
        "related_project_id": mms.get("id"),
        "body":       "\n".join(body_lines),
        "status":     "ready",
    })

    # v12.4: Sage's console reply leads with the plain-language headline.
    chat_lines = [
        f"I checked your website.",
        "",
        "The first thing I'd improve is making it clearer what you sell "
        "and where you serve. Here are the top things I'd do:",
        "",
        "  • Fix homepage wording",
        "  • Add local service terms",
        "  • Improve page titles",
        "  • Add calls to action",
    ]
    msg = append_message({
        "role": "sage", "partner": "sage",
        "text": _wrap_with_voice("sage", "\n".join(chat_lines), "start"),
        "actions": [
            {"label": "Open Sage", "kind": "scroll", "target": "sage-details"},
        ],
    })

    wi = _bump_work_item("sage")

    # v12.4 spec-format results card.
    result_card = {
        "headline":    f"I checked {proj_name}.",
        "bullets":     [
            "Fix homepage wording",
            "Add local service terms",
            "Improve page titles",
            "Add calls to action",
        ],
        "next_action": {
            "label":  "Open the checklist",
            "kind":   "scroll",
            "target": "sage-details",
        },
    }

    return {
        "ok":          True,
        "partner":     "sage",
        "messages":    [msg],
        "documents":   [doc],
        "work_item":   wi,
        "summary":     f"Sage finished your website check.",
        "result_card": result_card,
    }


# Parker doesn't have a generation module like Sage / Video / YouTube,
# so v12.2 ships a local template that mixes the agency profile's
# free/paid offers into a friendly promo draft. Hand-tuned to keep the
# spec-required language ("free homepage mockup" — no "3 free fixes").
def _make_parker_promo(profile: dict) -> str:
    name  = profile.get("agency_name")        or "MixedMakerShop"
    free  = profile.get("free_offer")         or "Free homepage mockup"
    paid  = profile.get("paid_offer")         or "Starter website fix from $150"
    area  = profile.get("default_search_area") or "your area"
    customers = profile.get("target_customers") or ["local businesses"]
    target_str = ", ".join(customers[:3]) or "local businesses"
    return (
        f"📣 PROMO — {free}\n"
        f"\n"
        f"Hey {area} businesses — quick offer from {name}.\n"
        f"\n"
        f"I make {free.lower()} for {target_str}. No commitment. "
        f"You'll get a clean, phone-first homepage you can keep — just "
        f"so you can see what a refresh would look like.\n"
        f"\n"
        f"If you like what you see, I do {paid.lower()} — pay once, "
        f"no subscription.\n"
        f"\n"
        f"Reply 'mockup' and I'll start one this week.\n"
        f"\n"
        f"— {name}\n"
        f"\n"
        f"(Internal note: this is a draft — review and personalize the "
        f"area + customer language before sending. Never publish without "
        f"approval.)"
    )


def _start_parker(context: str | None = None) -> dict:
    profile = _agency_profile()
    body = _make_parker_promo(profile)
    doc = create_document({
        "title":      f"Promo draft — {profile.get('free_offer', 'Free homepage mockup')}",
        "type":       "promo_copy",
        "created_by": "parker",
        "shared_with": ["olivia", "video"],
        "body":       body,
        "status":     "ready",
    })
    reply_body = (
        f"I drafted a promo built around your free offer "
        f"(**{profile.get('free_offer', 'Free homepage mockup')}**) and the "
        f"paid follow-up. It's in the shared library — review-only, nothing "
        f"goes out without you. If you want a Reels version, hand it to Video Partner."
    )
    msg = append_message({
        "role": "parker", "partner": "parker",
        "text": _wrap_with_voice("parker", reply_body, "start",
                                 add_banter_for="video"),
        "actions": [
            {"label": "Open Parker", "kind": "scroll", "target": "parker-details"},
            {"label": "Send to Video Partner", "kind": "ask_partner",
             "partner": "video", "prompt": "Turn the new promo into a short script."},
        ],
    })
    wi = _bump_work_item("parker")
    free_offer = profile.get("free_offer", "Free homepage mockup")
    paid_offer = profile.get("paid_offer", "Starter website fix from $150")
    return {
        "ok":          True,
        "partner":     "parker",
        "messages":    [msg],
        "documents":   [doc],
        "work_item":   wi,
        "summary":     "Parker wrote a promo for you to review.",
        "result_card": {
            "headline":    f"I wrote a promo built around \"{free_offer}\".",
            "bullets":     [
                f"Free offer baked in: {free_offer}",
                f"Paid follow-up offer: {paid_offer}",
                "Friendly, not pushy, no \"3 free fixes\" language",
            ],
            "next_action": {
                "label":  "Read it",
                "kind":   "scroll",
                "target": "parker-details",
            },
        },
    }


def _start_video(context: str | None = None) -> dict:
    """Generate a short_script via video_partner.generate_package using
    the agency's free offer as the topic.

    v12.8: if `context` is provided (user's answer to Video's question),
    parse topic + platform from it. Platform is included in the script
    title so the user can see what was generated.
    """
    profile = _agency_profile()
    topic = profile.get("free_offer") or "Free homepage mockup"
    platform = None
    if context:
        parsed_topic, parsed_platform = _parse_video_request(context)
        if parsed_topic: topic = parsed_topic
        platform = parsed_platform
    if platform:
        topic = f"{topic} ({platform})"
    try:
        import video_partner as _vp
        package = _vp.generate_package(content_type="short_script", topic=topic)
    except Exception as e:
        msg = append_message({
            "role": "video", "partner": "video",
            "text": f"Couldn't generate a script — {e}. Open Video Partner to try manually.",
            "actions": [{"label": "Open Video Partner", "kind": "scroll",
                         "target": "video-details"}],
        })
        return {"ok": False, "partner": "video", "messages": [msg],
                "documents": [], "work_item": None,
                "summary": f"Video stalled: {e}"}

    # Mirror the package into shared documents so the office library
    # shows what Video Partner produced.
    doc = create_document({
        "title":      package.get("title") or f"Short script — {topic}",
        "type":       "video_script",
        "created_by": "video",
        "shared_with": ["olivia", "parker", "youtube"],
        "body":       package.get("body") or "",
        "status":     "ready",
    })
    reply_body = (
        f"Short script's ready — built around **{topic}**. It's in the "
        f"library as a draft. Hand it to YouTube Growth if you want title "
        f"ideas on the same hook."
    )
    msg = append_message({
        "role": "video", "partner": "video",
        "text": _wrap_with_voice("video", reply_body, "start",
                                 add_banter_for="youtube"),
        "actions": [
            {"label": "Open Video Partner", "kind": "scroll", "target": "video-details"},
            {"label": "Send to YouTube Growth", "kind": "ask_partner",
             "partner": "youtube",
             "prompt": "Turn the new short script into title ideas."},
        ],
    })
    wi = _bump_work_item("video")
    return {
        "ok":          True,
        "partner":     "video",
        "messages":    [msg],
        "documents":   [doc],
        "work_item":   wi,
        "summary":     "Video Partner wrote a short script.",
        "result_card": {
            "headline":    f"I wrote a short video script for \"{topic}\".",
            "bullets":     [
                "Phone-first, friendly tone",
                "Built for Reels / TikTok / Shorts",
                "No publishing — review-only",
            ],
            "next_action": {
                "label":  "Read it",
                "kind":   "scroll",
                "target": "video-details",
            },
        },
    }


def _start_youtube(context: str | None = None) -> dict:
    """Generate a full YouTube package from the agency's free offer."""
    profile = _agency_profile()
    topic = profile.get("free_offer") or "Free homepage mockup"
    try:
        import youtube_partner as _yt
        package = _yt.generate_package(content_type="full", topic=topic)
    except Exception as e:
        msg = append_message({
            "role": "youtube", "partner": "youtube",
            "text": f"Couldn't generate ideas — {e}. Open YouTube Growth to try manually.",
            "actions": [{"label": "Open YouTube Growth", "kind": "scroll",
                         "target": "youtube-details"}],
        })
        return {"ok": False, "partner": "youtube", "messages": [msg],
                "documents": [], "work_item": None,
                "summary": f"YouTube stalled: {e}"}

    doc = create_document({
        "title":      package.get("title") or f"YouTube package — {topic}",
        "type":       "campaign_package",
        "created_by": "youtube",
        "shared_with": ["olivia", "video", "parker"],
        "body":       package.get("body") or "",
        "status":     "ready",
    })
    reply_body = (
        f"Full package drafted — title angles, hooks, and a concept all "
        f"around **{topic}**. Sitting in the library for your review. "
        f"Approval-based — nothing publishes."
    )
    msg = append_message({
        "role": "youtube", "partner": "youtube",
        "text": _wrap_with_voice("youtube", reply_body, "start"),
        "actions": [
            {"label": "Open YouTube Growth", "kind": "scroll", "target": "youtube-details"},
        ],
    })
    wi = _bump_work_item("youtube")
    return {
        "ok":          True,
        "partner":     "youtube",
        "messages":    [msg],
        "documents":   [doc],
        "work_item":   wi,
        "summary":     "YouTube Growth found video ideas.",
        "result_card": {
            "headline":    f"I found video ideas for \"{topic}\".",
            "bullets":     [
                "Title ideas, hooks, and a video concept",
                "Approval-based — I prep, you decide",
                "Nothing publishes automatically",
            ],
            "next_action": {
                "label":  "See the ideas",
                "kind":   "scroll",
                "target": "youtube-details",
            },
        },
    }


def start_work(partner_id: str, context: str | None = None) -> dict:
    """
    v12.2 — actually do the partner's first piece of work and surface
    it visibly. Olivia delegates → partner produces → user sees.

    v12.8 — optional `context` is the user's free-text answer to the
    partner's clarifying question. Logan parses it for category+city,
    Video parses it for topic+platform, etc. Handlers without context
    handling ignore it cleanly.

    Returns a structured response:
        {
          ok, partner, messages: [...], documents: [...],
          work_item: { ... | None }, summary,
        }

    Raises KeyError for unknown partners.
    """
    partner_id = (partner_id or "").strip().lower()
    handlers = {
        "olivia":  _start_olivia,
        "logan":   _start_logan,
        "sage":    _start_sage,
        "parker":  _start_parker,
        "video":   _start_video,
        "youtube": _start_youtube,
    }
    if partner_id not in handlers:
        raise KeyError(partner_id)
    handler = handlers[partner_id]
    # Pass context only to handlers that accept it (Python-style
    # introspection: try kwargs, fall back to no-arg).
    try:
        return handler(context=context)
    except TypeError:
        return handler()


# ======================================================================
# v12.3 — Morning briefing
# ----------------------------------------------------------------------
# Replaces the v12.1/v12.2 empty-state greeting. When you open the
# Hub, Olivia tells you what each partner has prepared — not in
# button-y "Logan: 0 tasks" form, but in conversational "Logan
# has 3 ranked candidates ready" form. Composed from live data
# across all partner modules.
# ======================================================================

def _partner_status_line(pid: str) -> tuple[str, dict | None]:
    """
    Return a (one-line status sentence in the partner's voice,
    optional action card) describing what that partner has ready.
    Empty sentence = nothing to surface for this partner today.
    """
    try:
        if pid == "logan":
            import lead_candidates as _lc
            picks = _lc.compute_picks(k=5)
            count = len(picks)
            if count == 0:
                return ("", None)
            top = picks[0].get("business_name") or "your top one"
            ready = sum(1 for p in picks if p.get("ready_for_outreach"))
            if ready:
                s = (f"Logan has {count} possible client"
                     f"{'s' if count != 1 else ''} — {top} is ready to reach out to.")
            else:
                s = (f"Logan has {count} possible client"
                     f"{'s' if count != 1 else ''} on the board — best one is {top}.")
            return (s, {"label": "Open Logan", "kind": "scroll",
                        "target": "logan-details"})
        if pid == "sage":
            import seo_partner as _sp
            queue = _sp.list_approval_queue()
            projects = _sp.load_projects()
            if queue:
                top = queue[0]
                s = (f"Sage has {len(queue)} website fix"
                     f"{'es' if len(queue) != 1 else ''} waiting for your OK — "
                     f"top one: \"{top.get('issue', 'a quick fix')}\".")
                return (s, {"label": "Open Sage", "kind": "scroll",
                            "target": "sage-details"})
            # No queue — is the latest website check walked yet?
            if projects:
                audits = _sp.list_audits(projects[0]["id"])
                if audits:
                    latest = audits[-1]
                    items = []
                    for section in (latest.get("checklist") or {}).values():
                        if isinstance(section, list):
                            items.extend(section)
                    pending = sum(1 for it in items
                                  if (it.get("status") or "") == "pending")
                    if pending:
                        s = (f"Sage's website check on {projects[0].get('project_name', 'your site')} "
                             f"still has {pending} item"
                             f"{'s' if pending != 1 else ''} to walk through.")
                        return (s, {"label": "Open Sage", "kind": "scroll",
                                    "target": "sage-details"})
            return ("", None)
        if pid == "youtube":
            import youtube_partner as _yt
            packages = _yt.load_packages()
            drafts = [p for p in packages
                      if (p.get("status") or "draft") == "draft"]
            if drafts:
                top = drafts[-1]
                s = (f"YouTube has {len(drafts)} video idea"
                     f"{'s' if len(drafts) != 1 else ''} drafted — "
                     f"latest is \"{top.get('title', 'untitled')}\".")
                return (s, {"label": "Open YouTube Growth", "kind": "scroll",
                            "target": "youtube-details"})
            return ("", None)
        if pid == "video":
            import video_partner as _vp
            packages = _vp.load_packages()
            drafts = [p for p in packages
                      if (p.get("status") or "draft") == "draft"]
            if drafts:
                top = drafts[-1]
                s = (f"Video has {len(drafts)} script"
                     f"{'s' if len(drafts) != 1 else ''} on the desk — "
                     f"newest is \"{top.get('title', 'untitled')}\".")
                return (s, {"label": "Open Video Partner", "kind": "scroll",
                            "target": "video-details"})
            return ("", None)
        if pid == "parker":
            docs = list_documents(partner="parker", type_="promo_copy")
            if docs:
                top = docs[-1]
                s = (f"Parker has a promo waiting for you — "
                     f"\"{top.get('title', 'untitled')}\".")
                return (s, {"label": "Open Parker", "kind": "scroll",
                            "target": "parker-details"})
            wis = list_work_items(partner="parker", status="new")
            if wis:
                s = (f"Parker has a promo to draft — \"{wis[0].get('title', 'a draft')}\".")
                return (s, {"label": "Make Promo", "kind": "do_it_for_me",
                            "partner": "parker"})
            return ("", None)
    except Exception:
        pass
    return ("", None)


def mission_board() -> dict:
    """
    v12.4: 'Today's Mission' whiteboard at the top of the office.
    Reads the agency profile + live partner state to surface ONE main
    mission + ONE next recommended move. No persistence.
    """
    try:
        import onboarding as _ob
        profile = _ob.load_agency_profile() or {}
    except Exception:
        profile = {}

    agency = profile.get("agency_name") or "MixedMakerShop"
    area   = profile.get("default_search_area") or "your area"
    free   = profile.get("free_offer") or "Free homepage mockup"

    # Default mission is the agency's headline goal.
    main_goal = (profile.get("main_goal") or
                 f"Get {agency} more local clients in {area}.")

    # Compute next-move using the same signals Olivia uses for the
    # next-actions list, but in plain language.
    next_text = ""
    next_action: dict | None = None
    try:
        import lead_candidates as _lc
        ready = [p for p in _lc.compute_picks(k=10)
                 if p.get("ready_for_outreach")]
        if ready:
            next_text = (
                f"Use {ready[0].get('business_name') or 'your top client'} — "
                f"Logan already prepped the outreach. Copy it and send."
            )
            next_action = {"label": "Open Logan",
                           "kind":  "scroll", "target": "logan-details"}
    except Exception:
        pass

    if not next_text:
        try:
            import seo_partner as _sp
            queue = _sp.list_approval_queue()
            if queue:
                top = queue[0]
                next_text = (
                    f"Approve Sage's website fix — \"{top.get('issue', 'a quick fix')}\"."
                )
                next_action = {"label": "Open Sage",
                               "kind": "scroll", "target": "sage-details"}
        except Exception:
            pass

    if not next_text:
        # Default: kick off the team to find the first batch of clients.
        next_text = (
            f"Ask Logan to find clients in {area}, then Parker to write outreach."
        )
        next_action = {"label": "Get me clients",
                       "kind":  "ask_partner",
                       "partner": "olivia",
                       "prompt":  "Get me clients"}

    return {
        "mission":      main_goal,
        "next_move":    next_text,
        "next_action":  next_action,
        "hq_name":      agency,
        "hq_area":      area,
        "free_offer":   free,
    }


def morning_briefing() -> dict:
    """
    Compose the morning briefing card. v12.4: spec-mandated leading
    line — "Hey Topher, I'm running the office today. Tell me what
    you need, or pick one of these." — then a soft summary of what
    each partner has on their desk. Plain language throughout.
    """
    hour = datetime.now().hour
    if hour < 5:
        time_word = "tonight"
    elif hour < 12:
        time_word = "this morning"
    elif hour < 17:
        time_word = "this afternoon"
    elif hour < 22:
        time_word = "this evening"
    else:
        time_word = "tonight"

    opener = (
        f"Hey Topher, I'm running the office {time_word}. "
        f"Tell me what you need, or pick one of these."
    )

    partner_lines: list[str] = []
    actions: list[dict] = []
    for pid in ("logan", "sage", "parker", "video", "youtube"):
        line, action = _partner_status_line(pid)
        if line:
            partner_lines.append(line)
            if action:
                actions.append(action)

    if partner_lines:
        team_summary = "\n\nWhile you decide, here's what's already on our desks:\n  " + \
            "\n  ".join(f"• {l}" for l in partner_lines)
    else:
        team_summary = "\n\nThe whole team is fresh — nothing on our desks yet."

    text = opener + team_summary
    return {
        "text":             text,
        "actions":          actions,
        "suggestion_chips": office_suggestion_chips(),
        "opener":           opener,
        "lines":            partner_lines,
    }


# ======================================================================
# v12.3 — Activity feed
# ----------------------------------------------------------------------
# Composes a chronological stream from existing storage:
#   - Console messages (user + partner replies)
#   - Work items created or status-changed
#   - Shared documents created or shared
#   - Sage audits + monthly reports
#   - YouTube / Video packages generated
# No new persistence — pure projection over current data.
# ======================================================================

def _activity_event(partner: str, kind: str, title: str,
                    when: str, target: str | None = None) -> dict:
    return {
        "partner":  partner,
        "icon":     PARTNERS.get(partner, {}).get("emoji", "•"),
        "kind":     kind,
        "title":    title,
        "when":     when,
        "target":   target,
    }


def activity_feed(limit: int = 20) -> list[dict]:
    """
    Build a chronological-newest-first activity stream from existing
    storage. Pure read — no persistence.

    Event kinds:
        message       — a console reply
        work_item     — work item created or status changed
        document      — shared document created
        audit         — Sage audit generated
        package       — YouTube/Video package generated
        report        — Sage monthly report generated
    """
    events: list[dict] = []

    # Console messages
    for m in load_messages():
        if m.get("role") in (None, "user"):
            continue
        events.append(_activity_event(
            m.get("partner") or "olivia",
            "message",
            # Truncate so the feed stays scannable.
            (m.get("text") or "").split("\n", 1)[0][:160],
            m.get("created_at") or "",
            target=None,
        ))

    # Work items (created)
    for w in load_work_items():
        events.append(_activity_event(
            w.get("source_partner") or "olivia",
            "work_item",
            f"assigned {w.get('assigned_partner', 'partner')}: "
            f"{w.get('title', 'untitled')}",
            w.get("created_at") or "",
            target=None,
        ))

    # Shared documents
    for d in load_documents():
        events.append(_activity_event(
            d.get("created_by") or "olivia",
            "document",
            f"created {d.get('type', 'note')}: "
            f"\"{d.get('title', 'untitled')}\"",
            d.get("created_at") or "",
            target=None,
        ))

    # Sage audits + reports
    try:
        import seo_partner as _sp
        projects = _sp.load_projects()
        for p in projects:
            pid = p.get("id")
            if not pid:
                continue
            for a in _sp.list_audits(pid):
                events.append(_activity_event(
                    "sage", "audit",
                    f"ran audit on {p.get('project_name', 'project')}",
                    a.get("generated_at") or "",
                    target="sage-details",
                ))
            for r in _sp.list_reports(pid):
                events.append(_activity_event(
                    "sage", "report",
                    f"generated {r.get('month', '?')} report for "
                    f"{p.get('project_name', 'project')}",
                    r.get("generated_at") or "",
                    target="sage-details",
                ))
    except Exception:
        pass

    # YouTube + Video packages
    try:
        import youtube_partner as _yt
        for p in _yt.load_packages():
            events.append(_activity_event(
                "youtube", "package",
                f"generated {p.get('content_type', 'package')}: "
                f"\"{p.get('title', 'untitled')}\"",
                p.get("created_at") or "",
                target="youtube-details",
            ))
    except Exception:
        pass
    try:
        import video_partner as _vp
        for p in _vp.load_packages():
            events.append(_activity_event(
                "video", "package",
                f"generated {p.get('content_type', 'package')}: "
                f"\"{p.get('title', 'untitled')}\"",
                p.get("created_at") or "",
                target="video-details",
            ))
    except Exception:
        pass

    # Sort newest-first, cap.
    events.sort(key=lambda e: e.get("when") or "", reverse=True)
    return events[:max(1, min(limit, 100))]


# ======================================================================
# v12.3 — Auto-delegation (outcome phrases → multi-partner workflows)
# ----------------------------------------------------------------------
# When the user types an outcome phrase like "get me more clients",
# Olivia delegates to multiple partners in sequence, each does real
# work, and the conversation is visible in the console.
# ======================================================================

# Each entry: keywords → ordered partner chain. The chain runs real
# start_work() for each partner in order; Olivia narrates the
# delegation between steps.
_AUTO_DELEGATIONS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    # Keywords, partner chain, Olivia's intro line.
    (
        ("more clients", "get me clients", "grow the business",
         "more customers", "more business", "more work"),
        ("logan", "parker", "video"),
        "OK Topher, big ask — I'll line up the team. Logan finds prospects, "
        "Parker drafts outreach, Video Partner stages content. Hang tight.",
    ),
    (
        ("improve seo", "improve our seo", "improve the seo",
         "rank higher", "fix seo", "fix the seo"),
        ("sage", "parker"),
        "Got it. Sage will audit and Parker can spin a promo off the wins.",
    ),
    (
        ("make a campaign", "build a campaign", "launch a campaign",
         "marketing campaign"),
        ("parker", "video", "youtube"),
        "Yep — Parker takes the angle, Video stages a script, "
        "YouTube hands me title ideas. All review-only.",
    ),
    (
        ("content plan", "content for the month",
         "make content"),
        ("video", "youtube", "parker"),
        "On it. Video drafts a script, YouTube hands ideas, "
        "Parker turns the wins into promo copy.",
    ),
)


def _detect_auto_delegation(text: str) -> tuple[tuple[str, ...], str] | None:
    t = (text or "").lower()
    for keywords, chain, intro in _AUTO_DELEGATIONS:
        if any(kw in t for kw in keywords):
            return chain, intro
    return None


def run_auto_delegation(text: str, chain: tuple[str, ...],
                        intro: str) -> dict:
    """
    Run a multi-partner outcome workflow. Olivia narrates the start
    and the wrap-up; each partner in the chain does real work via
    start_work() and posts their reply.

    Returns the same shape as route_command for the UI.
    """
    appended: list[dict] = []

    # User message
    user_msg = append_message({
        "role": "user", "partner": "user", "text": text,
    })
    appended.append(user_msg)

    # Olivia opens with the chain announcement.
    chain_names = " → ".join(PARTNERS[p]["name"] for p in chain)
    olivia_open = append_message({
        "role": "olivia", "partner": "olivia",
        "text": (
            f"{intro}\n\n"
            f"Order: {chain_names}."
        ),
        "actions": [],
    })
    appended.append(olivia_open)

    # Run each partner in sequence.
    for partner_id in chain:
        try:
            result = start_work(partner_id)
            # start_work() already appended the partner's message to
            # the console log; pull it back so the response carries it.
            if result.get("messages"):
                appended.extend(result["messages"])
        except Exception as e:
            # If a partner errors out, post an Olivia note and continue.
            err_msg = append_message({
                "role": "olivia", "partner": "olivia",
                "text": f"({PARTNERS[partner_id]['name']} stalled: {e}. "
                        "Skipping for now.)",
                "actions": [],
            })
            appended.append(err_msg)

    # Olivia wraps up.
    olivia_close = append_message({
        "role": "olivia", "partner": "olivia",
        "text": (
            "Topher, the team is ready for review. "
            "Check the activity feed and the shared documents — "
            "nothing went out, everything's draft."
        ),
        "actions": [
            {"label": "Show me what to do next",
             "kind":  "ask_partner",
             "partner": "olivia",
             "prompt": "What should I do next?"},
        ],
    })
    appended.append(olivia_close)

    return {
        "chosen_partner":     "olivia",
        "secondary_partners": list(chain),
        "intent":             "auto_delegation",
        "response_text":      olivia_open["text"],
        "suggested_actions":  olivia_close["actions"],
        "created_work_items": [],
        "created_documents":  [],
        "messages":           appended,
        "auto_delegation":    True,
    }


# ======================================================================
# v12.7 — Today's thread + smart next-step
# ----------------------------------------------------------------------
# Makes the landing screen evolve as the user works. Reads today's
# activity feed, summarizes what's been done, and computes the most
# useful next step based on partner sequencing rules. Pure projection
# over existing storage — no new persistence.
#
# Goal: tasks should feel like a continuing thread, not isolated
# one-shots that always return to the same five buttons.
# ======================================================================

def _today_prefix() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def today_thread() -> dict:
    """
    Compose a 'Today so far' view + smart next-step recommendation.

    Returns:
        {
          today_log:    [{partner, summary, when, icon}, ...],   # newest first
          next_step:    {label, partner, context, kind, target/prompt},
          has_progress: bool,
        }

    Reads from existing storage (activity_feed) — no new persistence.
    """
    today = _today_prefix()

    # Walk today's events. Compress to one row per partner-action so
    # the thread doesn't repeat the same partner three times in a row.
    feed = activity_feed(limit=50)
    today_events: list[dict] = []
    seen_keys: set[str] = set()
    partners_done_today: dict[str, list[dict]] = {}  # partner_id → events

    for ev in feed:
        when = ev.get("when") or ""
        if not when.startswith(today):
            continue
        # Compress: only keep the most recent event per (partner, kind).
        # Multiple "message" rows from one partner collapse to one line.
        compress_key = f"{ev.get('partner')}|{ev.get('kind')}"
        if compress_key in seen_keys:
            continue
        seen_keys.add(compress_key)
        today_events.append(ev)
        partners_done_today.setdefault(ev.get("partner") or "?", []).append(ev)

    # Build the user-facing log with a friendly one-line summary per
    # partner showing what they DID, not what kind of event it was.
    log_rows: list[dict] = []
    partner_summaries: dict[str, str] = {}
    for pid in ("logan", "sage", "parker", "video", "youtube", "olivia"):
        events = partners_done_today.get(pid)
        if not events:
            continue
        line = _summary_for_partner(pid)
        if not line:
            # Fallback to the most recent event's title.
            line = events[0].get("title") or ""
        partner_summaries[pid] = line
        latest_when = events[0].get("when", "")
        log_rows.append({
            "partner": pid,
            "icon":    PARTNERS.get(pid, {}).get("emoji", "•"),
            "summary": line,
            "when":    latest_when[11:16] if len(latest_when) > 10 else latest_when,
        })

    # Order log rows by most recent partner activity (newest first).
    log_rows.sort(
        key=lambda r: max(
            (e.get("when", "") for e in partners_done_today.get(r["partner"], [])),
            default="",
        ),
        reverse=True,
    )

    has_progress = bool(log_rows)
    next_step = compute_smart_next(partners_done_today)
    return {
        "today_log":    log_rows,
        "next_step":    next_step,
        "has_progress": has_progress,
    }


def _summary_for_partner(pid: str) -> str:
    """
    Live one-line summary of what this partner has on their desk
    today. Used by the today_thread renderer instead of raw event
    titles which read like log lines.
    """
    try:
        if pid == "logan":
            import lead_candidates as _lc
            picks = _lc.compute_picks(k=10)
            if picks:
                n = len(picks)
                return (f"Found {n} possible client{'s' if n != 1 else ''} "
                        f"— top is {picks[0].get('business_name', 'one of them')}.")
        if pid == "sage":
            import seo_partner as _sp
            queue = _sp.list_approval_queue()
            projects = _sp.load_projects()
            if queue:
                return (f"Flagged {len(queue)} website fix"
                        f"{'es' if len(queue) != 1 else ''} for your review.")
            if projects:
                audits = _sp.list_audits(projects[0]["id"])
                if audits:
                    return f"Checked your website."
        if pid == "parker":
            docs = list_documents(partner="parker", type_="promo_copy")
            if docs:
                return f"Drafted a promo around your free offer."
        if pid == "video":
            import video_partner as _vp
            packages = _vp.load_packages()
            if packages:
                latest = packages[-1]
                return f"Wrote a {latest.get('content_type', 'script')} for you."
        if pid == "youtube":
            import youtube_partner as _yt
            packages = _yt.load_packages()
            if packages:
                latest = packages[-1]
                return f"Drafted {latest.get('content_type', 'video ideas')}."
        if pid == "olivia":
            return "Ranked the next 3 things to do."
    except Exception:
        pass
    return ""


def compute_smart_next(partners_done_today: dict[str, list[dict]]) -> dict | None:
    """
    Return the most useful next step given what's been done today.
    Ordered rules so the first match wins — each rule corresponds to
    a real handoff pattern (Logan → Parker, Sage → fix approval,
    Parker → Video, Video → YouTube).

    Returns a dict the frontend uses to render the smart-next button:
        {
          label:     "Draft outreach for the top 3 clients",
          partner:   "parker",            # who handles it
          context:   "based on Logan's picks",
          kind:      "do_it_for_me" | "scroll" | "ask_partner",
          target?:   "<element id>" | "<partner id>",
          prompt?:   "..."
        }

    Returns None if there's no clear next step (the UI falls back
    to the 5 simple buttons).
    """
    done = set(partners_done_today.keys())
    has_logan   = "logan"   in done
    has_sage    = "sage"    in done
    has_parker  = "parker"  in done
    has_video   = "video"   in done
    has_youtube = "youtube" in done

    # Rule 1: Logan found clients but Parker hasn't drafted outreach yet.
    if has_logan and not has_parker:
        try:
            import lead_candidates as _lc
            n = len(_lc.compute_picks(k=10))
        except Exception:
            n = 0
        label = (f"Draft outreach for the top {min(n, 3)} client"
                 f"{'s' if min(n, 3) != 1 else ''}" if n else
                 "Draft outreach for your top client")
        return {
            "label":   label,
            "partner": "parker",
            "context": "Parker uses Logan's picks",
            "kind":    "do_it_for_me",
            "target":  "parker",
        }

    # Rule 2: Sage checked the site but no fixes approved yet.
    if has_sage:
        try:
            import seo_partner as _sp
            queue = _sp.list_approval_queue()
            if queue:
                return {
                    "label":   f"Approve the top website fix",
                    "partner": "sage",
                    "context": f"{(queue[0].get('issue') or 'top fix')}",
                    "kind":    "scroll",
                    "target":  "sage-details",
                }
        except Exception:
            pass

    # Rule 3: Parker drafted a promo, Video hasn't scripted it.
    if has_parker and not has_video:
        return {
            "label":   "Turn the promo into a video script",
            "partner": "video",
            "context": "Video Partner picks up Parker's promo",
            "kind":    "do_it_for_me",
            "target":  "video",
        }

    # Rule 4: Video scripted, YouTube hasn't ideated.
    if has_video and not has_youtube:
        return {
            "label":   "Spin into YouTube title ideas",
            "partner": "youtube",
            "context": "YouTube Growth takes Video's script",
            "kind":    "do_it_for_me",
            "target":  "youtube",
        }

    # Rule 5: Everything chained — ask Olivia what to focus on next.
    if has_logan and has_parker and has_video:
        return {
            "label":   "Tell me what's next",
            "partner": "olivia",
            "context": "Olivia reviews the whole desk",
            "kind":    "do_it_for_me",
            "target":  "olivia",
        }

    # Rule 6: Sage but not the website fix chain → suggest content.
    if has_sage and not has_parker:
        return {
            "label":   "Draft a promo from the website wins",
            "partner": "parker",
            "context": "Parker uses Sage's notes",
            "kind":    "do_it_for_me",
            "target":  "parker",
        }

    # Fallback: nothing matched cleanly — let the UI show the 5 buttons.
    return None


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
            "short_name":  meta.get("short_name", meta["name"]),
            "emoji":       meta["emoji"],
            "role":        meta["role"],
            "description": meta["description"],
            "status":      status,
            "task_count":  task_count,
            "do_it_label": meta["do_it_label"],
            # v12.0 ambient activity line:
            "chatter":     _desk_chatter(pid, task_count, status),
            # v12.3: desk decor — each desk gets 3 role-specific items
            "desk_items":  list(meta.get("desk_items", ())),
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
        # v12.3 office atmosphere:
        "briefing":         morning_briefing(),
        # v12.4 office atmosphere:
        "mission":          mission_board(),
    }
