"""
hashtag_cli.py
--------------
Manage memory/hashtag_bank.json from the command line.

Usage:
    python automation/hashtag_cli.py list [--platform instagram]
    python automation/hashtag_cli.py show "#Tag"      # or "Tag" or "tag"
    python automation/hashtag_cli.py add  "#Tag" --platforms instagram linkedin \
        --score 8 --category general --notes "..."
    python automation/hashtag_cli.py rescore     "#Tag" 9
    python automation/hashtag_cli.py renote      "#Tag" "new notes"
    python automation/hashtag_cli.py setplatforms "#Tag" instagram facebook linkedin
    python automation/hashtag_cli.py remove      "#Tag"
    python automation/hashtag_cli.py reset
    python automation/hashtag_cli.py audit-missing [--min-count N]   # read-only scan
    python automation/hashtag_cli.py absorb "#Tag" --platforms instagram linkedin \
        --score 8 --category brand --notes "..."                     # add from audit

Rules:
- Tags can be entered with or without a leading '#'; they're always stored with one.
- Tag matching is case-insensitive.
- Scores must be 1–10.
- Platforms are space-separated. Allowed values:
    instagram, facebook, linkedin, google_business_profile
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_manager
import memory_manager


# Local copy of the simple hashtag regex (approval_cli.py uses an identical
# one). Duplicated here to keep this CLI from importing another CLI.
_HASHTAG_RE = re.compile(r"#[A-Za-z0-9_]+")


# Platforms Parker actually writes for. Anything outside this set is rejected
# so a typo doesn't silently create an unreachable hashtag.
ALLOWED_PLATFORMS = {"instagram", "facebook", "linkedin", "google_business_profile"}


def _normalize_tag(raw: str) -> str:
    """Accept hashtags with or without a leading '#'; always store with one."""
    s = (raw or "").strip()
    if not s:
        return s
    return s if s.startswith("#") else "#" + s


def _validate_platforms(values: list[str]) -> tuple[list[str], list[str]]:
    """Lowercase the list; return (valid, invalid) splits."""
    cleaned = [p.strip().lower() for p in values if p and p.strip()]
    valid = [p for p in cleaned if p in ALLOWED_PLATFORMS]
    invalid = [p for p in cleaned if p not in ALLOWED_PLATFORMS]
    return valid, invalid


def _find(bank: dict, name: str) -> dict | None:
    target = _normalize_tag(name).lower()
    for t in bank.get("hashtags", []):
        if t["tag"].lower() == target:
            return t
    return None


def _print_table(bank: dict, platform_filter: str | None = None) -> None:
    tags = bank.get("hashtags", [])
    if platform_filter:
        p = platform_filter.lower()
        tags = [t for t in tags if p in [x.lower() for x in t.get("platforms", [])]]
    if not tags:
        print("(no matching hashtags)" if platform_filter else "(hashtag bank is empty)")
        return

    print(f"{'TAG':<24} {'PLATFORMS':<28} {'CATEGORY':<13} {'SCORE':>5} {'USED':>5}  LAST")
    print("-" * 95)
    for t in tags:
        plats = ",".join(t.get("platforms", []))
        print(
            f"{t['tag'][:23]:<24} "
            f"{plats[:27]:<28} "
            f"{(t.get('category') or '')[:12]:<13} "
            f"{t.get('score', 0):>5} "
            f"{t.get('times_used', 0):>5}  "
            f"{t.get('last_used') or '—'}"
        )


# --- Commands --------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    _print_table(memory_manager.load_hashtag_bank(), args.platform)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    t = _find(memory_manager.load_hashtag_bank(), args.tag)
    if not t:
        print(f"Hashtag not found: {_normalize_tag(args.tag)}")
        return 1
    print(f"Tag:        {t['tag']}")
    print(f"Platforms:  {', '.join(t.get('platforms', []))}")
    print(f"Category:   {t.get('category', '')}")
    print(f"Score:      {t.get('score', '')}")
    print(f"Times used: {t.get('times_used', 0)}")
    print(f"Last used:  {t.get('last_used') or '—'}")
    print(f"Notes:      {t.get('notes', '')}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    tag = _normalize_tag(args.tag)
    if not tag:
        print("Tag cannot be empty.")
        return 2
    bank = memory_manager.load_hashtag_bank()
    if _find(bank, tag):
        print(f"Hashtag already exists: {tag}")
        return 1
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2

    valid, invalid = _validate_platforms(args.platforms)
    if invalid:
        print(f"Unknown platform(s): {', '.join(invalid)}")
        print(f"Allowed: {', '.join(sorted(ALLOWED_PLATFORMS))}")
        return 2
    if not valid:
        print("At least one platform is required.")
        return 2

    bank.setdefault("hashtags", []).append({
        "tag": tag,
        "platforms": valid,
        "category": args.category,
        "times_used": 0,
        "last_used": None,
        "score": args.score,
        "notes": args.notes,
    })
    memory_manager.save_hashtag_bank(bank)
    print(f"Added: {tag}  (platforms={','.join(valid)}, score={args.score})")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2
    bank = memory_manager.load_hashtag_bank()
    t = _find(bank, args.tag)
    if not t:
        print(f"Hashtag not found: {_normalize_tag(args.tag)}")
        return 1
    old = t.get("score")
    t["score"] = args.score
    memory_manager.save_hashtag_bank(bank)
    print(f"Rescored {t['tag']}: {old} → {args.score}")
    return 0


def cmd_renote(args: argparse.Namespace) -> int:
    bank = memory_manager.load_hashtag_bank()
    t = _find(bank, args.tag)
    if not t:
        print(f"Hashtag not found: {_normalize_tag(args.tag)}")
        return 1
    t["notes"] = args.notes
    memory_manager.save_hashtag_bank(bank)
    print(f"Updated notes for {t['tag']}")
    return 0


def cmd_setplatforms(args: argparse.Namespace) -> int:
    valid, invalid = _validate_platforms(args.platforms)
    if invalid:
        print(f"Unknown platform(s): {', '.join(invalid)}")
        print(f"Allowed: {', '.join(sorted(ALLOWED_PLATFORMS))}")
        return 2
    if not valid:
        print("At least one platform is required.")
        return 2
    bank = memory_manager.load_hashtag_bank()
    t = _find(bank, args.tag)
    if not t:
        print(f"Hashtag not found: {_normalize_tag(args.tag)}")
        return 1
    old = t.get("platforms", [])
    t["platforms"] = valid
    memory_manager.save_hashtag_bank(bank)
    print(f"Platforms for {t['tag']}: {','.join(old)} → {','.join(valid)}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    tag = _normalize_tag(args.tag)
    bank = memory_manager.load_hashtag_bank()
    tags = bank.get("hashtags", [])
    kept = [t for t in tags if t["tag"].lower() != tag.lower()]
    if len(kept) == len(tags):
        print(f"Hashtag not found: {tag}")
        return 1
    bank["hashtags"] = kept
    memory_manager.save_hashtag_bank(bank)
    print(f"Removed: {tag}")
    return 0


def _find_casing_in_pending_drafts(target_lower: str) -> str | None:
    """
    Return the first casing seen in pending drafts for the given lowercased
    tag, or None if no pending draft uses it. Read-only.
    """
    for draft in approval_manager.list_pending():
        content = draft.get("content") or ""
        for tag in _HASHTAG_RE.findall(content):
            if tag.lower() == target_lower:
                return tag
    return None


def cmd_absorb(args: argparse.Namespace) -> int:
    """
    Add a hashtag (typically one surfaced by `audit-missing`) into the bank.
    If the tag exists in pending drafts, the casing Parker actually used wins
    over the input casing. If not, the user is prompted to confirm.
    """
    requested = _normalize_tag(args.tag)
    if not requested:
        print("Tag cannot be empty.")
        return 2

    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2

    valid, invalid = _validate_platforms(args.platforms)
    if invalid:
        print(f"Unknown platform(s): {', '.join(invalid)}")
        print(f"Allowed: {', '.join(sorted(ALLOWED_PLATFORMS))}")
        return 2
    if not valid:
        print("At least one platform is required.")
        return 2

    bank = memory_manager.load_hashtag_bank()
    existing = _find(bank, requested)
    if existing:
        print(f"Hashtag already exists in bank: {existing['tag']}")
        print("Use `rescore`, `renote`, or `setplatforms` to change it.")
        return 1

    seen = _find_casing_in_pending_drafts(requested.lower())
    if seen:
        stored_tag = seen
    else:
        reply = input(
            f"{requested} was not found in pending drafts. Add anyway? [y/N]: "
        ).strip().lower()
        if reply != "y":
            print("Cancelled.")
            return 0
        stored_tag = requested

    bank.setdefault("hashtags", []).append({
        "tag": stored_tag,
        "platforms": valid,
        "category": args.category,
        "times_used": 0,
        "last_used": None,
        "score": args.score,
        "notes": args.notes,
    })
    memory_manager.save_hashtag_bank(bank)

    print(f"Absorbed {stored_tag} into hashtag bank.")
    print(f"Platforms: {', '.join(valid)}")
    print(f"Score: {args.score}")
    print(f"Category: {args.category}")
    return 0


def cmd_audit_missing(args: argparse.Namespace) -> int:
    """
    Scan pending drafts for hashtags not currently in the bank.
    Read-only: never writes to the bank, the DB, or post statuses.
    """
    bank_lower = {
        t.get("tag", "").lower()
        for t in memory_manager.load_hashtag_bank().get("hashtags", [])
    }
    pending = approval_manager.list_pending()

    use_count: dict[str, int] = {}
    post_refs: dict[str, list[tuple[int, str]]] = {}

    for draft in pending:
        content = draft.get("content") or ""
        # Dedupe within a single post — Parker putting the same tag twice in
        # one body counts as one use for the "should we add this?" question.
        seen_in_post: set[str] = set()
        for tag in _HASHTAG_RE.findall(content):
            tag_lower = tag.lower()
            if tag_lower in bank_lower or tag_lower in seen_in_post:
                continue
            seen_in_post.add(tag_lower)
            use_count[tag_lower] = use_count.get(tag_lower, 0) + 1
            post_refs.setdefault(tag_lower, []).append(
                (draft["id"], draft["platform"])
            )

    # Sort by uses (desc), then alphabetical for deterministic output.
    items = sorted(use_count.items(), key=lambda kv: (-kv[1], kv[0]))

    min_count = max(1, args.min_count)
    items = [(t, c) for t, c in items if c >= min_count]

    print("Missing hashtag audit for pending drafts")
    print()

    if not pending:
        print("No pending drafts to audit.")
        return 0
    if not items:
        if min_count > 1:
            print(f"No missing hashtags with at least {min_count} uses.")
        else:
            print("No missing hashtags found in pending drafts.")
        return 0

    total_uses = sum(c for _, c in items)
    print(f"Total missing hashtag uses: {total_uses}")
    print(f"Unique missing hashtags:    {len(items)}")
    print()

    # Top list — pad tag column to longest entry for clean alignment.
    label_width = max(len(t) for t, _ in items) + 2
    for tag, count in items:
        unit = "use" if count == 1 else "uses"
        print(f"  {tag.ljust(label_width)}{count} {unit}")

    # Per-tag detail with the posts where each appeared.
    print()
    for tag, count in items:
        unit = "use" if count == 1 else "uses"
        refs = sorted(post_refs[tag], key=lambda r: r[0])
        refs_str = ", ".join(f"#{pid} {plat}" for pid, plat in refs)
        print(tag)
        print(f"  uses:  {count}")
        print(f"  posts: {refs_str}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    bank = memory_manager.load_hashtag_bank()
    n = 0
    for t in bank.get("hashtags", []):
        if t.get("times_used") or t.get("last_used"):
            t["times_used"] = 0
            t["last_used"] = None
            n += 1
    memory_manager.save_hashtag_bank(bank)
    print(f"Reset usage on {n} hashtag(s).")
    return 0


# --- Argparse wiring -------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hashtag_cli.py",
        description="Manage memory/hashtag_bank.json — Parker's hashtag rotation memory.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("list", help="show all hashtags (optionally filtered by platform)")
    sp.add_argument("--platform", default=None, help="filter to a single platform (e.g. instagram)")

    sp = sub.add_parser("show", help="show full details for one hashtag")
    sp.add_argument("tag")

    sp = sub.add_parser("add", help="add a new hashtag")
    sp.add_argument("tag", help="the hashtag, with or without leading # (stored with #)")
    sp.add_argument("--platforms", required=True, nargs="+",
                    help="space-separated platforms: instagram, facebook, linkedin, google_business_profile")
    sp.add_argument("--score", type=int, default=7, help="1–10, higher = preferred (default 7)")
    sp.add_argument("--category", default="general")
    sp.add_argument("--notes", default="")

    sp = sub.add_parser("rescore", help="change a hashtag's score")
    sp.add_argument("tag")
    sp.add_argument("score", type=int)

    sp = sub.add_parser("renote", help="replace a hashtag's notes field")
    sp.add_argument("tag")
    sp.add_argument("notes")

    sp = sub.add_parser("setplatforms", help="replace the platforms list for a hashtag")
    sp.add_argument("tag")
    sp.add_argument("platforms", nargs="+", help="space-separated platforms")

    sp = sub.add_parser("remove", help="delete a hashtag")
    sp.add_argument("tag")

    sub.add_parser("reset", help="zero times_used and last_used on all hashtags")

    sp = sub.add_parser(
        "audit-missing",
        help="read-only: list hashtags in pending drafts that aren't in the bank",
    )
    sp.add_argument(
        "--min-count", type=int, default=1,
        help="hide tags used fewer than this many times (default 1)",
    )

    sp = sub.add_parser(
        "absorb",
        help="add a hashtag (often one from `audit-missing`) into the bank",
    )
    sp.add_argument("tag", help="the hashtag, with or without leading '#'")
    sp.add_argument("--platforms", required=True, nargs="+",
                    help="space-separated platforms: instagram, facebook, linkedin, google_business_profile")
    sp.add_argument("--score", type=int, default=7, help="1–10 (default 7)")
    sp.add_argument("--category", default="general", help="free-form tag (default 'general')")
    sp.add_argument("--notes", default="Absorbed from pending draft audit.",
                    help="short description (default mentions audit origin)")
    return p


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
    handlers = {
        "list":          cmd_list,
        "show":          cmd_show,
        "add":           cmd_add,
        "rescore":       cmd_rescore,
        "renote":        cmd_renote,
        "setplatforms":  cmd_setplatforms,
        "remove":        cmd_remove,
        "reset":         cmd_reset,
        "audit-missing": cmd_audit_missing,
        "absorb":        cmd_absorb,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
