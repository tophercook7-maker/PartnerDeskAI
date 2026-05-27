"""
health_check.py
---------------
Read-only verification that PartnerDeskAI is set up correctly for a
daily run. Checks folders, files, the .env file, the SQLite database
schema, the four rotation banks, and the current approval queue.

Usage:
    python3 automation/health_check.py

Exit codes:
    0  all checks passed
    1  at least one check failed

This script never modifies files, never writes to the database, and
never calls OpenAI.
"""

import sqlite3
import sys
from pathlib import Path

# Make sibling modules importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_cli  # for _audit_draft only; importing has no side effects
import approval_manager
import memory_manager


ROOT = Path(__file__).resolve().parent.parent

# Items we expect to exist for a healthy install.
REQUIRED_FOLDERS = [
    "automation",
    "memory",
    "database",
    "daily_posts",
    "approval_queue",
    "logs",
    "partners/parker_promo",
]

REQUIRED_FILES = [
    ".env",
    "memory/business_profile.md",
    "memory/topic_bank.json",
    "memory/cta_bank.json",
    "memory/offer_bank.json",
    "memory/hashtag_bank.json",
    "partners/parker_promo/parker_promo_prompt.md",
    "partners/parker_promo/posting_schedule.json",
    "database/partnerdesk.db",
    "automation/daily_runner.py",
]

REQUIRED_ENV_VARS = ["OPENAI_API_KEY", "OPENAI_MODEL"]
REQUIRED_DB_TABLES = ["posts", "post_history"]


# --- Individual checks -----------------------------------------------------

def check_folders() -> list[str]:
    return [
        f"Missing folder: {d}"
        for d in REQUIRED_FOLDERS
        if not (ROOT / d).is_dir()
    ]


def check_files() -> list[str]:
    return [
        f"Missing file: {f}"
        for f in REQUIRED_FILES
        if not (ROOT / f).is_file()
    ]


def _read_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser — no os.environ side effects, no dotenv import."""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def check_env() -> list[str]:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return [".env file missing"]
    values = _read_dotenv(env_path)
    errors: list[str] = []
    for key in REQUIRED_ENV_VARS:
        if not values.get(key):
            errors.append(f"{key} is not set in .env")
    return errors


def check_database() -> list[str]:
    db_path = ROOT / "database" / "partnerdesk.db"
    if not db_path.is_file():
        return ["database/partnerdesk.db missing"]
    try:
        conn = sqlite3.connect(db_path)
        try:
            existing = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
    except sqlite3.Error as e:
        return [f"SQLite error: {e}"]
    return [f"Missing DB table: {t}" for t in REQUIRED_DB_TABLES if t not in existing]


def check_banks() -> list[str]:
    """
    Each bank must (a) exist on disk and (b) have at least one entry.
    We pre-check the file before calling the loader so we don't trigger
    memory_manager's auto-seed behavior on a missing bank.
    """
    banks = [
        (memory_manager.TOPIC_BANK_PATH,   memory_manager.load_topic_bank,   "topics",   "topic bank"),
        (memory_manager.CTA_BANK_PATH,     memory_manager.load_cta_bank,     "ctas",     "CTA bank"),
        (memory_manager.OFFER_BANK_PATH,   memory_manager.load_offer_bank,   "offers",   "offer bank"),
        (memory_manager.HASHTAG_BANK_PATH, memory_manager.load_hashtag_bank, "hashtags", "hashtag bank"),
    ]
    errors: list[str] = []
    for path, loader, key, label in banks:
        if not path.is_file():
            errors.append(f"{label} file missing: {path.relative_to(ROOT)}")
            continue
        bank = loader()
        if not bank.get(key):
            errors.append(f"{label} has no entries")
    return errors


def check_approval_queue() -> tuple[list[str], int, int]:
    """
    Return (errors, pending_count, drafts_with_warnings).
    Counts are 0 / 0 if errors prevented the read.
    """
    try:
        pending = approval_manager.list_pending()
    except Exception as e:
        return [f"Failed to read approval queue: {e}"], 0, 0
    with_warnings = sum(1 for d in pending if approval_cli._audit_draft(d))
    return [], len(pending), with_warnings


# --- Driver ---------------------------------------------------------------

def _report(label: str, errors: list[str]) -> bool:
    """Print one section's status. Returns True if it passed."""
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        return False
    print(f"[OK] {label}")
    return True


def main() -> int:
    print("PartnerDeskAI Health Check")
    print()

    all_ok = True
    all_ok &= _report("Required folders",     check_folders())
    all_ok &= _report("Required files",       check_files())
    all_ok &= _report("Environment variables", check_env())
    all_ok &= _report("SQLite database",      check_database())
    all_ok &= _report("Memory banks",         check_banks())

    queue_errors, pending_count, warned_count = check_approval_queue()
    all_ok &= _report("Approval queue", queue_errors)

    if not queue_errors:
        print()
        print(f"Pending drafts: {pending_count}")
        print(f"Drafts with warnings: {warned_count}")

    print()
    print(f"Status: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
