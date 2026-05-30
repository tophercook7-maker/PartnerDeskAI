#!/usr/bin/env python3
"""
setup_env.py
------------
Interactive .env setup wizard for PartnerDeskAI. Prompts only for
missing values, masks existing secrets, never echoes new secret values
after entry, and writes atomically via env_writer (which makes a
.env.bak snapshot per write and preserves file mode).

Safety contract:
    - NEVER prints any secret VALUE — only key names, presence, and
      masked previews (e.g. sk-XXXX...YYYY).
    - Existing non-empty values require explicit confirm before being
      overwritten.
    - .env is NEVER committed (already in .gitignore).
    - No OpenAI calls. No posting. No DB writes.
    - The only filesystem write target is .env (and .env.bak created
      by env_writer).

Usage:
    python3 automation/setup_env.py                   # walk all sections
    python3 automation/setup_env.py status            # report only — no prompts
    python3 automation/setup_env.py core              # walk one section
    python3 automation/setup_env.py linkedin
    python3 automation/setup_env.py facebook
    python3 automation/setup_env.py instagram
    python3 automation/setup_env.py gbp
"""

from pathlib import Path
import getpass
import shutil
import sys


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

sys.path.insert(0, str(ROOT / "automation"))
import env_writer  # noqa: E402


# Per-variable config: (KEY, is_secret, default_or_None)
# - is_secret=True   → entered via getpass (no echo); always masked in output
# - default          → suggested in prompt; accepted on empty input
SECTIONS: list[tuple[str, str, list[tuple[str, bool, str | None]]]] = [
    ("core", "Core", [
        ("OPENAI_API_KEY",                True,  None),
        ("OPENAI_MODEL",                  False, "gpt-4.1-mini"),
    ]),
    ("linkedin", "LinkedIn", [
        ("LINKEDIN_CLIENT_ID",            False, None),
        ("LINKEDIN_CLIENT_SECRET",        True,  None),
        ("LINKEDIN_REDIRECT_URI",         False,
                            "http://localhost:8787/api/oauth/linkedin/callback"),
        ("LINKEDIN_ACCESS_TOKEN",         True,  None),
        ("LINKEDIN_AUTHOR_URN",           False, None),
        ("LINKEDIN_VERSION",              False, "202605"),
    ]),
    ("facebook", "Facebook", [
        ("FACEBOOK_PAGE_ID",              False, None),
        ("FACEBOOK_PAGE_ACCESS_TOKEN",    True,  None),
    ]),
    ("instagram", "Instagram", [
        ("INSTAGRAM_BUSINESS_ACCOUNT_ID", False, None),
        ("INSTAGRAM_ACCESS_TOKEN",        True,  None),
    ]),
    ("gbp", "Google Business Profile", [
        ("GBP_ACCESS_TOKEN",              True,  None),
        ("GBP_ACCOUNT_ID",                False, None),
        ("GBP_LOCATION_ID",               False, None),
        ("GBP_LANGUAGE_CODE",             False, "en-US"),
        ("GBP_ACTION_TYPE",               False, "LEARN_MORE"),
        ("GBP_ACTION_URL",                False, "https://mixedmakershop.com"),
    ]),
]


# --- Helpers --------------------------------------------------------------

def _mask(value: str) -> str:
    """Mask a secret for display. Returns '(not set)' for empty values."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _read_env(path: Path) -> dict[str, str]:
    """Parse .env into a dict. Comments + blanks are ignored."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq <= 0:
            continue
        key = line[:eq].strip()
        val = line[eq + 1:].strip()
        # Strip surrounding quotes if present.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        out[key] = val
    return out


def _ensure_env_exists() -> bool:
    """
    Create .env from .env.example if missing.
    Returns True if a fresh .env was just created, False if it already existed.
    """
    if ENV_PATH.is_file():
        return False
    if not ENV_EXAMPLE.is_file():
        print(f"ERROR: neither {ENV_PATH.name} nor {ENV_EXAMPLE.name} exists.")
        print(f"       Cannot bootstrap .env. Create {ENV_EXAMPLE.name} first.")
        sys.exit(1)
    shutil.copy2(ENV_EXAMPLE, ENV_PATH)
    print(f"Created {ENV_PATH} from {ENV_EXAMPLE.name}.")
    print()
    return True


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    """[Y/n] / [y/N] prompt. Empty input takes the default."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


def _prompt_value(key: str, is_secret: bool, default: str | None) -> str | None:
    """
    Prompt for a new value. Returns None if user skips.
    Empty input + default present → returns the default.
    Empty input + no default → returns None (skip).
    """
    label = f"  {key}"
    if default:
        label += f"  [{default}]"
    label += ": "
    try:
        if is_secret:
            val = getpass.getpass(label)
        else:
            val = input(label)
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    val = val.strip()
    if not val:
        if default is not None:
            return default
        return None
    return val


# --- Status report --------------------------------------------------------

def cmd_status() -> int:
    """One-shot status report. No prompts. Masks secrets."""
    env = _read_env(ENV_PATH)
    print("PartnerDeskAI .env status")
    print(f"  path: {ENV_PATH}")
    print(f"  exists: {ENV_PATH.is_file()}")
    print()
    total = 0
    set_count = 0
    for _slug, title, vars_ in SECTIONS:
        print(f"{title}")
        for key, is_secret, default in vars_:
            total += 1
            current = env.get(key, "")
            if current:
                set_count += 1
                if is_secret:
                    display = _mask(current)
                else:
                    # Non-secrets display in full, but mark defaults
                    display = current
                    if default and current == default:
                        display += "  (default)"
                print(f"  ✓ {key:<32} {display}")
            else:
                hint = f"  [default: {default}]" if default else ""
                print(f"  ✗ {key:<32} (not set){hint}")
        print()
    print(f"Summary: {set_count}/{total} keys set.")
    return 0


# --- Interactive walk -----------------------------------------------------

def _walk_section(section_slug: str, env: dict[str, str]) -> dict[str, str]:
    """
    Walk one section interactively. Returns a dict of {key: new_value}
    containing only keys the user actually entered or accepted defaults
    for. Existing values that the user opted to keep are NOT included.
    """
    section = None
    for slug, title, vars_ in SECTIONS:
        if slug == section_slug:
            section = (slug, title, vars_); break
    if section is None:
        print(f"Unknown section: {section_slug}")
        print(f"Valid: {', '.join(s[0] for s in SECTIONS)}")
        sys.exit(2)

    _slug, title, vars_ = section
    print(f"=== {title} ===")
    updates: dict[str, str] = {}
    for key, is_secret, default in vars_:
        current = env.get(key, "")
        if current:
            # Existing non-empty value: show masked + ask confirm to overwrite.
            display = _mask(current) if is_secret else current
            print(f"  {key} is set ({display})")
            if not _ask_yes_no("  Replace?", default=False):
                continue
            # User wants to replace — fall through to prompt.
        new_val = _prompt_value(key, is_secret, default)
        if new_val is None:
            # User skipped (empty input, no default).
            continue
        updates[key] = new_val
        # Confirmation line — NEVER echoes the secret value.
        if is_secret:
            print(f"    → {key} set (length {len(new_val)})")
        else:
            print(f"    → {key} = {new_val}")
    print()
    return updates


def cmd_walk(only_section: str | None = None) -> int:
    """Walk all sections (or just one). Writes atomically at the end."""
    _ensure_env_exists()
    env = _read_env(ENV_PATH)
    all_updates: dict[str, str] = {}
    sections_to_walk = (
        [only_section] if only_section
        else [s[0] for s in SECTIONS]
    )
    print()
    for slug in sections_to_walk:
        all_updates.update(_walk_section(slug, env))

    if not all_updates:
        print("No changes to write.")
        cmd_status()
        return 0

    print(f"About to write {len(all_updates)} key(s) to {ENV_PATH}.")
    print(f"  keys: {', '.join(sorted(all_updates))}")
    if not _ask_yes_no("Proceed?", default=True):
        print("Aborted. No changes written.")
        return 1

    result = env_writer.update_env(ENV_PATH, all_updates)
    print()
    print(f"Wrote .env (backup: {Path(result['backup']).name}).")
    print(f"  added:    {', '.join(result['added']) or '(none)'}")
    print(f"  replaced: {', '.join(result['replaced']) or '(none)'}")
    print()
    cmd_status()
    return 0


# --- CLI dispatcher -------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) <= 1:
        return cmd_walk()
    cmd = argv[1].lower()
    if cmd == "status":
        return cmd_status()
    if cmd in (s[0] for s in SECTIONS):
        return cmd_walk(only_section=cmd)
    print(f"Usage: python3 {Path(argv[0]).name} [status|core|linkedin|facebook|instagram|gbp]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
