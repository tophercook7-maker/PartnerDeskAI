"""
gmail_partner.py
----------------
v12.11 — Gmail send integration. Layer 2 explicitly authorized by user.

Capability:
    - OAuth 2.0 (Web app loopback flow) against the user's own Google Cloud project
    - Send email as the authenticated Gmail account via the Gmail REST API
    - Persistent refresh-token-based auth (access token auto-refreshes)
    - Token storage in `data/gmail_tokens.json` (gitignored)
    - Client credentials in `data/google_oauth_client.json` (gitignored)

What this module DOES NOT do:
    - Read or list emails (out of scope for v12.11; would need extra scope)
    - Batch send (one email per call)
    - Bypass user confirmation (the UI shows a preview + final Send button)

Standing safety rules that WERE waived for this module (explicit
authorization in v12.11):
    - OAuth (Google sign-in flow)
    - Auto-send (one-click after preview; no batched auto-send)

Standing rules STILL in effect:
    - No new Python dependencies — stdlib only (urllib, base64, email.mime.text)
    - No live changes to other systems (this only sends Gmail; nothing else)
    - All state local; tokens never leave the machine via git

Threat model notes:
    - Tokens stored plaintext in data/. If data/ is shared or backed up
      to a public location, tokens are exposed and could be used to send
      mail as the user until revoked.
    - Refresh tokens last forever unless revoked. User can disconnect
      (deletes tokens) or revoke via Google Account → Security → Third-party.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import base64
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
CLIENT_PATH = ROOT / "data" / "google_oauth_client.json"
TOKENS_PATH = ROOT / "data" / "gmail_tokens.json"
SEND_LOG_PATH = ROOT / "data" / "gmail_send_log.json"

# Google OAuth endpoints
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL     = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
USERINFO_URL  = "https://openidconnect.googleapis.com/v1/userinfo"

# Scope kept minimal — only what's needed to send. NOT requesting
# read access, so the user doesn't grant more than necessary.
DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "email",
)

# OAuth callback path served by the Hub itself (same FastAPI app).
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8000/api/gmail/oauth/callback"

# v12.11 safety: hard ceiling on message size so we don't accidentally
# send something pathological. 1 MiB raw including the base64 overhead.
MAX_RAW_MESSAGE_BYTES = 1_048_576

# Identifier we include in the User-Agent so Google's logs can identify
# this app.
USER_AGENT = "PartnerDeskAI/12.11 (Gmail send integration)"


class GmailError(Exception):
    """Raised for any auth / transport / send error."""


# ======================================================================
# Atomic file IO
# ======================================================================

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


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================
# Client config (user pastes client_id + client_secret)
# ======================================================================

def load_client_config() -> dict:
    """Returns {client_id, client_secret, redirect_uri} or {} if unset."""
    cfg = _safe_load(CLIENT_PATH, {})
    if not isinstance(cfg, dict):
        return {}
    return cfg


def save_client_config(client_id: str, client_secret: str,
                       redirect_uri: str | None = None) -> dict:
    """Persist client_id + client_secret + redirect_uri to
    data/google_oauth_client.json. Returns the saved config."""
    client_id     = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise GmailError("client_id and client_secret are required")
    cfg = {
        "client_id":     client_id[:400],
        "client_secret": client_secret[:400],
        "redirect_uri":  (redirect_uri or DEFAULT_REDIRECT_URI)[:400],
        "updated_at":    _now_iso(),
    }
    _atomic_write(CLIENT_PATH, cfg)
    return cfg


def clear_client_config() -> dict:
    """Delete the stored client config — user wants to switch projects."""
    if CLIENT_PATH.is_file():
        try: CLIENT_PATH.unlink()
        except OSError: pass
    return {"ok": True, "cleared": "client_config"}


def is_configured() -> bool:
    cfg = load_client_config()
    return bool(cfg.get("client_id") and cfg.get("client_secret"))


# ======================================================================
# OAuth flow
# ======================================================================

def get_authorize_url(state: str = "") -> str:
    """
    Build the URL the user opens in a browser to authorize.
    `state` is echoed back in the callback — used for CSRF protection.
    """
    cfg = load_client_config()
    if not is_configured():
        raise GmailError(
            "Gmail not configured. Save your client_id + client_secret first."
        )
    params = {
        "client_id":     cfg["client_id"],
        "redirect_uri":  cfg.get("redirect_uri") or DEFAULT_REDIRECT_URI,
        "response_type": "code",
        "scope":         " ".join(DEFAULT_SCOPES),
        # access_type=offline ensures we get a refresh token
        "access_type":   "offline",
        # prompt=consent forces the consent screen even if user has
        # already authorized — needed to reliably get a refresh token
        "prompt":        "consent",
    }
    if state:
        params["state"] = state
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict:
    """
    Exchange the OAuth code from the callback for access + refresh
    tokens. Persists tokens. Returns the saved token record.
    """
    cfg = load_client_config()
    if not is_configured():
        raise GmailError("Gmail not configured.")
    body = urllib.parse.urlencode({
        "code":          code,
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri":  cfg.get("redirect_uri") or DEFAULT_REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise GmailError(
            f"Token exchange failed: HTTP {e.code}: "
            f"{e.read().decode('utf-8', errors='replace')[:400]}"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise GmailError(f"Token exchange unreachable: {e}") from e

    access  = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = int(payload.get("expires_in") or 3600)
    scope   = payload.get("scope") or " ".join(DEFAULT_SCOPES)
    if not access:
        raise GmailError(f"Token exchange returned no access_token: {payload}")
    # Fetch the user's email address so we can show it in the UI.
    email_address = ""
    try:
        email_address = _fetch_userinfo_email(access) or ""
    except Exception:
        pass
    tokens = {
        "access_token":  access,
        "refresh_token": refresh,
        "expires_at":    (datetime.now() + timedelta(seconds=expires_in - 60)
                          ).strftime("%Y-%m-%d %H:%M:%S"),
        "scope":         scope,
        "email_address": email_address,
        "connected_at":  _now_iso(),
    }
    _atomic_write(TOKENS_PATH, tokens)
    return tokens


def _fetch_userinfo_email(access_token: str) -> str:
    req = urllib.request.Request(
        USERINFO_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return ""
    return (data or {}).get("email", "") or ""


def load_tokens() -> dict:
    t = _safe_load(TOKENS_PATH, {})
    if not isinstance(t, dict):
        return {}
    return t


def is_connected() -> bool:
    t = load_tokens()
    return bool(t.get("access_token") or t.get("refresh_token"))


def disconnect() -> dict:
    """Delete the stored tokens. Client config preserved so the user
    can reconnect without re-pasting credentials."""
    if TOKENS_PATH.is_file():
        try: TOKENS_PATH.unlink()
        except OSError: pass
    return {"ok": True, "cleared": "tokens"}


def _refresh_if_needed() -> str:
    """
    Return a valid access_token. Refreshes it if expired.
    Raises GmailError if refresh fails (e.g. token revoked).
    """
    t = load_tokens()
    if not t.get("access_token") and not t.get("refresh_token"):
        raise GmailError("Not connected to Gmail.")
    expires_at = t.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            exp_dt = datetime.now() - timedelta(seconds=1)  # force refresh
        if datetime.now() < exp_dt and t.get("access_token"):
            return t["access_token"]
    # Need to refresh.
    refresh = t.get("refresh_token")
    if not refresh:
        raise GmailError(
            "Access token expired and no refresh token on file. "
            "Reconnect."
        )
    cfg = load_client_config()
    body = urllib.parse.urlencode({
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": refresh,
        "grant_type":    "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise GmailError(
            f"Token refresh failed: HTTP {e.code}: "
            f"{e.read().decode('utf-8', errors='replace')[:300]}"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise GmailError(f"Token refresh unreachable: {e}") from e
    access = payload.get("access_token")
    if not access:
        raise GmailError(f"Refresh returned no access_token: {payload}")
    expires_in = int(payload.get("expires_in") or 3600)
    t["access_token"] = access
    t["expires_at"]   = (datetime.now() + timedelta(seconds=expires_in - 60)
                         ).strftime("%Y-%m-%d %H:%M:%S")
    _atomic_write(TOKENS_PATH, t)
    return access


# ======================================================================
# Send + send log
# ======================================================================

def send_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict:
    """
    Send a single email as the authenticated user.

    Returns:
        {ok, message_id, thread_id, to, subject, sent_at}

    Raises GmailError on auth / size / transport / Gmail API failure.
    """
    to      = (to or "").strip()
    subject = (subject or "").strip()
    body_text = body_text or ""
    if not to:
        raise GmailError("recipient (to) is required")
    if not subject:
        raise GmailError("subject is required")
    if "@" not in to:
        raise GmailError(f"recipient does not look like an email: {to!r}")

    access = _refresh_if_needed()
    sender = load_tokens().get("email_address") or "me"

    # Build the MIME message
    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEText(body_text, "plain", "utf-8")
    msg["To"]      = to
    msg["From"]    = sender if "@" in sender else ""
    msg["Subject"] = subject
    if cc:  msg["Cc"]  = cc
    if bcc: msg["Bcc"] = bcc

    raw_bytes = msg.as_bytes()
    if len(raw_bytes) > MAX_RAW_MESSAGE_BYTES:
        raise GmailError(
            f"Message size {len(raw_bytes)} exceeds {MAX_RAW_MESSAGE_BYTES}-byte cap"
        )
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")

    payload = json.dumps({"raw": raw_b64}).encode("utf-8")
    req = urllib.request.Request(
        GMAIL_SEND_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {access}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "User-Agent":    USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise GmailError(f"Gmail send failed: HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, OSError) as e:
        raise GmailError(f"Gmail send unreachable: {e}") from e

    record = {
        "ok":         True,
        "message_id": result.get("id"),
        "thread_id":  result.get("threadId"),
        "to":         to,
        "subject":    subject,
        "sent_at":    _now_iso(),
        "from":       sender,
    }
    _append_send_log(record)
    return record


def _append_send_log(record: dict) -> None:
    """Append-only log of every send. Local for audit; gitignored."""
    log = _safe_load(SEND_LOG_PATH, [])
    if not isinstance(log, list):
        log = []
    log.append(record)
    # Cap to last 1000 entries
    if len(log) > 1000:
        log = log[-1000:]
    _atomic_write(SEND_LOG_PATH, log)


def load_send_log(limit: int = 50) -> list[dict]:
    log = _safe_load(SEND_LOG_PATH, [])
    if not isinstance(log, list):
        return []
    return log[-max(1, min(limit, 1000)):]


def status() -> dict:
    """Single-call summary the UI uses to decide what to show."""
    configured = is_configured()
    connected  = is_connected()
    t          = load_tokens() if connected else {}
    return {
        "configured":     configured,
        "connected":      connected,
        "email_address":  t.get("email_address", ""),
        "connected_at":   t.get("connected_at", ""),
        "redirect_uri":   (load_client_config().get("redirect_uri")
                            if configured else DEFAULT_REDIRECT_URI),
        "scopes":         list(DEFAULT_SCOPES),
        "send_log_count": len(load_send_log(limit=1000)),
    }
