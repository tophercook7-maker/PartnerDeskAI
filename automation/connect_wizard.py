"""
connect_wizard.py
-----------------
Guided setup helper for PartnerDeskAI publishing connections. Never auto-
logs in, never scrapes credentials, never reads cookies, never bypasses
OAuth, never prints existing .env values. Opens the relevant setup pages
in the user's default browser when asked, and reports which env keys are
still missing.

Usage:
    python3 automation/connect_wizard.py          # interactive menu
    python3 automation/connect_wizard.py status   # one-shot status report

Safety contract:
    - Reads env vars only to report present/missing — never echoes values.
    - Uses stdlib `webbrowser` to launch URLs; no scripted login.
    - Never modifies .env automatically. Topher edits the file himself.
    - Never makes outbound API calls to social networks.
    - Never posts anything publicly.
"""

import os
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

import social_posters  # sibling in automation/


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


# Local copy of the platform list. Mirrors hub/app.py's
# _PLATFORM_ENV_REQUIREMENTS so the wizard stays self-contained — no need
# to import the FastAPI app from the CLI.
PLATFORM_CONFIGS = [
    {
        "key": "linkedin",
        "name": "LinkedIn",
        "env_keys": ["LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_URN"],
        "setup_urls": ["https://www.linkedin.com/developers/"],
        "notes": (
            "Create a LinkedIn Developer App, request the 'w_member_social' "
            "scope, and generate a 3-legged OAuth access token. The author "
            "URN is your member URN, e.g. urn:li:person:XXXX."
        ),
    },
    {
        "key": "facebook",
        "name": "Facebook",
        "env_keys": ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN"],
        "setup_urls": ["https://developers.facebook.com/"],
        "notes": (
            "Create a Meta App, add your Facebook Page, and generate a "
            "long-lived Page Access Token with the 'pages_manage_posts' "
            "permission. Page ID is visible in your Page's About section."
        ),
    },
    {
        "key": "gbp",
        "name": "Google Business Profile",
        "env_keys": ["GBP_ACCESS_TOKEN", "GBP_ACCOUNT_ID", "GBP_LOCATION_ID"],
        "setup_urls": [
            "https://business.google.com/",
            "https://console.cloud.google.com/",
        ],
        "notes": (
            "Enable the Business Profile API in Google Cloud Console, "
            "create OAuth 2.0 credentials, and exchange the OAuth code "
            "for an access token. Account & location ids come from the "
            "/accounts and /locations endpoints."
        ),
    },
    {
        "key": "instagram",
        "name": "Instagram",
        "env_keys": ["INSTAGRAM_BUSINESS_ACCOUNT_ID", "INSTAGRAM_ACCESS_TOKEN"],
        "setup_urls": ["https://developers.facebook.com/"],
        "notes": (
            "Instagram publishing uses the same Meta Graph API as Facebook. "
            "Connect an Instagram Business or Creator account to a Facebook "
            "Page, then use a Page Access Token (same long-lived token as "
            "Facebook is fine)."
        ),
    },
]


# --- Status (never returns values, only presence) -------------------------

def _key_present(env_key: str) -> bool:
    """True iff the env value is non-empty after stripping whitespace."""
    return bool((os.getenv(env_key) or "").strip())


def _platform_status(platform: dict) -> dict:
    missing = [k for k in platform["env_keys"] if not _key_present(k)]
    return {
        "status":  "connected" if not missing else "not_configured",
        "missing": missing,
    }


def cmd_status() -> int:
    """One-shot status report. Same shape as the Hub's /api/connections."""
    print("PartnerDesk Connections")
    print()
    for p in PLATFORM_CONFIGS:
        s = _platform_status(p)
        label = "Connected" if s["status"] == "connected" else "Missing setup"
        print(f"  {p['name']:<26} {label}")
        if s["missing"]:
            print(f"      missing: {', '.join(s['missing'])}")
    return 0


# --- Interactive menu -----------------------------------------------------

def _print_platform_detail(p: dict) -> None:
    s = _platform_status(p)
    label = "Connected" if s["status"] == "connected" else "Missing setup"
    print()
    print(f"=== {p['name']} ===")
    print(f"  Status: {label}")
    print(f"  Required env keys:")
    for k in p["env_keys"]:
        marker = "[OK]" if _key_present(k) else "[--]"
        print(f"    {marker} {k}")
    print(f"  Setup URL{'s' if len(p['setup_urls']) > 1 else ''}:")
    for url in p["setup_urls"]:
        print(f"    {url}")
    print(f"  Notes: {p['notes']}")


def _ask(prompt: str) -> str:
    """Wrap input() with a clean Ctrl-C / EOF exit path."""
    try:
        return input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def _offer_browser_open(urls: list[str]) -> None:
    for url in urls:
        ans = _ask(f"  Open {url} in your browser? [y/N]: ")
        if ans != "y":
            continue
        try:
            opened = webbrowser.open(url)
        except Exception as e:
            print(f"  Could not open browser: {e}")
            continue
        if opened:
            print(f"  Opened {url}.")
        else:
            print(f"  Browser did not open. Visit manually: {url}")


def _menu() -> int:
    while True:
        print()
        print("PartnerDesk Connection Wizard")
        print()
        for i, p in enumerate(PLATFORM_CONFIGS, start=1):
            print(f"  {i}. {p['name']}")
        print(f"  {len(PLATFORM_CONFIGS) + 1}. Check current connections")
        print(f"  q. Quit")
        print()
        choice = _ask("Choose: ")
        if choice in ("q", "quit", "exit", ""):
            return 0
        if choice == str(len(PLATFORM_CONFIGS) + 1):
            print()
            cmd_status()
            continue
        try:
            idx = int(choice)
        except ValueError:
            print("  Please enter a number from the menu.")
            continue
        if not 1 <= idx <= len(PLATFORM_CONFIGS):
            print("  Out of range.")
            continue
        p = PLATFORM_CONFIGS[idx - 1]
        _print_platform_detail(p)
        _offer_browser_open(p["setup_urls"])
        print()
        print("  When you have your credentials, edit .env in the project")
        print("  root and add the missing keys listed above. The Hub's")
        print("  Connections card refreshes on the next page load.")


# --- Verify (read-only API probe) ----------------------------------------

# Use the same lowercase-with-underscores keys the Hub's
# /api/connections/verify endpoint accepts, so the two surfaces are
# always in sync.
_VERIFIERS = {
    "linkedin":                ("LinkedIn",                social_posters.verify_linkedin_connection),
    "facebook":                ("Facebook",                social_posters.verify_facebook_connection),
    "instagram":               ("Instagram",               social_posters.verify_instagram_connection),
    "google_business_profile": ("Google Business Profile", social_posters.verify_google_business_profile_connection),
}


def cmd_verify(platforms: list[str]) -> int:
    """
    Run read-only verification probes. With no platform names, verifies
    all four. With names ("facebook", "google_business_profile", …),
    verifies just those. Never publishes, never prints tokens.
    """
    if not platforms:
        targets = list(_VERIFIERS.keys())
    else:
        targets = []
        for p in platforms:
            key = p.strip().lower().replace(" ", "_").replace("-", "_")
            if key not in _VERIFIERS:
                print(f"Unknown platform: {p}")
                print(f"Allowed: {sorted(_VERIFIERS)}")
                return 2
            targets.append(key)

    print("PartnerDesk Connection Verification")
    print()
    for key in targets:
        label, verifier = _VERIFIERS[key]
        result = verifier()
        marker = "[OK]" if result.get("ok") else "[--]"
        print(f"  {marker} {label}: {result.get('message','')}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "status":
        return cmd_status()
    if len(argv) > 1 and argv[1] == "verify":
        return cmd_verify(argv[2:])
    return _menu()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
