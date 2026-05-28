"""
PartnerDesk Hub — v0.1
----------------------
Local FastAPI dashboard for PartnerDeskAI. Reuses the same data sources
the CLI scripts use (status._gather_status, summaries/, logs/) and runs
the existing `daily_ops.py` orchestrator via subprocess for actions.

Run:
    uvicorn hub.app:app --reload --port 8787

Open:
    http://127.0.0.1:8787

This file never writes anything on its own — file writes happen inside
the underlying scripts (daily_runner, status_snapshot, morning_summary).
The Hub only reads files and POSTs to those scripts.
"""

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


ROOT = Path(__file__).resolve().parent.parent
HUB_DIR = Path(__file__).resolve().parent

# Make automation/ importable so we can reuse status._gather_status()
# and approval_manager.get_post() (read-only single-row helper).
sys.path.insert(0, str(ROOT / "automation"))
import approval_manager  # noqa: E402
import status as status_mod  # noqa: E402


app = FastAPI(title="PartnerDesk Hub")
app.mount("/static", StaticFiles(directory=str(HUB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(HUB_DIR / "templates"))


# --- Pages -----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


# --- Read-only data endpoints ---------------------------------------------

DB_PATH = ROOT / "database" / "partnerdesk.db"


def _recent_posts(limit: int = 8) -> list[dict]:
    """
    Read-only: latest `limit` rows from posts ordered newest first.
    Returns id/platform/topic/status/created_at only — content is never
    included so the Hub API doesn't leak full draft bodies.
    """
    if not DB_PATH.is_file():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, platform, topic, status, created_at "
            "FROM posts ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/api/status")
def api_status() -> JSONResponse:
    """
    Same dict as `python3 automation/status.py --json`, plus a Hub-only
    `recent_posts` field for the dashboard's Recent Parker Work section.
    status._gather_status() itself is unchanged.
    """
    data = status_mod._gather_status()
    data["recent_posts"] = _recent_posts(limit=8)
    return JSONResponse(data)


@app.get("/api/posts/{post_id}")
def api_post(post_id: int) -> dict:
    """
    Return a single post (including content) for the Hub's draft preview.
    Content is shipped here on purpose because the caller asked for a
    specific id; the list endpoint at /api/status still hides it.
    404 when no row matches.
    """
    post = approval_manager.get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
    # Match the documented shape exactly — drop hashtags/image_idea so the
    # Hub's API surface stays small and the preview UI stays simple.
    return {
        "id":         post["id"],
        "platform":   post["platform"],
        "topic":      post["topic"],
        "status":     post["status"],
        "created_at": post["created_at"],
        "content":    post["content"],
    }


_ALLOWED_STATUS = {"approved", "rejected", "draft"}


class StatusUpdate(BaseModel):
    status: str


class BatchStatusUpdate(BaseModel):
    ids: list[int]
    status: str


# NOTE: the batch route MUST be declared before the parameterized
# /api/posts/{post_id}/status route — FastAPI matches routes in declaration
# order, and "batch" would otherwise be parsed as a (non-int) post_id and
# return 422 instead of reaching this handler.
@app.post("/api/posts/batch/status")
def api_batch_set_post_status(body: BatchStatusUpdate) -> dict:
    """
    Set the same status on a batch of posts. Mirrors the single-post
    endpoint exactly per id: mark_status, record_history on 'approved',
    and clear_queue_pointer_if_done on approved/rejected dates.

    Validation:
      - Empty `ids` list -> 400
      - Unknown `status`  -> 400
      - Non-int ids or missing fields -> Pydantic 422 (handled before
        the handler runs)

    Missing ids do NOT 404 — they're collected into `missing_ids` so a
    partial batch still completes. The response includes both updated
    and missing id lists plus their counts so the UI can show a clean
    summary.

    Never posts publicly.
    """
    if body.status not in _ALLOWED_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status {body.status!r}; allowed: {sorted(_ALLOWED_STATUS)}",
        )
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids must be a non-empty list")

    updated_ids: list[int] = []
    missing_ids: list[int] = []
    touched_dates: set[str] = set()

    for post_id in body.ids:
        post = approval_manager.get_post(post_id)
        if post is None:
            missing_ids.append(post_id)
            continue
        approval_manager.mark_status(post_id, body.status)
        if body.status == "approved":
            approval_manager.record_history(post["topic"], post["platform"])
        if body.status in ("approved", "rejected"):
            touched_dates.add(post["created_at"][:10])
        updated_ids.append(post_id)

    for d in touched_dates:
        approval_manager.clear_queue_pointer_if_done(d)

    return {
        "status":        body.status,
        "updated_ids":   updated_ids,
        "missing_ids":   missing_ids,
        "updated_count": len(updated_ids),
        "missing_count": len(missing_ids),
    }


@app.post("/api/posts/{post_id}/status")
def api_set_post_status(post_id: int, body: StatusUpdate) -> dict:
    """
    Set a single post's status. Reuses the same approval_manager helpers
    that approval_cli.py uses, so behavior matches the CLI exactly:

    - approved: sets posts.status='approved' AND inserts a post_history row
      so daily_runner.py's topic-dedup avoids the topic on future runs
    - rejected: sets posts.status='rejected'; post_history untouched
    - draft:    sets posts.status='draft' (lets a reviewer un-resolve a post)

    On approve/reject, the queue pointer for that draft's date is cleared
    if no other drafts remain pending for that date — same behavior as
    approval_cli.py's interactive review loop.

    This endpoint NEVER posts to any social network.
    """
    if body.status not in _ALLOWED_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status {body.status!r}; allowed: {sorted(_ALLOWED_STATUS)}",
        )

    post = approval_manager.get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")

    approval_manager.mark_status(post_id, body.status)
    if body.status == "approved":
        approval_manager.record_history(post["topic"], post["platform"])
    if body.status in ("approved", "rejected"):
        approval_manager.clear_queue_pointer_if_done(post["created_at"][:10])

    updated = approval_manager.get_post(post_id)
    return {
        "id":         updated["id"],
        "platform":   updated["platform"],
        "topic":      updated["topic"],
        "status":     updated["status"],
        "created_at": updated["created_at"],
    }


@app.get("/api/history")
def api_history(limit: int = 20) -> dict:
    """
    Read-only: latest post_history rows newest first. `limit` is clamped
    to [1, 100] so a too-large or non-positive query param still produces
    valid JSON instead of a 422.
    """
    limit = max(1, min(100, limit))
    if not DB_PATH.is_file():
        return {"items": []}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, topic, platform, posted_date FROM post_history "
            "ORDER BY posted_date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return {"items": [dict(r) for r in rows]}


@app.get("/api/history/analytics")
def api_history_analytics(days: int = 30) -> dict:
    """
    Read-only: counts from post_history within the trailing N days.
    `days` is clamped to [1, 365] so out-of-range query params still
    produce valid JSON instead of a 422.

    Three aggregations:
      - by_topic:           {topic, count}
      - by_platform:        {platform, count}
      - by_topic_platform:  {topic, platform, count}

    All sorted count DESC, then name ASC.
    """
    days = max(1, min(365, days))
    response = {
        "days": days,
        "total": 0,
        "by_topic": [],
        "by_platform": [],
        "by_topic_platform": [],
    }
    if not DB_PATH.is_file():
        return response

    cutoff_modifier = f"-{days} days"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        response["total"] = conn.execute(
            "SELECT COUNT(*) FROM post_history "
            "WHERE date(posted_date) >= date('now', ?)",
            (cutoff_modifier,),
        ).fetchone()[0]

        response["by_topic"] = [
            {"topic": r["topic"], "count": r["count"]}
            for r in conn.execute(
                "SELECT topic, COUNT(*) AS count FROM post_history "
                "WHERE date(posted_date) >= date('now', ?) "
                "GROUP BY topic ORDER BY count DESC, topic ASC",
                (cutoff_modifier,),
            )
        ]

        response["by_platform"] = [
            {"platform": r["platform"], "count": r["count"]}
            for r in conn.execute(
                "SELECT platform, COUNT(*) AS count FROM post_history "
                "WHERE date(posted_date) >= date('now', ?) "
                "GROUP BY platform ORDER BY count DESC, platform ASC",
                (cutoff_modifier,),
            )
        ]

        response["by_topic_platform"] = [
            {"topic": r["topic"], "platform": r["platform"], "count": r["count"]}
            for r in conn.execute(
                "SELECT topic, platform, COUNT(*) AS count FROM post_history "
                "WHERE date(posted_date) >= date('now', ?) "
                "GROUP BY topic, platform "
                "ORDER BY count DESC, topic ASC, platform ASC",
                (cutoff_modifier,),
            )
        ]
    finally:
        conn.close()
    return response


@app.get("/api/summary")
def api_summary() -> dict:
    """Read today's morning summary markdown, or report it's missing."""
    today = datetime.now().strftime("%Y-%m-%d")
    path = ROOT / "summaries" / f"{today}.md"
    if not path.is_file():
        return {
            "date": today,
            "exists": False,
            "content": (
                f"No summary for {today} yet. Click 'Refresh Summary Only' "
                "to generate one without calling OpenAI, or 'Run Daily Ops' "
                "to generate drafts plus the summary."
            ),
        }
    return {
        "date": today,
        "exists": True,
        "content": path.read_text(encoding="utf-8"),
    }


@app.get("/api/logs/latest")
def api_logs_latest() -> dict:
    """Latest log file's last 80 lines."""
    logs_dir = ROOT / "logs"
    if not logs_dir.is_dir():
        return {"path": None, "lines": [], "message": "No logs/ directory yet."}
    log_files = [p for p in logs_dir.glob("*.log") if p.is_file()]
    if not log_files:
        return {"path": None, "lines": [], "message": "No log files yet."}
    latest = max(log_files, key=lambda p: p.stat().st_mtime)
    text = latest.read_text(encoding="utf-8", errors="replace")
    tail = text.splitlines()[-80:]
    return {
        "path": str(latest.relative_to(ROOT)),
        "modified": datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        "lines": tail,
    }


# --- Action endpoints ------------------------------------------------------

def _run(args: list[str]) -> dict:
    """Run a child process and return {exit_code, stdout, stderr}."""
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.post("/api/run/daily-ops")
def run_daily_ops() -> dict:
    """Full daily sequence: generate (calls OpenAI) + snapshot + summary."""
    return _run([sys.executable, str(ROOT / "automation" / "daily_ops.py")])


@app.post("/api/run/refresh")
def run_refresh() -> dict:
    """Snapshot + summary only. Does NOT call OpenAI."""
    return _run(
        [sys.executable, str(ROOT / "automation" / "daily_ops.py"), "--skip-generate"]
    )
