"""
status.py
---------
Read-only operational dashboard for PartnerDeskAI.

Shows: overall health, post counts, pending-review summary, memory bank
sizes, today's draft folder, the latest log file, and a suggested next
action. Reuses the pure `check_*` helpers from `health_check.py` so the
PASS/FAIL signal stays consistent across both commands.

Usage:
    python3 automation/status.py            # human-readable
    python3 automation/status.py --json     # machine-readable JSON (no other output)

Never writes files, never modifies the database, never calls OpenAI.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Make sibling modules importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_manager
import health_check
import memory_manager


ROOT = Path(__file__).resolve().parent.parent

# Same simple pattern other CLIs use. Markdown headers like "# Topic" are
# safely ignored because the regex requires no space after '#'.
_HASHTAG_RE = re.compile(r"#[A-Za-z0-9_]+")


def _top_missing_hashtags(limit: int = 5) -> list[tuple[str, int]]:
    """
    Read-only: scan pending drafts, return up to `limit` hashtags that are
    not in the curated bank, sorted by use count (desc) then alphabetical.
    Same-tag-twice within one post counts once. Shared by status.py
    (boolean: "any missing?") and daily_checklist.py (top-5 display).
    """
    bank_lower = {
        t.get("tag", "").lower()
        for t in memory_manager.load_hashtag_bank().get("hashtags", [])
    }
    counts: dict[str, int] = {}
    for draft in approval_manager.list_pending():
        content = draft.get("content") or ""
        seen_in_post: set[str] = set()
        for tag in _HASHTAG_RE.findall(content):
            lower = tag.lower()
            if lower in bank_lower or lower in seen_in_post:
                continue
            seen_in_post.add(lower)
            counts[lower] = counts.get(lower, 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:limit]


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


def _gather_status() -> dict:
    """
    Build the canonical status data. Pure function — no printing or I/O
    beyond what the existing read-only helpers do.
    """
    health_ok, errors, pending, warned = _gather_health()
    counts = approval_manager.status_counts()
    folder, today_exists, md_count = _today_folder_info()
    latest = _latest_log()
    # Compute the top-5 list once and derive both `review.top_missing_hashtags`
    # and the `checklist.clean_hashtags` boolean from it. Scanning is the same
    # cost as limit=1, so we don't pay extra by asking for the list.
    top_missing = _top_missing_hashtags(limit=5)
    any_missing_hashtags = bool(top_missing)

    return {
        "health": {
            "status":   "PASS" if health_ok else "FAIL",
            "failures": errors,
        },
        "posts": {
            "approved": counts.get("approved", 0),
            "draft":    counts.get("draft", 0),
            "rejected": counts.get("rejected", 0),
        },
        "review": {
            "pending_drafts":       pending,
            "drafts_with_warnings": warned,
            "clean_drafts":         max(0, pending - warned),
            "top_missing_hashtags": [
                {"tag": tag, "uses": uses} for tag, uses in top_missing
            ],
        },
        "memory_banks": {
            "topics":   _bank_count(memory_manager.TOPIC_BANK_PATH,   memory_manager.load_topic_bank,   "topics"),
            "ctas":     _bank_count(memory_manager.CTA_BANK_PATH,     memory_manager.load_cta_bank,     "ctas"),
            "offers":   _bank_count(memory_manager.OFFER_BANK_PATH,   memory_manager.load_offer_bank,   "offers"),
            "hashtags": _bank_count(memory_manager.HASHTAG_BANK_PATH, memory_manager.load_hashtag_bank, "hashtags"),
        },
        "today": {
            "folder":         folder.relative_to(ROOT).as_posix(),
            "exists":         today_exists,
            "markdown_files": md_count,
        },
        "latest_log": (
            {
                "path":     latest[0].relative_to(ROOT).as_posix(),
                "modified": latest[1],
            }
            if latest else None
        ),
        "next_action": _next_action(health_ok, pending, today_exists),
        "checklist": {
            "generate_drafts": today_exists and md_count >= 4,
            "review_drafts":   pending == 0,
            "clean_hashtags":  not any_missing_hashtags,
            "status_pass":     health_ok,
        },
    }


def _render_human(data: dict) -> None:
    """Reproduce the v1.3 human-readable layout from the gathered data dict."""
    print("PartnerDeskAI Status")
    print()
    print(f"Health: {data['health']['status']}")

    _print_section("Posts")
    for k in ("approved", "draft", "rejected"):
        print(_fmt(f"{k}:", data["posts"][k], label_width=10))

    _print_section("Review")
    review = data["review"]
    print(_fmt("pending drafts:",       review["pending_drafts"]))
    print(_fmt("drafts with warnings:", review["drafts_with_warnings"]))
    print(_fmt("clean drafts:",         review["clean_drafts"]))

    _print_section("Memory banks")
    bank_labels = [("topics:", "topics"), ("CTAs:", "ctas"),
                   ("offers:", "offers"), ("hashtags:", "hashtags")]
    for label, key in bank_labels:
        n = data["memory_banks"][key]
        print(_fmt(label, "missing" if n is None else n, label_width=10))

    today = data["today"]
    _print_section("Today")
    if today["exists"]:
        print(_fmt("folder:",         today["folder"],         label_width=16))
        print(_fmt("markdown files:", today["markdown_files"], label_width=16))
    else:
        print(_fmt("folder:", f"{today['folder']} (not yet created)", label_width=16))

    log = data["latest_log"]
    _print_section("Latest log")
    if log is None:
        print("  (no log files yet)")
    else:
        print(log["path"])
        print(f"modified: {log['modified']}")

    _print_section("Next action")
    print(data["next_action"])


def main(argv: list[str]) -> int:
    as_json = "--json" in argv[1:]
    data = _gather_status()
    if as_json:
        # JSON-only output: no preamble, no trailing text, valid JSON.
        print(json.dumps(data, indent=2))
    else:
        _render_human(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
