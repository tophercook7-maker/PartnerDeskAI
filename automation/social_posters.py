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
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
# Load .env from the project root so env vars resolve regardless of cwd.
load_dotenv(ROOT / ".env")

LINKEDIN_API_URL = "https://api.linkedin.com/rest/posts"
_LINKEDIN_DEFAULT_VERSION = "202605"


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
