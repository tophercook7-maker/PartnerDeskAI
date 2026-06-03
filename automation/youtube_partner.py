"""
youtube_partner.py
------------------
YouTube Growth Partner (v8.5). Generates content packages from local
templates for a single business's YouTube channel.

Two persisted artifacts:
  - data/youtube_channel.json  : the channel profile (one row, free-edit)
  - data/youtube_packages.json : list of generated packages

NO OpenAI. NO YouTube API. NO uploads. NO scraping. Generation is
pure local string formatting; the human reviews and rewrites the
draft before recording. The 'Connected Accounts' panel is a future-
ready placeholder; nothing is currently wired to any social API.

Package schema:
    {
      "id":            "<timestamp string>",
      "title":         str,
      "content_type":  "ideas" | "script" | "shorts" | "thumbnails" |
                       "metadata" | "full",
      "status":        "draft" | "approved" | "used",
      "body":          str (markdown),
      "channel_snapshot": dict (the channel profile at gen time),
      "created_at":    "YYYY-MM-DD HH:MM:SS",
      "updated_at":    "YYYY-MM-DD HH:MM:SS",
    }
"""

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
CHANNEL_PATH  = ROOT / "data" / "youtube_channel.json"
PACKAGES_PATH = ROOT / "data" / "youtube_packages.json"

ALLOWED_CONTENT_TYPES = (
    "ideas", "script", "shorts", "thumbnails", "metadata", "full",
)
ALLOWED_STATUSES = ("draft", "approved", "used")
DEFAULT_STATUS = "draft"

MAX_TITLE_LEN = 200
MAX_BODY_LEN  = 20000

# Connected Accounts — static placeholder list. Nothing here is wired
# to a real social API yet; cards render as 'Not connected' / 'Coming
# soon'. Order is alphabetical except for YouTube first (Partner's
# primary surface).
CONNECTED_ACCOUNTS = [
    {"key": "youtube",   "name": "YouTube",   "status": "not_connected"},
    {"key": "facebook",  "name": "Facebook",  "status": "not_connected"},
    {"key": "instagram", "name": "Instagram", "status": "not_connected"},
    {"key": "linkedin",  "name": "LinkedIn",  "status": "not_connected"},
    {"key": "tiktok",    "name": "TikTok",    "status": "not_connected"},
    {"key": "x",         "name": "X",         "status": "not_connected"},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(items: list[dict]) -> str:
    base = str(int(time.time() * 1000))
    existing = {it.get("id") for it in items}
    cand = base
    n = 0
    while cand in existing:
        n += 1
        cand = f"{base}-{n}"
    return cand


# --- Channel profile ---------------------------------------------------

DEFAULT_CHANNEL = {
    "channel_niche":     "",
    "target_audience":   "",
    "video_style":       "",
    "tone":              "",
    "main_offer_cta":    "",
    "preferred_length":  "",
    "focus":             "longform",  # "longform" or "shorts"
}


def load_channel() -> dict:
    if not CHANNEL_PATH.is_file():
        return dict(DEFAULT_CHANNEL)
    try:
        data = json.loads(CHANNEL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CHANNEL)
    if not isinstance(data, dict):
        return dict(DEFAULT_CHANNEL)
    out = dict(DEFAULT_CHANNEL)
    for k in DEFAULT_CHANNEL:
        if k in data and isinstance(data[k], str):
            out[k] = data[k].strip()[:500]
    if data.get("focus") in ("longform", "shorts"):
        out["focus"] = data["focus"]
    return out


def save_channel(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("channel must be a dict")
    cur = load_channel()
    for k in DEFAULT_CHANNEL:
        if k in raw and raw[k] is not None:
            v = str(raw[k]).strip()[:500]
            cur[k] = v
    if raw.get("focus") in ("longform", "shorts"):
        cur["focus"] = raw["focus"]
    CHANNEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".youtube_channel.", suffix=".tmp", dir=str(CHANNEL_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2)
            f.write("\n")
        os.replace(tmp, CHANNEL_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return cur


# --- Packages CRUD -----------------------------------------------------

def load_packages() -> list[dict]:
    if not PACKAGES_PATH.is_file():
        return []
    try:
        data = json.loads(PACKAGES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return items if isinstance(items, list) else []


def _save_packages(items: list[dict]) -> None:
    PACKAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".youtube_packages.", suffix=".tmp", dir=str(PACKAGES_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"items": items}, f, indent=2)
            f.write("\n")
        os.replace(tmp, PACKAGES_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def _clean_package(raw: dict, existing: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("package must be a dict")
    ex = existing or {}
    title = str(raw.get("title") or ex.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    content_type = (raw.get("content_type") or ex.get("content_type") or "ideas").strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"content_type must be one of {ALLOWED_CONTENT_TYPES}, got {content_type!r}"
        )
    status = (raw.get("status") or ex.get("status") or DEFAULT_STATUS).strip()
    if status not in ALLOWED_STATUSES:
        raise ValueError(
            f"status must be one of {ALLOWED_STATUSES}, got {status!r}"
        )
    return {
        "id":              ex.get("id") or raw.get("id"),
        "title":           title[:MAX_TITLE_LEN],
        "content_type":    content_type,
        "status":          status,
        "body":            str(raw.get("body") or ex.get("body") or "")[:MAX_BODY_LEN],
        "channel_snapshot": raw.get("channel_snapshot") or ex.get("channel_snapshot") or {},
        "created_at":      ex.get("created_at") or _now(),
        "updated_at":      _now(),
    }


def add_package(raw: dict) -> dict:
    items = load_packages()
    cleaned = _clean_package(raw)
    cleaned["id"] = _next_id(items)
    cleaned["created_at"] = _now()
    cleaned["updated_at"] = cleaned["created_at"]
    items.append(cleaned)
    _save_packages(items)
    return cleaned


def update_package(pkg_id: str, raw: dict) -> dict:
    items = load_packages()
    for i, it in enumerate(items):
        if it.get("id") == pkg_id:
            merged = _clean_package(raw, existing=it)
            merged["id"] = pkg_id
            items[i] = merged
            _save_packages(items)
            return merged
    raise KeyError(pkg_id)


def delete_package(pkg_id: str) -> bool:
    items = load_packages()
    before = len(items)
    items = [it for it in items if it.get("id") != pkg_id]
    if len(items) == before:
        return False
    _save_packages(items)
    return True


# --- Generators (all local, NO OpenAI) --------------------------------

def _channel_or_placeholder(channel: dict, key: str, fallback: str) -> str:
    v = (channel or {}).get(key) or ""
    return v.strip() or fallback


def generate_ideas(channel: dict, count: int = 10) -> str:
    """Generate `count` video idea slots based on the channel profile.
    Output is a markdown list. The user fills in / refines each slot
    before turning any into a script."""
    if count < 1 or count > 30:
        raise ValueError("count must be 1..30")
    niche    = _channel_or_placeholder(channel, "channel_niche",   "your niche")
    audience = _channel_or_placeholder(channel, "target_audience", "your target audience")
    offer    = _channel_or_placeholder(channel, "main_offer_cta",  "your offer")
    style    = _channel_or_placeholder(channel, "video_style",     "your video style")
    # 10 evergreen content angles for any small-business channel.
    angles = [
        "Day-in-the-life walkthrough",
        "Top 5 mistakes {audience} make",
        "How we do X faster than competitors",
        "Behind-the-scenes of {offer}",
        "Free version of what we sell — and when to upgrade",
        "Quick fix tutorial under 3 minutes",
        "Common myth about {niche}",
        "Customer transformation story",
        "Tool / supply / setup tour",
        "Q&A: real questions we get this week",
        "Compare two approaches we tested",
        "What we'd do differently — lessons learned",
    ]
    lines = [
        f"# {count} Video Ideas",
        "",
        f"_Channel:_ {niche}  ·  _Audience:_ {audience}  ·  _Style:_ {style}",
        "",
    ]
    for i in range(count):
        angle = angles[i % len(angles)].format(
            audience=audience, niche=niche, offer=offer,
        )
        lines.append(f"{i+1}. **{angle}**")
        lines.append(
            f"   - Why it works: {audience} get a specific, useful "
            f"takeaway in <90 seconds."
        )
        lines.append(
            f"   - Hook seed: \"If you're a {audience}, the next 60 "
            f"seconds will save you a week.\""
        )
        lines.append(
            f"   - CTA: tie back to {offer}."
        )
        lines.append("")
    lines.append("---")
    lines.append("_Draft template. Review and customize before recording. "
                 "Nothing here was generated by an LLM — it's a structured "
                 "starting point._")
    return "\n".join(lines)


def write_script(channel: dict, topic: str) -> str:
    """Write a full long-form script structure for a given topic.
    Local template with hook → context → 3-point body → CTA."""
    topic = (topic or "").strip() or "Untitled video"
    niche    = _channel_or_placeholder(channel, "channel_niche",   "your niche")
    audience = _channel_or_placeholder(channel, "target_audience", "your audience")
    tone     = _channel_or_placeholder(channel, "tone",            "warm and direct")
    offer    = _channel_or_placeholder(channel, "main_offer_cta",  "your offer")
    length   = _channel_or_placeholder(channel, "preferred_length", "6-9 minutes")
    return f"""# Script: {topic}

_Target length:_ {length}  ·  _Tone:_ {tone}  ·  _Audience:_ {audience}

---

## Hook (0:00–0:15)

> Open with a specific, audience-shaped promise. Example structure:
> "If you {{audience}}, here's the {{specific outcome}} I'll show in the next {{length}}. No fluff."

Action: state {audience}'s exact pain in one sentence, then promise the
payoff. Cut to camera close-up.

## Context (0:15–0:45)

- Who you are (1 line, no resume).
- Why this matters TODAY for {audience}.
- One sentence credibility (real example or number).

## Point 1 — The trap most {audience} fall into (0:45–2:30)

- Name the trap.
- Show why it FEELS right (so viewers don't dismiss).
- Brief story or visual proof.
- One-liner takeaway.

## Point 2 — What to do instead (2:30–4:30)

- The actual technique / approach.
- Step-by-step (3 steps max).
- Show on screen if possible.
- Address the "but what about" objection.

## Point 3 — How to know it's working (4:30–6:00)

- The measurable signal viewers should watch for.
- What to do if it doesn't work yet.
- Optional: comparison before/after.

## Recap + CTA (6:00–end)

- 3-line recap (one per point).
- Tease the next video.
- CTA: {offer}.

---

## B-roll ideas

- Tight shots of the work being done (hands, tools, screen recordings).
- Whiteboard / paper sketch of Point 2 steps.
- "Receipt" — calendar, invoice, customer message — for the credibility line.
- Reaction shots in the editing pass.

## Pinned comment

> _Reply with the part of this you want me to go deeper on — I'll
> make a follow-up._

_Channel context: {niche}._

---

_Draft script template. Review every line. Replace bracketed prompts
with your own specifics. Record only what feels true._
"""


def create_shorts(channel: dict, count: int = 5) -> str:
    """Generate `count` Shorts (30-60s) cutdowns / standalone concepts.
    Each Short has hook, beats, on-screen text plan, and one CTA."""
    if count < 1 or count > 15:
        raise ValueError("count must be 1..15")
    niche    = _channel_or_placeholder(channel, "channel_niche",   "your niche")
    audience = _channel_or_placeholder(channel, "target_audience", "your audience")
    offer    = _channel_or_placeholder(channel, "main_offer_cta",  "your offer")
    short_seeds = [
        ("The 10-second version of {niche}",  "Show your single best output, no intro."),
        ("Why {audience} keep failing at X",   "Name the trap, show one fix."),
        ("Before / After — same hour",         "Visual juxtaposition, no talking head."),
        ("Question we get every week",         "Question on screen, fast answer."),
        ("Tool tour — the only 3 we need",     "Quick visual of the 3, no explanation."),
        ("Common myth: bust it",               "Myth + counterexample + receipt."),
        ("Real client message → our action",   "Screenshot + reaction + outcome."),
        ("Cost breakdown of {offer}",          "Honest numbers on screen."),
    ]
    lines = [f"# {count} Shorts", ""]
    for i in range(count):
        title_tmpl, beats = short_seeds[i % len(short_seeds)]
        title = title_tmpl.format(niche=niche, audience=audience, offer=offer)
        lines += [
            f"## Short #{i+1} — {title}",
            f"- **Length:** 30–60s",
            f"- **Hook (0:00–0:03):** start mid-action, no logo, no \"hey guys\".",
            f"- **Beats:** {beats}",
            f"- **On-screen text:** big, top third, one short line per beat.",
            f"- **CTA (last 2s):** \"More like this on the channel.\" "
                f"(Optional tie-in: {offer}.)",
            "",
        ]
    lines.append("---")
    lines.append("_Local template — no LLM was called. Customize the wording, "
                 "shoot vertically, leave room for top-third on-screen text._")
    return "\n".join(lines)


def generate_thumbnails(channel: dict, topic: str) -> str:
    topic = (topic or "").strip() or "Untitled video"
    audience = _channel_or_placeholder(channel, "target_audience", "your audience")
    return f"""# Thumbnail concepts — {topic}

3 directions. Pick one and shoot a frame for it.

## Direction A — Outcome shot
- **Subject:** the finished result (clean, lit, close).
- **Text:** 2–3 words, top-left, bold sans-serif. Example: "DONE IN 9 MIN".
- **Face:** small reaction in corner (optional).
- **Color:** one accent that pops against your usual feed colors.

## Direction B — Before/After split
- **Layout:** vertical split, before-left / after-right.
- **Text:** "BEFORE / AFTER" or a single number (e.g. "$0 → $300").
- **Face:** none — let the contrast carry.
- **Color:** desaturate the BEFORE side, full color on AFTER.

## Direction C — Question + face
- **Subject:** your face mid-react, mouth slightly open.
- **Text:** a question {audience} actually ask. Example: "WHY IS THIS BROKEN?".
- **Layout:** text fills top half, face fills bottom half.
- **Color:** high contrast — yellow on dark, or red on white.

---

_Pick one direction, mock it in your phone's photo app, A/B over 24h.
No LLM was used; these are reusable thumbnail patterns._
"""


def generate_metadata(channel: dict, topic: str) -> str:
    topic = (topic or "").strip() or "Untitled video"
    niche    = _channel_or_placeholder(channel, "channel_niche",   "your niche")
    audience = _channel_or_placeholder(channel, "target_audience", "your audience")
    offer    = _channel_or_placeholder(channel, "main_offer_cta",  "your offer")
    titles = [
        f"How {audience} can {{outcome}} in {{time}}",
        f"The biggest {niche} mistake (and the 3-step fix)",
        f"I tried {{specific approach}} — here's what happened",
        f"Don't {{common action}} until you watch this",
        f"{{number}} things {audience} should stop doing today",
    ]
    titles = [t.replace("{outcome}", "[outcome]")
                .replace("{time}",    "[time]")
                .replace("{specific approach}", "[approach]")
                .replace("{common action}", "[action]")
                .replace("{number}", "[N]")
              for t in titles]
    return f"""# Titles · Description · Tags — {topic}

## 5 Title options

{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(titles))}

_Pick the one that's both true and clickable. Edit for your specifics._

## Description

```
{topic}

In this video I show {audience} the exact {{thing}} I'd do today
to {{outcome}}.

Timestamps:
0:00 Intro
0:15 The trap
2:30 What to do instead
4:30 How to know it's working

Want help? {offer}

---

Music / sources / credits go here.
```

## Hashtags (3–5, real ones only)

#{niche.replace(' ', '')} #{audience.replace(' ', '')} #SmallBusiness

## Tags (10–15, comma-separated)

{niche}, {audience}, how to {niche}, {niche} tips,
small business, behind the scenes,
[your business name], [your city], [your niche keyword],
tutorial, beginner, real example

---

_Template — fill in bracketed placeholders. No LLM was called._
"""


def build_full_package(channel: dict, topic: str) -> str:
    """Compose every artifact into one markdown package."""
    topic = (topic or "").strip() or "Untitled video"
    parts = [
        f"# 📦 Full Video Package — {topic}",
        "",
        f"> **Status:** draft. Review every section before recording. ",
        f"> No social-account is connected yet — nothing will publish.",
        "",
        "---",
        "",
        write_script(channel, topic),
        "",
        "---",
        "",
        create_shorts(channel, count=3),
        "",
        "---",
        "",
        generate_thumbnails(channel, topic),
        "",
        "---",
        "",
        generate_metadata(channel, topic),
    ]
    return "\n".join(parts)


# --- High-level API used by the endpoints -----------------------------

def generate_package(content_type: str, topic: str = "", count: int = 10) -> dict:
    """Generate a content package and store it as a draft. Returns the
    saved row. Raises ValueError for unknown content_type."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"content_type must be one of {ALLOWED_CONTENT_TYPES}, "
            f"got {content_type!r}"
        )
    channel = load_channel()
    if content_type == "ideas":
        title = f"{count} video ideas — {datetime.now().strftime('%Y-%m-%d')}"
        body = generate_ideas(channel, count=count)
    elif content_type == "script":
        title = f"Script — {topic or 'untitled'}"
        body = write_script(channel, topic)
    elif content_type == "shorts":
        title = f"{count} Shorts pack — {datetime.now().strftime('%Y-%m-%d')}"
        body = create_shorts(channel, count=count)
    elif content_type == "thumbnails":
        title = f"Thumbnail concepts — {topic or 'untitled'}"
        body = generate_thumbnails(channel, topic)
    elif content_type == "metadata":
        title = f"Metadata — {topic or 'untitled'}"
        body = generate_metadata(channel, topic)
    elif content_type == "full":
        title = f"Full package — {topic or 'untitled'}"
        body = build_full_package(channel, topic)
    else:  # unreachable due to validation above
        raise ValueError(f"unknown content_type: {content_type!r}")
    return add_package({
        "title":            title,
        "content_type":     content_type,
        "status":           DEFAULT_STATUS,
        "body":             body,
        "channel_snapshot": channel,
    })
