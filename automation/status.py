"""
status.py
---------
Read-only operational dashboard for PartnerDeskAI.

Shows: overall health, post counts, pending-review summary, memory bank
sizes, today's draft folder, the latest log file, and a suggested next
action. Reuses the pure `check_*` helpers from `health_check.py` so the
PASS/FAIL signal stays consistent across both commands.

Usage:
    python3 automation/status.py

Never writes files, never modifies the database, never calls OpenAI.
"""

import sys
from datetime import datetime
from pathlib import Path

# Make sibling modules importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_manager
import health_check
import memory_manager


ROOT = Path(__file__).resolve().parent.parent


# --- Data gathering --------------------------------------------------------

def _gather_health() -> tuple[bool, list[str], int, int]:
    """
    Run every check from health_check (no printing).
    Returns (overall_ok, all_errors, pending_count, warnings_count).
    """
    errors: list[str] = []
    errors += health_check.check_folders()
    errors += health_check.check_files()
    errors += health_check.check_env()
    errors += health_check.check_database()
    errors += health_check.check_banks()
    queue_errors, pending_count, warnings_count = health_check.check_approval_queue()
    errors += queue_errors
    return (not errors, errors, pending_count, warnings_count)


def _bank_count(path: Path, loader, key: str) -> int | None:
    """Length of a bank's main list, or None if the file is missing."""
    if not path.is_file():
        return None
    return len(loader().get(key, []))


def _today_folder_info() -> tuple[Path, bool, int]:
    """Return (folder_path, exists, markdown_file_count) for today."""
    folder = ROOT / "daily_posts" / datetime.now().strftime("%Y-%m-%d")
    if not folder.is_dir():
        return folder, False, 0
    md_count = sum(1 for f in folder.iterdir() if f.is_file() and f.suffix == ".md")
    return folder, True, md_count


def _latest_log() -> tuple[Path, str] | None:
    """Most-recently-modified file in logs/, with its mtime string."""
    logs_dir = ROOT / "logs"
    if not logs_dir.is_dir():
        return None
    log_files = [p for p in logs_dir.glob("*.log") if p.is_file()]
    if not log_files:
        return None
    latest = max(log_files, key=lambda p: p.stat().st_mtime)
    mtime = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return latest, mtime


def _next_action(health_ok: bool, pending: int, today_exists: bool) -> str:
    """Suggested follow-up command for the operator."""
    if not health_ok:
        return "Run python3 automation/health_check.py"
    if pending > 0:
        return "Review drafts: python3 automation/approval_cli.py"
    if not today_exists:
        return "Generate drafts: python3 automation/daily_runner.py"
    return "System looks ready."


# --- Render ----------------------------------------------------------------

def _fmt(label: str, value, label_width: int = 22) -> str:
    return f"{label:<{label_width}}{value}"


def _print_section(title: str) -> None:
    print()
    print(f"{title}:")


def main() -> int:
    print("PartnerDeskAI Status")
    print()

    health_ok, _errors, pending, warned = _gather_health()
    print(f"Health: {'PASS' if health_ok else 'FAIL'}")

    counts = approval_manager.status_counts()
    _print_section("Posts")
    for k in ("approved", "draft", "rejected"):
        print(_fmt(f"{k}:", counts.get(k, 0), label_width=10))

    _print_section("Review")
    print(_fmt("pending drafts:",       pending))
    print(_fmt("drafts with warnings:", warned))
    print(_fmt("clean drafts:",         max(0, pending - warned)))

    _print_section("Memory banks")
    bank_specs = [
        ("topics:",   memory_manager.TOPIC_BANK_PATH,   memory_manager.load_topic_bank,   "topics"),
        ("CTAs:",     memory_manager.CTA_BANK_PATH,     memory_manager.load_cta_bank,     "ctas"),
        ("offers:",   memory_manager.OFFER_BANK_PATH,   memory_manager.load_offer_bank,   "offers"),
        ("hashtags:", memory_manager.HASHTAG_BANK_PATH, memory_manager.load_hashtag_bank, "hashtags"),
    ]
    for label, path, loader, key in bank_specs:
        n = _bank_count(path, loader, key)
        print(_fmt(label, "missing" if n is None else n, label_width=10))

    folder, today_exists, md_count = _today_folder_info()
    _print_section("Today")
    rel = folder.relative_to(ROOT)
    if today_exists:
        print(_fmt("folder:",         rel, label_width=16))
        print(_fmt("markdown files:", md_count, label_width=16))
    else:
        print(_fmt("folder:", f"{rel} (not yet created)", label_width=16))

    latest = _latest_log()
    _print_section("Latest log")
    if latest is None:
        print("  (no log files yet)")
    else:
        log_path, mtime = latest
        print(f"{log_path.relative_to(ROOT)}")
        print(f"modified: {mtime}")

    _print_section("Next action")
    print(_next_action(health_ok, pending, today_exists))
    return 0


if __name__ == "__main__":
    sys.exit(main())
