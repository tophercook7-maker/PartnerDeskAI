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
