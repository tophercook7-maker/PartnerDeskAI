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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import status as status_mod
# Shared helper for "what missing hashtags are in pending drafts?" lives in
# status.py so the boolean (status.checklist.clean_hashtags) and the top-5
# display here always agree.
from status import _top_missing_hashtags


def _box(complete: bool) -> str:
    """Render a checklist marker: [x] when done, [ ] when action still needed."""
    return "[x]" if complete else "[ ]"


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

    # Read the canonical completion state from status.py's gathered dict so
    # the checklist boxes here and the `checklist` block in status --json
    # always agree. The top-5 missing-tag list below is still computed
    # locally because it's a display concern, not a state concern.
    today = data["today"]
    review = data["review"]
    missing = _top_missing_hashtags(limit=5)

    checklist = data["checklist"]
    generated_done = checklist["generate_drafts"]
    review_done    = checklist["review_drafts"]
    hashtags_done  = checklist["clean_hashtags"]
    status_done    = checklist["status_pass"]

    # 1) Today's drafts
    print(f"{_box(generated_done)} Generate today's drafts")
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
    print(f"{_box(review_done)} Review pending drafts")
    print(f"    Pending:  {review['pending_drafts']}")
    print(f"    Warnings: {review['drafts_with_warnings']}")
    print(f"    Clean:    {review['clean_drafts']}")
    if review["pending_drafts"] > 0:
        print(f"    Command: python3 automation/approval_cli.py")
    print()

    # 3) Hashtag cleanup
    print(f"{_box(hashtags_done)} Clean hashtag bank")
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

    # 4) Status check (closing inspection — [x] when health passes)
    print(f"{_box(status_done)} Run status check")
    print("    Command: python3 automation/status.py")
    print()

    print("Suggested next action:")
    print(data["next_action"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
