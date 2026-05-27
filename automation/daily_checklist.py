"""
daily_checklist.py
------------------
A short, human-friendly checklist for Topher's daily run-through.

Reuses `status._gather_status()` so the health / posts / review / today
fields stay consistent with `status.py`. The missing-hashtag aggregation
is duplicated locally (small read-only regex pass over pending drafts)
rather than importing the print-based `hashtag_cli.cmd_audit_missing`.

Usage:
    python3 automation/daily_checklist.py

Never writes files, never modifies the database, never calls OpenAI.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_manager
import memory_manager
import status as status_mod


# Same simple pattern other CLIs use; markdown headers like "# Topic"
# are safely ignored because the regex requires no space after '#'.
_HASHTAG_RE = re.compile(r"#[A-Za-z0-9_]+")


def _top_missing_hashtags(limit: int = 5) -> list[tuple[str, int]]:
    """
    Scan pending drafts, return up to `limit` hashtags that are not in
    the curated bank, sorted by use count (desc) then alphabetical.
    Same-tag-twice within one post counts once. Read-only.
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


def main() -> int:
    data = status_mod._gather_status()

    print("PartnerDeskAI Daily Checklist")
    print()

    # Top-level health line (separate from the four checklist items).
    health = data["health"]["status"]
    print(f"Health: {health}")
    if health != "PASS":
        print("    Run python3 automation/health_check.py")
    print()

    # 1) Today's drafts
    today = data["today"]
    print("[ ] Generate today's drafts")
    if today["exists"] and today["markdown_files"] > 0:
        print(f"    Status: already generated — {today['markdown_files']} markdown files found.")
    elif today["exists"]:
        print(f"    Status: folder exists but no markdown files yet.")
        print(f"    Command: python3 automation/daily_runner.py")
    else:
        print(f"    Status: today's folder ({today['folder']}) does not exist yet.")
        print(f"    Command: python3 automation/daily_runner.py")
    print()

    # 2) Approval queue
    review = data["review"]
    print("[ ] Review pending drafts")
    print(f"    Pending:  {review['pending_drafts']}")
    print(f"    Warnings: {review['drafts_with_warnings']}")
    print(f"    Clean:    {review['clean_drafts']}")
    if review["pending_drafts"] > 0:
        print(f"    Command: python3 automation/approval_cli.py")
    print()

    # 3) Hashtag cleanup
    print("[ ] Clean hashtag bank")
    missing = _top_missing_hashtags(limit=5)
    if not missing:
        print("    Curated hashtag bank looks clean — no missing tags in pending drafts.")
    else:
        print("    Top missing tags:")
        for tag, count in missing:
            unit = "use" if count == 1 else "uses"
            print(f"    {tag} — {count} {unit}")
        print("    Audit:   python3 automation/hashtag_cli.py audit-missing")
        print("    Absorb:  python3 automation/hashtag_cli.py absorb \"<tag>\" --platforms <...>")
    print()

    # 4) Status check (always shown as a closing inspection step)
    print("[ ] Run status check")
    print("    Command: python3 automation/status.py")
    print()

    print("Suggested next action:")
    print(data["next_action"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
