"""
hashtag_cli.py
--------------
Manage memory/hashtag_bank.json from the command line.

Usage:
    python automation/hashtag_cli.py list [--platform instagram]
    python automation/hashtag_cli.py show "#Tag"
    python automation/hashtag_cli.py add  "#Tag" --platforms instagram,linkedin \
        --score 8 --category general --notes "..."
    python automation/hashtag_cli.py rescore     "#Tag" 9
    python automation/hashtag_cli.py renote      "#Tag" "new notes"
    python automation/hashtag_cli.py setplatforms "#Tag" instagram,facebook,linkedin
    python automation/hashtag_cli.py remove      "#Tag"
    python automation/hashtag_cli.py reset

Tag names are matched case-insensitively. Scores must be 1–10.
Platforms argument is comma-separated; valid values are any lowercase
platform key (typically: instagram, facebook, linkedin, google_business_profile).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_manager


def _find(bank: dict, name: str) -> dict | None:
    for t in bank.get("hashtags", []):
        if t["tag"].lower() == name.lower():
            return t
    return None


def _parse_platforms(s: str) -> list[str]:
    return [p.strip().lower() for p in s.split(",") if p.strip()]


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
        print(f"Hashtag not found: {args.tag}")
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
    bank = memory_manager.load_hashtag_bank()
    if _find(bank, args.tag):
        print(f"Hashtag already exists: {args.tag}")
        return 1
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2
    platforms = _parse_platforms(args.platforms)
    if not platforms:
        print("At least one platform is required (--platforms instagram,linkedin).")
        return 2

    bank.setdefault("hashtags", []).append({
        "tag": args.tag,
        "platforms": platforms,
        "category": args.category,
        "times_used": 0,
        "last_used": None,
        "score": args.score,
        "notes": args.notes,
    })
    memory_manager.save_hashtag_bank(bank)
    print(f"Added: {args.tag}  (platforms={','.join(platforms)}, score={args.score})")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2
    bank = memory_manager.load_hashtag_bank()
    t = _find(bank, args.tag)
    if not t:
        print(f"Hashtag not found: {args.tag}")
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
        print(f"Hashtag not found: {args.tag}")
        return 1
    t["notes"] = args.notes
    memory_manager.save_hashtag_bank(bank)
    print(f"Updated notes for {t['tag']}")
    return 0


def cmd_setplatforms(args: argparse.Namespace) -> int:
    platforms = _parse_platforms(args.platforms)
    if not platforms:
        print("At least one platform is required.")
        return 2
    bank = memory_manager.load_hashtag_bank()
    t = _find(bank, args.tag)
    if not t:
        print(f"Hashtag not found: {args.tag}")
        return 1
    old = t.get("platforms", [])
    t["platforms"] = platforms
    memory_manager.save_hashtag_bank(bank)
    print(f"Platforms for {t['tag']}: {','.join(old)} → {','.join(platforms)}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    bank = memory_manager.load_hashtag_bank()
    tags = bank.get("hashtags", [])
    kept = [t for t in tags if t["tag"].lower() != args.tag.lower()]
    if len(kept) == len(tags):
        print(f"Hashtag not found: {args.tag}")
        return 1
    bank["hashtags"] = kept
    memory_manager.save_hashtag_bank(bank)
    print(f"Removed: {args.tag}")
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
    sp.add_argument("tag", help="the hashtag, including the # (use quotes)")
    sp.add_argument("--platforms", required=True,
                    help="comma-separated platforms, e.g. instagram,linkedin")
    sp.add_argument("--score", type=int, default=7)
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
    sp.add_argument("platforms", help="comma-separated platforms")

    sp = sub.add_parser("remove", help="delete a hashtag")
    sp.add_argument("tag")

    sub.add_parser("reset", help="zero times_used and last_used on all hashtags")
    return p


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
    handlers = {
        "list":         cmd_list,
        "show":         cmd_show,
        "add":          cmd_add,
        "rescore":      cmd_rescore,
        "renote":       cmd_renote,
        "setplatforms": cmd_setplatforms,
        "remove":       cmd_remove,
        "reset":        cmd_reset,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
