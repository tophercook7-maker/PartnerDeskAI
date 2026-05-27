"""
daily_runner.py
---------------
PartnerDeskAI v0.1 — Parker Promo

Entry point. Run:
    python automation/daily_runner.py

Pipeline:
    1. load business profile
    2. load Parker prompt
    3. load posting schedule
    4. load recent post history
    5. build final prompt
    6. call OpenAI API
    7. parse structured sections
    8. create dated output folder
    9. save markdown files
    10. insert draft records into SQLite
    11. queue for approval + write log
"""

import os
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

# Make sibling modules importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import memory_manager
import content_parser
import file_manager
import approval_manager


# --- Config ----------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

# Low temperature keeps the output structurally clean and easy to parse.
TEMPERATURE = 0.6


# --- Prompt builder --------------------------------------------------------

def build_user_prompt(
    business_profile: str,
    schedule_json: str,
    history_text: str,
    today: str,
) -> str:
    """Compose the user-side message that primes Parker for today's run."""
    return (
        f"Today's date: {today}\n\n"
        f"--- BUSINESS PROFILE ---\n{business_profile}\n\n"
        f"--- POSTING SCHEDULE ---\n{schedule_json}\n\n"
        f"--- RECENT POST HISTORY ---\n{history_text}\n\n"
        "Generate today's posts for all four platforms using the required "
        "section-delimited output format. Pick ONE topic for the day. "
        "Do not repeat any topic from recent history."
    )


# --- OpenAI call -----------------------------------------------------------

def call_openai(system_prompt: str, user_prompt: str) -> str:
    """Single chat completion call. Returns the raw assistant text."""
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to the .env file at the project root."
        )

    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return resp.choices[0].message.content or ""


# --- Topic extraction ------------------------------------------------------

def resolve_topic(sections: dict[str, str]) -> str:
    """
    Prefer the explicit ===TOPIC=== section Parker emits.
    If it's missing or empty, fall back to the first short line of any
    platform post so the run still completes cleanly.
    """
    explicit = sections.get("TOPIC", "").strip()
    if explicit:
        # Strip stray quotes/punctuation a model sometimes adds.
        return explicit.strip("\"'.").splitlines()[0][:80]

    for key in ("LINKEDIN", "FACEBOOK", "GOOGLE_BUSINESS_PROFILE", "INSTAGRAM"):
        text = sections.get(key, "").strip()
        if not text:
            continue
        first_line = text.splitlines()[0].strip()
        if first_line:
            # Trim to a short phrase so it fits as a topic tag.
            return " ".join(first_line.split()[:8])
    return "Daily Promo"


# --- Main ------------------------------------------------------------------

def main() -> None:
    log_lines: list[str] = []

    # 1. Memory loads
    business_profile = memory_manager.load_business_profile()
    parker_prompt = memory_manager.load_parker_prompt()
    schedule_json = memory_manager.load_posting_schedule()
    log_lines += [
        "Loaded business profile",
        "Loaded Parker prompt",
        "Loaded posting schedule",
    ]

    # 2. History (also ensures DB exists so query is safe)
    approval_manager.init_db()
    history = memory_manager.load_recent_history(days=14)
    history_text = memory_manager.format_history_for_prompt(history)
    log_lines.append(f"Loaded {len(history)} recent history rows")

    # 3. Build prompt
    today = datetime.now().strftime("%Y-%m-%d")
    user_prompt = build_user_prompt(
        business_profile=business_profile,
        schedule_json=schedule_json,
        history_text=history_text,
        today=today,
    )

    # 4. Call OpenAI
    print(f"Calling OpenAI ({OPENAI_MODEL})...")
    raw = call_openai(system_prompt=parker_prompt, user_prompt=user_prompt)
    log_lines.append("Generated content")

    # 5. Parse
    sections = content_parser.parse_sections(raw)
    topic = resolve_topic(sections)
    log_lines.append(f"Topic for today: {topic}")

    # 6. Write markdown files (TOPIC is metadata, not a file)
    folder = file_manager.get_daily_folder()
    written: list[Path] = []
    for key, content in sections.items():
        if key == "TOPIC" or not content:
            continue
        path = file_manager.write_markdown(folder, key, content, topic)
        written.append(path)
    log_lines.append(f"Saved {len(written)} markdown files to {folder}")

    # Also save the raw model output for debugging / reuse.
    (folder / "_raw_response.txt").write_text(raw, encoding="utf-8")

    # 7. SQLite draft records (one per platform section, not for CTA/IMAGE bundles).
    platform_keys = ("GOOGLE_BUSINESS_PROFILE", "FACEBOOK", "INSTAGRAM", "LINKEDIN")
    image_idea_first = (sections.get("IMAGE_IDEAS", "").splitlines() or [""])[0]
    inserted_ids: list[int] = []
    for key in platform_keys:
        content = sections.get(key, "").strip()
        if not content:
            continue
        row_id = approval_manager.insert_draft(
            platform=file_manager.FILE_MAP[key][1],
            topic=topic,
            content=content,
            hashtags="",  # could extract from Instagram in a future iteration
            image_idea=image_idea_first.lstrip("-• ").strip(),
        )
        inserted_ids.append(row_id)
    log_lines.append(f"Inserted {len(inserted_ids)} draft rows into posts table")

    # 8. Queue for approval + log
    pointer = approval_manager.queue_for_approval(folder)
    log_lines.append(f"Queued drafts for approval: {pointer}")

    file_manager.append_log(log_lines)
    print("Done.")
    print(f"  Folder:  {folder}")
    print(f"  Drafts:  {len(inserted_ids)} rows inserted")
    print(f"  Review:  {pointer}")


if __name__ == "__main__":
    main()
