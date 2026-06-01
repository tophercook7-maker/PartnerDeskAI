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

import os
import re
import signal as _signal
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


# Dynamic repo-root derivation: hub/app.py lives at <repo>/hub/app.py,
# so parents[1] is the repo root regardless of where the repo is on
# disk. Use ROOT / "<filename>" everywhere instead of hardcoded paths
# so the project remains portable across moves/renames.
ROOT = Path(__file__).resolve().parents[1]
HUB_DIR = Path(__file__).resolve().parents[0]

# Make automation/ importable so we can reuse status._gather_status()
# and approval_manager.get_post() (read-only single-row helper).
sys.path.insert(0, str(ROOT / "automation"))
import approval_manager  # noqa: E402
import connection_state  # noqa: E402
import env_writer  # noqa: E402
import leads as leads_mod  # noqa: E402
import scout_queue as scout_mod  # noqa: E402
import linkedin_oauth  # noqa: E402
import meta_app_state  # noqa: E402
import social_posters  # noqa: E402
import status as status_mod  # noqa: E402

# Run any pending column migrations (e.g. v4.0's edited_at) on startup so
# the Hub doesn't return KeyError before the first approval_manager call.
approval_manager.init_db()

# Make .env vars available for /api/connections. social_posters also calls
# load_dotenv on its own import; calling here is idempotent and ensures the
# right .env loads regardless of import order.
load_dotenv(ROOT / ".env")


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
    Content is NEVER included so the Hub API doesn't leak full draft
    bodies on the default dashboard load.

    v6.3: includes posted_at + published_url (when set) so the Recent
    Parker Work row can show a "Posted →" link inline without a
    second fetch. The full receipt summary stays on /api/posts/{id}
    to keep this list payload small.
    """
    if not DB_PATH.is_file():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, platform, topic, status, created_at, edited_at, "
            "posted_at, published_url "
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


# NOTE: this fixed-path GET must be declared before the parameterized
# /api/posts/{post_id} route below — otherwise "ready" would be parsed as
# a non-int post_id and return 422.
@app.get("/api/posts/ready")
def api_posts_ready() -> dict:
    """
    Approved posts queued for manual posting, newest first.

    Returns content (unlike /api/status's recent_posts) because the UI
    needs the body to copy to the clipboard. Capped at 20 entries so the
    payload stays small.
    """
    if not DB_PATH.is_file():
        return {"items": []}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # v6.3: pull receipt fields so the ready/posted UI can show
        # "Posted at <url>" if a row in this list ever transitions
        # to status='posted' between renders (unusual but possible).
        rows = conn.execute(
            "SELECT id, platform, topic, status, created_at, edited_at, content, "
            "posted_at, published_platform, published_external_id, "
            "published_url, published_response_summary "
            "FROM posts WHERE status = 'approved' "
            "ORDER BY created_at DESC, id DESC LIMIT 20"
        ).fetchall()
    finally:
        conn.close()
    return {"items": [dict(r) for r in rows]}


class ContentUpdate(BaseModel):
    content: str


class PublishRequest(BaseModel):
    platform: str


_SUPPORTED_PUBLISH_PLATFORMS = {"linkedin", "facebook"}

# Maps the lowercase platform key from the request body to the canonical
# post.platform value in SQLite. Used to reject mismatches like trying to
# push a Facebook draft via the linkedin connector.
_PLATFORM_KEY_TO_POST_PLATFORM = {
    "linkedin": "LinkedIn",
    "facebook": "Facebook",
}

_PLATFORM_KEY_TO_PUBLISHER = {
    "linkedin": social_posters.publish_linkedin_post,
    "facebook": social_posters.publish_facebook_post,
}


@app.post("/api/posts/{post_id}/publish")
def api_publish_post(post_id: int, body: PublishRequest) -> dict:
    """
    Manually publish an approved draft to a real platform. v4.2 supports
    LinkedIn and Facebook. Returns the structured {ok, message, platform,
    ...} dict from social_posters so the Hub can render success or
    failure inline without try/except.

    Validation:
      - unsupported platform                  -> 400
      - missing post                          -> 404
      - non-approved post                     -> 400
      - platform/post.platform mismatch        -> 400
      - missing body field                    -> Pydantic 422

    On success the local post.status is flipped to 'posted' so it drops
    out of the Ready to Post queue. On any failure (including the
    "<platform> posting is not configured" path) the status is left
    untouched.
    """
    platform_key = body.platform.strip().lower()
    if platform_key not in _SUPPORTED_PUBLISH_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported platform {body.platform!r}; "
                   f"allowed: {sorted(_SUPPORTED_PUBLISH_PLATFORMS)}",
        )

    post = approval_manager.get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")

    if post["status"] != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Only approved posts may be published; "
                   f"post #{post_id} is {post['status']!r}",
        )

    expected_platform = _PLATFORM_KEY_TO_POST_PLATFORM[platform_key]
    if post["platform"] != expected_platform:
        raise HTTPException(
            status_code=400,
            detail=f"Post #{post_id} is for {post['platform']!r}, "
                   f"cannot publish via the {platform_key!r} connector.",
        )

    # v4.9 hard gate: only platforms whose latest verify probe
    # succeeded may be published to. "configured" (env set but never
    # verified, or last verify failed) is NOT enough.
    trust = connection_state.compute_state(platform_key)
    if trust["state"] != "verified":
        raise HTTPException(
            status_code=400,
            detail=(
                f"{expected_platform} connection is {trust['state']!r} — "
                f"verify the connection before publishing."
            ),
        )

    publisher = _PLATFORM_KEY_TO_PUBLISHER[platform_key]
    result = publisher(post["content"] or "")

    # Only flip status when the connector confirms a successful publish.
    # v6.3: extract receipt fields from the publisher's result and
    # record them atomically alongside the status transition. The
    # extract helper enforces "no tokens / no headers / safe summary".
    if result.get("ok"):
        receipt = social_posters.extract_publish_receipt(result)
        approval_manager.mark_published(
            post_id,
            published_platform=platform_key,
            published_external_id=receipt["external_id"],
            published_url=receipt["url"],
            published_response_summary=receipt["summary"],
        )
        # Echo the receipt back to the immediate caller (the Hub UI's
        # publish click handler) so it can render the success notice
        # without a second fetch. Same safe fields the receipt helper
        # produced — never the raw result dict (which may have
        # platform-specific fields we haven't audited).
        result["receipt"] = receipt

    return result


@app.put("/api/posts/{post_id}")
def api_update_post_content(post_id: int, body: ContentUpdate) -> dict:
    """
    Update only `posts.content` for the given post. Does not change status,
    never inserts post_history, never calls OpenAI.

    Validation:
      - Missing post id            -> 404
      - Empty content (after strip) -> 400
      - Missing/wrong-typed body    -> Pydantic 422

    Returns the refreshed post in the same shape as GET /api/posts/{id}
    (id, platform, topic, status, created_at, content).
    """
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content cannot be empty")

    post = approval_manager.get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")

    conn = sqlite3.connect(DB_PATH)
    try:
        # Set edited_at in the same UPDATE so the timestamp reflects the
        # exact moment the content actually changed.
        conn.execute(
            "UPDATE posts SET content = ?, edited_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (body.content, post_id),
        )
        conn.commit()
    finally:
        conn.close()

    updated = approval_manager.get_post(post_id)
    return {
        "id":         updated["id"],
        "platform":   updated["platform"],
        "topic":      updated["topic"],
        "status":     updated["status"],
        "created_at": updated["created_at"],
        "edited_at":  updated["edited_at"],
        "content":    updated["content"],
    }


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
    # v6.3: include posted_at + receipt fields so the preview modal can
    # render "Posted at <url>" when applicable. Receipt fields are NULL
    # for any post that hasn't been published.
    return {
        "id":         post["id"],
        "platform":   post["platform"],
        "topic":      post["topic"],
        "status":     post["status"],
        "created_at": post["created_at"],
        "edited_at":  post["edited_at"],
        "content":    post["content"],
        "posted_at":                  post.get("posted_at"),
        "published_platform":         post.get("published_platform"),
        "published_external_id":      post.get("published_external_id"),
        "published_url":              post.get("published_url"),
        "published_response_summary": post.get("published_response_summary"),
    }


# `posted` is set by the Hub's "Mark Posted" button after Topher manually
# publishes an already-approved draft on the real platform. The status
# update is local-only — no social media call is ever made. Posts in this
# state drop out of the Ready to Post queue (which filters status='approved')
# but stay in the posts table for historical visibility.
_ALLOWED_STATUS = {"approved", "rejected", "draft", "posted"}


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
        "edited_at":  updated["edited_at"],
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


# Map each platform's display name to the env keys it needs to publish.
# The /api/connections endpoint reports only key NAMES — never values —
# so this dict can be safely surfaced to the browser.
_PLATFORM_ENV_REQUIREMENTS = {
    "LinkedIn": [
        "LINKEDIN_ACCESS_TOKEN",
        "LINKEDIN_AUTHOR_URN",
    ],
    "Facebook": [
        "FACEBOOK_PAGE_ID",
        "FACEBOOK_PAGE_ACCESS_TOKEN",
    ],
    "Google Business Profile": [
        "GBP_ACCESS_TOKEN",
        "GBP_ACCOUNT_ID",
        "GBP_LOCATION_ID",
    ],
    "Instagram": [
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "INSTAGRAM_ACCESS_TOKEN",
    ],
}

# Setup-help URLs surfaced to the Hub so the "Open Setup Help" button
# knows where to open. Mirrors automation/connect_wizard.py's
# PLATFORM_CONFIGS — see that file for the longer setup notes.
_PLATFORM_SETUP_URLS = {
    "LinkedIn":                "https://www.linkedin.com/developers/",
    "Facebook":                "https://developers.facebook.com/",
    "Google Business Profile": "https://business.google.com/",
    "Instagram":               "https://developers.facebook.com/",
}


class VerifyRequest(BaseModel):
    platform: str


# Maps the platform query key to the verify_* function in social_posters.
# Uses lowercase-with-underscores keys so the wizard CLI and the Hub API
# accept identical strings ("facebook", "google_business_profile", etc.).
_VERIFY_HANDLERS = {
    "linkedin":                social_posters.verify_linkedin_connection,
    "facebook":                social_posters.verify_facebook_connection,
    "instagram":               social_posters.verify_instagram_connection,
    "google_business_profile": social_posters.verify_google_business_profile_connection,
}


@app.post("/api/connections/verify")
def api_verify_connection(body: VerifyRequest) -> dict:
    """
    Run a read-only connection probe for the given platform. Returns the
    structured {ok, platform, message} dict from social_posters. Never
    publishes, never returns tokens, never modifies the database.
    Unsupported platform -> 400.
    """
    key = body.platform.strip().lower()
    if key not in _VERIFY_HANDLERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported platform {body.platform!r}; "
                   f"allowed: {sorted(_VERIFY_HANDLERS)}",
        )
    result = _VERIFY_HANDLERS[key]()
    # Persist the outcome so /api/connections (and the publish gate)
    # reflect the new trust state. record_verification handles the
    # env-missing case correctly — see connection_state.py.
    connection_state.record_verification(
        key, ok=bool(result.get("ok")), message=result.get("message", "")
    )
    return result


# --- LinkedIn OAuth connect flow (v6.1) ----------------------------------
# Two endpoints + tiny in-memory state store. The Hub button navigates
# the browser to /api/oauth/linkedin/start which 302s to LinkedIn; the
# user authenticates; LinkedIn redirects back to /api/oauth/linkedin/
# callback?code=…&state=… ; the callback exchanges the code for a
# token, writes the token into .env (via env_writer's atomic update),
# then triggers a verify. NEVER logs / returns the token value.

import secrets as _py_secrets  # stdlib — used only for the CSRF state token

# state token -> expiry timestamp. Cleared on use; expired entries
# are pruned opportunistically on each /start call. In-memory only —
# survives only as long as the Hub process. That's fine: the OAuth
# round-trip is seconds long.
_LINKEDIN_OAUTH_STATES: dict[str, datetime] = {}
_LINKEDIN_OAUTH_STATE_TTL_MINS = 10


def _prune_expired_oauth_states() -> None:
    now = datetime.now()
    expired = [s for s, exp in _LINKEDIN_OAUTH_STATES.items() if exp < now]
    for s in expired:
        _LINKEDIN_OAUTH_STATES.pop(s, None)


@app.get("/api/oauth/linkedin/start")
def api_oauth_linkedin_start():
    """
    Step 1 of the LinkedIn OAuth flow. Generates a fresh CSRF state
    token, stores it server-side with a 10-minute expiry, and
    redirects the browser to LinkedIn's authorization URL.

    No secrets in the response.
    """
    _prune_expired_oauth_states()
    try:
        state = _py_secrets.token_urlsafe(32)
        url = linkedin_oauth.build_authorization_url(state)
    except linkedin_oauth.LinkedInOAuthError as e:
        # Surface a helpful error (which only names the missing keys —
        # never values).
        raise HTTPException(status_code=400, detail=str(e))
    from datetime import timedelta as _td
    _LINKEDIN_OAUTH_STATES[state] = (
        datetime.now() + _td(minutes=_LINKEDIN_OAUTH_STATE_TTL_MINS)
    )
    return RedirectResponse(url=url, status_code=302)


def _oauth_result_page(title: str, body_html: str, ok: bool) -> HTMLResponse:
    """Tiny self-contained result page (no token values rendered)."""
    color = "#2a6ec1" if ok else "#b34a4a"
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body style='font-family: -apple-system, sans-serif; "
        "max-width: 540px; margin: 3rem auto; padding: 1.5rem; line-height: 1.5;'>"
        f"<h1 style='color:{color}; margin-top:0'>{title}</h1>"
        f"{body_html}"
        "<p><a href='/'>← Back to PartnerDesk Hub</a></p>"
        "</body></html>"
    )
    return HTMLResponse(content=html, status_code=200 if ok else 400)


@app.get("/api/oauth/linkedin/callback")
def api_oauth_linkedin_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """
    Step 2 entry point. Delegates to _oauth_callback_impl inside a
    backstop try/except so any unhandled exception becomes a friendly
    HTML error page rather than a 500. The friendly page includes the
    Hub's resolved ROOT and the .env path it tried, which is the data
    you need to debug the most common class of bugs (wrong repo root
    after a project move).
    """
    try:
        return _oauth_callback_impl(code, state, error, error_description)
    except Exception as e:
        return _oauth_result_page(
            "OAuth callback hit an unexpected error",
            f"<p>Error type: <code>{type(e).__name__}</code></p>"
            f"<p>Error message: {_escape_html(str(e))}</p>"
            f"<p>Repo root this Hub is running with: "
            f"<code>{_escape_html(str(ROOT))}</code></p>"
            f"<p>.env path expected: <code>{_escape_html(str(ROOT / '.env'))}</code></p>"
            "<p>Check the Hub's server logs for the full traceback. "
            "If the repo root above doesn't match where your project "
            "actually lives, restart the Hub from the new location: "
            "<code>pkill -f 'uvicorn hub.app' && bash automation/open_hub.sh</code>.</p>",
            ok=False,
        )


def _oauth_callback_impl(
    code: str | None,
    state: str | None,
    error: str | None,
    error_description: str | None,
):
    """
    Actual OAuth callback body. Returns an HTMLResponse for every
    branch. Any uncaught exception bubbles up to the wrapper above.
    Steps:
      1. Verify state matches one we issued (CSRF protection).
      2. POST the code to LinkedIn's token endpoint via
         linkedin_oauth.exchange_code_for_token.
      3. Atomically write LINKEDIN_ACCESS_TOKEN to .env via env_writer.
      4. Reload the process env so the new token is live in this Hub.
      5. Call connection_state.record_verification with the result of
         verify_linkedin_connection().
    Token value is NEVER rendered or logged.
    """
    # User denied or LinkedIn errored.
    if error:
        return _oauth_result_page(
            "LinkedIn authorization declined",
            f"<p>LinkedIn returned: <code>{error}</code>"
            + (f" — {error_description}" if error_description else "")
            + "</p><p>No changes were made to your .env or connection state.</p>",
            ok=False,
        )

    if not code or not state:
        return _oauth_result_page(
            "LinkedIn callback missing parameters",
            "<p>Expected <code>code</code> and <code>state</code> query parameters.</p>"
            "<p>No changes were made.</p>",
            ok=False,
        )

    expiry = _LINKEDIN_OAUTH_STATES.pop(state, None)
    if expiry is None or expiry < datetime.now():
        return _oauth_result_page(
            "LinkedIn callback rejected (state mismatch)",
            "<p>The CSRF state token didn't match an in-flight request, or it expired. "
            "This can happen if the authorization took longer than 10 minutes, or if "
            "the callback URL was opened from an old browser tab.</p>"
            "<p>No changes were made. Try clicking Connect LinkedIn again.</p>",
            ok=False,
        )

    # Exchange the code for a token (POSTs the client_secret in the body —
    # never in a URL). Errors surface as exceptions that we catch here.
    try:
        token_resp = linkedin_oauth.exchange_code_for_token(code)
    except linkedin_oauth.LinkedInOAuthError as e:
        return _oauth_result_page(
            "LinkedIn token exchange failed",
            f"<p>{_escape_html(str(e))}</p>"
            "<p>No changes were made to your .env.</p>",
            ok=False,
        )

    access_token = token_resp.get("access_token", "")
    token_len = len(access_token)

    # v6.3: best-effort URN auto-fetch via /v2/userinfo. Requires the
    # OAuth scope to include openid+profile, which we now request in
    # the start URL. If the LinkedIn app doesn't have "Sign In with
    # LinkedIn using OpenID Connect" enabled the userinfo call will
    # 401/403; we record that and continue without URN — the access
    # token is still valid for posting.
    urn_writes: dict[str, str] = {}
    urn_msg = ""
    try:
        info = linkedin_oauth.fetch_userinfo(access_token)
        sub = (info.get("sub") or "").strip()
        if sub:
            urn_writes["LINKEDIN_AUTHOR_URN"] = f"urn:li:person:{sub}"
            urn_msg = f"URN auto-fetched and saved (urn:li:person:{sub[:6]}…)."
        else:
            urn_msg = "userinfo returned no `sub` claim — URN not set."
    except linkedin_oauth.LinkedInOAuthError as e:
        urn_msg = f"URN auto-fetch unavailable ({e}). Set LINKEDIN_AUTHOR_URN manually."

    # Atomic .env write — bundle the token AND URN (if any) into ONE
    # update so .env.bak captures the pre-OAuth state once, not twice.
    # env_writer preserves file mode and never logs values, and refuses
    # to create .env from scratch (raises FileNotFoundError) so we
    # never silently scaffold a wrong file.
    env_path = ROOT / ".env"
    updates = {"LINKEDIN_ACCESS_TOKEN": access_token, **urn_writes}
    try:
        write_result = env_writer.update_env(env_path, updates)
    except FileNotFoundError as e:
        return _oauth_result_page(
            ".env not found",
            f"<p>The OAuth callback tried to update <code>{_escape_html(str(env_path))}</code> "
            "but no .env file exists at that location.</p>"
            "<p>Run the setup wizard from the terminal to create it:</p>"
            "<pre>python3 automation/setup_env.py</pre>"
            f"<p>Or copy the example: <pre>cp {_escape_html(str(ROOT))}/.env.example {_escape_html(str(env_path))}</pre></p>"
            "<p>Then click Connect LinkedIn again. The token was received "
            "from LinkedIn but NOT written anywhere on disk.</p>",
            ok=False,
        )
    except (ValueError, OSError) as e:
        return _oauth_result_page(
            ".env write failed",
            f"<p>Tried to write: <code>{_escape_html(str(env_path))}</code></p>"
            f"<p>Error: {_escape_html(str(e))}</p>"
            "<p>The token was received from LinkedIn but NOT written. "
            "You can manually add <code>LINKEDIN_ACCESS_TOKEN</code> to "
            "<code>.env</code> and click Verify Connections.</p>",
            ok=False,
        )

    # Refresh process env so the new values are visible to the verify probe.
    os.environ["LINKEDIN_ACCESS_TOKEN"] = access_token
    if "LINKEDIN_AUTHOR_URN" in urn_writes:
        os.environ["LINKEDIN_AUTHOR_URN"] = urn_writes["LINKEDIN_AUTHOR_URN"]
    # Clear the local token reference; Python can't guarantee zeroisation
    # but this drops one accessible reference sooner.
    del access_token

    # Trigger verify; record the outcome.
    verify_result = social_posters.verify_linkedin_connection()
    connection_state.record_verification(
        "linkedin",
        ok=bool(verify_result.get("ok")),
        message=verify_result.get("message", ""),
    )

    op_token = ("replaced"
                if "LINKEDIN_ACCESS_TOKEN" in write_result["replaced"] else "added")
    body = (
        f"<p><strong>Access token {op_token}</strong> in "
        f"<code>{_escape_html(str(env_path))}</code> "
        f"(length: {token_len} chars). Backup saved to "
        f"<code>{_escape_html(str(env_path))}.bak</code>.</p>"
        f"<p><strong>Author URN:</strong> {_escape_html(urn_msg)}</p>"
        f"<p><strong>Verify probe:</strong> {_escape_html(verify_result.get('message', ''))}</p>"
    )
    if not verify_result.get("ok") and "LINKEDIN_AUTHOR_URN" not in urn_writes:
        body += (
            "<p>If you can find your member URN manually (your LinkedIn "
            "profile URL → numeric ID), add it to <code>.env</code> as "
            "<code>LINKEDIN_AUTHOR_URN=urn:li:person:XXXX</code> and click "
            "Verify Connections.</p>"
        )
    return _oauth_result_page("LinkedIn connected", body, ok=True)


def _escape_html(s: str) -> str:
    """Minimal HTML escape for the OAuth result page body."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- v6.7: Meta (Facebook + Instagram) Readiness Center -----------------
#
# Per-platform setup metadata, kept here (Python) rather than scattered
# across the frontend so all Meta-specific guidance lives in one place.

_META_READINESS_PLATFORMS = {
    "facebook": {
        "name":          "Facebook",
        "required_keys": ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN"],
        "doc_url":       "https://developers.facebook.com/docs/pages-api",
        "setup_steps": [
            "Create a Meta Developer App at developers.facebook.com",
            "Add the 'Facebook Login for Business' and 'Pages API' products",
            "Request 'pages_manage_posts' + 'pages_read_engagement' permissions",
            "Submit your app for review (Meta approval — currently pending)",
            "After approval, generate a long-lived Page Access Token",
            "Set FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN in .env",
            "Click 'Verify' below — Hub probes Graph API read-only",
        ],
    },
    "instagram": {
        "name":          "Instagram",
        "required_keys": ["INSTAGRAM_BUSINESS_ACCOUNT_ID", "INSTAGRAM_ACCESS_TOKEN"],
        "doc_url":       "https://developers.facebook.com/docs/instagram-platform",
        "setup_steps": [
            "Convert your Instagram account to Business or Creator",
            "Connect the IG account to a Facebook Page in Meta Business Suite",
            "In your Meta Developer App, add the 'Instagram Graph API' product",
            "Request 'instagram_content_publish' + 'instagram_basic' permissions",
            "Submit for app review (same Meta approval as Facebook)",
            "Set INSTAGRAM_BUSINESS_ACCOUNT_ID and INSTAGRAM_ACCESS_TOKEN in .env",
            "Click 'Verify' below — Hub probes Graph API read-only",
        ],
    },
}


@app.get("/api/meta/readiness")
def api_meta_readiness() -> dict:
    """
    Structured readiness report for Facebook + Instagram. Read-only,
    purely informational — built so the Hub's Meta Readiness Center can
    show "what's still needed" while you're waiting on Meta app review.

    Safety:
        - Returns env-key NAMES + present/absent booleans only.
          Actual values are NEVER returned.
        - Never calls any Meta API. Never modifies anything.
        - last_verified_at + verify_message come from
          connection_state.compute_state which already excludes tokens.
    """
    states = connection_state.load_states()
    notes_state = meta_app_state.load()
    out: dict[str, dict] = {}
    for slug, meta in _META_READINESS_PLATFORMS.items():
        state = connection_state.compute_state(slug, states)
        required_keys = [
            {"key": k, "present": bool((os.getenv(k) or "").strip())}
            for k in meta["required_keys"]
        ]
        missing = [r["key"] for r in required_keys if not r["present"]]
        # v6.8: per-platform user notes (app review status etc.).
        # Free-text only — no secrets, no Meta API payloads.
        notes_entry = notes_state.get(slug, {})
        out[slug] = {
            "name":             meta["name"],
            "status":           state["state"],
            "required_keys":    required_keys,
            "missing_keys":     missing,
            "setup_steps":      meta["setup_steps"],
            "doc_url":          meta["doc_url"],
            "last_verified_at": state["last_verified_at"],
            "verify_message":   state["last_message"],
            "notes":            notes_entry.get("notes") or "",
            "notes_updated_at": notes_entry.get("updated_at") or None,
        }
    return out


class MetaNotesUpdate(BaseModel):
    platform: str
    notes:    str


@app.post("/api/meta/notes")
def api_meta_notes(body: MetaNotesUpdate) -> dict:
    """
    Replace one Meta platform's notes with user-provided text. The text
    is capped at meta_app_state.MAX_NOTES_LEN chars and stamped with
    updated_at. Returns the saved entry — never includes anything
    other than the notes + timestamp.

    Safety:
        - Refuses platforms outside the allowed set (FB, IG).
        - meta_app_state validates + clamps length on save.
        - Note text is user-typed free text; the frontend escapes
          on render.
    """
    try:
        result = meta_app_state.set_notes(body.platform, body.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")
    return {"ok": True, "platform": body.platform, **result}


# --- v6.9: LinkedIn Lead Tracker (outbound CRM-lite) ---------------------
#
# Pure local storage in data/leads.json. No LinkedIn API. No outbound
# calls. All write paths go through leads_mod which whitelists fields
# and clamps lengths.

class LeadIn(BaseModel):
    """Accepts partial input — leads_mod._clean_lead enforces what's
    required and clamps/validates each field. Marking everything
    optional here lets PUT requests omit fields they don't change."""
    name:    str | None = None
    company: str | None = None
    handle:  str | None = None
    source:  str | None = None
    status:  str | None = None
    notes:   str | None = None


class LeadBatchIn(BaseModel):
    # v7.20: raw textarea contents for the bulk-paste importer. Server
    # splits on newlines and parses each line independently — keeps the
    # wire format simple. Defined here (not next to MessageDraftIn) so
    # api_leads_batch can resolve the forward reference at import time.
    text: str


class ScoutLeadIn(BaseModel):
    """v7.28: scout-queue input. All optional so PUT can omit fields.
    Server's scout_mod._clean enforces business_name required +
    validates status/priority enums."""
    business_name:  str | None = None
    category:       str | None = None
    city_state:     str | None = None
    contact_email:  str | None = None
    contact_source: str | None = None
    website_status: str | None = None
    evidence:       str | None = None
    offer_angle:    str | None = None
    priority:       str | None = None
    status:         str | None = None
    notes:          str | None = None


@app.get("/api/leads")
def api_leads_list() -> dict:
    """All leads, newest-first by updated_at."""
    items = leads_mod.load()
    items.sort(key=lambda l: l.get("updated_at") or "", reverse=True)
    return {"items": items, "count": len(items)}


@app.post("/api/leads")
def api_leads_add(body: LeadIn) -> dict:
    """Add a new lead. Returns the saved row."""
    try:
        return leads_mod.add(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")


@app.post("/api/leads/batch")
def api_leads_batch(body: LeadBatchIn) -> dict:
    """
    v7.20: bulk-add leads from a paste of LinkedIn URLs/handles.
    Each line is parsed independently; recognized handles become cold
    leads with source='paste-import'. Duplicates (vs existing leads
    AND within the same paste) are skipped silently and counted.
    Unrecognized non-blank lines are reported back so the user can
    fix and re-submit. Hard cap at MAX_BATCH_SIZE (50) to prevent
    accidental large pastes.
    """
    try:
        return leads_mod.add_batch(body.text.splitlines())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")


@app.put("/api/leads/{lead_id}")
def api_leads_update(lead_id: str, body: LeadIn) -> dict:
    """Update an existing lead. 404 if id not found."""
    try:
        return leads_mod.update(lead_id, body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")


@app.delete("/api/leads/{lead_id}")
def api_leads_delete(lead_id: str) -> dict:
    """Delete one lead. 404 if id not found."""
    try:
        removed = leads_mod.delete(lead_id)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")
    if not removed:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id!r} not found")
    return {"ok": True, "id": lead_id}


# --- v7.0: Lead follow-up queue endpoints --------------------------------
# Three POST actions that operate on a specific lead. All purely local —
# no LinkedIn messaging, no OpenAI, no browser automation. message-draft
# returns a fixed-template string the user is expected to copy + paste
# into LinkedIn manually.

class FollowUpUpdate(BaseModel):
    follow_up_date: str | None = None


class MessageDraftIn(BaseModel):
    # v7.16: optional template selector. None → server picks based on
    # lead status. Unknown key → 400.
    template: str | None = None


@app.post("/api/leads/{lead_id}/contacted")
def api_leads_mark_contacted(lead_id: str) -> dict:
    """
    Mark a lead as contacted (stamp contacted_at = now) and auto-promote
    cold → warm. Returns the updated lead row.
    """
    try:
        return leads_mod.mark_contacted(lead_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id!r} not found")
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/leads/{lead_id}/follow-up")
def api_leads_set_follow_up(lead_id: str, body: FollowUpUpdate) -> dict:
    """Set the lead's follow_up_date (YYYY-MM-DD or empty to clear)."""
    try:
        return leads_mod.set_follow_up(lead_id, body.follow_up_date or "")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")


@app.post("/api/leads/{lead_id}/message-draft")
def api_leads_message_draft(
    lead_id: str,
    body: MessageDraftIn | None = None,
) -> dict:
    """
    Produce a stage-aware templated outreach message (NO OpenAI),
    store it in the lead's last_message, and return {message, lead,
    template}. If body.template is None, the server picks based on
    lead status (cold→intro, warm→check_in, hot→close_ask).

    The Hub does NOT send this anywhere. The user copies + pastes into
    LinkedIn manually. This endpoint cannot trigger any outbound
    message to LinkedIn or any other service.
    """
    template = body.template if body else None
    try:
        return leads_mod.draft_message(lead_id, template)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id!r} not found")
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/leads/templates")
def api_leads_templates() -> dict:
    """
    Expose the outreach template registry to the frontend so the
    picker stays in sync with leads.py without hardcoding labels
    on the client.

    v7.17: also returns each template's raw body (with {name}/
    {company} placeholders) so the frontend can render a per-lead
    preview tooltip without an extra round-trip. Bodies are static
    public marketing copy — no secrets.
    """
    return {
        "templates": [
            {
                "key":        k,
                "label":      v["label"],
                "for_status": v["for_status"],
                "body":       v["body"],
            }
            for k, v in leads_mod.MESSAGE_TEMPLATES.items()
        ],
    }


# --- v7.28: Logan Lead Scout Queue ------------------------------------
# Local-only capture + qualification queue. NO scraping, NO outreach,
# NO OpenAI. The /convert helper copies a row into the existing leads
# registry — that's the only cross-data-file write any of these do.

@app.get("/api/scout-leads")
def api_scout_leads_list() -> dict:
    items = scout_mod.load()
    return {"items": items, "count": len(items)}


@app.post("/api/scout-leads")
def api_scout_leads_add(body: ScoutLeadIn) -> dict:
    try:
        return scout_mod.add(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")


@app.put("/api/scout-leads/{scout_id}")
def api_scout_leads_update(scout_id: str, body: ScoutLeadIn) -> dict:
    try:
        return scout_mod.update(scout_id, body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Scout lead {scout_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")


@app.delete("/api/scout-leads/{scout_id}")
def api_scout_leads_delete(scout_id: str) -> dict:
    if not scout_mod.delete(scout_id):
        raise HTTPException(status_code=404, detail=f"Scout lead {scout_id!r} not found")
    return {"ok": True, "id": scout_id}


@app.post("/api/scout-leads/{scout_id}/convert")
def api_scout_leads_convert(scout_id: str) -> dict:
    """
    Copy a scout lead into the Logan/LinkedIn Leads registry as a cold
    lead, then mark the scout row as 'converted'. Returns
    {scout, lead}. Local-only: no external calls, no outreach.
    """
    try:
        return scout_mod.convert(scout_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Scout lead {scout_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write: {e}")


@app.get("/api/connections")
def api_connections() -> dict:
    """
    Reports which publishing platforms are configured by checking that each
    platform's required env keys are present and non-empty.

    Returns ONLY env key NAMES that are missing — never any value. No OAuth,
    no outbound calls, no DB writes. Treats whitespace-only values as missing
    so a stray space in .env doesn't count as "configured."
    """
    cache = connection_state.load_states()
    connections = []
    for platform, keys in _PLATFORM_ENV_REQUIREMENTS.items():
        missing = [k for k in keys if not (os.getenv(k) or "").strip()]
        # Resolve the canonical key the cache uses ("linkedin",
        # "google_business_profile", …) from the display name.
        platform_key = platform.lower().replace(" ", "_")
        state = connection_state.compute_state(platform_key, cache)
        age = connection_state.verification_age_days(state["last_verified_at"])
        warning = connection_state.expiry_warning(state["state"], state["last_verified_at"])
        connections.append({
            "platform":              platform,
            "status":                state["state"],   # verified | configured | not_configured
            "missing":               missing,
            "setup_url":             _PLATFORM_SETUP_URLS.get(platform, ""),
            "last_verified_at":      state["last_verified_at"],
            "last_message":          state["last_message"],
            "verification_age_days": age,
            "warning":               warning,
        })
    return {"connections": connections}


# Report Inbox (v5.15). Strict filename pattern keeps the Hub-side
# read endpoints safe against path-traversal — only files named
# exactly YYYY-MM-DD.md inside reports/ can be opened.
_REPORTS_DIR = ROOT / "reports"
_REPORT_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


@app.get("/api/reports")
def api_reports_list() -> dict:
    """
    Read-only list of available daily report files. Returns metadata
    only (name, date stem, size, mtime, approvals, publishes) — never
    opens file contents. Filenames not matching YYYY-MM-DD.md are
    silently filtered out so stray files in reports/ never appear in
    the inbox.

    v5.19: per-row approval + publish counts come from two batched
    GROUP BY queries against the DB (one for each table), so the cost
    is O(2 queries) regardless of how many report files exist.
    """
    approvals_by_date: dict[str, int] = {}
    publishes_by_date: dict[str, int] = {}
    if DB_PATH.is_file():
        conn = sqlite3.connect(DB_PATH)
        try:
            for d, n in conn.execute(
                "SELECT date(posted_date) AS d, COUNT(*) "
                "FROM post_history GROUP BY d"
            ).fetchall():
                if d:
                    approvals_by_date[d] = n
            for d, n in conn.execute(
                "SELECT date(posted_at) AS d, COUNT(*) "
                "FROM posts "
                "WHERE status = 'posted' AND posted_at IS NOT NULL "
                "GROUP BY d"
            ).fetchall():
                if d:
                    publishes_by_date[d] = n
        finally:
            conn.close()

    items: list[dict] = []
    if _REPORTS_DIR.is_dir():
        for p in _REPORTS_DIR.glob("*.md"):
            if not _REPORT_NAME_RE.fullmatch(p.name):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            items.append({
                "name":      p.name,
                "date":      p.stem,
                "size":      st.st_size,
                "mtime":     datetime.fromtimestamp(st.st_mtime)
                                     .strftime("%Y-%m-%d %H:%M:%S"),
                "approvals": approvals_by_date.get(p.stem, 0),
                "publishes": publishes_by_date.get(p.stem, 0),
            })
    items.sort(key=lambda x: x["date"], reverse=True)
    return {"items": items, "count": len(items)}


@app.get("/api/reports/{filename}")
def api_reports_get(filename: str) -> dict:
    """
    Read-only fetch of a specific report's markdown content. Filename
    is validated against a strict YYYY-MM-DD.md regex before any
    filesystem access — there is no way to ask for ../, an absolute
    path, or any non-report file.
    """
    if not _REPORT_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid report filename")
    p = _REPORTS_DIR / filename
    # resolve() collapses any . / .. that somehow slipped past the regex,
    # then we verify the result is actually inside _REPORTS_DIR.
    try:
        resolved = p.resolve()
        _REPORTS_DIR.resolve()  # ensure _REPORTS_DIR is resolvable
        if _REPORTS_DIR.resolve() not in resolved.parents:
            raise HTTPException(status_code=400, detail="Invalid report path")
    except OSError:
        raise HTTPException(status_code=404, detail=f"Report {filename!r} not found")
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"Report {filename!r} not found")
    try:
        content = p.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"name": filename, "date": p.stem, "content": content}


@app.get("/api/activity")
def api_activity() -> dict:
    """
    Read-only activity feed assembled from existing sources:
      - generation events    → group rows of `posts` by created_at minute
                                (one daily_runner run inserts ~4 posts at
                                the same minute)
      - approval events      → each row in `post_history`
      - publish events       → rows of `posts` with status='posted' and
                                a non-NULL posted_at (v5.8)
      - connection events    → each verified entry in
                                data/connection_status.json
      - refresh events       → mtime of data/connection_status.json,
                                which represents the most recent trust-
                                state refresh (v5.11) — stat() only
      - system events        → mtime of each non-empty .log in logs/
                                modified within the trailing 14 days
                                (v5.10) — stat() only, no contents read
    No polling loop. Capped at 25 entries, sorted newest first, with
    (timestamp, message) dedupe so a duplicate run never spams the feed.
    """
    events: list[dict] = []

    if DB_PATH.is_file():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # Generation batches: group recent posts by created_at minute.
            for row in conn.execute(
                "SELECT substr(created_at, 1, 16) AS minute, "
                "       COUNT(*) AS n, "
                "       MAX(created_at) AS last_ts "
                "FROM posts "
                "GROUP BY minute "
                "ORDER BY last_ts DESC LIMIT 10"
            ).fetchall():
                noun = "draft" if row["n"] == 1 else "drafts"
                events.append({
                    "ts":      row["last_ts"],
                    "type":    "generation",
                    "message": f"Parker generated {row['n']} {noun}",
                })

            # Each approval (post_history row). post_history has long
            # been the approval log in this codebase — the column name
            # "posted_date" is historical and refers to the approval
            # moment, not a publish moment.
            for row in conn.execute(
                "SELECT topic, platform, posted_date "
                "FROM post_history ORDER BY posted_date DESC LIMIT 15"
            ).fetchall():
                events.append({
                    "ts":      row["posted_date"],
                    "type":    "approval",
                    "message": f"Approved {row['platform']} draft — {row['topic']}",
                })

            # Publish events (v5.8). Only surfaces rows that have a real
            # posted_at — rows that were marked 'posted' before the
            # posted_at column existed have NULL and are skipped (we
            # cannot fabricate a timestamp for those).
            # v6.3: include published_url so the renderer can embed a
            # "View →" link on rows that have a known public URL.
            for row in conn.execute(
                "SELECT topic, platform, posted_at, published_url "
                "FROM posts "
                "WHERE status = 'posted' AND posted_at IS NOT NULL "
                "ORDER BY posted_at DESC LIMIT 15"
            ).fetchall():
                event = {
                    "ts":      row["posted_at"],
                    "type":    "publish",
                    "message": f"Published {row['platform']} post — {row['topic']}",
                }
                if row["published_url"]:
                    event["url"] = row["published_url"]
                events.append(event)
        finally:
            conn.close()

    # Verified connections from the local cache. Cache timestamps are
    # "YYYY-MM-DD HH:MM" (no seconds), so pad for consistent lexicographic
    # sort against the SQLite timestamps which include seconds.
    for platform_key, entry in connection_state.load_states().items():
        if entry.get("state") != "verified":
            continue
        ts = entry.get("last_verified_at")
        if not ts:
            continue
        pretty = platform_key.replace("_", " ").title()
        events.append({
            "ts":      ts if len(ts) > 16 else f"{ts}:00",
            "type":    "connection",
            "message": f"{pretty} connection verified",
        })

    # Refresh events from connection_status.json mtime (v5.11). The
    # file is written only by connection_state.record_verification(),
    # so its mtime is the timestamp of the most recent trust-state
    # refresh — i.e. the last time any platform's verify probe ran
    # (Hub's Verify Connections button or the CLI `verify` command).
    # File mtime captures only the LAST write, so this surfaces at most
    # ONE refresh event per request (the latest); the dedupe further
    # down would collapse duplicates anyway.
    cs_path = ROOT / "data" / "connection_status.json"
    if cs_path.is_file():
        try:
            cs_stat = cs_path.stat()
        except OSError:
            cs_stat = None
        if cs_stat is not None and cs_stat.st_size > 0:
            cs_mtime = datetime.fromtimestamp(cs_stat.st_mtime)
            if (datetime.now() - cs_mtime).days <= 14:
                events.append({
                    "ts":      cs_mtime.strftime("%Y-%m-%d %H:%M:%S"),
                    "type":    "refresh",
                    "message": "Connection states refreshed",
                })

    # System events from log file mtimes (v5.10). One event per .log
    # file in logs/ that has size > 0 and was modified within the last
    # 14 days. Read-only stat() — never opens or parses file contents,
    # never writes anything.
    logs_dir = ROOT / "logs"
    if logs_dir.is_dir():
        now = datetime.now()
        for log_path in logs_dir.glob("*.log"):
            try:
                st = log_path.stat()
            except OSError:
                continue
            if st.st_size == 0:
                continue
            mtime = datetime.fromtimestamp(st.st_mtime)
            if (now - mtime).days > 14:
                continue
            name = log_path.stem
            is_date_stem = (
                len(name) == 10 and name[4] == "-" and name[7] == "-"
                and name[:4].isdigit() and name[5:7].isdigit()
                and name[8:10].isdigit()
            )
            if is_date_stem:
                message = "Daily ops completed"
            elif name == "launchd.out":
                message = "Launchd output log updated"
            elif name == "launchd.err":
                message = "Launchd error log updated"
            else:
                message = f"{name} log updated"
            events.append({
                "ts":      mtime.strftime("%Y-%m-%d %H:%M:%S"),
                "type":    "system",
                "message": message,
            })

    # Sort newest first, dedupe identical (ts, message) pairs, cap at 25.
    events.sort(key=lambda e: e["ts"], reverse=True)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for e in events:
        key = (e["ts"], e["message"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    deduped = deduped[:25]

    today_str = datetime.now().strftime("%Y-%m-%d")
    items = []
    for e in deduped:
        # ts looks like "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD HH:MM".
        full = e["ts"]
        date_part = full[:10]
        time_part = full[11:16] if len(full) >= 16 else full

        # display_time = bare "HH:MM" for today; "MMM D HH:MM" for older
        # events so the date is visible without checking the divider.
        # Build the month/day part manually so we don't depend on the
        # GNU-only "%-d" strftime extension.
        if date_part == today_str:
            display_time = time_part
        else:
            try:
                dt = datetime.strptime(full[:16], "%Y-%m-%d %H:%M")
                display_time = f"{dt.strftime('%b')} {dt.day} {dt.strftime('%H:%M')}"
            except ValueError:
                display_time = full

        item = {
            "time":         time_part,    # kept for backward compat
            "date":         date_part,
            "display_time": display_time,
            "message":      e["message"],
            "type":         e["type"],
        }
        # v6.3: pass through receipt url (set by the publish-event
        # loop) so the activity-feed renderer can embed a link.
        if e.get("url"):
            item["url"] = e["url"]
        items.append(item)
    return {"items": items}


def _count_partner_files(directory: Path, suffix: str) -> int:
    """Defensive file count for partner-metric directories. Returns 0
    on missing dir. Filters by suffix to skip .gitkeep, .DS_Store, etc."""
    if not directory.is_dir():
        return 0
    return sum(
        1 for p in directory.iterdir()
        if p.is_file() and p.name.endswith(suffix)
    )


@app.get("/api/partners")
def api_partners() -> dict:
    """
    Lightweight partner roster for the Hub's Partner Rooms section.
    Parker's metrics come from the posts table; Logan's from the v6.9
    leads tracker; Olivia's from the daily-ops output directories
    (summaries/*.md and status_history/*.json). Read-only — no DB
    writes, no OpenAI calls, no filesystem mutations.
    """
    # Direct status_counts() so we get every status (including 'posted')
    # without touching status._gather_status's documented JSON shape.
    counts = approval_manager.status_counts() if DB_PATH.is_file() else {}
    # v7.12: Logan's metrics from the leads tracker. load() is
    # defensive — returns [] on missing/corrupt file — so no guard
    # needed. outreach_queue = anything not closed or dropped.
    all_leads = leads_mod.load()
    active_leads = [
        l for l in all_leads
        if l.get("status") not in ("closed", "dropped")
    ]
    # v7.29: Logan also owns the scout queue (v7.28). Count only
    # actively-scouted rows — converted/rejected are done.
    all_scouts = scout_mod.load()
    active_scouts = [
        s for s in all_scouts
        if s.get("status") not in ("converted", "rejected")
    ]
    # v7.14: Olivia's metrics from the daily-ops output dirs. Both are
    # populated by automation/daily_ops.py:
    #   morning_summary.py  → summaries/YYYY-MM-DD.md
    #   status_snapshot.py  → status_history/YYYY-MM-DD.json
    # If a cron run misses, the count just doesn't tick — which is the
    # truthful signal.
    summaries_count = _count_partner_files(ROOT / "summaries", ".md")
    snapshots_count = _count_partner_files(ROOT / "status_history", ".json")

    return {
        "partners": [
            {
                "key":    "parker",
                "name":   "Parker Promo",
                "status": "active",
                "role":   "Content + publishing",
                "metrics": {
                    "pending":  counts.get("draft", 0),
                    "approved": counts.get("approved", 0),
                    "posted":   counts.get("posted", 0),
                },
            },
            {
                "key":    "logan",
                # v7.29: Logan is active now that v7.6→v7.28 shipped
                # the leads pipeline + scout queue.
                "name":   "Logan Leads",
                "status": "active",
                "role":   "Lead generation",
                "metrics": {
                    "prospects_tracked": len(all_leads),
                    "outreach_queue":    len(active_leads),
                    "scout_queue":       len(active_scouts),
                },
            },
            {
                "key":    "olivia",
                # v7.30: Olivia is active — daily_ops.py has been
                # writing her summaries + snapshots on the cron every
                # morning. v7.14 already wired real metrics; the
                # status label was the last thing lagging the truth.
                "name":   "Olivia Office",
                "status": "active",
                "role":   "Operations / admin",
                "metrics": {
                    "summaries_generated": summaries_count,
                    "snapshots_archived":  snapshots_count,
                },
            },
        ],
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


# --- v6.6: Hub diagnostics --------------------------------------------------

def _redact_secrets(text: str) -> str:
    """
    Defense-in-depth redaction for output that may be returned to the
    browser (e.g. hub_doctor output). Three passes:

      1. Every non-empty .env value of length > 8 is replaced
         verbatim with [REDACTED]. Catches the case where a token
         accidentally ended up in a log line.
      2. OAuth-shaped query params (?code=, ?state=, ?access_token=)
         have their values masked. uvicorn's access log records full
         URLs; the OAuth callback URL contains a short-lived code we
         shouldn't surface even briefly.
      3. `Bearer <token>` patterns are masked. Belt-and-braces in
         case any error path logs an Authorization header.

    Pure string scrub — never raises, never reads env vars beyond
    parsing .env at request time.
    """
    if not text:
        return text
    # 1. Verbatim .env values
    env_path = ROOT / ".env"
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                _key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                if value and len(value) > 8:
                    text = text.replace(value, "[REDACTED]")
        except OSError:
            pass
    # 2. Sensitive OAuth-style query params
    text = re.sub(
        r"([?&](?:code|state|access_token|client_secret)=)[^&\s\"']+",
        r"\1[REDACTED]",
        text,
    )
    # 3. Bearer tokens
    text = re.sub(
        r"(Bearer\s+)[A-Za-z0-9._\-]+",
        r"\1[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    return text


@app.get("/api/hub/diagnostics")
def api_hub_diagnostics() -> dict:
    """
    Run automation/hub_doctor.sh and return its (redacted) output for
    the Hub's Control Panel "Show Hub Diagnostics" button.

    Read-only: the doctor itself never starts/stops the server or
    modifies any file. The endpoint:
      - caps the subprocess at 5 seconds
      - passes the doctor's combined stdout + stderr through
        _redact_secrets before returning
      - returns ok=False (not 500) on any error so the UI can render
        the failure message in the same Command Output panel

    Output is safe to display in the browser.
    """
    doctor = ROOT / "automation" / "hub_doctor.sh"
    if not doctor.is_file():
        return {
            "ok": False,
            "output": f"hub_doctor.sh not found at {doctor}",
        }
    try:
        result = subprocess.run(
            ["/bin/bash", str(doctor)],
            capture_output=True, text=True, timeout=5,
            cwd=str(ROOT),
        )
        combined = result.stdout
        if result.stderr:
            combined += "\n--- STDERR ---\n" + result.stderr
        return {
            "ok": result.returncode == 0,
            "output": _redact_secrets(combined),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "output": "hub_doctor.sh timed out after 5 seconds.",
        }
    except (subprocess.SubprocessError, OSError) as e:
        return {
            "ok": False,
            "output": f"hub_doctor.sh failed: {type(e).__name__}: {e}",
        }


@app.post("/api/hub/stop")
def api_hub_stop() -> dict:
    """
    Send SIGTERM to the running Hub process (v6.5). The PID is read
    from logs/hub.pid which open_hub.sh wrote at startup. The response
    is returned BEFORE uvicorn actually exits — the client will lose
    connectivity within a second of receiving the response.

    Safety layers (defense against PID reuse):
        1. Only signals the PID in logs/hub.pid — never an arbitrary
           PID passed in the request.
        2. Verifies the target process is alive via kill(pid, 0).
        3. Inspects /usr/bin/ps to confirm the command line includes
           both "uvicorn" and "hub.app". If anything else is at that
           PID (e.g., the PID got recycled by the kernel), refuses.
        4. Sends SIGTERM (not SIGKILL) so uvicorn shuts down
           gracefully — same signal nohup-detached child receives.
    """
    pid_file = ROOT / "logs" / "hub.pid"
    if not pid_file.is_file():
        return {
            "ok": False,
            "message": (
                "logs/hub.pid not found. The Hub may have been started "
                "without open_hub.sh, or it was already stopped. To "
                "stop a manually-started server, kill its PID from the "
                "terminal."
            ),
        }

    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError) as e:
        return {"ok": False, "message": f"Cannot read PID from logs/hub.pid: {e}"}

    # Liveness check — kill(pid, 0) raises if not alive.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {
            "ok": False,
            "message": f"PID {pid} from logs/hub.pid is not running (already stopped). "
                       "You can delete logs/hub.pid manually if it's stale.",
        }
    except PermissionError:
        return {
            "ok": False,
            "message": f"Cannot signal PID {pid} — permission denied. The Hub may "
                       "be running as a different user.",
        }

    # PID-reuse defense: confirm the command at this PID actually
    # looks like our Hub. We need TWO checks because a bash script
    # whose body MENTIONS "uvicorn hub.app" would otherwise pass the
    # second check alone (the strings are in the bash process's
    # full command line). ps comm= gives just the executable name —
    # bash != python so the executable-name check rejects bash even
    # if its arguments happen to contain Hub-shaped strings.
    try:
        comm_result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=2,
        )
        cmd_result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=2,
        )
        comm = comm_result.stdout.strip()
        cmd  = cmd_result.stdout.strip()
    except (subprocess.SubprocessError, OSError) as e:
        return {"ok": False, "message": f"Cannot inspect PID {pid}: {e}"}

    # The executable must be a Python interpreter (covers framework
    # Python's Python.app shim, /usr/bin/python3, homebrew python3.x,
    # etc.). Case-insensitive because macOS framework Python is
    # "Python" with a capital P.
    comm_basename = comm.rsplit("/", 1)[-1].lower()
    is_python = comm_basename.startswith("python")
    has_hub_args = ("uvicorn" in cmd) and ("hub.app" in cmd)

    if not (is_python and has_hub_args):
        return {
            "ok": False,
            "message": (
                f"PID {pid} does not look like our Hub "
                f"(comm={comm!r}, command snippet={cmd[:80]!r}). "
                "Refusing to signal in case the PID has been reused. "
                "Both an exec name starting with 'python' AND "
                "'uvicorn'+'hub.app' in args are required."
            ),
        }

    # All checks pass — send SIGTERM. Uvicorn handles SIGTERM
    # gracefully and exits cleanly within ~100ms.
    try:
        os.kill(pid, _signal.SIGTERM)
    except OSError as e:
        return {"ok": False, "message": f"Failed to signal PID {pid}: {e}"}

    return {
        "ok": True,
        "pid": pid,
        "message": f"SIGTERM sent to PID {pid}. The Hub will shut down "
                   "within a second. Restart with the Desktop icon "
                   "or `bash automation/open_hub.sh`.",
    }
