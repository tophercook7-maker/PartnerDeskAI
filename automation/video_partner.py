"""
video_partner.py
----------------
PartnerDeskAI Video Partner (v8.6). Local-business video creation +
marketing assistant. Generates approval-based video packages from
structured local templates — NO OpenAI, NO YouTube/TikTok/Instagram/
Facebook API, NO uploads.

Two persisted artifacts:
  - data/video_profile.json   : the business/video profile (single row)
  - data/video_packages.json  : list of generated packages

Sibling to youtube_partner.py (v8.5). Where YouTube Growth Partner is
focused on a single YouTube channel, Video Partner takes a broader
small-business video-marketing angle (cross-platform calendars, ad
scripts, shot lists, caption packs).

Package schema (mirrors v8.5):
    {
      "id":              "<timestamp string>",
      "title":           str,
      "content_type":    str,
      "status":          "draft" | "approved" | "used",
      "body":            str (markdown),
      "profile_snapshot": dict,
      "created_at":      "YYYY-MM-DD HH:MM:SS",
      "updated_at":      "YYYY-MM-DD HH:MM:SS",
    }
"""

from datetime import datetime
from pathlib import Path
import json
import os
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH  = ROOT / "data" / "video_profile.json"
PACKAGES_PATH = ROOT / "data" / "video_packages.json"

ALLOWED_CONTENT_TYPES = (
    "calendar",          # 30-day idea calendar
    "short_script",      # short-form script (Reels/Shorts/TikTok)
    "ad_script",         # local business ad
    "shot_list",         # scene-by-scene shot list
    "caption_pack",      # 5 platform-ready captions
    "metadata",          # title/description/hashtag pack
    "full",              # full campaign package
)
ALLOWED_STATUSES = ("draft", "approved", "used")
DEFAULT_STATUS = "draft"

MAX_TITLE_LEN = 200
MAX_BODY_LEN  = 30000


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


# --- Profile -----------------------------------------------------------

DEFAULT_PROFILE = {
    "business_name":    "",
    "niche":            "",
    "target_customer":  "",
    "offer":            "",
    "tone":             "",
    "platforms":        "",    # comma-separated, e.g. "TikTok, Instagram, YouTube Shorts"
    "video_length":     "",
    "call_to_action":   "",
}


def load_profile() -> dict:
    if not PROFILE_PATH.is_file():
        return dict(DEFAULT_PROFILE)
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_PROFILE)
    if not isinstance(data, dict):
        return dict(DEFAULT_PROFILE)
    out = dict(DEFAULT_PROFILE)
    for k in DEFAULT_PROFILE:
        if k in data and isinstance(data[k], str):
            out[k] = data[k].strip()[:500]
    return out


def save_profile(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("profile must be a dict")
    cur = load_profile()
    for k in DEFAULT_PROFILE:
        if k in raw and raw[k] is not None:
            cur[k] = str(raw[k]).strip()[:500]
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".video_profile.", suffix=".tmp", dir=str(PROFILE_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2)
            f.write("\n")
        os.replace(tmp, PROFILE_PATH)
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
        prefix=".video_packages.", suffix=".tmp", dir=str(PACKAGES_PATH.parent),
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
    content_type = (raw.get("content_type") or ex.get("content_type") or "calendar").strip()
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
        "profile_snapshot": raw.get("profile_snapshot") or ex.get("profile_snapshot") or {},
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


# --- Generators (all local, NO OpenAI, NO web calls) ----------------

def _pp(profile: dict, key: str, fallback: str = "") -> str:
    """Pick from profile; fall back to spec's friendly defaults when the
    user has skipped the field. Keeps generated content readable instead
    of stuck on placeholder phrases like 'your business'."""
    _DEFAULTS = {
        "business_name":   "Your Business",
        "niche":            "local service business",
        "target_customer":  "local customers",
        "offer":             "your main service",
        "tone":              "friendly and helpful",
        "platforms":         "Facebook, Instagram, TikTok, YouTube",
        "video_length":      "30-60 seconds",
        "call_to_action":    "Contact us today",
    }
    v = (profile or {}).get(key) or ""
    v = v.strip()
    if v:
        return v
    return fallback or _DEFAULTS.get(key, fallback)


def generate_calendar(profile: dict, count: int = 30) -> str:
    """30-day video idea calendar. One idea per day, each tagged with a
    content angle. Rotates through angle types so the calendar feels
    varied. Local template — review and customize each entry."""
    if count < 1 or count > 60:
        raise ValueError("count must be 1..60")
    biz   = _pp(profile, "business_name",   "your business")
    niche = _pp(profile, "niche",           "your niche")
    cust  = _pp(profile, "target_customer", "your customer")
    offer = _pp(profile, "offer",           "your offer")
    cta   = _pp(profile, "call_to_action",  "your CTA")
    angles = [
        ("Hook reel",        "30-60s opener. State the customer's pain in one line, promise the payoff."),
        ("Tutorial",         "Show one process step. Talking head + screen / hands. Slow enough to copy."),
        ("Behind-the-scenes","Camera moves through your workspace. Real, not staged."),
        ("Customer story",   "Before / during / after of one real {cust}. Keep it specific."),
        ("Common mistake",   "Name a mistake {cust} make. Show what to do instead."),
        ("Quick fix",        "Under 60s — one tactical thing they can do today."),
        ("Tool tour",        "The 1–3 tools you use most. Why each beats the alternative."),
        ("Myth bust",        "A {niche} myth. Counter with a real example."),
        ("Q&A",              "Real question from this week + your real answer."),
        ("Comparison",       "Two approaches you've tested. Which won, why."),
    ]
    lines = [
        f"# {count}-day video idea calendar — {biz}",
        "",
        f"_Niche:_ {niche}  ·  _Customer:_ {cust}  ·  _Offer:_ {offer}",
        "",
        f"| Day | Angle | Idea | CTA |",
        f"|-----|-------|------|-----|",
    ]
    for i in range(count):
        angle_name, angle_desc = angles[i % len(angles)]
        angle_desc = angle_desc.format(cust=cust, niche=niche)
        lines.append(
            f"| {i+1} | {angle_name} | "
            f"{angle_desc[:60]}{'…' if len(angle_desc) > 60 else ''} | "
            f"{cta[:40]}{'…' if len(cta) > 40 else ''} |"
        )
    lines.append("")
    lines.append("---")
    lines.append(
        "_Local template — review each entry. Swap any day you've already "
        "shot. The goal is a weekly cadence (5 keepers per 7 days, 2 rest)._"
    )
    lines.append("")
    lines.append(
        "**Review required before publishing. This tool prepares content only.**"
    )
    return "\n".join(lines)


def write_short_form_script(profile: dict, topic: str) -> str:
    topic = (topic or "").strip() or "Untitled short"
    biz   = _pp(profile, "business_name",   "your business")
    cust  = _pp(profile, "target_customer", "your customer")
    cta   = _pp(profile, "call_to_action",  "your CTA")
    return f"""# Short-form script — {topic}

_Business:_ {biz}  ·  _Customer:_ {cust}  ·  _Length target:_ 30–60s

---

## Hook (0:00–0:03)

> Camera tight on subject (hands, screen, face). NO logo intro, NO "hey guys".
> Line: "If you {{cust}} ever {{specific pain}}, this 30 seconds is for you."

## Setup (0:03–0:10)

- Show the pain in one frame (clutter, error message, slow page, missed call).
- One sentence: "This is what most {cust} do — and why it doesn't work."

## Reveal (0:10–0:35)

- The fix, in 1–2 steps. Show on screen if you can.
- Voiceover stays calm, doesn't oversell.
- One concrete proof point — "I did this for [example] and they went from X to Y."

## CTA (0:35–0:55)

- "{cta}"
- Make it specific. No "follow for more" — give them a real next step.

---

## On-screen text plan

- 0:00 — pain in 4 words, top third.
- 0:10 — "do this instead" mid-frame.
- 0:35 — CTA pinned bottom.

## Captions style

- 1–2 lines max per beat.
- Yellow on dark background, sans-serif bold.

---

**Review required before publishing. This tool prepares content only.**
"""


def write_local_ad_script(profile: dict, topic: str) -> str:
    topic = (topic or "").strip() or "Untitled local ad"
    biz   = _pp(profile, "business_name",   "your business")
    niche = _pp(profile, "niche",           "your niche")
    cust  = _pp(profile, "target_customer", "your customer")
    offer = _pp(profile, "offer",           "your offer")
    cta   = _pp(profile, "call_to_action",  "your CTA")
    return f"""# Local business ad — {topic}

_Business:_ {biz}  ·  _Niche:_ {niche}  ·  _Length target:_ 30s

> This is an AD, not a content video. Optimize for clarity + a single
> ask. Pay-once production: shoot all 3 cuts in one session.

---

## 30-second version

**Beat 1 (0:00–0:05) — the problem**
- One-sentence problem statement that {cust} hear themselves saying.
- Example: "Most {cust} are losing customers to a website nobody can find."

**Beat 2 (0:05–0:15) — what you do**
- Plain English: who you are + what you fix.
- {biz} helps {cust} with {offer}.

**Beat 3 (0:15–0:25) — proof**
- One number or one specific example. Real, not invented.
- Example: "We rebuilt [neighbor business]'s site in a week — calls up 40%."

**Beat 4 (0:25–0:30) — the ask**
- {cta}
- Show phone number, web URL, OR scan code on screen the whole final beat.

---

## 15-second cutdown

Pain → fix → ask. One sentence each. Cut the proof beat.

## 60-second cutdown

Add a second proof point (different customer) + show a behind-the-scenes shot.

---

## Production notes

- Shoot all 3 lengths in one session — same wardrobe, same location.
- No music swells. Local + direct beats "produced" every time.
- End frame must show: business name, phone, web. Hold for 3 seconds minimum.
- If you can't show proof, cut Beat 3. Better silence than fake.

---

**Review required before publishing. This tool prepares content only.**
"""


def generate_shot_list(profile: dict, topic: str) -> str:
    topic = (topic or "").strip() or "Untitled video"
    biz   = _pp(profile, "business_name",   "your business")
    return f"""# Shot list — {topic}

_Business:_ {biz}

> Capture all of these in one shoot day if possible. Wide → medium →
> tight, with intentional B-roll. Everything is reusable across
> long-form, Shorts, and the ad.

---

## A-roll (talking-head / on-camera)

| # | Shot | Lens / framing | Notes |
|---|------|----------------|-------|
| A1 | Open: full-body, room visible | Wide, eye level | Establishes credibility |
| A2 | Main talking-head | Medium, chest-up | Most of the video lives here |
| A3 | Close reaction | Tight | For emphasis / cutaway |
| A4 | Address-camera CTA at end | Medium, slight zoom-in | The ask |

## B-roll (no audio, used for cutaways)

| # | Shot | Notes |
|---|------|-------|
| B1 | Hands working on the thing | Tight, fluid |
| B2 | Screen recording / device close | Captured separately, paste in edit |
| B3 | Customer or workspace wide | Establishes "this is real" |
| B4 | Product / output close-up | Final result, well-lit |
| B5 | Receipt shot | Invoice, calendar, message — proof |

## Cutdown shots (Shorts / TikTok)

| # | Shot | Notes |
|---|------|-------|
| C1 | Vertical opener — same as A2 but reframed | Top third stays clear for caption |
| C2 | Vertical close on hands | Highest engagement frame |
| C3 | Vertical CTA — phone number on screen | End card |

---

## Audio

- Lav mic on main subject. Backup: phone propped close.
- Capture 30s room tone for editor.
- No copyrighted music; royalty-free or original.

## Coverage checklist (before wrap)

- [ ] Every A-roll line covered twice (safety take).
- [ ] At least 60s of B-roll per major beat.
- [ ] One unplanned candid moment (best cutaway you'll get).
- [ ] All 3 cutdown shots vertical.

---

**Review required before publishing. This tool prepares content only.**
"""


def generate_caption_pack(profile: dict, topic: str, count: int = 5) -> str:
    if count < 1 or count > 10:
        raise ValueError("count must be 1..10")
    topic = (topic or "").strip() or "Untitled video"
    biz   = _pp(profile, "business_name",   "your business")
    cust  = _pp(profile, "target_customer", "your customer")
    cta   = _pp(profile, "call_to_action",  "your CTA")
    plats = _pp(profile, "platforms",       "Instagram, TikTok, YouTube Shorts, Facebook")
    captions = [
        f"Most {cust} ask me this every week. Here's the 30-second answer.\\n\\n{cta}",
        f"If you're trying to {{specific outcome}}, watch this before you do anything else.\\n\\n{cta}",
        f"I tested two versions of this for {biz}. Only one worked. Showing both.\\n\\n{cta}",
        f"Don't {{common bad action}} until you watch this.\\n\\n{cta}",
        f"Real customer message we got this week → here's what we did about it.\\n\\n{cta}",
        f"3 things {cust} can stop doing today.\\n\\n{cta}",
        f"Quick fix that takes 9 minutes. Most folks skip it. Don't.\\n\\n{cta}",
    ]
    lines = [f"# Caption pack — {topic}", "", f"_Platforms:_ {plats}", ""]
    for i in range(count):
        cap = captions[i % len(captions)]
        lines += [
            f"## Caption #{i+1}",
            "",
            "```",
            cap.replace("\\n\\n", "\n\n"),
            "```",
            "",
            "_Edit the bracketed placeholders. Keep it under 220 chars for "
            "Instagram/TikTok readability._",
            "",
        ]
    lines.append("---")
    lines.append("")
    lines.append("**Review required before publishing. This tool prepares content only.**")
    return "\n".join(lines)


def generate_metadata(profile: dict, topic: str) -> str:
    topic = (topic or "").strip() or "Untitled video"
    biz   = _pp(profile, "business_name",   "your business")
    niche = _pp(profile, "niche",           "your niche")
    cust  = _pp(profile, "target_customer", "your customer")
    offer = _pp(profile, "offer",           "your offer")
    cta   = _pp(profile, "call_to_action",  "your CTA")
    plats = _pp(profile, "platforms",       "YouTube, Instagram, TikTok, Facebook")
    return f"""# Title · Description · Hashtags — {topic}

_Business:_ {biz}  ·  _Platforms:_ {plats}

## 5 Title options

1. How {cust} can {{outcome}} in {{time}}
2. The biggest {niche} mistake (and the 3-step fix)
3. I tried {{specific approach}} — here's what happened
4. Don't {{common action}} until you watch this
5. {{N}} things {cust} should stop doing today

_Pick the one that's both true and clickable. Edit bracketed placeholders._

## Long-form description

```
{topic}

In this video I show {cust} the exact {{thing}} I'd do today
to {{outcome}}.

Timestamps:
0:00 Intro
0:15 The trap
2:30 What to do instead
4:30 How to know it's working

Want help?
{cta}

About {biz}:
{offer}

---

Music / sources / credits go here.
```

## Short-form caption

```
Most {cust} miss this.
30 seconds to fix it.

{cta}
```

## Hashtags (3–5 per platform)

- **YouTube:** #{niche.replace(' ', '')} #SmallBusiness #LocalBusiness
- **Instagram:** #{niche.replace(' ', '')} #{cust.replace(' ', '')} #smallbiz #behindthescenes
- **TikTok:** #{niche.replace(' ', '')} #smallbusiness #fyp
- **Facebook:** #{niche.replace(' ', '')} #shoplocal

## Tags (long-form, 10–15 comma-separated)

{niche}, {cust}, how to {niche}, {niche} tips, small business,
local business, behind the scenes, {biz}, tutorial, real example,
beginner, before after, quick fix

---

**Review required before publishing. This tool prepares content only.**
"""


def build_full_campaign(profile: dict, topic: str) -> str:
    """One topic → every artifact, composed."""
    topic = (topic or "").strip() or "Untitled campaign"
    parts = [
        f"# 🎬 Full Video Campaign — {topic}",
        "",
        f"> **Status:** draft. Review every section before recording.",
        f"> No social account is connected — nothing will publish.",
        "",
        "---",
        "",
        write_short_form_script(profile, topic),
        "",
        "---",
        "",
        write_local_ad_script(profile, topic),
        "",
        "---",
        "",
        generate_shot_list(profile, topic),
        "",
        "---",
        "",
        generate_caption_pack(profile, topic, count=3),
        "",
        "---",
        "",
        generate_metadata(profile, topic),
        "",
        "---",
        "",
        "**Review required before publishing. This tool prepares content only.**",
    ]
    return "\n".join(parts)


# --- High-level API used by the endpoints -----------------------------

def generate_package(content_type: str, topic: str = "", count: int = 30) -> dict:
    """Generate + persist a package as a draft. Returns the saved row."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"content_type must be one of {ALLOWED_CONTENT_TYPES}, "
            f"got {content_type!r}"
        )
    profile = load_profile()
    if content_type == "calendar":
        title = f"{count}-day calendar — {datetime.now().strftime('%Y-%m-%d')}"
        body = generate_calendar(profile, count=count)
    elif content_type == "short_script":
        title = f"Short script — {topic or 'untitled'}"
        body = write_short_form_script(profile, topic)
    elif content_type == "ad_script":
        title = f"Local ad — {topic or 'untitled'}"
        body = write_local_ad_script(profile, topic)
    elif content_type == "shot_list":
        title = f"Shot list — {topic or 'untitled'}"
        body = generate_shot_list(profile, topic)
    elif content_type == "caption_pack":
        title = f"{count} captions — {topic or 'untitled'}"
        body = generate_caption_pack(profile, topic, count=count)
    elif content_type == "metadata":
        title = f"Metadata — {topic or 'untitled'}"
        body = generate_metadata(profile, topic)
    elif content_type == "full":
        title = f"Full campaign — {topic or 'untitled'}"
        body = build_full_campaign(profile, topic)
    else:  # unreachable
        raise ValueError(f"unknown content_type: {content_type!r}")
    return add_package({
        "title":            title,
        "content_type":     content_type,
        "status":           DEFAULT_STATUS,
        "body":             body,
        "profile_snapshot": profile,
    })
