"""
social_posters.py
-----------------
Manual-only public posting helpers. v4.1 ships LinkedIn only.

Every function returns a structured `{ok, message, platform, ...}` dict
so the Hub can render success/failure inline without try/except
scaffolding. Nothing in this module ever runs automatically — posting
only happens when an authenticated Hub endpoint calls in, and the Hub
UI already gates every call behind a browser confirm() that says the
post will publish publicly.

No new dependencies — uses stdlib `urllib` for the HTTPS POST.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
# Load .env from the project root so env vars resolve regardless of cwd.
load_dotenv(ROOT / ".env")

LINKEDIN_API_URL = "https://api.linkedin.com/rest/posts"
_LINKEDIN_DEFAULT_VERSION = "202605"

_FACEBOOK_GRAPH_VERSION = "v20.0"


def publish_linkedin_post(content: str) -> dict:
    """
    Publish a single LinkedIn post via the official Posts API.

    Returns a structured dict so callers can render success/failure
    without try/except. Shape:

        {"ok": True,  "platform": "linkedin",
         "message": "Posted to LinkedIn.", "post_urn": "..."}

        {"ok": False, "platform": "linkedin",
         "message": "LinkedIn posting is not configured."}

        {"ok": False, "platform": "linkedin",
         "message": "LinkedIn API error: HTTP 401 — ..."}

    Never raises — every error path is captured and returned in the dict.
    """
    token   = (os.getenv("LINKEDIN_ACCESS_TOKEN") or "").strip()
    author  = (os.getenv("LINKEDIN_AUTHOR_URN")   or "").strip()
    version = (os.getenv("LINKEDIN_VERSION") or _LINKEDIN_DEFAULT_VERSION).strip()

    if not token or not author:
        return {
            "ok": False,
            "platform": "linkedin",
            "message": "LinkedIn posting is not configured.",
        }

    if not content or not content.strip():
        return {
            "ok": False,
            "platform": "linkedin",
            "message": "Cannot publish empty content.",
        }

    payload = {
        "author": author,
        "commentary": content,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    req = urllib.request.Request(
        LINKEDIN_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {
                "ok": True,
                "platform": "linkedin",
                "message": "Posted to LinkedIn.",
                "status_code": resp.status,
                # LinkedIn returns the created URN in x-restli-id.
                "post_urn": resp.headers.get("x-restli-id")
                          or resp.headers.get("X-RestLi-Id"),
            }
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return {
            "ok": False,
            "platform": "linkedin",
            "message": f"LinkedIn API error: HTTP {e.code} — {err_body}",
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "platform": "linkedin",
            "message": f"LinkedIn API connection failed: {e.reason}",
        }
    except Exception as e:
        return {
            "ok": False,
            "platform": "linkedin",
            "message": f"LinkedIn posting failed: {type(e).__name__}: {e}",
        }


def publish_facebook_post(content: str) -> dict:
    """
    Publish a single Facebook Page post via the Graph API
    /{PAGE_ID}/feed endpoint. Same return-shape contract as
    publish_linkedin_post — always a structured dict, never raises.

    Required env:
      FACEBOOK_PAGE_ID            the numeric Page id
      FACEBOOK_PAGE_ACCESS_TOKEN  a long-lived Page access token

    Response shapes:
      {"ok": True,  "platform": "facebook",
       "message": "Posted to Facebook.", "id": "<pageid>_<postid>"}
      {"ok": False, "platform": "facebook",
       "message": "Facebook posting is not configured."}
      {"ok": False, "platform": "facebook",
       "message": "Facebook API error: HTTP 400 — ..."}
    """
    page_id = (os.getenv("FACEBOOK_PAGE_ID") or "").strip()
    token   = (os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") or "").strip()

    if not page_id or not token:
        return {
            "ok": False,
            "platform": "facebook",
            "message": "Facebook posting is not configured.",
        }

    if not content or not content.strip():
        return {
            "ok": False,
            "platform": "facebook",
            "message": "Cannot publish empty content.",
        }

    url = f"https://graph.facebook.com/{_FACEBOOK_GRAPH_VERSION}/{page_id}/feed"
    # Graph expects form-encoded params, not JSON.
    data = urllib.parse.urlencode({
        "message": content,
        "access_token": token,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body_text = resp.read().decode("utf-8", errors="replace")
            body_json: dict = {}
            try:
                body_json = json.loads(body_text)
            except (ValueError, json.JSONDecodeError):
                pass
            return {
                "ok": True,
                "platform": "facebook",
                "message": "Posted to Facebook.",
                "status_code": resp.status,
                "id": body_json.get("id"),
            }
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return {
            "ok": False,
            "platform": "facebook",
            "message": f"Facebook API error: HTTP {e.code} — {err_body}",
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "platform": "facebook",
            "message": f"Facebook API connection failed: {e.reason}",
        }
    except Exception as e:
        return {
            "ok": False,
            "platform": "facebook",
            "message": f"Facebook posting failed: {type(e).__name__}: {e}",
        }
