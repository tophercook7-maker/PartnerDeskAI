"""
linkedin_oauth.py
-----------------
LinkedIn-specific OAuth 2.0 helpers. Two responsibilities:

    1. Build the authorization URL the user is redirected to.
    2. Exchange the authorization code returned in the callback for an
       access token (POST to https://www.linkedin.com/oauth/v2/accessToken).

Safety contract:
    - NEVER prints / returns the client_secret or any access token.
    - The client_secret is sent ONLY in the POST body of the token
      exchange, never in a URL.
    - Outbound network is limited to two LinkedIn endpoints:
        https://www.linkedin.com/oauth/v2/authorization (redirect target)
        https://www.linkedin.com/oauth/v2/accessToken   (POST)
    - This module is read-only against the environment; it does NOT
      touch .env. The Hub endpoint orchestrates env_writer.update_env
      after this module returns the token.

Scopes requested:
    w_member_social   — required for the existing publish_linkedin_post
                        flow. We do NOT request openid / profile here;
                        LINKEDIN_AUTHOR_URN must still be set manually
                        (matches existing connect_wizard guidance).
"""

from urllib.parse import urlencode
import json
import os
import urllib.error
import urllib.request


AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL         = "https://www.linkedin.com/oauth/v2/accessToken"
SCOPE             = "w_member_social"


class LinkedInOAuthError(Exception):
    """Raised when LinkedIn returns an error or env vars are missing."""


def _required_env() -> tuple[str, str, str]:
    """
    Returns (client_id, client_secret, redirect_uri) or raises
    LinkedInOAuthError with a message safe to surface to the user.
    Values are read but NEVER logged or echoed.
    """
    cid = (os.getenv("LINKEDIN_CLIENT_ID")     or "").strip()
    sec = (os.getenv("LINKEDIN_CLIENT_SECRET") or "").strip()
    uri = (os.getenv("LINKEDIN_REDIRECT_URI")  or "").strip()
    missing = [k for k, v in
               [("LINKEDIN_CLIENT_ID", cid),
                ("LINKEDIN_CLIENT_SECRET", sec),
                ("LINKEDIN_REDIRECT_URI", uri)] if not v]
    if missing:
        raise LinkedInOAuthError(
            "Missing required env vars: " + ", ".join(missing)
        )
    return cid, sec, uri


def build_authorization_url(state: str) -> str:
    """
    Build the LinkedIn authorization URL the user is redirected to.
    `state` is the CSRF token that LinkedIn echoes back to the callback
    so we can verify the response wasn't forged.
    """
    cid, _sec, uri = _required_env()
    params = {
        "response_type": "code",
        "client_id":     cid,
        "redirect_uri":  uri,
        "state":         state,
        "scope":         SCOPE,
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str, timeout: float = 15.0) -> dict:
    """
    Exchange `code` (from the callback's ?code= query param) for an
    access token. Returns the parsed LinkedIn response dict — which
    includes the access_token; the CALLER is responsible for handing
    it to env_writer and never logging it.

    Raises LinkedInOAuthError on missing env, non-200 response, or
    malformed JSON.
    """
    cid, sec, uri = _required_env()
    # POST body is x-www-form-urlencoded. Secret goes in the body,
    # never in the URL.
    body = urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  uri,
        "client_id":     cid,
        "client_secret": sec,
    }).encode("ascii")

    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept":       "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # LinkedIn includes a JSON error body. Surface the error name
        # but NOT the request (which contains the secret).
        try:
            err = json.loads(e.read().decode("utf-8", errors="replace"))
            msg = err.get("error_description") or err.get("error") or str(e)
        except Exception:
            msg = f"HTTP {e.code}"
        raise LinkedInOAuthError(f"LinkedIn token exchange failed: {msg}")
    except urllib.error.URLError as e:
        raise LinkedInOAuthError(f"LinkedIn token exchange network error: {e.reason}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise LinkedInOAuthError("LinkedIn returned non-JSON token response.")

    if "access_token" not in data:
        # LinkedIn occasionally returns 200 with an error payload.
        raise LinkedInOAuthError(
            "LinkedIn response missing access_token: "
            + (data.get("error_description") or data.get("error") or "(unknown)")
        )
    return data
