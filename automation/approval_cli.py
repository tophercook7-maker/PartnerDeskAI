"""
approval_cli.py
---------------
Local interactive review tool for Parker Promo drafts.

Usage:
    python automation/approval_cli.py                 # interactive review of pending drafts
    python automation/approval_cli.py list            # multi-line summary of pending drafts
                                                      #   (id, platform, status, topic, file, tags)
    python automation/approval_cli.py status          # counts by status
    python automation/approval_cli.py status --warnings   # also: warning summary for pending drafts
    python automation/approval_cli.py preview <id>    # print the full draft content for one post

Approve -> sets posts.status = 'approved' AND inserts a post_history row,
            so Parker won't repeat the topic on future runs.
Reject  -> sets posts.status = 'rejected'. History is not touched.
Skip    -> leaves status as 'draft' for next time.
"""

import re
import sys
from functools import lru_cache
from pathlib import Path
from datetime import datetime

# Make sibling modules importable when running directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import approval_manager
import file_manager
import memory_manager


HR = "─" * 64

# Simple, conservative hashtag pattern. Doesn't match markdown headers like
# "# Platform" because the regex requires no space between '#' and the word.
HASHTAG_RE = re.compile(r"#[A-Za-z0-9_]+")


def _extract_hashtags(text: str) -> list[str]:
    """Return hashtags from a draft body in order of first appearance, deduped."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for tag in HASHTAG_RE.findall(text):
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


# --- Audit (v0.6) ---------------------------------------------------------
#
# _audit_draft inspects a stored post and returns a list of human-readable
# warning strings. Warnings are informational only — they never block
# approval. The CLI prints them above the body in review and inline in the
# `list` / `preview` summaries.

# Per-platform hashtag ceilings, mirroring Parker's prompt rules.
_HASHTAG_MAX_BY_PLATFORM = {
    "Instagram": 6,
    "Facebook": 3,
    "LinkedIn": 3,
    "Google Business Profile": 0,
}

# Phrases that count as an "obvious" CTA. Lowercase substring match. We
# intentionally keep this list short and conservative — false negatives
# (missed warnings) are preferable to overwarning every draft.
_CTA_PHRASES = (
    "message me", "reply", "contact", "get started", "ask",
    "book", "send me", "reach out", "dm", "comment",
    "learn more", "let's talk",
)


@lru_cache(maxsize=1)
def _bank_tags_lowercase() -> frozenset[str]:
    """Cache the lowercase set of hashtags in memory/hashtag_bank.json."""
    bank = memory_manager.load_hashtag_bank()
    return frozenset(t.get("tag", "").lower() for t in bank.get("hashtags", []))


def _audit_draft(post: dict) -> list[str]:
    """Return a list of informational warnings about the given draft."""
    warnings: list[str] = []
    content = post.get("content") or ""
    platform = post.get("platform") or ""
    tags = _extract_hashtags(content)

    # 1) Too many hashtags for the platform.
    max_tags = _HASHTAG_MAX_BY_PLATFORM.get(platform)
    if max_tags is not None and len(tags) > max_tags:
        if max_tags == 0:
            warnings.append(f"{platform} should usually have no hashtags.")
        else:
            warnings.append(
                f"Too many hashtags for {platform}: {len(tags)} found, max {max_tags}."
            )

    # 2) Hashtag not in the curated bank (case-insensitive).
    if tags:
        bank = _bank_tags_lowercase()
        for tag in tags:
            if tag.lower() not in bank:
                warnings.append(f"Hashtag not in bank: {tag}")

    # 3) No obvious CTA phrase present. We use word boundaries so short
    #    phrases like "dm" don't match inside brand names like "MixedMakerShop".
    content_lower = content.lower()
    if not any(
        re.search(rf"\b{re.escape(phrase)}\b", content_lower)
        for phrase in _CTA_PHRASES
    ):
        warnings.append("No obvious CTA found.")

    # 4) Very short content (under 120 chars, body only — DB.content already
    #    excludes the markdown metadata header).
    body_len = len(content.strip())
    if body_len < 120:
        warnings.append(f"Draft is very short: {body_len} characters.")

    return warnings


def _format_warnings_block(warnings: list[str]) -> str:
    """Render the warning list as a labeled block. Empty list -> empty string."""
    if not warnings:
        return ""
    return "Warnings:\n" + "\n".join(f"- {w}" for w in warnings)


def _md_path_for(draft: dict) -> Path | None:
    """Resolve the markdown file path for a draft, or None."""
    return file_manager.file_for_platform(draft["created_at"][:10], draft["platform"])


def _format_summary(draft: dict) -> str:
    """Multi-line summary used by `list` and `preview`."""
    md_path = _md_path_for(draft)
    tags = _extract_hashtags(draft.get("content", ""))

    file_line = "(no markdown file resolved)"
    if md_path:
        file_line = str(md_path) + ("" if md_path.exists() else "  (missing)")

    summary = (
        f"[#{draft['id']}] {draft['platform']}  ·  status: {draft['status']}  ·  {draft['created_at']}\n"
        f"     Topic: {draft.get('topic') or '(no topic)'}\n"
        f"     File:  {file_line}\n"
        f"     Tags:  {' '.join(tags) if tags else '(none)'}"
    )

    warnings_block = _format_warnings_block(_audit_draft(draft))
    if warnings_block:
        summary += "\n" + warnings_block
    return summary


def _print_draft(idx: int, total: int, draft: dict) -> None:
    print()
    print(HR)
    print(f"[{idx}/{total}]  {draft['platform']}  ·  {draft['created_at'][:10]}")
    print(f"Topic:  {draft['topic']}")
    if draft.get("image_idea"):
        print(f"Image:  {draft['image_idea']}")

    md_path = _md_path_for(draft)
    if md_path and md_path.exists():
        print(f"File:   {md_path}")

    tags = _extract_hashtags(draft.get("content", ""))
    if tags:
        print(f"Tags:   {' '.join(tags)}")

    warnings_block = _format_warnings_block(_audit_draft(draft))
    if warnings_block:
        print(warnings_block)

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
            # v0.7: when warnings exist, require one extra confirmation. The
            # default is No — pressing Enter (or anything other than y/Y)
            # leaves the draft as 'draft' and counts it as skipped.
            warnings = _audit_draft(draft)
            if warnings:
                confirm = input(
                    f"Approve despite {len(warnings)} warning(s)? [y/N]: "
                ).strip().lower()
                if confirm != "y":
                    skipped += 1
                    print("  · skipped (approval declined)")
                    continue
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
    print(f"Pending drafts: {len(pending)}")
    for d in pending:
        print()
        print(_format_summary(d))
    return 0


def cmd_preview(post_id: int) -> int:
    post = approval_manager.get_post(post_id)
    if not post:
        print(f"Post not found: id {post_id}")
        return 1

    print(_format_summary(post))
    print()

    md_path = _md_path_for(post)
    if md_path and md_path.exists():
        print(f"--- {md_path} ---")
        print(md_path.read_text(encoding="utf-8"))
        print("--- end of file ---")
    else:
        print("(markdown file not found — showing stored DB content)")
        print()
        print(post.get("content", "") or "(empty)")
    return 0


def cmd_status(show_warnings: bool = False) -> int:
    counts = approval_manager.status_counts()
    if not counts:
        print("No posts in database yet.")
        return 0

    if show_warnings:
        print("Status counts:")
    width = max(len(k) for k in counts)
    for status, n in sorted(counts.items()):
        print(f"  {status.ljust(width)}  {n}")

    if show_warnings:
        _print_warning_summary()
    return 0


def _print_warning_summary() -> None:
    """Aggregate _audit_draft output across all pending drafts and print it."""
    pending = approval_manager.list_pending()
    total = len(pending)

    # Ordered for stable presentation; only types with non-zero counts print.
    by_type: dict[str, int] = {
        "Missing CTA":         0,
        "Off-bank hashtags":   0,
        "Too many hashtags":   0,
        "Very short drafts":   0,
        "GBP hashtags":        0,
    }
    per_draft: list[tuple[int, str, int]] = []
    with_warnings = 0

    for d in pending:
        warnings = _audit_draft(d)
        if not warnings:
            continue
        with_warnings += 1
        per_draft.append((d["id"], d["platform"], len(warnings)))
        for w in warnings:
            # Classification mirrors the spec; first match wins so each
            # warning increments exactly one bucket.
            if "No obvious CTA" in w:
                by_type["Missing CTA"] += 1
            elif "Hashtag not in bank" in w:
                by_type["Off-bank hashtags"] += 1
            elif "Too many hashtags" in w:
                by_type["Too many hashtags"] += 1
            elif "very short" in w.lower():
                by_type["Very short drafts"] += 1
            elif "Google Business Profile" in w:
                by_type["GBP hashtags"] += 1

    clean = total - with_warnings

    print()
    print("Warning summary for pending drafts:")
    print(f"  {'Pending drafts:':<20}{total:>5}")
    print(f"  {'With warnings:':<20}{with_warnings:>5}")
    print(f"  {'Clean drafts:':<20}{clean:>5}")

    if any(by_type.values()):
        print()
        print("Warning types:")
        for label, n in by_type.items():
            if n:
                print(f"  {label + ':':<20}{n:>5}")

    if per_draft:
        # Worst first; stable secondary sort by id keeps output deterministic.
        per_draft.sort(key=lambda x: (-x[2], x[0]))
        print()
        print("Drafts needing review:")
        for pid, platform, count in per_draft:
            label = "warning" if count == 1 else "warnings"
            print(f"  #{pid} {platform} — {count} {label}")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "review"
    if cmd == "review":
        return cmd_review()
    if cmd == "list":
        return cmd_list()
    if cmd == "status":
        show_warnings = "--warnings" in argv[2:]
        return cmd_status(show_warnings=show_warnings)
    if cmd == "preview":
        if len(argv) < 3:
            print("Usage: python automation/approval_cli.py preview <post_id>")
            return 2
        try:
            post_id = int(argv[2])
        except ValueError:
            print(f"Invalid post id: {argv[2]}")
            return 2
        return cmd_preview(post_id)
    print(f"Unknown command: {cmd}")
    print("Usage: python automation/approval_cli.py [review|list|status [--warnings]|preview <id>]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
