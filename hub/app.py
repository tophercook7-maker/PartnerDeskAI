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


ROOT = Path(__file__).resolve().parent.parent
HUB_DIR = Path(__file__).resolve().parent

# Make automation/ importable so we can reuse status._gather_status()
# and approval_manager.get_post() (read-only single-row helper).
sys.path.insert(0, str(ROOT / "automation"))
import approval_manager  # noqa: E402
import connection_state  # noqa: E402
import env_writer  # noqa: E402
import linkedin_oauth  # noqa: E402
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
    Returns id/platform/topic/status/created_at/edited_at — content is
    never included so the Hub API doesn't leak full draft bodies.
    """
    if not DB_PATH.is_file():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, platform, topic, status, created_at, edited_at "
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
        rows = conn.execute(
            "SELECT id, platform, topic, status, created_at, edited_at, content "
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
    if result.get("ok"):
        approval_manager.mark_status(post_id, "posted")

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
    return {
        "id":         post["id"],
        "platform":   post["platform"],
        "topic":      post["topic"],
        "status":     post["status"],
        "created_at": post["created_at"],
        "edited_at":  post["edited_at"],
        "content":    post["content"],
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
    Step 2: LinkedIn redirects here with ?code=… and ?state=… on
    success, or ?error=… on user denial. We:
      1. Verify state matches one we issued (CSRF protection).
      2. POST the code to LinkedIn's token endpoint via
         linkedin_oauth.exchange_code_for_token.
      3. Atomically write LINKEDIN_ACCESS_TOKEN to .env via env_writer.
      4. Reload the process env so the new token is live in this Hub.
      5. Call connection_state.record_verification with the result of
         verify_linkedin_connection().
    Returns a small HTML page with success/failure — token value is
    NEVER rendered or logged.
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
    # env_writer preserves file mode and never logs values.
    updates = {"LINKEDIN_ACCESS_TOKEN": access_token, **urn_writes}
    try:
        write_result = env_writer.update_env(ROOT / ".env", updates)
    except (FileNotFoundError, ValueError, OSError) as e:
        return _oauth_result_page(
            "Token received but .env write failed",
            f"<p>{_escape_html(str(e))}</p>"
            "<p>Try again, or manually add LINKEDIN_ACCESS_TOKEN to .env.</p>",
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
        f"<p><strong>Access token {op_token}</strong> in <code>.env</code> "
        f"(length: {token_len} chars). Backup saved to <code>.env.bak</code>.</p>"
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
            for row in conn.execute(
                "SELECT topic, platform, posted_at "
                "FROM posts "
                "WHERE status = 'posted' AND posted_at IS NOT NULL "
                "ORDER BY posted_at DESC LIMIT 15"
            ).fetchall():
                events.append({
                    "ts":      row["posted_at"],
                    "type":    "publish",
                    "message": f"Published {row['platform']} post — {row['topic']}",
                })
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

        items.append({
            "time":         time_part,    # kept for backward compat
            "date":         date_part,
            "display_time": display_time,
            "message":      e["message"],
            "type":         e["type"],
        })
    return {"items": items}


@app.get("/api/partners")
def api_partners() -> dict:
    """
    Lightweight partner roster for the Hub's Partner Rooms section.
    Parker's metrics are pulled live from the posts table; Logan and
    Olivia ship as zero-valued placeholders for now. Read-only — no DB
    writes, no OpenAI calls.
    """
    # Direct status_counts() so we get every status (including 'posted')
    # without touching status._gather_status's documented JSON shape.
    counts = approval_manager.status_counts() if DB_PATH.is_file() else {}

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
                "name":   "Logan Leads",
                "status": "standby",
                "role":   "Lead generation",
                "metrics": {
                    "prospects_tracked": 0,
                    "outreach_queue":    0,
                },
            },
            {
                "key":    "olivia",
                "name":   "Olivia Office",
                "status": "standby",
                "role":   "Operations / admin",
                "metrics": {
                    "summaries_generated": 0,
                    "snapshots_archived":  0,
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
