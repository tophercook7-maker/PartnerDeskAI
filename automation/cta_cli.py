"""
cta_cli.py
----------
Manage memory/cta_bank.json from the command line.

Usage:
    python automation/cta_cli.py list
    python automation/cta_cli.py show "CTA text"
    python automation/cta_cli.py add "CTA text" --score 8 --category social --notes "..."
    python automation/cta_cli.py rescore "CTA text" 10
    python automation/cta_cli.py renote "CTA text" "new notes"
    python automation/cta_cli.py remove "CTA text"
    python automation/cta_cli.py reset

CTA names are matched case-insensitively.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_manager


def _find(bank: dict, name: str) -> dict | None:
    for t in bank.get("ctas", []):
        if t["cta"].lower() == name.lower():
            return t
    return None


def _print_table(bank: dict) -> None:
    ctas = bank.get("ctas", [])
    if not ctas:
        print("(cta bank is empty)")
        return
    print(f"{'CTA':<48} {'CATEGORY':<13} {'SCORE':>5} {'USED':>5}  LAST")
    print("-" * 92)
    for t in ctas:
        print(
            f"{t['cta'][:47]:<48} "
            f"{(t.get('category') or '')[:12]:<13} "
            f"{t.get('score', 0):>5} "
            f"{t.get('times_used', 0):>5}  "
            f"{t.get('last_used') or '—'}"
        )


def cmd_list(args: argparse.Namespace) -> int:
    _print_table(memory_manager.load_cta_bank())
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    t = _find(memory_manager.load_cta_bank(), args.cta)
    if not t:
        print(f"CTA not found: {args.cta}")
        return 1
    print(f"CTA:        {t['cta']}")
    print(f"Category:   {t.get('category', '')}")
    print(f"Score:      {t.get('score', '')}")
    print(f"Times used: {t.get('times_used', 0)}")
    print(f"Last used:  {t.get('last_used') or '—'}")
    print(f"Notes:      {t.get('notes', '')}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    bank = memory_manager.load_cta_bank()
    if _find(bank, args.cta):
        print(f"CTA already exists: {args.cta}")
        return 1
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2
    bank.setdefault("ctas", []).append({
        "cta": args.cta,
        "category": args.category,
        "times_used": 0,
        "last_used": None,
        "score": args.score,
        "notes": args.notes,
    })
    memory_manager.save_cta_bank(bank)
    print(f"Added: {args.cta}  (score={args.score}, category={args.category})")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    if not 1 <= args.score <= 10:
        print("Score must be between 1 and 10.")
        return 2
    bank = memory_manager.load_cta_bank()
    t = _find(bank, args.cta)
    if not t:
        print(f"CTA not found: {args.cta}")
        return 1
    old = t.get("score")
    t["score"] = args.score
    memory_manager.save_cta_bank(bank)
    print(f"Rescored {t['cta']}: {old} → {args.score}")
    return 0


def cmd_renote(args: argparse.Namespace) -> int:
    bank = memory_manager.load_cta_bank()
    t = _find(bank, args.cta)
    if not t:
        print(f"CTA not found: {args.cta}")
        return 1
    t["notes"] = args.notes
    memory_manager.save_cta_bank(bank)
    print(f"Updated notes for {t['cta']}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    bank = memory_manager.load_cta_bank()
    ctas = bank.get("ctas", [])
    kept = [t for t in ctas if t["cta"].lower() != args.cta.lower()]
    if len(kept) == len(ctas):
        print(f"CTA not found: {args.cta}")
        return 1
    bank["ctas"] = kept
    memory_manager.save_cta_bank(bank)
    print(f"Removed: {args.cta}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    bank = memory_manager.load_cta_bank()
    n = 0
    for t in bank.get("ctas", []):
        if t.get("times_used") or t.get("last_used"):
            t["times_used"] = 0
            t["last_used"] = None
            n += 1
    memory_manager.save_cta_bank(bank)
    print(f"Reset usage on {n} CTA(s).")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cta_cli.py",
        description="Manage memory/cta_bank.json — Parker's CTA rotation memory.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show all CTAs in the bank")

    sp = sub.add_parser("show", help="show full details for one CTA")
    sp.add_argument("cta")

    sp = sub.add_parser("add", help="add a new CTA")
    sp.add_argument("cta", help="CTA text (use quotes)")
    sp.add_argument("--score", type=int, default=7)
    sp.add_argument("--category", default="general")
    sp.add_argument("--notes", default="")

    sp = sub.add_parser("rescore", help="change a CTA's score")
    sp.add_argument("cta")
    sp.add_argument("score", type=int)

    sp = sub.add_parser("renote", help="replace a CTA's notes field")
    sp.add_argument("cta")
    sp.add_argument("notes")

    sp = sub.add_parser("remove", help="delete a CTA")
    sp.add_argument("cta")

    sub.add_parser("reset", help="zero times_used and last_used on all CTAs")
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
