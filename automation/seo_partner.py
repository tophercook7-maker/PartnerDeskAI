"""
seo_partner.py
--------------
v10.0 Sage SEO Partner. Local-only SEO project management for the
MixedMakerShop agency: audits, local SEO checklists, Google Business
Profile improvement plans, fix-task workflow, approval queue, monthly
client reports.

Safety perimeter:
    - NO auto-publishing of website changes.
    - NO live Google Business Profile changes.
    - NO OAuth / API connections (Phase 3+ in the spec).
    - NO scraping, NO paid APIs, NO OpenAI calls.
    - NO new Python dependencies (stdlib only).
    - Pure local JSON state. All atomic writes via tempfile +
      os.replace.
    - Sage prepares recommendations, drafts, reports, and task lists
      for manual approval. The user still does the actual website
      edits in their own tooling.

Data files (all gitignored):
    data/seo_agency.json   — single agency record (MixedMakerShop)
    data/seo_projects.json — list of client SEO projects + inline fix_tasks
    data/seo_audits.json   — audit-history dict keyed by project_id
    data/seo_reports.json  — monthly-report-history dict keyed by project_id

Project naming convention (spec section 'Default project format'):
    "MMS - <Client Business Name> - SEO"

On first ever access to load_projects(), Sage auto-seeds
    "MMS - MixedMakerShop - SEO"
so the agency dashboard isn't empty on day one.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
AGENCY_PATH   = ROOT / "data" / "seo_agency.json"
PROJECTS_PATH = ROOT / "data" / "seo_projects.json"
AUDITS_PATH   = ROOT / "data" / "seo_audits.json"
REPORTS_PATH  = ROOT / "data" / "seo_reports.json"


# ---- Enums + caps ---------------------------------------------------

ALLOWED_FIX_STATUSES    = ("suggested", "approved", "in_progress", "completed", "skipped")
DEFAULT_FIX_STATUS      = "suggested"
ALLOWED_FIX_SEVERITIES  = ("critical", "high", "medium", "low")
DEFAULT_FIX_SEVERITY    = "medium"

ALLOWED_AUDIT_ITEM_STATUSES = ("pending", "passing", "failing", "needs_check")
DEFAULT_AUDIT_ITEM_STATUS   = "pending"

ALLOWED_PROJECT_STATUSES = (
    "active", "on_hold", "completed", "archived",
)
DEFAULT_PROJECT_STATUS   = "active"

MAX_NAME_LEN      = 200
MAX_URL_LEN       = 1000
MAX_TYPE_LEN      = 200
MAX_LOCATION_LEN  = 200
MAX_GOAL_LEN      = 1000
MAX_NOTES_LEN     = 8000
MAX_ISSUE_LEN     = 500
MAX_FIX_LEN       = 2000
MAX_PAGE_LEN      = 500
MAX_KEYWORDS      = 50
MAX_KEYWORD_LEN   = 100
MAX_AUDITS        = 50    # history cap per project
MAX_REPORTS       = 50    # history cap per project
MAX_FIX_TASKS     = 500   # per project

# Agency name is fixed by spec to "MixedMakerShop" but the field
# remains editable for future flexibility.
DEFAULT_AGENCY_NAME = "MixedMakerShop"

# First-run project bootstrap values from the spec.
FIRST_PROJECT_TEMPLATE = {
    "client_name":   DEFAULT_AGENCY_NAME,
    "project_name":  "MMS - MixedMakerShop - SEO",
    "website_url":   "https://mixedmakershop.com",
    "business_type": "Web design, SEO, digital business cards, AI systems",
    "location":      "Local service area",
    "main_goal":     (
        "Get more local web design and SEO clients through better "
        "search visibility."
    ),
    "target_keywords": [
        "local web design",
        "small business SEO",
        "Google Business Profile help",
        "local SEO consultant",
        "small business website redesign",
    ],
    "current_status": "active",
    "next_action":    "Generate first SEO audit and triage fixes.",
}


# ---- Time + ID helpers ----------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _next_id(items_or_dict) -> str:
    """Monotonic ms-timestamp id, collision-guarded by `items_or_dict`
    (accepts a list of dicts or a dict whose values may carry `id`)."""
    base = str(int(time.time() * 1000))
    existing: set[str] = set()
    if isinstance(items_or_dict, dict):
        for v in items_or_dict.values():
            if isinstance(v, dict) and v.get("id"):
                existing.add(v["id"])
            elif isinstance(v, list):
                for entry in v:
                    if isinstance(entry, dict) and entry.get("id"):
                        existing.add(entry["id"])
    else:
        for entry in (items_or_dict or []):
            if isinstance(entry, dict) and entry.get("id"):
                existing.add(entry["id"])
    cand = base
    n = 0
    while cand in existing:
        n += 1
        cand = f"{base}-{n}"
    return cand


# ---- Atomic write helper --------------------------------------------

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
# Agency (single-record)
# ======================================================================

DEFAULT_AGENCY = {
    "name":        DEFAULT_AGENCY_NAME,
    "tagline":     "",
    "website_url": "https://mixedmakershop.com",
    "service_area": "Local service area",
    "notes":       "",
    "created_at":  None,
    "updated_at":  None,
}


def load_agency() -> dict:
    data = _safe_load(AGENCY_PATH, None)
    if not isinstance(data, dict) or "name" not in data:
        # First-run bootstrap.
        seeded = dict(DEFAULT_AGENCY)
        seeded["created_at"] = _now()
        seeded["updated_at"] = seeded["created_at"]
        _atomic_write(AGENCY_PATH, seeded)
        return seeded
    # Setdefault new-ish fields so legacy rows survive schema bumps.
    data.setdefault("name",         DEFAULT_AGENCY_NAME)
    data.setdefault("tagline",      "")
    data.setdefault("website_url",  "")
    data.setdefault("service_area", "")
    data.setdefault("notes",        "")
    data.setdefault("created_at",   _now())
    data.setdefault("updated_at",   data.get("created_at"))
    return data


def save_agency(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("agency must be a dict")
    existing = load_agency()
    def _pick(k):
        return raw.get(k, existing.get(k))
    merged = {
        "name":         str(_pick("name") or DEFAULT_AGENCY_NAME).strip()[:MAX_NAME_LEN],
        "tagline":      str(_pick("tagline") or "").strip()[:MAX_NAME_LEN],
        "website_url":  str(_pick("website_url") or "").strip()[:MAX_URL_LEN],
        "service_area": str(_pick("service_area") or "").strip()[:MAX_LOCATION_LEN],
        "notes":        str(_pick("notes") or "")[:MAX_NOTES_LEN],
        "created_at":   existing.get("created_at") or _now(),
        "updated_at":   _now(),
    }
    if not merged["name"]:
        raise ValueError("agency.name is required")
    _atomic_write(AGENCY_PATH, merged)
    return merged


# ======================================================================
# Projects (list with inline fix_tasks)
# ======================================================================

def _slugify_project_name(client_name: str) -> str:
    """Spec format: 'MMS - <Client Business Name> - SEO'."""
    name = (client_name or "").strip() or "Unknown Client"
    return f"MMS - {name} - SEO"


def _clean_fix_task(raw: dict, existing: dict | None = None) -> dict:
    ex = existing or {}
    if not isinstance(raw, dict):
        raise ValueError("fix task must be a dict")
    def _pick(k):
        return raw.get(k, ex.get(k))
    issue = str(_pick("issue") or "").strip()[:MAX_ISSUE_LEN]
    if not issue:
        raise ValueError("fix_task.issue is required")
    severity = (_pick("severity") or DEFAULT_FIX_SEVERITY)
    severity = str(severity).strip().lower()
    if severity not in ALLOWED_FIX_SEVERITIES:
        severity = DEFAULT_FIX_SEVERITY
    status = (_pick("status") or DEFAULT_FIX_STATUS)
    status = str(status).strip().lower()
    if status not in ALLOWED_FIX_STATUSES:
        raise ValueError(
            f"fix_task.status must be one of {ALLOWED_FIX_STATUSES}, got {status!r}"
        )
    requires_approval_raw = _pick("requires_approval")
    if requires_approval_raw is None:
        # Default: high+critical require approval; lower severity does not.
        requires_approval = severity in ("critical", "high")
    else:
        requires_approval = bool(requires_approval_raw)
    completed_at = _pick("completed_at")
    if status == "completed" and not completed_at:
        completed_at = _now()
    if status != "completed":
        completed_at = None
    return {
        "id":                ex.get("id") or raw.get("id"),
        "issue":             issue,
        "severity":          severity,
        "recommended_fix":   str(_pick("recommended_fix") or "").strip()[:MAX_FIX_LEN],
        "page_affected":     str(_pick("page_affected") or "").strip()[:MAX_PAGE_LEN],
        "status":            status,
        "requires_approval": requires_approval,
        "completed_at":      completed_at,
        "notes":             str(_pick("notes") or "")[:MAX_NOTES_LEN],
        "created_at":        ex.get("created_at") or _now(),
        "updated_at":        _now(),
    }


def _clean_project(raw: dict, existing: dict | None = None) -> dict:
    ex = existing or {}
    if not isinstance(raw, dict):
        raise ValueError("project must be a dict")
    def _pick(k):
        return raw.get(k, ex.get(k))
    client_name = str(_pick("client_name") or "").strip()
    if not client_name:
        raise ValueError("project.client_name is required")
    # project_name: auto-derive unless explicitly provided.
    project_name = str(_pick("project_name") or "").strip()
    if not project_name:
        project_name = _slugify_project_name(client_name)
    status = (_pick("current_status") or DEFAULT_PROJECT_STATUS)
    status = str(status).strip().lower()
    if status not in ALLOWED_PROJECT_STATUSES:
        status = DEFAULT_PROJECT_STATUS
    # target_keywords: list of strings, length-capped.
    kws_raw = _pick("target_keywords") or []
    if not isinstance(kws_raw, list):
        kws_raw = []
    keywords: list[str] = []
    for k in kws_raw[:MAX_KEYWORDS]:
        if isinstance(k, str) and k.strip():
            keywords.append(k.strip()[:MAX_KEYWORD_LEN])
    # fix_tasks: preserve existing if not overridden.
    tasks_raw = _pick("fix_tasks")
    if tasks_raw is None:
        fix_tasks = list(ex.get("fix_tasks") or [])
    elif isinstance(tasks_raw, list):
        fix_tasks = list(tasks_raw)[:MAX_FIX_TASKS]
    else:
        fix_tasks = list(ex.get("fix_tasks") or [])
    # connected_data_sources: placeholder list (Phase 3+ wiring).
    conn = _pick("connected_data_sources") or []
    if not isinstance(conn, list):
        conn = []
    return {
        "id":             ex.get("id") or raw.get("id"),
        "client_name":    client_name[:MAX_NAME_LEN],
        "project_name":   project_name[:MAX_NAME_LEN],
        "website_url":    str(_pick("website_url") or "").strip()[:MAX_URL_LEN],
        "business_type":  str(_pick("business_type") or "").strip()[:MAX_TYPE_LEN],
        "location":       str(_pick("location") or "").strip()[:MAX_LOCATION_LEN],
        "main_goal":      str(_pick("main_goal") or "").strip()[:MAX_GOAL_LEN],
        "target_keywords": keywords,
        "connected_data_sources": conn,
        "fix_tasks":      fix_tasks,
        "current_status": status,
        "next_action":    str(_pick("next_action") or "").strip()[:MAX_FIX_LEN],
        "notes":          str(_pick("notes") or "")[:MAX_NOTES_LEN],
        "created_at":     ex.get("created_at") or _now(),
        "updated_at":     _now(),
    }


def _bootstrap_first_project(items: list[dict]) -> list[dict]:
    """Auto-seed MMS - MixedMakerShop - SEO if the list is empty."""
    if items:
        return items
    seed = _clean_project(FIRST_PROJECT_TEMPLATE)
    seed["id"] = _next_id(items)
    seed["created_at"] = _now()
    seed["updated_at"] = seed["created_at"]
    items.append(seed)
    _atomic_write(PROJECTS_PATH, {"items": items})
    return items


def load_projects() -> list[dict]:
    data = _safe_load(PROJECTS_PATH, None)
    if not isinstance(data, dict):
        data = {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    # Setdefaults to keep legacy projects renderable after schema bumps.
    for it in items:
        if isinstance(it, dict):
            it.setdefault("target_keywords", [])
            it.setdefault("connected_data_sources", [])
            it.setdefault("fix_tasks", [])
            it.setdefault("current_status", DEFAULT_PROJECT_STATUS)
            it.setdefault("next_action", "")
            it.setdefault("notes", "")
    return _bootstrap_first_project(items)


def _save_projects(items: list[dict]) -> None:
    _atomic_write(PROJECTS_PATH, {"items": items})


def find_project(pid: str) -> dict:
    for p in load_projects():
        if p.get("id") == pid:
            return p
    raise KeyError(pid)


def add_project(raw: dict) -> dict:
    items = load_projects()
    cleaned = _clean_project(raw)
    cleaned["id"] = _next_id(items)
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    items.append(cleaned)
    _save_projects(items)
    return cleaned


def update_project(pid: str, raw: dict) -> dict:
    items = load_projects()
    for i, it in enumerate(items):
        if it.get("id") == pid:
            merged = _clean_project(raw, existing=it)
            merged["id"] = pid
            items[i] = merged
            _save_projects(items)
            return merged
    raise KeyError(pid)


def delete_project(pid: str) -> bool:
    items = load_projects()
    before = len(items)
    items = [it for it in items if it.get("id") != pid]
    if len(items) == before:
        return False
    _save_projects(items)
    # Cascade: drop audit + report history for the deleted project.
    audits = _safe_load(AUDITS_PATH, {})
    if isinstance(audits, dict) and pid in audits:
        del audits[pid]
        _atomic_write(AUDITS_PATH, audits)
    reports = _safe_load(REPORTS_PATH, {})
    if isinstance(reports, dict) and pid in reports:
        del reports[pid]
        _atomic_write(REPORTS_PATH, reports)
    return True


# ======================================================================
# Fix-task lifecycle (suggested → approved → in_progress → completed | skipped)
# ======================================================================

def add_fix_task(pid: str, raw: dict) -> dict:
    project = find_project(pid)
    cleaned = _clean_fix_task(raw)
    cleaned["id"] = _next_id(project.get("fix_tasks") or [])
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    project["fix_tasks"].append(cleaned)
    update_project(pid, project)
    return cleaned


def update_fix_task(pid: str, tid: str, raw: dict) -> dict:
    project = find_project(pid)
    tasks = project.get("fix_tasks") or []
    for i, t in enumerate(tasks):
        if t.get("id") == tid:
            merged = _clean_fix_task(raw, existing=t)
            merged["id"] = tid
            tasks[i] = merged
            project["fix_tasks"] = tasks
            update_project(pid, project)
            return merged
    raise KeyError(tid)


def delete_fix_task(pid: str, tid: str) -> bool:
    project = find_project(pid)
    tasks = project.get("fix_tasks") or []
    before = len(tasks)
    tasks = [t for t in tasks if t.get("id") != tid]
    if len(tasks) == before:
        return False
    project["fix_tasks"] = tasks
    update_project(pid, project)
    return True


def _transition_fix_task(pid: str, tid: str, new_status: str) -> dict:
    if new_status not in ALLOWED_FIX_STATUSES:
        raise ValueError(f"new_status must be one of {ALLOWED_FIX_STATUSES}")
    return update_fix_task(pid, tid, {"status": new_status})


def approve_fix_task(pid: str, tid: str) -> dict:
    return _transition_fix_task(pid, tid, "approved")


def start_fix_task(pid: str, tid: str) -> dict:
    return _transition_fix_task(pid, tid, "in_progress")


def complete_fix_task(pid: str, tid: str) -> dict:
    return _transition_fix_task(pid, tid, "completed")


def skip_fix_task(pid: str, tid: str) -> dict:
    return _transition_fix_task(pid, tid, "skipped")


# ======================================================================
# Approval queue
# ======================================================================

def list_approval_queue(pid: str | None = None) -> list[dict]:
    """
    Fix tasks where requires_approval=True AND status='suggested'.
    Optionally scoped to one project. Returns each task augmented with
    project_id + project_name + client_name so the UI can render
    without a second lookup.
    """
    out: list[dict] = []
    projects = load_projects()
    if pid is not None:
        projects = [p for p in projects if p.get("id") == pid]
    for proj in projects:
        for task in (proj.get("fix_tasks") or []):
            if not task.get("requires_approval"):
                continue
            if (task.get("status") or "") != "suggested":
                continue
            row = dict(task)
            row["project_id"]   = proj.get("id")
            row["project_name"] = proj.get("project_name")
            row["client_name"]  = proj.get("client_name")
            out.append(row)
    # Severity-first ordering (critical / high / medium / low).
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda t: rank.get(t.get("severity") or "medium", 4))
    return out


# ======================================================================
# Audit generator (static template — no scraping, no API calls)
# ======================================================================

# Each section is a list of (item_text, severity_when_failing) tuples.
# The checklist is GENERATED at audit time so item ids are fresh and
# the user can record per-item status as they audit manually.
_TECHNICAL_SEO_ITEMS = (
    ("Every important page has a unique <title> tag (50-60 chars).", "high"),
    ("Every important page has a unique meta description (140-160 chars).", "high"),
    ("Heading hierarchy is clean: one H1 per page, H2/H3 used semantically.", "medium"),
    ("Every meaningful image has descriptive alt text (no 'image1.jpg').", "medium"),
    ("No broken links on key landing pages (homepage, services, contact).", "high"),
    ("Site is mobile-friendly (text legible without zoom, tap targets OK).", "high"),
    ("Pages load in under 3 seconds on a mobile network.", "high"),
    ("sitemap.xml exists and lists all important URLs.", "medium"),
    ("robots.txt is present and not blocking important paths.", "high"),
    ("No critical pages return 404 / 500 in basic crawl.", "critical"),
    ("Canonical tags resolve cleanly; no canonical-to-redirect chains.", "medium"),
    ("HTTPS is enforced; no mixed-content warnings.", "high"),
)

_ONPAGE_SEO_ITEMS = (
    ("Homepage tells a first-time visitor WHAT and WHERE in 5 seconds.", "high"),
    ("Each service has its own dedicated page (not all crammed in one).", "medium"),
    ("Target keywords appear naturally in H1 + intro paragraph.", "high"),
    ("Internal links connect services → homepage → about → contact.", "medium"),
    ("Every page has a clear primary call-to-action.", "high"),
    ("Content gaps: there's a page for every common customer question.", "medium"),
    ("FAQ section answers buyer-stage questions, not generic ones.", "low"),
    ("Service pages name the city + service area, not just 'local'.", "high"),
)

_LOCAL_SEO_ITEMS = (
    ("City + service area named consistently on every page footer.", "high"),
    ("Name / Address / Phone (NAP) is identical site-wide and on GBP.", "critical"),
    ("Google Business Profile claimed and verified.", "critical"),
    ("GBP categories match the actual business (primary + secondary).", "high"),
    ("GBP photos: storefront, interior, team, product/service (10+).", "medium"),
    ("Active review-collection plan in place (asks after every job).", "medium"),
    ("Recent reviews: at least 5 in the last 90 days.", "high"),
    ("City-specific landing pages exist for each major service area.", "medium"),
    ("LocalBusiness schema markup on homepage + service pages.", "medium"),
    ("Posts on GBP at least monthly (offers, updates, photos).", "low"),
)


def generate_audit(pid: str) -> dict:
    """
    Generate a fresh audit checklist for the project. Persisted in the
    audit history. Returns the new audit record.

    This is a STATIC template — Sage doesn't crawl the site; the user
    works through the checklist manually and records per-item statuses
    via update_audit_item().
    """
    project = find_project(pid)
    items_for_audit = lambda src: [
        {
            "id":      f"item-{i}",
            "item":    text,
            "severity_if_failing": sev,
            "status":  DEFAULT_AUDIT_ITEM_STATUS,
            "notes":   "",
        }
        for i, (text, sev) in enumerate(src)
    ]
    new_audit = {
        "id":           _next_id(_safe_load(AUDITS_PATH, {})),
        "generated_at": _now(),
        "project_id":   pid,
        "project_name": project.get("project_name", ""),
        "website_url":  project.get("website_url", ""),
        "checklist": {
            "technical_seo": items_for_audit(_TECHNICAL_SEO_ITEMS),
            "on_page_seo":   items_for_audit(_ONPAGE_SEO_ITEMS),
            "local_seo":     items_for_audit(_LOCAL_SEO_ITEMS),
        },
        "summary": (
            f"Initial SEO audit for {project.get('project_name', '')}. "
            "Work through each item manually — Sage does not auto-crawl. "
            "Flag failing items, then promote them to fix tasks via the "
            "Approval Queue."
        ),
    }
    audits = _safe_load(AUDITS_PATH, {})
    if not isinstance(audits, dict):
        audits = {}
    history = audits.get(pid) if isinstance(audits.get(pid), list) else []
    history.append(new_audit)
    # Cap history at MAX_AUDITS.
    if len(history) > MAX_AUDITS:
        history = history[-MAX_AUDITS:]
    audits[pid] = history
    _atomic_write(AUDITS_PATH, audits)
    return new_audit


def list_audits(pid: str) -> list[dict]:
    audits = _safe_load(AUDITS_PATH, {})
    if not isinstance(audits, dict):
        return []
    history = audits.get(pid)
    return list(history) if isinstance(history, list) else []


def get_latest_audit(pid: str) -> dict | None:
    hist = list_audits(pid)
    return hist[-1] if hist else None


def update_audit_item(
    pid: str, audit_id: str, item_id: str,
    status: str | None = None, notes: str | None = None,
) -> dict:
    """Update one checklist item's status + notes in an existing audit."""
    audits = _safe_load(AUDITS_PATH, {})
    if not isinstance(audits, dict):
        audits = {}
    history = audits.get(pid) or []
    for audit in history:
        if audit.get("id") != audit_id:
            continue
        checklist = audit.get("checklist") or {}
        for section_items in checklist.values():
            if not isinstance(section_items, list):
                continue
            for item in section_items:
                if item.get("id") != item_id:
                    continue
                if status is not None:
                    s = str(status).strip().lower()
                    if s not in ALLOWED_AUDIT_ITEM_STATUSES:
                        raise ValueError(
                            f"audit item status must be one of "
                            f"{ALLOWED_AUDIT_ITEM_STATUSES}"
                        )
                    item["status"] = s
                if notes is not None:
                    item["notes"] = str(notes)[:MAX_NOTES_LEN]
                audits[pid] = history
                _atomic_write(AUDITS_PATH, audits)
                return audit
        raise KeyError(item_id)
    raise KeyError(audit_id)


# ======================================================================
# Monthly report generator
# ======================================================================

def generate_monthly_report(pid: str, month: str | None = None) -> dict:
    """
    Synthesize a client-friendly monthly report from project state.
    Six sections per spec:
        1. What we checked
        2. What we fixed
        3. Current wins
        4. Current issues
        5. Ranking / traffic notes (manual entry, prefilled placeholder)
        6. Next recommended actions

    `month` defaults to the current YYYY-MM. Persists to
    data/seo_reports.json, keyed by project_id.
    """
    project = find_project(pid)
    if month is None:
        month = _today_month()
    if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        raise ValueError("month must be 'YYYY-MM'")

    tasks = project.get("fix_tasks") or []
    completed = [t for t in tasks if (t.get("status") or "") == "completed"]
    in_progress = [t for t in tasks if (t.get("status") or "") == "in_progress"]
    suggested = [t for t in tasks if (t.get("status") or "") == "suggested"]
    skipped = [t for t in tasks if (t.get("status") or "") == "skipped"]
    audits = list_audits(pid)
    latest_audit = audits[-1] if audits else None

    what_we_checked: list[str] = []
    if latest_audit:
        for section, items in (latest_audit.get("checklist") or {}).items():
            done = sum(1 for it in items if (it.get("status") or "") != "pending")
            total = len(items) or 0
            label = section.replace("_", " ").title()
            what_we_checked.append(f"{label}: {done} of {total} items reviewed.")
    else:
        what_we_checked.append("No SEO audit on file yet — run one to populate this section.")

    what_we_fixed: list[str] = []
    for t in completed:
        what_we_fixed.append(
            f"{t.get('issue', '?')} (page {t.get('page_affected') or 'site-wide'})."
        )
    if not what_we_fixed:
        what_we_fixed.append("No fixes completed yet this period.")

    current_wins: list[str] = []
    if completed:
        # Crude grouping by page_affected.
        pages = sorted({t.get("page_affected") or "site-wide" for t in completed})
        if pages:
            current_wins.append(
                f"Improvements landed on {len(pages)} page"
                f"{'s' if len(pages) != 1 else ''}: "
                f"{', '.join(pages[:5])}."
            )
    if not current_wins:
        current_wins.append("No client-visible wins to highlight yet.")

    current_issues: list[str] = []
    for t in suggested:
        if (t.get("severity") or "") in ("critical", "high"):
            current_issues.append(
                f"[{t.get('severity', '?').upper()}] {t.get('issue', '?')}"
            )
    if not current_issues:
        current_issues.append(
            "No critical or high-severity issues outstanding."
        )

    ranking_notes = [
        "Ranking + traffic data: pending. (Phase 3 will pull this from "
        "Google Search Console / Analytics. For now, record manually if "
        "you have it.)",
    ]

    next_actions: list[str] = []
    for t in suggested[:5]:
        next_actions.append(
            f"Approve and ship: {t.get('issue', '?')} "
            f"({t.get('severity', '?')} severity)."
        )
    for t in in_progress[:3]:
        next_actions.append(f"Finish: {t.get('issue', '?')}.")
    if not next_actions:
        next_actions.append("Generate a new audit and triage findings.")

    report = {
        "id":           _next_id(_safe_load(REPORTS_PATH, {})),
        "project_id":   pid,
        "project_name": project.get("project_name", ""),
        "client_name":  project.get("client_name", ""),
        "month":        month,
        "generated_at": _now(),
        "sections": {
            "what_we_checked": what_we_checked,
            "what_we_fixed":   what_we_fixed,
            "current_wins":    current_wins,
            "current_issues":  current_issues,
            "ranking_notes":   ranking_notes,
            "next_actions":    next_actions,
        },
        "summary": (
            f"Monthly SEO update for {project.get('client_name', '')} "
            f"({month}). {len(completed)} fix"
            f"{'es' if len(completed) != 1 else ''} completed, "
            f"{len(suggested)} pending review."
        ),
    }
    reports = _safe_load(REPORTS_PATH, {})
    if not isinstance(reports, dict):
        reports = {}
    history = reports.get(pid) if isinstance(reports.get(pid), list) else []
    history.append(report)
    if len(history) > MAX_REPORTS:
        history = history[-MAX_REPORTS:]
    reports[pid] = history
    _atomic_write(REPORTS_PATH, reports)
    return report


def list_reports(pid: str) -> list[dict]:
    reports = _safe_load(REPORTS_PATH, {})
    if not isinstance(reports, dict):
        return []
    history = reports.get(pid)
    return list(history) if isinstance(history, list) else []


# ======================================================================
# Dashboard metrics
# ======================================================================

def agency_dashboard() -> dict:
    """One-shot summary the Hub + the agency dashboard card both read."""
    projects = load_projects()
    active = [p for p in projects if (p.get("current_status") or "") == "active"]
    audits = _safe_load(AUDITS_PATH, {}) or {}
    audits_count = sum(
        len(v) for v in audits.values() if isinstance(v, list)
    )
    reports = _safe_load(REPORTS_PATH, {}) or {}
    reports_count = sum(
        len(v) for v in reports.values() if isinstance(v, list)
    )
    queue_count = len(list_approval_queue())
    return {
        "agency":             load_agency(),
        "total_projects":     len(projects),
        "active_projects":    len(active),
        "audits_run":         audits_count,
        "reports_generated":  reports_count,
        "approval_queue_len": queue_count,
    }
