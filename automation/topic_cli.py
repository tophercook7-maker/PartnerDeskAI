"""
topic_cli.py
------------
Manage memory/topic_bank.json from the command line.

Usage:
    python automation/topic_cli.py list
    python automation/topic_cli.py show "Topic Name"
    python automation/topic_cli.py add "Topic Name" --score 8 --category educational --notes "..."
    python automation/topic_cli.py rescore "Topic Name" 10
    python automation/topic_cli.py renote "Topic Name" "new notes"
    python automation/topic_cli.py remove "Topic Name"
    python automation/topic_cli.py reset

Topic names are matched case-insensitively.
"""

import argparse
import sys
from pathlib import Path

# Make sibling modules importable when running directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import memory_manager


def _find(bank: dict, name: str) -> dict | None:
    """Locate a topic by case-insensitive name match."""
    for t in bank.get("topics", []):
        if t["topic"].lower() == name.lower():
            return t
    return None


def _print_table(bank: dict) -> None:
    topics = bank.get("topics", [])
    if not topics:
        print("(topic bank is empty)")
        return

    print(f"{'TOPIC':<34} {'CATEGORY':<17} {'SCORE':>5} {'USED':>5}  LAST")
    print("-" * 78)
    for t in topics:
        print(
            f"{t['topic'][:33]:<34} "
            f"{(t.get('category') or '')[:16]:<17} "
            f"{t.get('score', 0):>5} "
            f"{t.get('times_used', 0):>5}  "
            f"{t.get('last_used') or '—'}"
        )


# --- Commands --------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    _print_table(memory_manager.load_topic_bank())
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    bank = memory_manager.load_topic_bank()
    t = _find(bank, args.topic)
    if not t:
        print(f"Topic not found: {args.topic}")
        return 1
    print(f"Topic:      {t['topic']}")
    print(f"Category:   {t.get('category', '')}")
    print(f"Score:      {t.get('score', '')}")
    print(f"Times used: {t.get('times_used', 0)}")
    print(f"Last used:  {t.get('last_used') or '—'}")
    print(f"Notes:      {t.get('notes', '')}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    bank = memory_manager.load_topic_bank()
    if _find(bank, args.topic):
        print(f"Topic already exists: {args.topic}")
        return 1
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2

    bank.setdefault("topics", []).append({
        "topic": args.topic,
        "category": args.category,
        "times_used": 0,
        "last_used": None,
        "score": args.score,
        "notes": args.notes,
    })
    memory_manager.save_topic_bank(bank)
    print(f"Added: {args.topic}  (score={args.score}, category={args.category})")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2

    bank = memory_manager.load_topic_bank()
    t = _find(bank, args.topic)
    if not t:
        print(f"Topic not found: {args.topic}")
        return 1
    old = t.get("score")
    t["score"] = args.score
    memory_manager.save_topic_bank(bank)
    print(f"Rescored {t['topic']}: {old} → {args.score}")
    return 0


def cmd_renote(args: argparse.Namespace) -> int:
    bank = memory_manager.load_topic_bank()
    t = _find(bank, args.topic)
    if not t:
        print(f"Topic not found: {args.topic}")
        return 1
    t["notes"] = args.notes
    memory_manager.save_topic_bank(bank)
    print(f"Updated notes for {t['topic']}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    bank = memory_manager.load_topic_bank()
    topics = bank.get("topics", [])
    kept = [t for t in topics if t["topic"].lower() != args.topic.lower()]
    if len(kept) == len(topics):
        print(f"Topic not found: {args.topic}")
        return 1
    bank["topics"] = kept
    memory_manager.save_topic_bank(bank)
    print(f"Removed: {args.topic}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    bank = memory_manager.load_topic_bank()
    n = 0
    for t in bank.get("topics", []):
        if t.get("times_used") or t.get("last_used"):
            t["times_used"] = 0
            t["last_used"] = None
            n += 1
    memory_manager.save_topic_bank(bank)
    print(f"Reset usage on {n} topic(s).")
    return 0


# --- Argparse wiring -------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="topic_cli.py",
        description="Manage memory/topic_bank.json — Parker's topic rotation memory.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show all topics in the bank")

    sp = sub.add_parser("show", help="show full details for one topic")
    sp.add_argument("topic", help="topic name (case-insensitive)")

    sp = sub.add_parser("add", help="add a new topic")
    sp.add_argument("topic", help="topic name (use quotes for multi-word)")
    sp.add_argument("--score", type=int, default=7, help="1–10, higher = preferred (default 7)")
    sp.add_argument("--category", default="general", help="free-form tag (default 'general')")
    sp.add_argument("--notes", default="", help="short description / angle")

    sp = sub.add_parser("rescore", help="change a topic's score")
    sp.add_argument("topic")
    sp.add_argument("score", type=int, help="new score 1–10")

    sp = sub.add_parser("renote", help="replace a topic's notes field")
    sp.add_argument("topic")
    sp.add_argument("notes")

    sp = sub.add_parser("remove", help="delete a topic from the bank")
    sp.add_argument("topic")

    sub.add_parser("reset", help="zero out times_used and last_used on all topics")
    return p


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv[1:])
    handlers = {
        "list":    cmd_list,
        "show":    cmd_show,
        "add":     cmd_add,
        "rescore": cmd_rescore,
        "renote":  cmd_renote,
        "remove":  cmd_remove,
        "reset":   cmd_reset,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
