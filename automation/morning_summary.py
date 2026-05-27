"""
morning_summary.py
------------------
Write a plain-markdown daily summary derived from status._gather_status()
to summaries/YYYY-MM-DD.md. The single intentional side effect is that
one file; nothing else is touched.

Usage:
    python3 automation/morning_summary.py

Never calls OpenAI, never modifies the database, never modifies any
memory bank, and never auto-posts.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import status as status_mod


ROOT = Path(__file__).resolve().parent.parent
SUMMARIES_DIR = ROOT / "summaries"


def _render_markdown(data: dict, today: str) -> str:
    """Build the day's summary as a single markdown string."""
    lines: list[str] = []

    lines.append(f"# PartnerDeskAI Morning Summary — {today}")
    lines.append("")

    lines.append("## Health")
    lines.append(f"Status: {data['health']['status']}")
    lines.append("")

    today_block = data["today"]
    lines.append("## Today")
    lines.append(f"Draft folder: {today_block['folder']}")
    lines.append(f"Markdown files: {today_block['markdown_files']}")
    lines.append("")

    review = data["review"]
    lines.append("## Review")
    lines.append(f"Pending drafts: {review['pending_drafts']}")
    lines.append(f"Drafts with warnings: {review['drafts_with_warnings']}")
    lines.append(f"Clean drafts: {review['clean_drafts']}")
    lines.append("")

    banks = data["memory_banks"]
    lines.append("## Memory Banks")
    lines.append(f"Topics: {banks['topics']}")
    lines.append(f"CTAs: {banks['ctas']}")
    lines.append(f"Offers: {banks['offers']}")
    lines.append(f"Hashtags: {banks['hashtags']}")
    lines.append("")

    missing = review.get("top_missing_hashtags", [])
    lines.append("## Top Missing Hashtags")
    if missing:
        for entry in missing:
            unit = "use" if entry["uses"] == 1 else "uses"
            lines.append(f"- {entry['tag']} — {entry['uses']} {unit}")
    else:
        lines.append("Curated hashtag bank looks clean.")
    lines.append("")

    lines.append("## Next Action")
    lines.append(data["next_action"])
    lines.append("")

    lines.append("## Commands")
    lines.append("```bash")
    lines.append("python3 automation/daily_checklist.py")
    lines.append("python3 automation/status.py")
    lines.append("python3 automation/approval_cli.py")
    lines.append("python3 automation/hashtag_cli.py audit-missing --min-count 2")
    lines.append("```")

    return "\n".join(lines) + "\n"


def main() -> int:
    data = status_mod._gather_status()
    today = datetime.now().strftime("%Y-%m-%d")

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    path = SUMMARIES_DIR / f"{today}.md"
    path.write_text(_render_markdown(data, today), encoding="utf-8")

    print(f"Wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
