"""
leads.py
--------
Outbound prospect tracker (CRM-lite). Pure local storage — no network
calls, no LinkedIn API, no auto-sync. Backed by data/leads.json with
atomic writes via tempfile + os.replace.

Schema for a single lead:
    {
      "id":         "<numeric string, monotonic>",
      "name":       "...",                # required, ≤200 chars
      "company":    "...",                # optional, ≤200 chars
      "handle":     "...",                # optional, ≤500 chars (URL etc.)
      "source":     "...",                # optional, ≤500 chars
      "status":     "cold|warm|hot|closed|dropped",
      "notes":      "...",                # optional, ≤MAX_NOTES_LEN chars
      "created_at": "YYYY-MM-DD HH:MM:SS",
      "updated_at": "YYYY-MM-DD HH:MM:SS",
    }

Safety:
    - data/leads.json is GITIGNORED — never leaves the local machine
      via git.
    - No tokens / credentials stored. Field whitelist + length caps
      enforced on every write.
    - Unknown fields silently dropped on save (defense against schema
      drift / malicious input).
    - Status whitelisted to a known enum.
"""

from datetime import datetime
from pathlib import Path
import json
import os
import re
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
LEADS_PATH = ROOT / "data" / "leads.json"

ALLOWED_STATUSES = ("cold", "warm", "hot", "closed", "dropped")
DEFAULT_STATUS = "cold"

MAX_NAME_LEN    = 200
MAX_COMPANY_LEN = 200
MAX_HANDLE_LEN  = 500
MAX_SOURCE_LEN  = 500
MAX_NOTES_LEN   = 4000

# v8.4: outreach pipeline. outreach_status runs PARALLEL to the existing
# v6.9 status enum (cold/warm/hot/closed/dropped) — the v7.23 pipeline
# board, v7.24 dashboard, and v7.25 click-to-filter all continue to
# read 'status'. The new pipeline UIs read 'outreach_status'.
ALLOWED_OUTREACH_STATUSES = (
    "not_started", "found", "qualified", "outreach_ready",
    "contacted", "follow_up_due", "warm", "hot", "won", "dead",
)
DEFAULT_OUTREACH_STATUS = "not_started"
ALLOWED_DEAD_REASONS = (
    "no reply after 3 follow-ups",
    "bad email",
    "not a fit",
    "already has good website",
    "not interested",
    "closed business",
)
MAX_EMAIL_LEN   = 200
MAX_URL_LEN     = 1000
MAX_STATUS_LEN  = 200
MAX_EVIDENCE    = 2000
MAX_OFFER_LEN   = 500
MAX_SUBJECT_LEN = 200
MAX_BODY_LEN    = 8000
MAX_REASON_LEN  = 200


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(leads: list[dict]) -> str:
    """Monotonic timestamp-based id. Single-user app — collisions are
    effectively impossible at millisecond resolution; we still guard
    with a deduplication check against existing ids."""
    base = str(int(time.time() * 1000))
    existing = {l.get("id") for l in leads}
    cand = base
    n = 0
    while cand in existing:
        n += 1
        cand = f"{base}-{n}"
    return cand


def _clean_lead(raw: dict, existing: dict | None = None) -> dict:
    """
    Whitelist + clamp a single lead dict. `existing` is the prior
    state of the row (for updates) so we can preserve created_at /
    id when the user doesn't supply them. Unknown keys are dropped.

    v7.0: contacted_at, follow_up_date, last_message added. Existing
    rows that pre-date these fields just get null defaults — no
    destructive migration.
    """
    if not isinstance(raw, dict):
        raise ValueError("lead must be a dict")
    name = str(raw.get("name") or (existing or {}).get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    status = (raw.get("status") or (existing or {}).get("status") or DEFAULT_STATUS).strip()
    if status not in ALLOWED_STATUSES:
        raise ValueError(
            f"status must be one of {ALLOWED_STATUSES}, got {status!r}"
        )
    ex = existing or {}
    # For nullable v7.0 fields: if the caller put the key in raw, use
    # that value (even if it's None — that's an explicit "clear"). If
    # the key isn't in raw at all, preserve the existing value. This
    # differs from the older `or` chains above which treat any falsy
    # value as "missing" — for these fields we need to distinguish
    # "not touched" from "cleared on purpose".
    def _pick(key):
        if key in raw:
            return raw[key]
        return ex.get(key)

    # v8.4: optional outreach_status with allowed-enum validation. We
    # only check if a value was *explicitly* supplied — None / blank
    # falls back to the existing value (or default).
    outreach_status_raw = raw.get("outreach_status")
    if outreach_status_raw is not None and outreach_status_raw != "":
        ors = str(outreach_status_raw).strip()
        if ors not in ALLOWED_OUTREACH_STATUSES:
            raise ValueError(
                f"outreach_status must be one of {ALLOWED_OUTREACH_STATUSES}, "
                f"got {outreach_status_raw!r}"
            )
        outreach_status = ors
    else:
        outreach_status = ex.get("outreach_status") or DEFAULT_OUTREACH_STATUS
    return {
        "id":         ex.get("id") or raw.get("id"),
        "name":       name[:MAX_NAME_LEN],
        "company":    str(raw.get("company") or ex.get("company") or "").strip()[:MAX_COMPANY_LEN],
        "handle":     str(raw.get("handle")  or ex.get("handle")  or "").strip()[:MAX_HANDLE_LEN],
        "source":     str(raw.get("source")  or ex.get("source")  or "").strip()[:MAX_SOURCE_LEN],
        "status":     status,
        "notes":      str(raw.get("notes")   or ex.get("notes")   or "")[:MAX_NOTES_LEN],
        "created_at": ex.get("created_at") or _now(),
        "updated_at": _now(),
        # v7.0 follow-up queue fields. All start as None.
        "contacted_at":   _pick("contacted_at"),
        "follow_up_date": _pick("follow_up_date"),
        "last_message":   (str(_pick("last_message") or "")[:MAX_NOTES_LEN]) or None,
        # v7.18: which template was last used for this lead, so the
        # picker can default to it next time. Validated lazily — if the
        # key drifts away from the registry, the frontend just falls
        # back to Auto.
        "last_template_key": _pick("last_template_key"),
        # --- v8.4: outreach pipeline fields ---
        # All optional. Setdefault on load() keeps pre-v8.4 rows
        # readable; this dict ensures new writes always include the
        # whole shape.
        "email":              str(raw.get("email")          or ex.get("email")          or "").strip()[:MAX_EMAIL_LEN],
        "website_url":        str(raw.get("website_url")    or ex.get("website_url")    or "").strip()[:MAX_URL_LEN],
        "website_status":     str(raw.get("website_status") or ex.get("website_status") or "").strip()[:MAX_STATUS_LEN],
        "source_url":         str(raw.get("source_url")     or ex.get("source_url")     or "").strip()[:MAX_URL_LEN],
        "evidence":           str(raw.get("evidence")       or ex.get("evidence")       or "")[:MAX_EVIDENCE],
        "offer_angle":        str(raw.get("offer_angle")    or ex.get("offer_angle")    or "").strip()[:MAX_OFFER_LEN],
        "outreach_status":    outreach_status,
        "outreach_subject":   str(raw.get("outreach_subject") or ex.get("outreach_subject") or "")[:MAX_SUBJECT_LEN],
        "outreach_body":      str(raw.get("outreach_body")    or ex.get("outreach_body")    or "")[:MAX_BODY_LEN],
        "last_contacted_at":  _pick("last_contacted_at"),
        "next_follow_up_at":  _pick("next_follow_up_at"),
        "follow_up_count":    int(_pick("follow_up_count") or 0),
        "dead_reason":        (str(_pick("dead_reason") or "")[:MAX_REASON_LEN]) or None,
    }


def load() -> list[dict]:
    """Return the full leads list, or [] if file missing/corrupt.
    v7.0: normalizes rows to always expose contacted_at / follow_up_date
    / last_message (set to None when absent on disk) so the API
    response shape is stable regardless of when the row was added."""
    if not LEADS_PATH.is_file():
        return []
    try:
        data = json.loads(LEADS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("leads")
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, dict):
            item.setdefault("contacted_at",      None)
            item.setdefault("follow_up_date",    None)
            item.setdefault("last_message",      None)
            item.setdefault("last_template_key", None)  # v7.18
            # --- v8.4: outreach pipeline back-compat defaults ---
            item.setdefault("email",              "")
            item.setdefault("website_url",        "")
            item.setdefault("website_status",     "")
            item.setdefault("source_url",         "")
            item.setdefault("evidence",           "")
            item.setdefault("offer_angle",        "")
            item.setdefault("outreach_status",    DEFAULT_OUTREACH_STATUS)
            item.setdefault("outreach_subject",   "")
            item.setdefault("outreach_body",      "")
            item.setdefault("last_contacted_at",  None)
            item.setdefault("next_follow_up_at",  None)
            item.setdefault("follow_up_count",    0)
            item.setdefault("dead_reason",        None)
    return items


def _save(leads: list[dict]) -> None:
    """Atomic write of the full leads list."""
    LEADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".leads.", suffix=".tmp", dir=str(LEADS_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"leads": leads}, f, indent=2)
            f.write("\n")
        os.replace(tmp, LEADS_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(raw: dict) -> dict:
    """Append a new lead. Returns the saved row (with id, timestamps)."""
    cleaned = _clean_lead(raw)
    cleaned["id"] = _next_id(load())
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    leads = load()
    leads.append(cleaned)
    _save(leads)
    return cleaned


def update(lead_id: str, raw: dict) -> dict:
    """Update one lead. Raises KeyError if not found."""
    leads = load()
    for i, l in enumerate(leads):
        if l.get("id") == lead_id:
            merged = _clean_lead(raw, existing=l)
            merged["id"] = lead_id  # never let the caller change the id
            leads[i] = merged
            _save(leads)
            return merged
    raise KeyError(lead_id)


def delete(lead_id: str) -> bool:
    """Remove a lead. Returns True iff something was removed."""
    leads = load()
    before = len(leads)
    leads = [l for l in leads if l.get("id") != lead_id]
    if len(leads) == before:
        return False
    _save(leads)
    return True


# --- v7.20: Bulk paste import ------------------------------------------

MAX_BATCH_SIZE = 50

# Match the canonical LinkedIn profile URL shapes. We accept with or
# without protocol, with or without www, and with or without a trailing
# slash. The slug is captured for normalization. Bare slugs (without
# /in/) are rejected because they're too ambiguous against natural
# text.
_LINKEDIN_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_\-]+)/?",
    re.IGNORECASE,
)


def parse_linkedin_input(line: str) -> dict | None:
    """
    Parse one line of paste input. Returns a {handle, name} dict on
    success or None for blank lines, comment lines (#…), or anything
    that isn't a recognizable LinkedIn URL. Name is guessed from the
    slug ("christian-kovac" → "Christian Kovac"); the user can edit
    after import.
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    m = _LINKEDIN_URL_RE.search(s)
    if not m:
        return None
    slug = m.group(1)
    name_words = [w.capitalize() for w in slug.replace("_", "-").split("-") if w]
    return {
        "handle": f"linkedin.com/in/{slug}",
        "name":   " ".join(name_words) or slug,
    }


# --- v8.4: Logan autonomous outreach pipeline -------------------------
# Pure local. NO emails sent. NO LinkedIn messages. NO OpenAI. NO web
# fetches. Everything writes to data/leads.json only.

from datetime import timedelta as _td

_OUTREACH_SUBJECT_TMPL = "quick website/contact idea for {business_name}"

_OUTREACH_BODY_TMPL = """Hi {business_name},

I’m Topher with MixedMakerShop. I was looking at local businesses that could make it easier for customers to contact them from a phone, and I noticed {evidence}.

I help small businesses set up simple websites, landing pages, and tap/contact hubs so people can call, message, book, or find them faster.

If you’re curious what a fresh homepage could look like for {business_name}, I’d be happy to put together a free mockup — no charge, no commitment. If you want me to actually build the site after seeing it, my starter website fix begins at $150.

Want me to send the mockup?

Topher
MixedMakerShop"""

_FOLLOW_UP_TMPL = """Hi {business_name},

Just checking back on this — want me to put together that free homepage mockup I mentioned? Takes me about a day and there’s no charge to look.

No pressure either way.

Topher
MixedMakerShop"""


def prepare_outreach(lead_id: str) -> dict:
    """
    Generate the outreach subject + body for a lead and flip
    outreach_status to 'outreach_ready'. Requires the lead to have an
    email — otherwise raises ValueError so the caller surfaces a 400.

    Writes outreach_subject + outreach_body to the lead row. Does NOT
    send anything; the user copies and pastes manually.
    """
    existing = _find(lead_id)
    if not (existing.get("email") or "").strip():
        raise ValueError("lead has no email — cannot prepare outreach")
    name = (existing.get("name") or "there").strip() or "there"
    evidence = (existing.get("evidence") or "").strip() or (
        "your business could be easier to reach online"
    )
    subject = _OUTREACH_SUBJECT_TMPL.format(business_name=name)
    body = _OUTREACH_BODY_TMPL.format(business_name=name, evidence=evidence)
    return update(lead_id, {
        "outreach_subject": subject,
        "outreach_body":    body,
        "outreach_status":  "outreach_ready",
    })


def mark_outreach_sent(lead_id: str) -> dict:
    """
    Record that the user manually sent the prepared outreach. Stamps
    last_contacted_at + contacted_at = now, schedules
    next_follow_up_at = today + 3 days, flips outreach_status to
    'contacted'. NO email sent — the user already did that out of band.
    """
    now = datetime.now()
    next_due = (now + _td(days=3)).strftime("%Y-%m-%d")
    return update(lead_id, {
        "last_contacted_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "contacted_at":      now.strftime("%Y-%m-%d %H:%M:%S"),
        "next_follow_up_at": next_due,
        "outreach_status":   "contacted",
    })


def write_follow_up(lead_id: str) -> dict:
    """
    Generate the follow-up message body and store it in
    outreach_subject + outreach_body, increment follow_up_count, flip
    outreach_status to 'follow_up_due' if not already 'dead'/'won'.
    """
    existing = _find(lead_id)
    name = (existing.get("name") or "there").strip() or "there"
    subject = "re: " + _OUTREACH_SUBJECT_TMPL.format(business_name=name)
    body = _FOLLOW_UP_TMPL.format(business_name=name)
    count = int(existing.get("follow_up_count") or 0) + 1
    raw = {
        "outreach_subject":   subject,
        "outreach_body":      body,
        "follow_up_count":    count,
    }
    cur = (existing.get("outreach_status") or "").lower()
    if cur not in ("dead", "won"):
        raw["outreach_status"] = "follow_up_due"
    return update(lead_id, raw)


def snooze_follow_up(lead_id: str, days: int = 3) -> dict:
    """
    Push next_follow_up_at out by N days. Days must be 1..30; values
    outside that range raise ValueError.
    """
    if not isinstance(days, int) or days < 1 or days > 30:
        raise ValueError("snooze days must be an integer in 1..30")
    next_due = (datetime.now() + _td(days=days)).strftime("%Y-%m-%d")
    return update(lead_id, {"next_follow_up_at": next_due})


def mark_dead(lead_id: str, reason: str) -> dict:
    """
    Set outreach_status='dead' + dead_reason. Reason must be one of
    ALLOWED_DEAD_REASONS — anything else raises ValueError.
    """
    reason = (reason or "").strip()
    if reason not in ALLOWED_DEAD_REASONS:
        raise ValueError(
            f"dead_reason must be one of {ALLOWED_DEAD_REASONS}, got {reason!r}"
        )
    return update(lead_id, {
        "outreach_status":   "dead",
        "dead_reason":       reason,
        "next_follow_up_at": None,
    })


# ======================================================================
# v9.2 — Follow-up tracking
# ----------------------------------------------------------------------
# Generalized scheduling + multi-channel follow-up drafts + due-list
# query. Builds on the v8.4 next_follow_up_at / follow_up_count fields
# and the existing _FOLLOW_UP_TMPL (free-mockup CTA). Zero outbound
# calls — every action is pure local state mutation; the user still
# copy-pastes and sends from their own client.
# ======================================================================

# Default cadence: first follow-up 3 days after contact; subsequent
# follow-ups +5 days each. Configurable per-call via the `days` arg.
DEFAULT_FIRST_FOLLOWUP_DAYS  = 3
DEFAULT_REPEAT_FOLLOWUP_DAYS = 5
MAX_SNOOZE_DAYS              = 30
MAX_FOLLOWUP_DAYS            = 60


def schedule_follow_up(lead_id: str, days: int = DEFAULT_FIRST_FOLLOWUP_DAYS) -> dict:
    """
    v9.2 generalization of mark_outreach_sent: stamp last_contacted_at,
    set next_follow_up_at = today + days, increment follow_up_count,
    and (if not already 'dead'/'won'/'follow_up_due') set
    outreach_status='contacted'. Idempotent in spirit — each call
    represents a real touchpoint the user just completed manually.

    Args:
        days: 1..60 (clamped at MAX_FOLLOWUP_DAYS). Default 3.
    """
    if not isinstance(days, int) or days < 1:
        raise ValueError("days must be a positive integer")
    if days > MAX_FOLLOWUP_DAYS:
        raise ValueError(f"days exceeds max {MAX_FOLLOWUP_DAYS}")
    existing = _find(lead_id)
    now = datetime.now()
    next_due = (now + _td(days=days)).strftime("%Y-%m-%d")
    count = int(existing.get("follow_up_count") or 0) + 1
    cur_status = (existing.get("outreach_status") or "").lower()
    raw = {
        "last_contacted_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "contacted_at":      now.strftime("%Y-%m-%d %H:%M:%S"),
        "next_follow_up_at": next_due,
        "follow_up_count":   count,
    }
    # Promote terminal-friendly statuses respectfully — don't unkill a
    # dead/won lead by re-contacting.
    if cur_status not in ("dead", "won"):
        # First touch → 'contacted'; subsequent touches → 'follow_up_due'
        # if not already past contacted (warm/hot/qualified take priority).
        if cur_status in ("not_started", "found", "qualified", "outreach_ready", ""):
            raw["outreach_status"] = "contacted"
        elif cur_status == "contacted":
            # Already contacted once; a re-touch means we're now in the
            # follow-up cadence.
            raw["outreach_status"] = "follow_up_due"
        # warm / hot / follow_up_due: leave as-is — the user manually
        # promoted them and we shouldn't downgrade.
    return update(lead_id, raw)


def list_due_follow_ups(today: str | None = None) -> list[dict]:
    """
    Return leads whose next_follow_up_at is today or earlier AND whose
    outreach_status is in {contacted, follow_up_due, warm, hot}. Sorted
    most-overdue first (oldest next_follow_up_at first).

    Excludes dead/won/empty-outreach_status leads. The Today panel and
    Logan's Follow-Ups Due section both read from this.

    Args:
        today: 'YYYY-MM-DD' for testability. Defaults to current date.
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    eligible = {"contacted", "follow_up_due", "warm", "hot"}
    out: list[dict] = []
    for lead in load():
        fu = (lead.get("next_follow_up_at") or "").strip()
        if not fu:
            continue
        if fu > today:
            continue
        st = (lead.get("outreach_status") or "").lower()
        if st not in eligible:
            continue
        out.append(lead)
    out.sort(key=lambda l: (l.get("next_follow_up_at") or "9999-99-99"))
    return out


# v9.2 multi-channel follow-up drafts. Reuses the existing
# _FOLLOW_UP_TMPL body (which already uses the free-mockup CTA) and
# adds FB / SMS / phone-notes variants. No "3 free fixes" anywhere.

_FOLLOW_UP_FB_TMPL = (
    "Hi {name} — circling back. Want me to put together that free "
    "homepage mockup I mentioned? Takes me about a day and there's "
    "no charge to look. No pressure either way."
)
_FOLLOW_UP_SMS_TMPL = (
    "Hi {name}, just checking in — still happy to make you that free "
    "homepage mockup if you're interested. No pressure."
)
_FOLLOW_UP_PHONE_NOTES = (
    "Follow-up talking points (not a script):\n"
    "  • Reference the prior touch — don't re-pitch from scratch.\n"
    "  • Reoffer the free homepage mockup. No charge to look.\n"
    "  • If they're busy: 'No rush — I just wanted to make sure my\n"
    "    last note didn't get buried. I'll check back in a few days.'\n"
    "  • If they're interested: ask what their main customer call-to-\n"
    "    action is right now (phone? message? walk-in?).\n"
    "  • If they pass: thank them, leave the door open, mark dead.\n"
)


def write_follow_up_drafts(lead_id: str) -> dict:
    """
    v9.2: like write_follow_up() but returns drafts for FOUR channels
    (email_subject + email_body + fb_message + sms_message +
    phone_notes) instead of just email. Does NOT mutate the lead —
    the user calls mark_followed_up() after they actually send.

    Returns:
        {email_subject, email_body, fb_message, sms_message, phone_notes,
         follow_up_count: <current count + 1 preview>}
    """
    existing = _find(lead_id)
    name = (existing.get("name") or "there").strip() or "there"
    subject = "re: " + _OUTREACH_SUBJECT_TMPL.format(business_name=name)
    body = _FOLLOW_UP_TMPL.format(business_name=name)
    return {
        "email_subject":     subject,
        "email_body":        body,
        "fb_message":        _FOLLOW_UP_FB_TMPL.format(name=name),
        "sms_message":       _FOLLOW_UP_SMS_TMPL.format(name=name),
        "phone_notes":       _FOLLOW_UP_PHONE_NOTES,
        "follow_up_count":   int(existing.get("follow_up_count") or 0) + 1,
        "previous_count":    int(existing.get("follow_up_count") or 0),
        "next_follow_up_at": existing.get("next_follow_up_at"),
    }


def mark_followed_up(lead_id: str, days: int = DEFAULT_REPEAT_FOLLOWUP_DAYS) -> dict:
    """
    v9.2: user just sent a follow-up. Increment follow_up_count, push
    next_follow_up_at out by `days` (default 5), and ensure
    outreach_status is at least 'follow_up_due'. Mirrors what
    write_follow_up() did but with a configurable reschedule horizon.
    """
    if not isinstance(days, int) or days < 1:
        raise ValueError("days must be a positive integer")
    if days > MAX_FOLLOWUP_DAYS:
        raise ValueError(f"days exceeds max {MAX_FOLLOWUP_DAYS}")
    existing = _find(lead_id)
    cur = (existing.get("outreach_status") or "").lower()
    if cur in ("dead", "won"):
        raise ValueError(
            f"cannot mark follow-up on a {cur!r} lead — un-dead it first"
        )
    now = datetime.now()
    next_due = (now + _td(days=days)).strftime("%Y-%m-%d")
    count = int(existing.get("follow_up_count") or 0) + 1
    raw = {
        "last_contacted_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "next_follow_up_at": next_due,
        "follow_up_count":   count,
    }
    if cur in ("contacted", "not_started", "found", "qualified",
               "outreach_ready", ""):
        raw["outreach_status"] = "follow_up_due"
    return update(lead_id, raw)


def mark_replied(lead_id: str, outcome: str) -> dict:
    """
    v9.2: user got a reply. outcome ∈ {warm, hot, won}.
    Updates outreach_status and clears next_follow_up_at — the lead is
    now in active conversation, not in the auto-cadence.
    """
    outcome = (outcome or "").strip().lower()
    allowed = ("warm", "hot", "won")
    if outcome not in allowed:
        raise ValueError(f"outcome must be one of {allowed}, got {outcome!r}")
    return update(lead_id, {
        "outreach_status":   outcome,
        "next_follow_up_at": None,
        "last_contacted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def add_batch(lines: list[str]) -> dict:
    """
    Bulk-create cold leads from paste input. Dedupes against existing
    leads AND within the batch itself (both by handle, case-insensitive).
    All recognized lines get status=cold, source='paste-import'. Single
    atomic write at the end so a 50-line paste is one disk hit, not 50.

    Returns:
        {
          "added":              [<new lead rows>],
          "skipped_duplicates": [<handles already present>],
          "skipped_invalid":    [<lines that didn't parse>],
          "total_processed":    int,
        }
    """
    if len(lines) > MAX_BATCH_SIZE:
        raise ValueError(
            f"batch size {len(lines)} exceeds limit of {MAX_BATCH_SIZE}"
        )
    leads = load()
    existing_handles = {(l.get("handle") or "").lower() for l in leads}
    added: list[dict] = []
    duplicates: list[str] = []
    invalid: list[str] = []
    seen_in_batch: set[str] = set()
    for raw_line in lines:
        parsed = parse_linkedin_input(raw_line)
        if parsed is None:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#"):
                invalid.append(stripped[:200])  # cap reported length
            continue
        handle_lower = parsed["handle"].lower()
        if handle_lower in existing_handles or handle_lower in seen_in_batch:
            duplicates.append(parsed["handle"])
            continue
        seen_in_batch.add(handle_lower)
        cleaned = _clean_lead({
            "name":   parsed["name"],
            "handle": parsed["handle"],
            "source": "paste-import",
            "status": DEFAULT_STATUS,
        })
        # _next_id reads existing-id set; pass leads+added so siblings
        # added earlier in this same batch can't collide.
        cleaned["id"] = _next_id(leads + added)
        cleaned["created_at"] = _now()
        cleaned["updated_at"] = cleaned["created_at"]
        added.append(cleaned)
    if added:
        leads.extend(added)
        _save(leads)
    return {
        "added":              added,
        "skipped_duplicates": duplicates,
        "skipped_invalid":    invalid,
        "total_processed":    len(lines),
    }


# --- v7.0: Follow-up queue helpers --------------------------------------

def _find(lead_id: str) -> dict:
    """Return the existing row by id, or raise KeyError."""
    for l in load():
        if l.get("id") == lead_id:
            return l
    raise KeyError(lead_id)


def mark_contacted(lead_id: str) -> dict:
    """
    Stamp contacted_at = now AND, if the lead is still 'cold',
    auto-promote it to 'warm'. Returns the updated row. Raises
    KeyError if not found.

    v7.3 auto-snooze: if the lead's follow_up_date is set and is
    today-or-earlier, clear it — the reminder has been satisfied by
    this contact. Future-dated follow-ups are preserved; the user set
    those intentionally and today's contact doesn't satisfy them.
    """
    existing = _find(lead_id)
    raw = {"contacted_at": _now()}
    if existing.get("status") == "cold":
        raw["status"] = "warm"
    fu = existing.get("follow_up_date")
    if fu and fu <= datetime.now().strftime("%Y-%m-%d"):
        raw["follow_up_date"] = None
    return update(lead_id, raw)


def set_follow_up(lead_id: str, follow_up_date: str) -> dict:
    """
    Update follow_up_date. Validates YYYY-MM-DD format. Empty string
    or None clears the field. Returns the updated row.
    """
    if follow_up_date:
        try:
            datetime.strptime(follow_up_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(
                f"follow_up_date must be YYYY-MM-DD, got {follow_up_date!r}"
            ) from e
        return update(lead_id, {"follow_up_date": follow_up_date})
    # Empty / None → clear. update() with {} would no-op since None
    # values fall back to existing; we have to bypass _clean_lead's
    # None-fallback for explicit clearing.
    existing = _find(lead_id)
    existing = dict(existing)
    existing["follow_up_date"] = None
    return update(lead_id, existing)


# --- v7.16: Multi-template outreach -------------------------------------
#
# Four stage-aware templates. Each is a literal Python format string with
# {name} and {company} placeholders — NO OpenAI, NO scraping, NO
# personalization beyond the lead's own fields. The user copy-pastes
# the result into LinkedIn manually; nothing here sends anything.
#
# Adding/editing a template:
#   - Bump the version in the docstring above and keep wording stable
#     after that so the same lead doesn't get drift-y drafts day to day.
#   - The for_status field is a HINT for default selection only; the
#     user can override per-draft.

MESSAGE_TEMPLATES = {
    "intro": {
        "label":      "Intro",
        "for_status": "cold",
        "body": (
            "Hey {name}, I saw your work with {company}. "
            "I help small businesses clean up their online presence with "
            "simple websites, digital business cards, and AI-powered systems. "
            "If you ever want a quick second set of eyes on your website or "
            "online setup, I’d be happy to take a look."
        ),
    },
    "check_in": {
        "label":      "Check-in",
        "for_status": "warm",
        "body": (
            "Hey {name}, just circling back on my note from a while ago. "
            "No pressure — let me know if a quick chat about {company}’s "
            "online setup would be useful sometime."
        ),
    },
    "value_add": {
        "label":      "Value-add",
        "for_status": "warm",
        "body": (
            "Hey {name}, one thought for {company}: a simple one-page site "
            "or a digital business card can really lift discoverability for "
            "a local business. Happy to share a quick example if it’s useful."
        ),
    },
    "close_ask": {
        "label":      "Close ask",
        "for_status": "hot",
        "body": (
            "Hey {name}, sounds like there might be a fit for {company}. "
            "Would a quick 15-minute call this week work to talk through "
            "what a simple online setup could look like?"
        ),
    },
}

DEFAULT_TEMPLATE_BY_STATUS = {
    "cold":    "intro",
    "warm":    "check_in",
    "hot":     "close_ask",
    # closed/dropped fall through to 'intro' as a safe default — the user
    # shouldn't normally draft for those statuses but we won't 500.
    "closed":  "intro",
    "dropped": "intro",
}


def draft_message(lead_id: str, template_key: str | None = None) -> dict:
    """
    Produce a templated outreach message for the lead, store it in
    last_message, and return {message, lead, template}.

    If template_key is None, pick based on lead status via
    DEFAULT_TEMPLATE_BY_STATUS. If template_key is given but unknown,
    raise ValueError (the API surfaces this as HTTP 400).

    NO OpenAI. Pure local string substitution. Caller is responsible
    for any actual sending (which we don't do — the user copy-pastes
    manually).
    """
    existing = _find(lead_id)
    if template_key is None:
        status = (existing.get("status") or "cold").lower()
        template_key = DEFAULT_TEMPLATE_BY_STATUS.get(status, "intro")
    if template_key not in MESSAGE_TEMPLATES:
        raise ValueError(
            f"unknown template: {template_key!r}; "
            f"expected one of {sorted(MESSAGE_TEMPLATES)}"
        )
    name    = (existing.get("name")    or "there").strip() or "there"
    company = (existing.get("company") or "").strip()      or "your business"
    message = MESSAGE_TEMPLATES[template_key]["body"].format(
        name=name, company=company,
    )
    # v7.18: also remember which template was used so the next render
    # can default the picker to it.
    updated = update(lead_id, {
        "last_message":      message,
        "last_template_key": template_key,
    })
    return {"message": message, "lead": updated, "template": template_key}
