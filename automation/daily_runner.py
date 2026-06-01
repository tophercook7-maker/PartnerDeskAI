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
import connection_state


# --- Config ----------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

# Low temperature keeps the output structurally clean and easy to parse.
TEMPERATURE = 0.6

# How many curated hashtags to pull per platform. Platforms not listed (or
# set to 0) won't receive a hashtag list. Matches Parker's prompt:
#   Instagram up to 6, Facebook 0–3, LinkedIn 0–3, GBP usually 0.
HASHTAG_COUNTS = {
    "instagram": 6,
    "facebook": 3,
    "linkedin": 3,
}

# v7.19: Generator skips platforms whose connection isn't verified.
# Section-key (used in Parker's output + the SQLite insert loop) ↔
# connection_state key (lowercase-with-underscores). Add new platforms
# here when they get wired up.
SECTION_TO_CONN_KEY = {
    "LINKEDIN":                "linkedin",
    "FACEBOOK":                "facebook",
    "GOOGLE_BUSINESS_PROFILE": "google_business_profile",
    "INSTAGRAM":               "instagram",
}

# Human labels for the prompt copy. Keys match connection_state keys.
PLATFORM_LABELS = {
    "linkedin":                "LinkedIn",
    "facebook":                "Facebook",
    "instagram":               "Instagram",
    "google_business_profile": "Google Business Profile",
}


def verified_platform_keys() -> set[str]:
    """
    Return the set of connection_state keys whose live trust state is
    'verified' right now. Defensive: read-only, returns empty set if
    nothing is verified. Used to short-circuit generation for
    unconfigured platforms so we don't pile up unshipping drafts.
    """
    cache = connection_state.load_states()
    return {
        k for k in connection_state.PLATFORM_ENV_KEYS
        if connection_state.compute_state(k, cache).get("state") == "verified"
    }


def _platforms_phrase(verified: set[str]) -> str:
    """Render a natural-language phrase listing verified platforms in
    a stable order. Used inside the user prompt."""
    ordered = [
        PLATFORM_LABELS[k] for k in
        ("linkedin", "facebook", "instagram", "google_business_profile")
        if k in verified
    ]
    if not ordered:
        return "no platforms"
    if len(ordered) == 1:
        return f"only {ordered[0]}"
    if len(ordered) == 2:
        return f"{ordered[0]} and {ordered[1]}"
    return ", ".join(ordered[:-1]) + f", and {ordered[-1]}"


# --- Prompt builder --------------------------------------------------------

def build_user_prompt(
    business_profile: str,
    schedule_json: str,
    history_text: str,
    today: str,
    chosen_topic: str,
    recent_topics: list[str],
    chosen_cta: str,
    recent_ctas: list[str],
    chosen_offer: str,
    recent_offers: list[str],
    hashtags_by_platform: dict[str, list[str]],
    recent_hashtags: list[str],
    enabled_platforms: set[str],
) -> str:
    """Compose the user-side message that primes Parker for today's run.

    enabled_platforms is the set of connection_state keys whose state is
    verified — Parker is told to ONLY emit sections for those. v7.19.
    """
    def _join(items: list[str]) -> str:
        return "; ".join(items) if items else "none yet"

    def _tags_line(tags: list[str]) -> str:
        return " ".join(tags) if tags else "(none — skip hashtags on this platform)"

    # v7.19: only show hashtag lines for verified platforms that actually
    # take hashtags. GBP normally uses none even when verified.
    hashtag_blocks = ""
    for plat in ("instagram", "facebook", "linkedin"):
        if plat in enabled_platforms:
            hashtag_blocks += (
                f"Recommended {PLATFORM_LABELS[plat]} hashtags:\n"
                f"{_tags_line(hashtags_by_platform.get(plat, []))}\n\n"
            )

    phrase = _platforms_phrase(enabled_platforms)

    return (
        f"Today's date: {today}\n\n"
        f"Recommended topic for today:\n{chosen_topic}\n"
        f"Avoid recently used topics: {_join(recent_topics)}\n\n"
        f"Recommended CTA for today:\n{chosen_cta}\n"
        f"Avoid recently used CTAs: {_join(recent_ctas)}\n\n"
        f"Recommended offer angle for today:\n{chosen_offer}\n"
        f"Avoid recently used offers: {_join(recent_offers)}\n\n"
        f"{hashtag_blocks}"
        f"Avoid recently used hashtags:\n{' '.join(recent_hashtags) if recent_hashtags else 'none yet'}\n\n"
        f"--- BUSINESS PROFILE ---\n{business_profile}\n\n"
        f"--- POSTING SCHEDULE ---\n{schedule_json}\n\n"
        f"--- RECENT POST HISTORY ---\n{history_text}\n\n"
        f"Generate today's posts for {phrase} using the required "
        "section-delimited output format. Emit a section ONLY for the "
        "platforms listed above; omit sections for any other platform. "
        "Use the recommended topic as the single topic for the day. "
        "Weave the recommended CTA (verbatim or lightly rephrased) into "
        "each platform post where natural. Reference the recommended "
        "offer angle in posts where it fits — don't force it into every "
        "post. Use the recommended hashtags per platform; do not invent "
        "unrelated hashtags. Google Business Profile should normally use "
        "no hashtags. Do not repeat any recent topic, CTA, offer, or "
        "hashtag."
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

    # v7.19: short-circuit if no platform is verified. Without this
    # guard the run would still call OpenAI (real cost) and emit drafts
    # the user can't ship. Returning early keeps the cron output honest.
    verified = verified_platform_keys()
    if not verified:
        msg = (
            "No platforms are verified — skipping draft generation. "
            "Verify a connection in the Hub (Connections section) and "
            "re-run."
        )
        print(msg)
        file_manager.append_log([msg])
        return
    log_lines.append(f"Verified platforms: {sorted(verified)}")

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

    # 3. Rotation memory: pick topic + CTA + offer + hashtags, gather recents.
    chosen_topic = memory_manager.choose_topic()
    recent_topics_list = memory_manager.get_recent_topics(limit=10)
    chosen_cta = memory_manager.choose_cta()
    recent_ctas_list = memory_manager.get_recent_ctas(limit=5)
    chosen_offer = memory_manager.choose_offer()
    recent_offers_list = memory_manager.get_recent_offers(limit=5)
    # v7.19: skip hashtag picks for unverified platforms.
    hashtags_by_platform = {
        platform: memory_manager.choose_hashtags(platform, limit=count)
        for platform, count in HASHTAG_COUNTS.items()
        if platform in verified
    }
    recent_hashtags_list = memory_manager.get_recent_hashtags(limit=10)
    log_lines.append(f"Chose topic: {chosen_topic}")
    log_lines.append(f"Chose CTA:   {chosen_cta}")
    log_lines.append(f"Chose offer: {chosen_offer}")
    for platform, tags in hashtags_by_platform.items():
        log_lines.append(f"Chose hashtags for {platform}: {tags}")

    # 4. Build prompt
    today = datetime.now().strftime("%Y-%m-%d")
    user_prompt = build_user_prompt(
        business_profile=business_profile,
        schedule_json=schedule_json,
        history_text=history_text,
        today=today,
        chosen_topic=chosen_topic,
        recent_topics=recent_topics_list,
        chosen_cta=chosen_cta,
        recent_ctas=recent_ctas_list,
        chosen_offer=chosen_offer,
        recent_offers=recent_offers_list,
        hashtags_by_platform=hashtags_by_platform,
        recent_hashtags=recent_hashtags_list,
        enabled_platforms=verified,
    )

    # 5. Call OpenAI
    print(f"Calling OpenAI ({OPENAI_MODEL})...")
    raw = call_openai(system_prompt=parker_prompt, user_prompt=user_prompt)
    log_lines.append("Generated content")

    # 6. Parse
    sections = content_parser.parse_sections(raw)
    topic = resolve_topic(sections)
    log_lines.append(f"Topic emitted by Parker: {topic}")

    # 7. Write markdown files (TOPIC is metadata, not a file)
    # v7.19: same filter as the SQLite loop below — skip writing platform
    # markdowns for unverified platforms. Auxiliary sections (CTA, image
    # ideas) are platform-agnostic and always write through.
    folder = file_manager.get_daily_folder()
    written: list[Path] = []
    for key, content in sections.items():
        if key == "TOPIC" or not content:
            continue
        if key in SECTION_TO_CONN_KEY and SECTION_TO_CONN_KEY[key] not in verified:
            continue
        path = file_manager.write_markdown(folder, key, content, topic)
        written.append(path)
    log_lines.append(f"Saved {len(written)} markdown files to {folder}")

    # Also save the raw model output for debugging / reuse.
    (folder / "_raw_response.txt").write_text(raw, encoding="utf-8")

    # 8. SQLite draft records (one per platform section, not for CTA/IMAGE bundles).
    # v7.19: filter to verified platforms. Defense-in-depth — even if
    # Parker ignores the prompt and emits an unverified-platform section,
    # we won't insert it, so the Ready pile stays free of unshipping
    # drafts. Sections we drop here get logged for visibility.
    platform_keys = tuple(
        sec for sec, conn_k in SECTION_TO_CONN_KEY.items()
        if conn_k in verified
    )
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
    # v7.19: surface any rogue sections Parker emitted for unverified
    # platforms so the user sees them in the cron log even though they
    # didn't make it into the DB.
    skipped = [
        sec for sec in SECTION_TO_CONN_KEY
        if sec not in platform_keys and sections.get(sec, "").strip()
    ]
    if skipped:
        log_lines.append(
            f"Skipped {len(skipped)} section(s) for unverified platforms: "
            f"{skipped}"
        )

    # 9. Queue for approval
    pointer = approval_manager.queue_for_approval(folder)
    log_lines.append(f"Queued drafts for approval: {pointer}")

    # 10. Rotation memory: record usage so picks rotate out next run.
    if memory_manager.update_topic_usage(chosen_topic):
        log_lines.append(f"Topic bank updated: {chosen_topic}")
    else:
        log_lines.append(f"Topic '{chosen_topic}' not in bank; usage not updated")
    if chosen_cta and memory_manager.update_cta_usage(chosen_cta):
        log_lines.append(f"CTA bank updated:   {chosen_cta}")
    if chosen_offer and memory_manager.update_offer_usage(chosen_offer):
        log_lines.append(f"Offer bank updated: {chosen_offer}")
    all_chosen_tags = [t for tags in hashtags_by_platform.values() for t in tags]
    if all_chosen_tags:
        n_tags = memory_manager.update_hashtag_usage(all_chosen_tags)
        log_lines.append(f"Hashtag bank updated: {n_tags} tag(s)")

    file_manager.append_log(log_lines)
    print("Done.")
    print(f"  Folder:  {folder}")
    print(f"  Drafts:  {len(inserted_ids)} rows inserted")
    print(f"  Review:  {pointer}")


if __name__ == "__main__":
    main()
