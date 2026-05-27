"""
memory_manager.py
-----------------
Loads memory files and recent posting history for Parker Promo.

Memory is intentionally just markdown + SQLite. No vector store, no embeddings.
"""

from pathlib import Path
import sqlite3
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
PARTNER_DIR = ROOT / "partners" / "parker_promo"
DB_PATH = ROOT / "database" / "partnerdesk.db"


def load_business_profile() -> str:
    """Read the business profile markdown as a plain string."""
    path = MEMORY_DIR / "business_profile.md"
    return path.read_text(encoding="utf-8")


def load_parker_prompt() -> str:
    """Read the Parker Promo system prompt markdown."""
    path = PARTNER_DIR / "parker_promo_prompt.md"
    return path.read_text(encoding="utf-8")


def load_posting_schedule() -> str:
    """Read the posting schedule JSON as a raw string (passed into the prompt)."""
    path = PARTNER_DIR / "posting_schedule.json"
    return path.read_text(encoding="utf-8")


def load_recent_history(days: int = 14) -> list[dict]:
    """
    Return recent posts from post_history table.
    Used to help Parker avoid repeating topics.
    """
    if not DB_PATH.exists():
        return []

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT topic, platform, posted_date "
            "FROM post_history "
            "WHERE posted_date >= ? "
            "ORDER BY posted_date DESC",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]


def format_history_for_prompt(history: list[dict]) -> str:
    """Turn the history rows into a short, prompt-friendly summary."""
    if not history:
        return "No recent posts yet. This is one of the first runs."

    lines = ["Recent topics (avoid repeating these):"]
    for row in history:
        lines.append(f"- {row['posted_date'][:10]} | {row['platform']} | {row['topic']}")
    return "\n".join(lines)
