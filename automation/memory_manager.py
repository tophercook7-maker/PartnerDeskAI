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
CTA_BANK_PATH = MEMORY_DIR / "cta_bank.json"
OFFER_BANK_PATH = MEMORY_DIR / "offer_bank.json"

# Defaults used when a bank JSON file is missing on disk.
_DEFAULT_CTA_BANK = {
    "ctas": [
        {"cta": "DM us to learn more", "category": "social",
         "times_used": 0, "last_used": None, "score": 8,
         "notes": "Low-friction social CTA — good on Instagram and Facebook."},
        {"cta": "Book a free 15-minute consult", "category": "direct",
         "times_used": 0, "last_used": None, "score": 9,
         "notes": "Strong intent signal. Best for LinkedIn and Google Business."},
        {"cta": "Visit mixedmakershop.com to see what we do", "category": "website",
         "times_used": 0, "last_used": None, "score": 7,
         "notes": "Drives traffic to the site. Use when the post has space."},
        {"cta": "Reply to this post and we'll get back to you the same day",
         "category": "engagement", "times_used": 0, "last_used": None, "score": 7,
         "notes": "Boosts platform algorithm signals via replies."},
        {"cta": "Share this with a small business owner who could use the help",
         "category": "viral", "times_used": 0, "last_used": None, "score": 7,
         "notes": "Good occasional change-up. Works best on educational posts."},
    ]
}

_DEFAULT_OFFER_BANK = {
    "offers": [
        {"offer": "Free initial consultation", "category": "consult",
         "times_used": 0, "last_used": None, "score": 9,
         "notes": "Low-friction entry point. Works for almost any service."},
        {"offer": "Complimentary website audit", "category": "audit",
         "times_used": 0, "last_used": None, "score": 8,
         "notes": "Great when the post topic is websites or visibility."},
        {"offer": "Bundle: website + digital business card", "category": "bundle",
         "times_used": 0, "last_used": None, "score": 8,
         "notes": "Use when promoting either service individually feels too narrow."},
        {"offer": "No subscription — pay once, own it", "category": "positioning",
         "times_used": 0, "last_used": None, "score": 7,
         "notes": "Differentiator vs. SaaS-style competitors. Soft offer angle."},
        {"offer": "Limited spots open this month", "category": "scarcity",
         "times_used": 0, "last_used": None, "score": 6,
         "notes": "Use sparingly so it doesn't feel manipulative or repetitive."},
    ]
}

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


# --- Rotation memory: shared helpers --------------------------------------
#
# The three banks (topic, CTA, offer) share the same shape: a JSON file with a
# top-level list of dicts, each with a name field, a score, times_used, and
# last_used. The private helpers below factor that shape; public per-domain
# functions are thin wrappers.

def _load_bank(path: Path, default: dict) -> dict:
    """Load a bank JSON file. Seeds with defaults on first run."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _save_bank(path, default)
        return json.loads(json.dumps(default))  # deep copy
    return json.loads(path.read_text(encoding="utf-8"))


def _save_bank(path: Path, bank: dict) -> None:
    """Persist a bank dict to disk as pretty-printed JSON."""
    path.write_text(json.dumps(bank, indent=2) + "\n", encoding="utf-8")


def _choose_from_bank(
    items: list[dict],
    name_key: str,
    also_recent: set[str] | None = None,
    recent_window_days: int = 7,
) -> str:
    """
    Score-weighted, recency-aware pick from a bank's items list.

    - Filters out items used in the last `recent_window_days` (by `last_used`)
      and items whose name appears in `also_recent` (an external signal, e.g.
      post_history for topics).
    - If all items are filtered, falls back to the oldest-used half.
    - Among remaining candidates, weighted-random by `score`.
    """
    if not items:
        return ""
    also_recent = also_recent or set()
    cutoff = datetime.now() - timedelta(days=recent_window_days)

    def _is_recent(t: dict) -> bool:
        if t.get(name_key) in also_recent:
            return True
        last = t.get("last_used")
        if not last:
            return False
        try:
            return datetime.fromisoformat(last) >= cutoff
        except (TypeError, ValueError):
            return False

    candidates = [t for t in items if not _is_recent(t)]
    if not candidates:
        candidates = sorted(
            items, key=lambda t: (t.get("last_used") or "0000-00-00")
        )[: max(1, len(items) // 2)]

    weights = [max(1, int(t.get("score", 5))) for t in candidates]
    chosen = random.choices(candidates, weights=weights, k=1)[0]
    return chosen[name_key]


def _record_usage(items: list[dict], name_key: str, name: str) -> bool:
    """Increment times_used and set last_used=today for the matching item."""
    today = datetime.now().strftime("%Y-%m-%d")
    for t in items:
        if t.get(name_key) == name:
            t["times_used"] = int(t.get("times_used", 0)) + 1
            t["last_used"] = today
            return True
    return False


def _recent_from_bank(items: list[dict], name_key: str, limit: int) -> list[str]:
    """Return item names ordered by most recent `last_used` (None entries skipped)."""
    used = [t for t in items if t.get("last_used")]
    used.sort(key=lambda t: t["last_used"], reverse=True)
    return [t[name_key] for t in used[:limit]]


# --- Topic Intelligence (v0.2) --------------------------------------------

def load_topic_bank() -> dict:
    return _load_bank(TOPIC_BANK_PATH, _DEFAULT_TOPIC_BANK)


def save_topic_bank(bank: dict) -> None:
    _save_bank(TOPIC_BANK_PATH, bank)


def get_recent_topics(limit: int = 10) -> list[str]:
    """
    Return distinct topic strings from post_history (newest first).
    This is the approved-and-posted signal — stronger than bank.last_used.
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
    """Pick today's topic. Considers both bank.last_used and post_history."""
    items = load_topic_bank().get("topics", [])
    chosen = _choose_from_bank(
        items, "topic", also_recent=set(get_recent_topics(limit=10))
    )
    return chosen or "Daily Promo"


def update_topic_usage(topic: str) -> bool:
    bank = load_topic_bank()
    if _record_usage(bank.get("topics", []), "topic", topic):
        save_topic_bank(bank)
        return True
    return False


# --- CTA Rotation (v0.3) --------------------------------------------------

def load_cta_bank() -> dict:
    return _load_bank(CTA_BANK_PATH, _DEFAULT_CTA_BANK)


def save_cta_bank(bank: dict) -> None:
    _save_bank(CTA_BANK_PATH, bank)


def get_recent_ctas(limit: int = 5) -> list[str]:
    """CTAs ordered by most recently used. Source: cta_bank.last_used."""
    return _recent_from_bank(load_cta_bank().get("ctas", []), "cta", limit)


def choose_cta() -> str:
    """Pick today's CTA. Score-weighted, avoids ones used in the last 7 days."""
    return _choose_from_bank(load_cta_bank().get("ctas", []), "cta")


def update_cta_usage(cta: str) -> bool:
    bank = load_cta_bank()
    if _record_usage(bank.get("ctas", []), "cta", cta):
        save_cta_bank(bank)
        return True
    return False


# --- Offer Rotation (v0.3) ------------------------------------------------

def load_offer_bank() -> dict:
    return _load_bank(OFFER_BANK_PATH, _DEFAULT_OFFER_BANK)


def save_offer_bank(bank: dict) -> None:
    _save_bank(OFFER_BANK_PATH, bank)


def get_recent_offers(limit: int = 5) -> list[str]:
    """Offers ordered by most recently used. Source: offer_bank.last_used."""
    return _recent_from_bank(load_offer_bank().get("offers", []), "offer", limit)


def choose_offer() -> str:
    """Pick today's offer angle. Score-weighted, avoids ones used in the last 7 days."""
    return _choose_from_bank(load_offer_bank().get("offers", []), "offer")


def update_offer_usage(offer: str) -> bool:
    bank = load_offer_bank()
    if _record_usage(bank.get("offers", []), "offer", offer):
        save_offer_bank(bank)
        return True
    return False
