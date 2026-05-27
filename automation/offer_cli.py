"""
offer_cli.py
------------
Manage memory/offer_bank.json from the command line.

Usage:
    python automation/offer_cli.py list
    python automation/offer_cli.py show "Offer angle"
    python automation/offer_cli.py add "Offer angle" --score 8 --category consult --notes "..."
    python automation/offer_cli.py rescore "Offer angle" 10
    python automation/offer_cli.py renote "Offer angle" "new notes"
    python automation/offer_cli.py remove "Offer angle"
    python automation/offer_cli.py reset

Offer names are matched case-insensitively.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_manager


def _find(bank: dict, name: str) -> dict | None:
    for t in bank.get("offers", []):
        if t["offer"].lower() == name.lower():
            return t
    return None


def _print_table(bank: dict) -> None:
    offers = bank.get("offers", [])
    if not offers:
        print("(offer bank is empty)")
        return
    print(f"{'OFFER':<48} {'CATEGORY':<13} {'SCORE':>5} {'USED':>5}  LAST")
    print("-" * 92)
    for t in offers:
        print(
            f"{t['offer'][:47]:<48} "
            f"{(t.get('category') or '')[:12]:<13} "
            f"{t.get('score', 0):>5} "
            f"{t.get('times_used', 0):>5}  "
            f"{t.get('last_used') or '—'}"
        )


def cmd_list(args: argparse.Namespace) -> int:
    _print_table(memory_manager.load_offer_bank())
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    t = _find(memory_manager.load_offer_bank(), args.offer)
    if not t:
        print(f"Offer not found: {args.offer}")
        return 1
    print(f"Offer:      {t['offer']}")
    print(f"Category:   {t.get('category', '')}")
    print(f"Score:      {t.get('score', '')}")
    print(f"Times used: {t.get('times_used', 0)}")
    print(f"Last used:  {t.get('last_used') or '—'}")
    print(f"Notes:      {t.get('notes', '')}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    bank = memory_manager.load_offer_bank()
    if _find(bank, args.offer):
        print(f"Offer already exists: {args.offer}")
        return 1
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2
    bank.setdefault("offers", []).append({
        "offer": args.offer,
        "category": args.category,
        "times_used": 0,
        "last_used": None,
        "score": args.score,
        "notes": args.notes,
    })
    memory_manager.save_offer_bank(bank)
    print(f"Added: {args.offer}  (score={args.score}, category={args.category})")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2
    bank = memory_manager.load_offer_bank()
    t = _find(bank, args.offer)
    if not t:
        print(f"Offer not found: {args.offer}")
        return 1
    old = t.get("score")
    t["score"] = args.score
    memory_manager.save_offer_bank(bank)
    print(f"Rescored {t['offer']}: {old} → {args.score}")
    return 0


def cmd_renote(args: argparse.Namespace) -> int:
    bank = memory_manager.load_offer_bank()
    t = _find(bank, args.offer)
    if not t:
        print(f"Offer not found: {args.offer}")
        return 1
    t["notes"] = args.notes
    memory_manager.save_offer_bank(bank)
    print(f"Updated notes for {t['offer']}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    bank = memory_manager.load_offer_bank()
    offers = bank.get("offers", [])
    kept = [t for t in offers if t["offer"].lower() != args.offer.lower()]
    if len(kept) == len(offers):
        print(f"Offer not found: {args.offer}")
        return 1
    bank["offers"] = kept
    memory_manager.save_offer_bank(bank)
    print(f"Removed: {args.offer}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    bank = memory_manager.load_offer_bank()
    n = 0
    for t in bank.get("offers", []):
        if t.get("times_used") or t.get("last_used"):
            t["times_used"] = 0
            t["last_used"] = None
            n += 1
    memory_manager.save_offer_bank(bank)
    print(f"Reset usage on {n} offer(s).")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="offer_cli.py",
        description="Manage memory/offer_bank.json — Parker's offer rotation memory.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show all offers in the bank")

    sp = sub.add_parser("show", help="show full details for one offer")
    sp.add_argument("offer")

    sp = sub.add_parser("add", help="add a new offer")
    sp.add_argument("offer", help="offer angle (use quotes)")
    sp.add_argument("--score", type=int, default=7)
    sp.add_argument("--category", default="general")
    sp.add_argument("--notes", default="")

    sp = sub.add_parser("rescore", help="change an offer's score")
    sp.add_argument("offer")
    sp.add_argument("score", type=int)

    sp = sub.add_parser("renote", help="replace an offer's notes field")
    sp.add_argument("offer")
    sp.add_argument("notes")

    sp = sub.add_parser("remove", help="delete an offer")
    sp.add_argument("offer")

    sub.add_parser("reset", help="zero times_used and last_used on all offers")
    return p


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
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
