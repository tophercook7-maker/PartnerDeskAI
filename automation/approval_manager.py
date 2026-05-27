"""
approval_manager.py
-------------------
Manages the SQLite database and writes drafts to the approval queue.

Approval flow:
- Every generated post is saved with status = 'draft'.
- Nothing is auto-posted. A human reviews drafts later.
- The post_history table is only written when a draft is approved (future feature).
"""

from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "partnerdesk.db"
APPROVAL_QUEUE_DIR = ROOT / "approval_queue"


SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT,
    topic TEXT,
    content TEXT,
    hashtags TEXT,
    image_idea TEXT,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS post_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT,
    platform TEXT,
    posted_date TIMESTAMP
);
"""


def init_db() -> None:
    """Ensure the database file and required tables exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def insert_draft(
    platform: str,
    topic: str,
    content: str,
    hashtags: str = "",
    image_idea: str = "",
) -> int:
    """Insert a draft post and return its row id."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "INSERT INTO posts (platform, topic, content, hashtags, image_idea, status) "
            "VALUES (?, ?, ?, ?, ?, 'draft')",
            (platform, topic, content, hashtags, image_idea),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def queue_for_approval(date_folder: Path) -> Path:
    """
    Create a lightweight pointer file in approval_queue/ so a human knows
    a fresh batch of drafts is waiting. Returns the pointer path.
    """
    APPROVAL_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    pointer = APPROVAL_QUEUE_DIR / f"{date_folder.name}.txt"
    pointer.write_text(
        f"Drafts pending review.\nFolder: {date_folder}\nStatus: awaiting approval\n",
        encoding="utf-8",
    )
    return pointer


# --- Approval-time helpers -------------------------------------------------

def _connect() -> sqlite3.Connection:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_pending() -> list[dict]:
    """All posts currently in 'draft' status, oldest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, platform, topic, content, hashtags, image_idea, status, created_at "
            "FROM posts WHERE status = 'draft' ORDER BY created_at ASC, id ASC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def status_counts() -> dict[str, int]:
    """Return {status: count} across all posts."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM posts GROUP BY status"
        ).fetchall()
    finally:
        conn.close()
    return {r["status"]: r["n"] for r in rows}


def mark_status(post_id: int, status: str) -> None:
    """Set a post's status (e.g. 'approved' or 'rejected')."""
    conn = _connect()
    try:
        conn.execute("UPDATE posts SET status = ? WHERE id = ?", (status, post_id))
        conn.commit()
    finally:
        conn.close()


def record_history(topic: str, platform: str) -> None:
    """
    Insert a row into post_history when a draft is approved.
    Skips if (topic, platform, today) already exists so re-runs are idempotent.
    """
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT 1 FROM post_history "
            "WHERE topic = ? AND platform = ? AND date(posted_date) = date('now')",
            (topic, platform),
        ).fetchone()
        if existing:
            return
        conn.execute(
            "INSERT INTO post_history (topic, platform, posted_date) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (topic, platform),
        )
        conn.commit()
    finally:
        conn.close()


def clear_queue_pointer_if_done(date_str: str) -> bool:
    """
    Remove approval_queue/<date>.txt if no drafts remain for that date.
    Returns True if a pointer was removed.
    """
    pointer = APPROVAL_QUEUE_DIR / f"{date_str}.txt"
    if not pointer.exists():
        return False

    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM posts "
            "WHERE status = 'draft' AND date(created_at) = ?",
            (date_str,),
        ).fetchone()
    finally:
        conn.close()

    if row["n"] == 0:
        pointer.unlink()
        return True
    return False
