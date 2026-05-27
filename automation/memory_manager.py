"""
memory_manager.py
-----------------
Loads memory files and recent posting history for Parker Promo.

Memory is intentionally just markdown + SQLite. No vector store, no embeddings.
"""

from pathlib import Path
import sqlite3
import json
import random
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
PARTNER_DIR = ROOT / "partners" / "parker_promo"
DB_PATH = ROOT / "database" / "partnerdesk.db"
TOPIC_BANK_PATH = MEMORY_DIR / "topic_bank.json"

# Topics seeded when memory/topic_bank.json is missing.
_DEFAULT_TOPIC_BANK = {
    "topics": [
        {"topic": "Local Business Visibility", "category": "educational",
         "times_used": 0, "last_used": None, "score": 8,
         "notes": "Useful for helping small businesses understand why online presence matters."},
        {"topic": "Digital Business Cards", "category": "service",
         "times_used": 0, "last_used": None, "score": 9,
         "notes": "Good for promoting NFC/tap hub services."},
        {"topic": "Website Cleanup", "category": "problem-solving",
         "times_used": 0, "last_used": None, "score": 8,
         "notes": "Good angle for businesses with outdated or confusing websites."},
        {"topic": "Social Media Consistency", "category": "educational",
         "times_used": 0, "last_used": None, "score": 7,
         "notes": "Useful for businesses that rarely post."},
        {"topic": "AI Business Systems", "category": "authority",
         "times_used": 0, "last_used": None, "score": 9,
         "notes": "Positions MixedMakerShop as modern and practical."},
    ]
}


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


# --- Topic Intelligence v0.2 ----------------------------------------------

def load_topic_bank() -> dict:
    """
    Load memory/topic_bank.json. Seeds the file with defaults if missing.
    """
    if not TOPIC_BANK_PATH.exists():
        TOPIC_BANK_PATH.parent.mkdir(parents=True, exist_ok=True)
        save_topic_bank(_DEFAULT_TOPIC_BANK)
        return json.loads(json.dumps(_DEFAULT_TOPIC_BANK))  # deep copy
    return json.loads(TOPIC_BANK_PATH.read_text(encoding="utf-8"))


def save_topic_bank(bank: dict) -> None:
    """Persist the topic bank to disk as pretty-printed JSON."""
    TOPIC_BANK_PATH.write_text(json.dumps(bank, indent=2) + "\n", encoding="utf-8")


def get_recent_topics(limit: int = 10) -> list[str]:
    """
    Return distinct topic strings from post_history, newest first.
    Used as a 'do not repeat' signal for the next run.
    """
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT topic, MAX(posted_date) AS last "
            "FROM post_history GROUP BY topic ORDER BY last DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [r["topic"] for r in rows]


def choose_topic() -> str:
    """
    Pick the next topic Parker should write about.

    Strategy:
    - Skip topics used in the last 7 days (by topic_bank.last_used).
    - Skip topics that appear in recent post_history (approved-and-posted signal).
    - Among the remaining, pick weighted-random by score so high-score topics
      come up more often but rotation stays alive.
    - If everything has been used recently, fall back to the least-recently-used
      half of the bank.
    """
    bank = load_topic_bank()
    topics = bank.get("topics", [])
    if not topics:
        return "Daily Promo"

    recent_in_history = set(get_recent_topics(limit=10))
    cutoff = datetime.now() - timedelta(days=7)

    def is_recent(t: dict) -> bool:
        if t["topic"] in recent_in_history:
            return True
        last = t.get("last_used")
        if not last:
            return False
        try:
            return datetime.fromisoformat(last) >= cutoff
        except (TypeError, ValueError):
            return False

    candidates = [t for t in topics if not is_recent(t)]
    if not candidates:
        # All topics are "recent" — fall back to oldest-used half of the bank.
        candidates = sorted(
            topics, key=lambda t: (t.get("last_used") or "0000-00-00")
        )[: max(1, len(topics) // 2)]

    weights = [max(1, int(t.get("score", 5))) for t in candidates]
    chosen = random.choices(candidates, weights=weights, k=1)[0]
    return chosen["topic"]


def update_topic_usage(topic: str) -> bool:
    """
    Increment times_used and set last_used=today for the matching topic.
    Returns True if the topic was found and updated, False otherwise.
    """
    bank = load_topic_bank()
    today = datetime.now().strftime("%Y-%m-%d")
    for t in bank.get("topics", []):
        if t["topic"] == topic:
            t["times_used"] = int(t.get("times_used", 0)) + 1
            t["last_used"] = today
            save_topic_bank(bank)
            return True
    return False
