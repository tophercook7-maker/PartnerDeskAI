"""
approval_cli.py
---------------
Local interactive review tool for Parker Promo drafts.

Usage:
    python automation/approval_cli.py            # review pending drafts
    python automation/approval_cli.py list       # non-interactive list
    python automation/approval_cli.py status     # count by status

Approve -> sets posts.status = 'approved' AND inserts a post_history row,
            so Parker won't repeat the topic on future runs.
Reject  -> sets posts.status = 'rejected'. History is not touched.
Skip    -> leaves status as 'draft' for next time.
"""

import sys
from pathlib import Path
from datetime import datetime

# Make sibling modules importable when running directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import approval_manager
import file_manager


HR = "─" * 64


def _print_draft(idx: int, total: int, draft: dict) -> None:
    print()
    print(HR)
    print(f"[{idx}/{total}]  {draft['platform']}  ·  {draft['created_at'][:10]}")
    print(f"Topic:  {draft['topic']}")
    if draft.get("image_idea"):
        print(f"Image:  {draft['image_idea']}")

    md_path = file_manager.file_for_platform(
        draft["created_at"][:10], draft["platform"]
    )
    if md_path and md_path.exists():
        print(f"File:   {md_path}")
    print(HR)
    print(draft["content"].strip())
    print(HR)


def _prompt_action() -> str:
    """Ask the user what to do with the current draft. Returns 'a','r','s','q','v'."""
    while True:
        choice = input("Action — [a]pprove · [r]eject · [s]kip · [v]iew file · [q]uit: ").strip().lower()
        if choice in {"a", "r", "s", "q", "v"}:
            return choice
        print("  Please enter one of: a, r, s, v, q")


def _view_file(draft: dict) -> None:
    md_path = file_manager.file_for_platform(
        draft["created_at"][:10], draft["platform"]
    )
    if not md_path or not md_path.exists():
        print("  (No markdown file found for this draft.)")
        return
    print()
    print(f"--- {md_path} ---")
    print(md_path.read_text(encoding="utf-8"))
    print("--- end ---")


def cmd_review() -> int:
    pending = approval_manager.list_pending()
    if not pending:
        print("No drafts pending review. Nothing to do.")
        return 0

    print(f"PartnerDeskAI — Approval Review")
    print(f"Pending drafts: {len(pending)}")

    approved = rejected = skipped = 0
    touched_dates: set[str] = set()

    for i, draft in enumerate(pending, start=1):
        _print_draft(i, len(pending), draft)

        while True:
            choice = _prompt_action()
            if choice == "v":
                _view_file(draft)
                continue
            break

        if choice == "q":
            print("Stopping. Remaining drafts left as 'draft'.")
            break

        if choice == "a":
            approval_manager.mark_status(draft["id"], "approved")
            approval_manager.record_history(draft["topic"], draft["platform"])
            touched_dates.add(draft["created_at"][:10])
            approved += 1
            print("  ✓ approved")
        elif choice == "r":
            approval_manager.mark_status(draft["id"], "rejected")
            touched_dates.add(draft["created_at"][:10])
            rejected += 1
            print("  ✗ rejected")
        else:
            skipped += 1
            print("  · skipped")

    # Clean up queue pointers for dates that now have zero pending drafts.
    cleared: list[str] = []
    for d in touched_dates:
        if approval_manager.clear_queue_pointer_if_done(d):
            cleared.append(d)

    print()
    print(HR)
    print(f"Done. Approved: {approved}  Rejected: {rejected}  Skipped: {skipped}")
    if cleared:
        print(f"Cleared approval_queue pointers: {', '.join(cleared)}")
    return 0


def cmd_list() -> int:
    pending = approval_manager.list_pending()
    if not pending:
        print("No drafts pending.")
        return 0
    print(f"{'ID':<4} {'PLATFORM':<25} {'TOPIC':<40} CREATED")
    for d in pending:
        topic = (d["topic"] or "")[:38]
        print(f"{d['id']:<4} {d['platform']:<25} {topic:<40} {d['created_at']}")
    return 0


def cmd_status() -> int:
    counts = approval_manager.status_counts()
    if not counts:
        print("No posts in database yet.")
        return 0
    width = max(len(k) for k in counts)
    for status, n in sorted(counts.items()):
        print(f"  {status.ljust(width)}  {n}")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "review"
    if cmd == "review":
        return cmd_review()
    if cmd == "list":
        return cmd_list()
    if cmd == "status":
        return cmd_status()
    print(f"Unknown command: {cmd}")
    print("Usage: python automation/approval_cli.py [review|list|status]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
