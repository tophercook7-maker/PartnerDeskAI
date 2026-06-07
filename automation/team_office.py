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


def partner_reply(partner_id: str, text: str, context: dict | None = None) -> dict:
    """
    Generate a personality-tuned reply from the named partner.
    Returns {partner, response_text, actions}.

    No external AI — these are rule-based templates with light
    context-aware variation.
    """
    partner_id = (partner_id or "olivia").strip().lower()
    if partner_id not in PARTNERS:
        partner_id = "olivia"
    meta = PARTNERS[partner_id]
    t_low = (text or "").lower()

    actions: list[dict] = []
    if partner_id == "olivia":
        if any(k in t_low for k in ("next", "what should", "what's up", "show me")):
            response, actions = _olivia_next_actions_text()
        else:
            primary, secondary = _detect_partner(text)
            if primary == "olivia":
                response = (
                    "I'll keep an eye on the team. If you tell me what "
                    "you want done — find leads, run an SEO audit, "
                    "draft a promo — I'll route it to the right partner."
                )
            else:
                names = [PARTNERS[primary]["name"]]
                if secondary:
                    names += [PARTNERS[p]["name"] for p in secondary]
                if len(names) == 1:
                    response = f"I'll route that to {names[0]}."
                else:
                    response = (
                        f"I'll route that to {names[0]}, then loop in "
                        f"{' and '.join(names[1:])}."
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
            response = (
                f"I have {count} ranked candidate{'s' if count != 1 else ''} "
                f"ready right now. Strongest is {top_name}. "
                f"I can keep finding more if you tell me a category + city."
            )
            actions.append({"label": "Open Logan", "kind": "scroll", "target": "logan-details"})
        else:
            response = (
                "Queue is empty. Tell me a business type + city and I'll "
                "discover real businesses via OpenStreetMap, top up with "
                "research missions if coverage is thin, and rank them."
            )
            actions.append({"label": "Find Leads For Me", "kind": "do_it_for_me", "partner": "logan"})
    elif partner_id == "sage":
        if "first" in t_low or "start" in t_low or "begin" in t_low:
            response = (
                "Start with one project. For MixedMakerShop, I recommend:\n"
                "  1. Generate the SEO audit.\n"
                "  2. Review the failed or unknown items.\n"
                "  3. Turn important issues into fix tasks.\n"
                "  4. Approve the fixes you want done.\n"
                "  5. Generate a monthly report after work is completed."
            )
            actions.append({"label": "Start SEO Audit For Me", "kind": "do_it_for_me", "partner": "sage"})
        elif "audit" in t_low:
            response = (
                "I can start with a basic SEO audit. First, I'll check "
                "titles, headings, service clarity, local signals, and "
                "approval-needed fixes. No live website or GBP changes — "
                "everything stays approval-based."
            )
            actions.append({"label": "Start SEO Audit For Me", "kind": "do_it_for_me", "partner": "sage"})
        elif "report" in t_low or "monthly" in t_low:
            response = (
                "I can generate a client-friendly monthly report from "
                "current project state — what we checked, what we fixed, "
                "current wins, current issues, and next actions."
            )
            actions.append({"label": "Open Sage", "kind": "scroll", "target": "sage-details"})
        else:
            response = (
                "I'm Sage — I manage SEO audits, local SEO, website fix "
                "tasks, an approval queue, and monthly reports. Ask me "
                "to start an audit or what to do first."
            )
            actions.append({"label": "Open Sage", "kind": "scroll", "target": "sage-details"})
    elif partner_id == "parker":
        response = (
            "I can turn that into a friendly promo. The free offer "
            "should stay as a homepage mockup, not free fixes. "
            "I'll draft copy you can review and approve before sending."
        )
        actions.append({"label": "Make Promo For Me", "kind": "do_it_for_me", "partner": "parker"})
        actions.append({"label": "Open Parker", "kind": "scroll", "target": "parker-details"})
    elif partner_id == "video":
        response = (
            "I can make a short script from that offer and keep it "
            "ready for review. Reels, TikTok, YouTube Shorts — pick "
            "the format and I'll draft. Nothing publishes automatically."
        )
        actions.append({"label": "Make Video Campaign For Me", "kind": "do_it_for_me", "partner": "video"})
        actions.append({"label": "Open Video Partner", "kind": "scroll", "target": "video-details"})
    elif partner_id == "youtube":
        response = (
            "I can turn this into title ideas, hooks, and a video "
            "concept. Approval-based — I prepare ideas, you decide "
            "what gets made."
        )
        actions.append({"label": "Find Video Ideas For Me", "kind": "do_it_for_me", "partner": "youtube"})
        actions.append({"label": "Open YouTube Growth", "kind": "scroll", "target": "youtube-details"})
    else:
        response = "(no reply template registered for this partner yet)"

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

    # 3. If multi-partner, Olivia speaks first as dispatcher.
    if secondary and primary != "olivia":
        olivia_reply = partner_reply("olivia", text)
        msg = append_message({
            "role":    "olivia",
            "partner": "olivia",
            "text":    olivia_reply["response_text"],
            "actions": olivia_reply["actions"],
        })
        appended.append(msg)

    # 4. Primary partner reply
    primary_reply = partner_reply(primary, text)
    msg = append_message({
        "role":    primary,
        "partner": primary,
        "text":    primary_reply["response_text"],
        "actions": primary_reply["actions"],
    })
    appended.append(msg)

    # 5. Secondary partners chime in (one-line acknowledgements)
    for sec_id in secondary:
        if sec_id == primary:
            continue
        sec_reply = partner_reply(sec_id, text)
        # Use a shorter ack from the secondary partner.
        ack = sec_reply["response_text"].split("\n", 1)[0]
        msg = append_message({
            "role":    sec_id,
            "partner": sec_id,
            "text":    f"(I can help too.) {ack}",
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

def summary() -> dict:
    """
    One-shot UI payload: every partner's desk status + task count.
    Lazy-imports each partner module so a broken partner doesn't crash
    the whole Team Office.
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
                # Use the existing content publishing queue if available;
                # otherwise count team work items routed to parker.
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
        })
    return {
        "desks":           desks,
        "work_items":      len(load_work_items()),
        "documents":       len(load_documents()),
        "messages":        len(load_messages()),
        "waiting_approval": len(list_work_items(status="waiting_approval")),
    }
