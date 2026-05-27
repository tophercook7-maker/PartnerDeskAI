"""
file_manager.py
---------------
Handles all filesystem writes: dated output folders, markdown drafts, and logs.
"""

from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DAILY_POSTS_DIR = ROOT / "daily_posts"
LOGS_DIR = ROOT / "logs"


# Mapping: section key -> (filename, platform label, topic-hint)
# The topic field is filled in at runtime from a single chosen topic for the day.
FILE_MAP = {
    "GOOGLE_BUSINESS_PROFILE": ("google_business_post.md", "Google Business Profile"),
    "FACEBOOK": ("facebook_post.md", "Facebook"),
    "INSTAGRAM": ("instagram_post.md", "Instagram"),
    "LINKEDIN": ("linkedin_post.md", "LinkedIn"),
    "CTA_SUGGESTIONS": ("cta_suggestions.md", "CTA Suggestions"),
    "IMAGE_IDEAS": ("image_ideas.md", "Image Ideas"),
}


def get_daily_folder(date: datetime | None = None) -> Path:
    """Create (if needed) and return the daily_posts/YYYY-MM-DD folder."""
    date = date or datetime.now()
    folder = DAILY_POSTS_DIR / date.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_markdown(folder: Path, section_key: str, content: str, topic: str) -> Path:
    """
    Write one section to a markdown file with metadata header.
    Returns the path written.
    """
    filename, platform_label = FILE_MAP[section_key]
    path = folder / filename
    generated = datetime.now().strftime("%Y-%m-%d %I:%M %p")

    body = (
        f"# Platform\n{platform_label}\n\n"
        f"# Topic\n{topic}\n\n"
        f"# Generated\n{generated}\n\n"
        f"# Status\nDraft\n\n"
        f"---\n\n"
        f"{content.strip()}\n"
    )

    path.write_text(body, encoding="utf-8")
    return path


def file_for_platform(date_str: str, platform_label: str) -> Path | None:
    """
    Given a date string and human-readable platform label (the value stored in
    the DB's platform column), return the markdown file path or None.
    """
    for filename, label in FILE_MAP.values():
        if label == platform_label:
            return DAILY_POSTS_DIR / date_str / filename
    return None


def append_log(lines: list[str]) -> Path:
    """Append timestamped lines to today's log file."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = LOGS_DIR / f"{today}.log"

    stamp = datetime.now().strftime("[%I:%M %p]")
    block = stamp + "\n" + "\n".join(lines) + "\n\n"

    with path.open("a", encoding="utf-8") as f:
        f.write(block)
    return path
