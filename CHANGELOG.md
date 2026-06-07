# PartnerDeskAI Changelog

Newest first. v12.5 is the current shipped version.

---

## v12.5 — Real customer-facing polish

v12.4 nailed the layout + plain language. v12.5 polishes the
moment-to-moment experience — the in-flight feel that's the
difference between "software" and "coworkers". All frontend +
a tiny router keyword tweak. No new endpoints, no new data files.

### Staged conversation arrival

v12.3's auto-delegation returned all 5+ messages at once — Olivia
+ Logan + Parker + Video + Olivia would appear simultaneously, like
batch output. v12.5 stages them client-side: each partner's
message renders after a short typing pause (~350-750ms), with the
typing indicator cycling between partners. The conversation feels
live without changing the backend.

Implementation: `_stageAutoDelegationMessages()` in app.js iterates
the response's messages, sets `_teamTyping` to the next partner's
id, sleeps, then pushes the message and re-renders. Skipping any
message the user echo already showed.

### Skeleton loaders replace placeholder text

First paint used to flash "Setting up the desks…" / "Olivia is
reviewing the desks…" / "Loading the whiteboard…" for a split
second before real data arrived. v12.5 paints visual skeleton
shimmer cards in the exact shape of the final layout. Calmer
load, no jarring text swap.

### Console message slide-in

Each new console message gets an `is-new` class on first render
that drives a 320ms slide-up + fade-in keyframe. Messages "arrive"
instead of just "rendering."

### Activity-feed new-event highlight

The feed polls every 12s. New events (tracked via a Set of stable
keys) get a soft gold border-glow that fades over 1.8s. You can
spot what just happened without re-reading the whole list.

### Desk wake-up pop

When a desk transitions from `idle` → `active|thinking|waiting`, the
avatar plays a 380ms scale pop (1.0 → 1.12 → 1.0). Subtle but
unmistakable — you see the partner "wake up" the moment they get
assigned work.

### Empty-state polish

Activity feed empty state goes from a flat "No recent activity"
line to a centered ☕ icon + "Quiet morning. Click a desk or use the
command box to get the team started." Friendlier on first run.

### Reset clears the local message tracker

Without this, console-reset would clear the message list but on the
next reload, the same server-side messages would NOT animate in (the
client thought it had already seen them). Now `_seenMessageIds` is
cleared on reset so re-fetched messages animate in like new arrivals.

### One small router fix (caught by tests)

The Sage do-it button label is "Check My Website" but Sage's
keyword list didn't include "website" or "check website" — so a
user typing the same phrase Sage's button shows would route to
Olivia instead. Added `"website"`, `"check website"`, `"check my
website"`, `"my website"`, `"check site"` to Sage's keywords. All 6
plain do-it labels now route to their expected partner when typed
into the console.

### All animations honor `prefers-reduced-motion`

Skeleton shimmer, message slide-in, activity highlight, desk
wake-up — every keyframe is gated. Reduced-motion users see static
states.

### Live verification

```
1. All 6 do-it labels ("Tell Me Next Step", "Find Clients", "Check My
   Website", "Make Promo", "Make Video", "Find Video Ideas") route
   to their expected partner when typed
2. Auto-delegation returns multi-message payload (frontend stages it
   for visible turn-taking; backend unchanged)
3. summary preserves v12.4 mission + briefing + desk_items
4. start_work preserves v12.4 result_card shape
5. activity feed event shape unchanged (partner/icon/title/when)
```

py_compile + node --check + module-init smoke all PASS. Leak scan
clean. Christian Kovac safe.

### Safety perimeter unchanged

- ❌ No new endpoints. No new data files. No new Python deps.
- ❌ No publishing. No auto-send. No connections. No live changes.
- ✅ Staged conversation is a UI illusion over an already-completed
  server response. The auto-delegation server flow is unchanged.
- ✅ Animations are pure CSS keyframes; all honor
  `prefers-reduced-motion`.
- ✅ Backward-compatible — every existing endpoint payload preserved.

---

## v12.4 — Office experience polish

v12.3 built the office room. v12.4 polishes it: bigger characters,
plain language everywhere, mission whiteboard, results card, per-
partner working animations. Zero new endpoints, zero new data files.

### Plain language (no jargon in user-facing text)

Spec section 2 verified — banned terms removed from all user-facing
surfaces:
- "candidate" → "possible client"
- "audit checklist" → "website check"
- "work items" → "tasks" (UI label: "Team Tasks")
- "documents" → "files" (UI label: "Shared Files")
- "enrichment" → "extra details"
- "pipeline" → "next steps"

Per-partner Do-It-For-Me buttons relabeled to the spec's 6 plain
labels:
- Olivia: **Tell Me Next Step**
- Logan: **Find Clients**
- Sage: **Check My Website**
- Parker: **Make Promo**
- Video: **Make Video**
- YouTube: **Find Video Ideas**

### Mission whiteboard

New `mission_board()` function composes from agency profile + live
partner state:

```
📋 Today's Mission
Get MixedMakerShop more local clients in Hot Springs, AR.

Next move: Use 501 Plumbing — Logan already prepped the outreach.
                                                    [Open Logan]
```

Rendered above the briefing card as a dashed-border whiteboard.
Surfaced inside the existing `/api/team-office/summary` payload
under a new `mission` key — no new endpoint.

### Morning briefing rewrite (spec section 3)

Olivia's opening now reads verbatim per spec:

> Hey Topher, I'm running the office this afternoon. Tell me what
> you need, or pick one of these.

The 4 v12.3 chips are replaced with the spec's 5 plain chips:
**Get me clients** · **Improve my website** · **Make a promo** ·
**Make a video** · **Tell me what to do next**.

### Sage's plain reply (spec section 9 — verbatim)

When Sage finishes a website check, the console reply now leads
with:

> "I checked your website. The first thing I'd improve is making
> it clearer what you sell and where you serve. Here are the top
> things I'd do:
>   • Fix homepage wording
>   • Add local service terms
>   • Improve page titles
>   • Add calls to action"

Not "technical SEO" first. Not "audit completed." The 30-item
checklist still exists in the Sage section for power users; the
console-facing summary is the plain language.

### Logan's plain reply (spec section 10)

> "I found 1 possible client in Hot Springs, AR. … 501 Plumbing —
> no website yet"

Uses "possible client" everywhere. Bullets explain WHY each pick
stands out using the v9.0 weak_presence_flags (in plain words: "no
website yet" / "on Facebook only" / "dated website" / "uses a free
email").

### Results card (spec section 8)

When a partner finishes work, a focused panel appears above the
console:

```
✓ DONE
I checked MMS - MixedMakerShop - SEO.

1. Fix homepage wording
2. Add local service terms
3. Improve page titles
4. Add calls to action

Next best action → [Open the checklist]   Dismiss
```

Replaces the long technical text dump. Each `start_work()` handler
now returns a `result_card: {headline, bullets, next_action}`
structure alongside the existing fields. The JS renders it as a
green-bordered card with a single big primary button.

### Bigger characters + speech bubbles + per-partner animations

Desks redesigned with:
- Avatar circle 3.2rem (up from 1.5rem), with a soft inner shadow
- Name + role + status pulse stacked next to avatar
- Speech bubble showing current ambient chatter (italic, with the
  classic speech-bubble tail)
- One BIG primary button using the new plain label
- Smaller "Ask <name>" secondary

Each busy desk gets a CSS-only animation tied to the partner's role
(spec section 5):
- **Logan** (`📍`) — pin bounces up/down
- **Sage** (`🔎`) — screen glow pulse (box-shadow)
- **Parker** (`📣`) — sticky-note shuffle (rotation)
- **Video** (`🎬`) — blinking red recording dot
- **YouTube** (`▶️`) — thumbnail pulse (red glow)
- **Olivia** (`🗂️`) — green check mark appears and fades

All animations gated by `prefers-reduced-motion`.

### Office room atmosphere (spec section 11)

- **🏢 MixedMakerShop HQ** sign (top-left of office, brown desk-
  plaque styling)
- Water cooler 💧 and AC vent 💨 (gently animated) and clock 🕐 as
  ambient details top-right
- Whiteboard texture on the mission board (dashed inner border)
- Warm linen + amber gradient from v12.3 preserved

### Live verification (9 tests, all pass)

```
1. /summary returns mission board with mission + next_move + hq_name
2. All 6 desks use spec do_it_labels exactly
3. Briefing opener matches spec verbatim + 5 spec chips
4. Sage start_work result_card has spec headline + 4 spec bullets
5. Sage console message leads with "checked your website";
   no "technical SEO" in first paragraph
6. Logan result_card uses "possible client" language
7. Parker, Video, YouTube all return result_card with next_action
8. Zero jargon in briefing / mission / next_move / opener
9. Auto-delegation still works (v12.3 back-compat)
```

py_compile + node --check + module-init smoke all PASS. Leak scan
clean. Christian Kovac safe.

### Safety perimeter unchanged

- ❌ No publishing. No auto-send. No connections. No live changes.
- ❌ No new endpoints. No new data files. No new partner types.
- ❌ No new Python deps.
- ✅ All polish surfaces compose from existing storage. The mission
  whiteboard reads agency profile + lead picks + Sage queue. The
  results card is computed by the existing `start_work()` handlers.
- ✅ Per-partner animations are CSS-only and honor
  `prefers-reduced-motion`.
- ✅ Backward-compatible — `summary` payload gained 1 field
  (`mission`); start_work payload gained 1 field (`result_card`).
  Both ignored gracefully by older clients.

---

## v12.3 — Living Agency Office

v12.0 gave the partners voices. v12.1 made onboarding feel like a
front-desk welcome. v12.2 made the buttons actually do work. v12.3
finishes the experience: the Agency Office becomes the **primary
surface** of the Hub, looks like an actual room with desks, shows
the team collaborating visibly, and surfaces a morning briefing
from Olivia that knows what each partner has prepared.

### Visual transformation

The office is now a room, not a row of cards:

- **Linen + amber color palette** with a radial gradient that mimics
  warm office light
- **6 desks in a grid**, each with 3 role-specific decor items
  rendered as an emoji row:
  - Olivia: 📋 ✅ ☕
  - Logan: 🗺️ 📞 📒
  - Sage: 📊 📈 💻
  - Parker: 🎨 💡 📌
  - Video: 📷 🎞️ 💡
  - YouTube: 🖼️ 📈 🎯
- **Animated status pulse** under each desk (green when active, blue
  when thinking, amber when waiting; honors `prefers-reduced-motion`)
- **Busy desks get a subtle ring** so you can see at a glance who's
  working

### Morning briefing (new endpoint)

`GET /api/team-office/briefing` — Olivia's conversational greeting
composed from live data:

```
Good afternoon, Topher. The team is ready.

  • Logan has 1 ranked candidate — 501 Plumbing is ready to send.
  • Sage's audit on MMS - MixedMakerShop - SEO has 30 checklist items still to walk.
  • Parker has a promo draft on file — "Promo draft — Free homepage mockup".
  • Video has 2 drafts on the desk — newest is "Short script — Free homepage mockup".
  • YouTube has 4 packages drafted — latest is "Full package — Free homepage mockup".

What would you like us to work on today?
```

Each line is built from real storage — picks count, audit checklist
state, draft document titles, package counts. No hardcoded copy
beyond the wrapper. The briefing card replaces the v12.1 empty-state
greeting.

### Activity feed (new endpoint)

`GET /api/team-office/activity?limit=20` — chronological-newest-first
stream of partner actions composed from existing storage. **No new
persistence.** Pure projection over:
- Console messages (partner replies)
- Work items (created)
- Shared documents (created)
- Sage audits + monthly reports
- YouTube + Video packages

Renders in a column alongside the console so you literally watch the
team work. Polled every 12 seconds while the tab is visible; paused
when hidden. Each event shows partner icon + truncated title + a
"partner · HH:MM" footer.

### Auto-delegation (multi-partner workflows)

The router now detects outcome phrases and runs real multi-partner
workflows visibly in the console:

| Phrase | Chain |
|---|---|
| "get me more clients" / "grow the business" | Logan → Parker → Video |
| "improve our SEO" / "rank higher" | Sage → Parker |
| "make a campaign" / "launch a campaign" | Parker → Video → YouTube |
| "content plan" / "make content" | Video → YouTube → Parker |

When detected, `route_command()` calls `run_auto_delegation()`:
1. User message logged
2. Olivia narrates the dispatch: *"OK Topher, big ask — I'll line
   up the team. Logan finds prospects, Parker drafts outreach,
   Video Partner stages content. Hang tight."*
3. Each partner in the chain runs real `start_work()` and posts
   their reply (Logan's real OSM discovery, Parker's promo draft,
   Video's script — all using v12.2 generators)
4. Olivia wraps up: *"Topher, the team is ready for review."*

Five+ messages land in the console; you see the conversation, not
"completed."

### Richer partner replies

Templates now reference real data:

- **Logan** mentions WHY top picks stand out, pulling from the v9.0
  `weak_presence_flags`: *"They rely heavily on Facebook and don't
  have strong websites."* / *"They have no website on file — ideal
  for the free mockup pitch."*
- **Sage** mentions WHICH audit section has the biggest opportunity:
  *"I just finished checking MMS - MixedMakerShop - SEO. The biggest
  opportunity I see right now is technical seo. I count 12 items
  that could move the needle."*

### Advanced workspaces collapsed

Today panel + all six partner sections (Parker, Logan, Sage, Video,
YouTube, Olivia) now wrap inside one `<details id="advanced-workspaces">`
disclosure, closed by default. **Nothing removed** — everything still
works exactly as before, it just doesn't compete with the Office for
attention. System section stays outside (so Reset Onboarding + Logs
stay accessible).

### New API surface (2 endpoints)

- `GET /api/team-office/briefing` → morning briefing
- `GET /api/team-office/activity?limit=N` → activity stream (1≤N≤100)

`GET /api/team-office/summary` extended with per-desk `desk_items`
(decor) + `short_name`. Backward-compatible — old fields preserved.

### Live verification (9 tests, all pass)

```
1. Briefing returns Olivia text with team status lines + 4 chips
2. Activity feed returns chronological events with partner icons
3. Summary includes desk_items + short_name per desk
4. Auto-delegation "Get me more clients" → 6-message conversation
   (user + olivia open + logan + parker + video + olivia close);
   Logan does real OSM, Parker drafts promo, Video generates script
5. Auto-delegation "Improve our SEO" → sage + parker chain
6. Logan reply mentions specific standout reason from real flags
7. Sage reply mentions specific audit section with item counts
8. Activity feed reflects new conversation events
9. v12.2 start-work endpoint unchanged (back-compat)
```

py_compile + node --check + module-init smoke all PASS. Leak scan
0/4. Christian Kovac safe.

### Safety perimeter unchanged

- ❌ No publishing. No auto-send. No connections. No live website changes.
- ❌ No OAuth. No paid APIs. No new Python deps.
- ❌ **No new data files** — briefing + activity feed are pure
  projections over existing storage.
- ✅ Auto-delegation runs the existing v12.2 `start_work()`
  generators; no new outbound surface. Logan still hits OSM with
  the same v8.9.1+ approved call. Everything else is local generation.
- ✅ Activity feed polls every 12s **only while the tab is visible**
  (pauses on `document.hidden`).
- ✅ All advanced workspaces still accessible — collapsed, not removed.

---

## v12.2 — Olivia actually starts the work

v12.1's onboarding success screen had four buttons — **Start SEO
Audit**, **Find Leads**, **Make Promo**, **Go to Office** — but three
of them just scrolled and set a status message. Sage was the only one
that generated something real. v12.2 fixes that: every "Do It For Me"
button now produces a real artifact, posts a message from the partner
to the console, and saves the output to the shared document library.

### Backend (`automation/team_office.py`, +~280 LOC)

New `start_work(partner_id)` dispatcher + 6 per-partner handlers.
Each handler:
- Generates a real artifact (audit / picks / promo / script / package)
- Saves it to `data/team_documents.json` (typed by partner role)
- Posts a partner message to the console (in the partner's v12.0 voice)
- Bumps any matching `status="new"` work item for that partner to
  `waiting_approval`
- Returns `{ok, partner, messages, documents, work_item, summary}`

Per-partner work:

- **`_start_olivia`** — runs the existing `_olivia_next_actions_text()`
  (ranked top-3 across Logan picks + Sage approval queue + drafts +
  team work items). Posts a single Olivia message with action cards.
- **`_start_logan`** — calls `lead_candidates.do_it_all(category="plumber",
  city_state=<agency profile's default_search_area>, count=10)`. Real
  OSM discovery + bulk-enrich + ranking, 5-15s round trip. Saves picks
  summary as a `lead_list` document shared with Olivia + Parker. Posts
  Logan's message with the picks count + an action chip.
- **`_start_sage`** — calls `seo_partner.generate_audit(mms.id)`. Saves
  audit summary as a `seo_audit` document shared with Olivia + Parker.
  Posts Sage's message with the checklist counts (Technical/On-Page/Local).
- **`_start_parker`** — Parker doesn't have a generation module; v12.2
  ships `_make_parker_promo(profile)` that builds promo copy from the
  agency profile's `free_offer` + `paid_offer` + `agency_name` +
  `default_search_area` + first 3 `target_customers`. Saves as
  `promo_copy` document. Free-mockup CTA preserved verbatim, zero
  "3 free fixes" language (verified by grep in test 3).
- **`_start_video`** — calls `video_partner.generate_package(
  content_type="short_script", topic=<free_offer>)`. Mirrors result
  into `video_script` shared document.
- **`_start_youtube`** — calls `youtube_partner.generate_package(
  content_type="full", topic=<free_offer>)`. Mirrors into
  `campaign_package` shared document.

### New endpoint

`POST /api/team-office/start-work/{partner_id}` — returns the
structured `start_work` result. KeyError → 404, ValueError → 400.

### Frontend (`hub/static/app.js`)

`_runTeamDoItForMe(partnerId)` rewritten. Was a per-partner switch
that scrolled + set a status message. Now:
1. Scrolls the Agency Office into view so the user sees the work land
2. Shows the typing indicator (partner-specific)
3. POSTs to `/api/team-office/start-work/{partner}`
4. On success: reloads messages, refreshes desk summary, refreshes
   work queue + documents, refreshes the partner's own UI section
   (Sage / candidates list / etc.)

The same handler powers:
- Onboarding success-screen buttons (4 of them)
- Per-desk "Do It For Me" buttons in the Agency Office
- Any action card from a console message with
  `kind: "do_it_for_me"`

### Live verification (8 tests, all pass)

```
1. start-work/olivia → ranked next-3 message
2. start-work/sage → audit generated (30 items: 12 Tech + 8 On-Page +
   10 Local), Sage's voice with sign-off, document type=seo_audit
3. start-work/parker → promo draft document (type=promo_copy),
   zero "3 free fixes", free-mockup CTA verbatim, agency profile
   values interpolated correctly
4. start-work/video → short_script document, Video's voice with
   banter mentioning YouTube
5. start-work/youtube → campaign_package document, YouTube's voice
6. start-work/logan → real OSM discovery succeeded: 1 OSM + 9 research
   missions = 10 ranked candidates; lead_list document created;
   Logan's message reports actual counts
7. Unknown partner → 404 with helpful detail
8. Console reflects all 6 partners speaking after the test run
```

py_compile + node --check + module-init smoke all PASS. Leak scan
clean. Christian Kovac safe.

### Safety perimeter unchanged

- ❌ No publishing. No auto-send. No connections. No live website changes.
- ❌ No OAuth. No paid APIs. No new Python deps.
- ❌ No new data files (uses existing `team_documents.json` + the
  partner-module storage).
- ✅ Logan's discovery is the same OSM HTTPS POST already approved in
  v8.9.1+ — no new outbound surface.
- ✅ Every generated artifact lands as `status="ready"` in shared docs
  (draft / review-only — no publishing path).
- ✅ Work items bumped to `waiting_approval`, never auto-completed.
- ✅ Spec-critical language compliance: zero "3 free fixes" in Parker's
  promo template; free-mockup CTA verbatim.

---

## v12.1 — Easiest Automated Onboarding

First-time setup turns an empty Hub into a ready-to-use office in
~7 conversational steps with Olivia hosting. New users no longer see
dashboards first; they see Olivia at the front desk asking what they
want to build, with every input pre-filled with sensible defaults.

### Backend (`automation/onboarding.py`, +~400 LOC)

- `DEFAULT_ANSWERS` — spec-verbatim defaults for every wizard step:
  agency_name=MixedMakerShop, first_website=https://mixedmakershop.com,
  8 services, 5 target customer types, Free homepage mockup, Starter
  website fix from $150, Hot Springs AR.
- `load_state() / save_state()` — `data/onboarding_state.json`,
  atomic writes.
- `load_agency_profile() / save_agency_profile()` —
  `data/agency_profile.json`, atomic writes.
- `apply(answers)` orchestrator that:
  - Saves agency profile + Sage agency name
  - Ensures Sage MMS project exists (uses the v10.0 auto-bootstrap),
    then patches its website_url + business_type (joined services)
    + location + main_goal (target customers)
  - Seeds Video Partner profile (business_name, business_type,
    target_customer, main_service, tone, platforms, video_length,
    call_to_action=free offer)
  - Seeds YouTube Growth channel (channel_niche, target_audience,
    tone, main_offer_cta=free offer)
  - Creates 3 starter work items (all `status="new"`,
    `needs_approval=True`):
    - Run first SEO audit on <agency> — assigned to Sage
    - Find first local leads in <area> — assigned to Logan
    - Draft promo for <free offer> — assigned to Parker
  - Creates a welcome document in shared library with the setup
    summary, shared with sage / logan / parker
  - Marks state complete + persists answers for prefill
- `reset()` — clears completion flag only. Saved leads, SEO projects,
  reports, documents, work items, partner profiles, and last answers
  all preserved.

### Endpoints (3 new)

- `GET /api/onboarding/state` → `{complete, completed_at, answers,
  defaults, profile}`
- `POST /api/onboarding/complete` body = answers → applies setup,
  returns full result (profile + per-partner seeding + recommendations
  + actions + olivia_summary)
- `POST /api/onboarding/reset` → clears completion flag

### UI

- Fullscreen overlay (`#onboarding-overlay`) — gates the Hub on first
  load. JS calls `GET /api/onboarding/state` on page open; if
  `complete=false`, renders the wizard.
- **7 steps** with progress dots, Olivia speech bubble at the top of
  each card, Back / Skip for now / Next buttons. Step 1, 2, 5, 6, 7
  are text inputs; steps 3 (services) and 4 (target customers) are
  checkbox groups with the spec defaults pre-checked.
- **Success screen** — animated success checkmark, "Your office is
  ready." heading, 6 desk emojis lighting up in sequence (CSS
  keyframe animation, respects `prefers-reduced-motion`), Olivia's
  recommendation paragraph (spec-verbatim), 4 action buttons:
  **Start SEO Audit**, **Find Leads**, **Make Promo**, **Go to Office**.
  Action buttons wire to the existing v11.0 `_runTeamDoItForMe()`
  handlers.
- **Reset button** in System → Onboarding subsection. Confirms with
  a message clarifying that data is preserved.
- Softer cozy palette (linen + amber) matches the v12.0 Living
  Office aesthetic.

### Live verification (7 tests, all pass)

```
1. Fresh state → complete=false, defaults match spec
2. POST /complete with empty body uses all defaults; seeds Sage,
   Video, YouTube, 3 work items, welcome doc; olivia_summary is
   spec-verbatim
3. Second GET → complete=true, completed_at stamped, answers persisted
4. Seeded artifacts verified:
   - Sage agency name = MixedMakerShop
   - MMS project website_url + business_type updated from answers
   - Video Partner business_name + call_to_action set to free offer
   - YouTube niche set
   - 3 work items created with status='new' + needs_approval=True
   - Welcome doc created in shared library
5. POST /reset → complete=false; SEO project, work items, leads
   all preserved; answers preserved for re-fill
6. Custom answers (agency_name, free_offer, default_search_area)
   override defaults; unspecified fields inherit defaults
7. Spec compliance: zero "3 free fixes" language in any onboarding
   output; free-mockup CTA present
```

py_compile + node --check + module-init smoke all PASS. Leak scan
clean (real patterns only — no false positives). Christian Kovac safe.

### Safety perimeter unchanged

- ❌ No publishing. No auto-send. No connections. No live website
  changes. No OAuth. No paid APIs.
- ❌ No new Python dependencies.
- ✅ Every starter work item carries `needs_approval=True` and
  `status="new"` — the user must explicitly act on them.
- ✅ Reset preserves ALL saved data — only the completion flag
  flips. Re-runnable safely.
- ✅ Spec wording preserved — zero "3 free fixes" language anywhere.
  Free-mockup CTA is the default but user-editable.

### Known limitations (deferred to v12.2 candidates)

- Re-running onboarding with a different `agency_name` updates the
  Sage project's content but doesn't rename the existing
  `MMS - MixedMakerShop - SEO` project. Users can rename projects
  manually via Sage. Auto-rename on agency change would risk
  breaking references to the project_id.

---

## v12.0 — Living Office Experience

v11.0 built the Team Office command system. v12.0 makes the partners
feel like coworkers instead of buttons. Pure polish layer — zero new
backend systems, zero new databases, zero new partner types, zero new
management features. Per spec: characters, conversation, visible
delegation, simple atmosphere.

### Voices

Each partner now has a `_VOICES` entry in `team_office.py` with:
- **openers** — characteristic phrasing tics (Logan: "Right —", "On it.";
  Sage: "OK,", "Let me think.", "Here's what I'd do —"; Parker:
  "Oh nice —", "Yeah —", "Love this.")
- **sign_offs** — how they close a reply (Logan: "Holler when you've
  got a target."; Sage: "Ready when you are."; Parker: "Want me to
  keep going?")
- **ack_olivia** — receiving-a-handoff openers ("On it, Olivia. Topher
  — …")
- **banter_about** — short mentions of other partners (Logan banters
  about Parker: "Once I've ranked a few, Parker can draft the first
  outreach.")
- **idle_chatter** / **active_chatter** — one-line ambient activity
  strings ("scanning OSM", "ranking 4 candidates")

`_wrap_with_voice()` assembles `opener + body + (optional banter) +
sign-off`. Deterministic picks off a hash of the request keep replies
consistent for the same prompt while varying across prompts.

### Visible delegation

`route_command()` now produces a **real conversation** when work
involves multiple partners:
1. Olivia speaks first with a handoff line: *"OK, Logan, this one's
   yours. Topher wants find me 25 lawn care leads near Hot."*
2. The receiving partner opens by acknowledging Olivia AND addressing
   the user: *"On it, Olivia. Topher — queue is empty right now.
   Throw me a business type and a city…"*
3. Banter context: the primary partner mentions the secondary
   collaborator: *"Once I've ranked a few, Parker can draft the first
   outreach."*
4. Secondary partners chime in with their voice, not boilerplate:
   *"Yeah — I can spin this into a friendly promo…"*

Before v12.0 the same flow was four sterile separate replies. After,
it reads like watching the team actually work together.

### Office atmosphere

- `office_greeting()` — time-aware Olivia greeting for the empty
  console ("Morning. Topher — I'm watching the team. Tell me what
  you want done…"). Branches: morning / afternoon / evening / late
  night.
- `office_suggestion_chips()` — 4 one-tap starter prompts that send
  the chip text to /command when clicked.
- `desk_chatter()` — every desk shows an italic activity line under
  the role (Logan: "scanning OSM" when idle, "ranking 4 candidates"
  when busy). Stable per-day per-task-count so it feels fresh but
  not frantic.
- Typing indicator — 3 bouncing dots in a speech bubble while a
  partner is "thinking" (in-flight to /command or /partner/{id}/ask).
  Honors `prefers-reduced-motion`.
- Softer warm color palette on the Agency Office section (linen +
  amber gradients instead of corporate blues).
- Subtle active-desk glow when a partner has work in progress.

### Frontend behavior

- Empty console renders a greeting card from Olivia + 4 chip
  suggestions; clicking a chip sends the chip text to /command.
- Direct asks and command sends both echo the user message
  immediately, show a typing indicator while in flight, then reload
  the full thread when the reply lands.
- All Work Queue + Shared Documents details stay collapsed by default
  (already correct in v11.0; verified).

### API surface

`GET /api/team-office/summary` adds two top-level fields:
`greeting: str` and `suggestion_chips: list[str]`. Each desk also
gains a `chatter: str`. **Old v11.0 clients ignore them safely.**
No new endpoints. No request-shape changes.

### Tests (5 live tests, all pass)

```
1. /summary returns greeting + suggestion_chips + per-desk chatter
2. Handoff flow ("Find me leads") produces:
   - Olivia message naming Logan
   - Logan message addressing Olivia + bantering about Parker
   - Parker secondary message in Parker's voice (not boilerplate)
3. Direct ask to Sage retains opener + sign-off
4. v11.0 work-item + console-reset endpoints unchanged
5. Greeting is time-aware (includes morning/afternoon/evening/etc)
   and addresses Topher
```

py_compile + node --check + module-init smoke all PASS. Leak scan
clean (false positives only — pattern matched `desk-chatter` CSS
class names). Christian Kovac safe.

### Safety perimeter unchanged

- ❌ No external AI / OpenAI / paid APIs
- ❌ No auto-send. No publishing. No live changes.
- ❌ No OAuth. No new Python deps. No new data files.
- ❌ No new backend systems, no new state machines, no new project types.
- ✅ Voice templates are pure local strings.
- ✅ Typing indicator is a UI illusion — no fake delay added on the
  server; it appears while the legitimate request is in flight.
- ✅ Suggestion chips send their text through the existing /command
  endpoint; nothing new there to attack.

---

## v11.0 — Team Office command system

PartnerDeskAI's 6 individual partner dashboards were each fine in
isolation but collectively felt like 6 separate apps. v11.0 introduces
the **Agency Office** — a single command console + 6 cartoon desk
cards — that becomes the new primary interface. Existing partner
dashboards stay accessible by scrolling down (no removal); they're
just no longer the first thing the user sees.

**Core idea:** Olivia is the office dispatcher. The user types a
plain-English request, a keyword-based router picks the right
partner, and every partner that fires appends a personality-tuned
reply to the persistent console. Multi-partner workflows route the
primary then loop in secondaries.

**New `automation/team_office.py`** (+~750 LOC) — pure-local, no
external AI:

- **PARTNERS registry** for all 6 (id, emoji, role, keywords,
  do-it-for-me label, description).
- **`route_command(text)`** — keyword scoring (longer phrases
  weighted higher) → primary + secondary partners. Multi-partner
  detection: any secondary with ≥50% of the top score gets looped in.
- **`partner_reply(partner_id, text)`** — rule-based response
  templates with light context awareness. Sage's "What do I do
  first?" returns the spec-verbatim 5-step plan. Logan's reply
  pulls live picks from `lead_candidates`. Olivia's "What should I
  do next?" queries Logan + Sage + YouTube + work items to build a
  ranked top-3 action list.
- **Work items** — cross-partner task substrate with state machine
  (`new → assigned → in_progress → waiting_approval → completed |
  rejected`). CRUD + list-by-status/partner.
- **Shared documents** — `lead_list`, `seo_audit`, `seo_report`,
  `promo_copy`, `outreach_draft`, `video_script`, `campaign_package`,
  `monthly_report`, `notes`, `next_actions` types. Sharing adds a
  partner to the doc's `shared_with` list and flips status to
  `shared`.
- **Console message log** — ring buffer (200 messages). User
  messages, partner replies, action cards all persist.
- **`summary()`** — desk states + task counts. Each desk lazy-loads
  from its partner module so a broken partner doesn't crash the
  whole Office.
- **`clear_console()`** — spec section 14: clears ONLY console
  state; leads / SEO projects / reports / documents / work items
  / partner data all preserved.

**Hub API — 10 new endpoints:**

- `GET /api/team-office/summary` — desks + counts
- `GET /api/team-office/messages` — console history
- `POST /api/team-office/command` — main entry; routes + replies
- `POST /api/team-office/partner/{partner_id}/ask` — direct chat
- `POST /api/team-office/reset` — clears console only
- `GET/POST /api/team-office/work-items[/{id}]` + `PUT`
- `GET/POST /api/team-office/documents` + share

**UI — new Agency Office section at the top of the Hub:**

- 6 cartoon partner desk cards (Olivia first, then Logan, Sage,
  Parker, Video, YouTube). Each shows emoji avatar, role line,
  status badge (idle / active / waiting / thinking), task count
  pill, **Do It For Me** primary button, and **Ask <name>** secondary.
- Central command console: scrolling message history with
  user-vs-partner styling (color-coded per partner), action-card
  buttons on each partner reply.
- Bottom inputs: main command form, **Start Fresh Conversation**
  button (with confirmation; clears console only).
- Two collapsible side panels: **Work Queue** and **Shared
  Documents**.
- New CSS for cartoon desks, speech-bubble styling, color tints
  per partner.

**"Do It For Me" buttons wired meaningfully:**

- **Olivia** → asks the next-actions endpoint; reply lands in console
- **Logan** → scrolls to + focuses the existing Find Leads For Me
  form
- **Sage** → fetches MMS - MixedMakerShop - SEO; if no audit exists,
  generates one; scrolls to Sage section + refreshes
- **Parker / Video / YouTube** → scroll to the existing partner
  section (their existing generators handle the heavy lift)

**Existing partner sections preserved** — Today panel, Parker, Logan,
Sage, Video, YouTube, Olivia all still work unchanged below the
Agency Office. v11.0 wraps nothing; it just adds the new primary
interface on top.

**Live verification (12 tests):**

```
1. /summary returns 6 desks in correct order with Olivia first
2. "Find me 25 lawn care leads" → primary=logan, secondary=parker
3. "Have Sage audit MixedMakerShop" → primary=sage, intent=audit
4. "What should I do next?" → olivia, reply with ranked actions
   pulled from live partner state
5. "Make a promo for the free homepage mockup" → parker
6. Direct ask: POST /partner/sage/ask "What do I do first?" returns
   the spec-verbatim 5-step plan
7. Unknown partner → 404 with helpful detail
8. Work item CRUD (create, list-by-status, update)
9. Document CRUD + share (visible to shared partner)
10. Messages persist across requests; reset clears ONLY console
    (work items + documents preserved)
11. Empty command → 400
12. Multi-partner routing (logan + parker on "leads and outreach")
```

py_compile + node --check + module-init smoke all PASS. Leak scan
clean (apparent hits in team_office.py are false-positives from the
`sk_` pattern matching `task_count` and `ask_partner`; verified by
hand). Christian Kovac safe across the cycle.

**Safety perimeter — every spec constraint honored:**

- ❌ NO external AI / OpenAI / paid APIs
- ❌ NO auto-sending outreach
- ❌ NO auto-publishing
- ❌ NO live website changes
- ❌ NO OAuth / API connections
- ❌ NO social posting / form submission
- ❌ NO new Python dependencies (stdlib only)
- ✅ Rule-based keyword router
- ✅ Template-based personality replies
- ✅ Action cards surface — user clicks to act
- ✅ All major actions require user click; nothing fires automatically
- ✅ Start Fresh clears console only — leads/projects/reports/
  documents/work items/partner data all preserved
- ✅ Existing partner sections untouched

---

## v10.0 — Sage SEO Partner (agency project management)

PartnerDeskAI graduates from "lead generation + content publishing"
into a multi-service operating system for the MixedMakerShop agency.
v10.0 introduces **Sage**, a dedicated SEO and Local SEO partner with
its own project hierarchy, audit checklists, fix-task lifecycle,
approval queue, and monthly report generator.

**Agency structure decision:** ONE agency account (MixedMakerShop).
Clients become projects inside Sage, formatted
`MMS - <Client Business Name> - SEO`. On first run of
`GET /api/seo/projects`, Sage auto-seeds the
`MMS - MixedMakerShop - SEO` project so the dashboard isn't empty.

**New `automation/seo_partner.py`** (+~750 LOC):

- **Agency:** single-record store, first-run bootstrap. `load_agency()`
  / `save_agency()`.
- **Projects:** list with inline `fix_tasks`. CRUD + cascading delete
  (drops audit + report history when a project is removed).
- **Fix-task lifecycle:** `suggested → approved → in_progress →
  completed | skipped`. State-machine helpers
  `approve_fix_task / start_fix_task / complete_fix_task / skip_fix_task`.
  `requires_approval` defaults to True for high+critical severity.
- **Approval queue:** cross-project or per-project view of every
  fix_task where `requires_approval=True && status='suggested'`.
  Severity-sorted (critical first).
- **Audit generator:** static-template checklist with 12 Technical +
  8 On-Page + 10 Local SEO items per the spec. Sage does NOT crawl
  the site — the user works the checklist manually and updates
  per-item statuses via `update_audit_item()`. History persisted
  per-project, capped at 50.
- **Monthly report generator:** synthesizes the spec's 6 sections
  (What we checked / What we fixed / Current wins / Current issues /
  Ranking notes / Next actions) from current project state.
  Persisted per-project, capped at 50.
- **`agency_dashboard()`** single-shot summary.

**Storage** (all gitignored):
- `data/seo_agency.json`
- `data/seo_projects.json`
- `data/seo_audits.json` (dict keyed by project_id)
- `data/seo_reports.json` (dict keyed by project_id)

**Hub API — 20 new endpoints:**

- `GET/PUT /api/seo/agency`
- `GET /api/seo/dashboard`
- `GET/POST /api/seo/projects` + `GET/PUT/DELETE /api/seo/projects/{pid}`
- `POST/PUT/DELETE /api/seo/projects/{pid}/fix-tasks[/{tid}]`
- `POST .../{tid}/approve | /start | /complete | /skip`
- `GET /api/seo/approval-queue` (cross-project) +
  `GET /api/seo/projects/{pid}/approval-queue` (per-project)
- `GET/POST /api/seo/projects/{pid}/audits`
- `PUT /api/seo/projects/{pid}/audits/{audit_id}/items/{item_id}`
- `GET/POST /api/seo/projects/{pid}/reports`

Sage added to `/api/partners` with `status='active'` and live metrics
(total/active projects, audits run, reports generated, approval queue
length).

**UI — new collapsible Sage section** (parallel to Parker / Logan /
YouTube / Video / Olivia):

- Agency Dashboard card with 5 stats (projects / active clients /
  audits run / fixes waiting approval / reports generated)
- Project list with one-click project cards (Open / Generate audit /
  Monthly report)
- Per-project detail view with 4 tabs: **Overview** (client info,
  goals, keywords) / **Audit** (interactive checklist with per-item
  status dropdowns) / **Website Fixes** (fix-task cards with
  state-machine buttons) / **Reports** (6-section client-friendly
  reports)
- Add-project form (auto-formats `MMS - <client> - SEO`)
- Inline add-fix-task form per project
- Cross-project Approval Queue disclosure with Approve/Skip buttons
- Auto-refresh when the user expands the Sage section

**Live verification — 16 tests passed end-to-end:**

```
1. First-run agency bootstrap → MixedMakerShop
2. First-run project bootstrap → MMS - MixedMakerShop - SEO with
   spec-verbatim website/business_type/main_goal/target_keywords
3. Dashboard reflects bootstrap state (1 project, 0 audits, 0 queue)
4. Add new client project → name auto-formats to MMS - Joe Coffee Shop - SEO
5. Generate audit → 12 tech + 8 on-page + 10 local items
6. PUT audit item status → 'failing' with notes persists
7. Add fix task (severity=high) → requires_approval=True automatically
8. Approval queue includes the task
9. approve → start → complete lifecycle works; completed_at stamped
10. Queue empty after completion
11. Monthly report generates with all 6 spec sections; what_we_fixed
    pulls from completed tasks
12. Dashboard updates to 2 projects, 1 audit, 1 report, 0 queue
13. Sage appears in /api/partners with live metrics
14. Delete project cascades audit + report history
15. Empty client_name → 400
16. Unknown project → 404
```

py_compile + node --check + module-init smoke all PASS. Leak scan
0/5 on the v10.0 diff (8 false positives in app.js for the regex
catching `sage-task-action` substring — verified clean by hand).
Christian Kovac untouched.

**Safety perimeter — every spec constraint honored:**

- ❌ NO auto-publishing of website changes
- ❌ NO live Google Business Profile changes
- ❌ NO OAuth / API connections (Phase 3+ in roadmap)
- ❌ NO scraping, NO paid APIs, NO OpenAI calls
- ❌ NO new Python dependencies (stdlib only)
- ✅ Audit is a STATIC TEMPLATE; user works it manually
- ✅ Approval required before high+critical fixes can be implemented
- ✅ Reports are local-template synthesis from project state
- ✅ All state is local JSON; data/seo_*.json all gitignored
- ✅ Atomic writes via tempfile + os.replace
- ✅ All inputs length-capped + enum-validated

---

## v9.4 — CSV import provider

The v9.3 architecture promised "adding a provider means a new file +
one register line, no lead-engine changes." v9.4 proves it by adding
the second non-OSM provider.

**New `automation/discovery/csv_import.py`** — local-only discovery
from CSV files dropped into `data/imports/`.

Workflow:
1. User saves a CSV anywhere (chamber roster, exported business
   directory, hand-built spreadsheet, even an LLM-generated list)
   into `data/imports/`.
2. User clicks Find Leads For Me with the **📄 CSV Import** chip
   selected.
3. The provider reads every `*.csv` in that folder, maps headers via
   a synonym table, filters by category + city when those columns
   exist, returns matching rows as candidate dicts.

**Header-tolerant matching** — canonical fields with common synonyms:
- `business_name`: business name | name | company | company name | title
- `phone`: phone | phone number | telephone | tel | cell | mobile
- `email`: email | e-mail | email address | contact email
- `website_url`: website | url | web | site | homepage
- `city_state`: city, state | city | town | location
- `category`: category | type | industry | vertical
- `evidence_notes`: notes | description | about
- `source_url`, `facebook_url`, `instagram_url` — same pattern

**Filtering semantics:** if a CSV has a `category` column, the user's
category arg becomes a loose substring filter against that column.
If the CSV doesn't have a category column, every row inherits the
user's category arg. Same for city. CSV doesn't need to be perfect.

**Safety constraints baked in:**
- Reads ONLY from `data/imports/`. Path-traversal guarded — even when
  the optional `source` arg names a specific file, only the basename
  is used.
- 10 MB per file cap; files larger are skipped with a clear message.
- 5,000 rows per file cap; larger files truncated with warning.
- `data/imports/*.csv` added to `.gitignore` — business lists never
  leave the local machine via git.
- Stdlib `csv` only. No new Python deps.
- `is_available()` returns False when the folder is empty or missing
  — the UI chip auto-disables.
- Per-file parse errors are surfaced in the result message; one bad
  CSV doesn't poison a multi-file import.
- No outbound calls of any kind. Pure local file read.

**Registration:** two-line change to
`automation/discovery/__init__.py` — `from . import csv_import` +
`register(_csv)`. Exactly what the v9.3 architecture promised.

**Schema fix found during testing:** the `ALLOWED_DISCOVERY_SOURCES`
enum in `lead_candidates.py` didn't include `csv_import`, so CSV
candidates were silently falling back to `discovery_source='manual'`.
Added `csv_import` to the enum. Future-providers will need the same
one-line addition (or we generalize the enum to accept any
registered NAME — left as a future cleanup).

**UI:**
- 📄 CSV Import chip appears automatically next to the existing
  Auto / 🌍 OSM / 🔍 Research Missions chips.
- When the folder is empty, the chip is disabled and clicking it
  surfaces the spec-helpful hint: *"CSV Import is unavailable
  because data/imports/ is empty. Drop a .csv there and reload."*

**New file: `data/imports.SAMPLE.csv`** — a committed 5-row sample
the user can copy to `data/imports/sample.csv` to test the workflow
without needing to source a real CSV.

**Live verification (6 tests):**

```
1. csv_import shows up in /discovery-providers (available=True with
   sample.csv present, requires_network=False)
2. provider=csv_import + plumber/Mountain View → 1 row, ds=csv_import
3. coffee/Hot Springs filter → 1 match (Joe's Coffee Shop)
4. Re-run same query → 0 new (dedup works)
5. Empty folder → available=False, helpful "drop a .csv" message
6. Full pipeline: CSV → enrich → convert → schedule-follow-up works
   end-to-end with discovery_source='csv_import' preserved through
   the Logan lead conversion
```

py_compile + node --check + module-init smoke all PASS. Leak scan
0/6 on the v9.4 diff. Christian Kovac safe.

**Architecture validation:** zero edits to `lead_candidates.py` were
needed for the new provider to work end-to-end (other than the
enum fix, which is a one-liner each time, not a refactor). Chain
composition, dedup, persistence, enrichment, conversion all worked
unchanged. The v9.3 design is sound.

---

## v9.3 — Discovery Sources First (pluggable provider system)

Logan was hardwired to OpenStreetMap. `lead_candidates.py` imported
`overpass_discovery` directly and called it by name. Adding any other
source — CSV importer, chamber list, directory feed — would have meant
editing the lead engine.

v9.3 architects discovery as a registry of pluggable providers. The
lead engine no longer knows the names of any specific source; it asks
the registry for one. Adding a new provider is now: create
`automation/discovery/your_provider.py`, register it in
`automation/discovery/__init__.py`, done.

**New package `automation/discovery/`:**

- `__init__.py` — registry (`PROVIDERS`, `register`, `get_provider`,
  `list_providers`), chain orchestrator (`discover_chain`), default
  chain constant (`DEFAULT_CHAIN = ("osm", "research_missions")`),
  shared dedup helper.
- `osm.py` — thin adapter over the existing `overpass_discovery`
  module. Same Nominatim + Overpass behavior, byte-for-byte. Carries
  the standard NAME / DISPLAY_NAME / DESCRIPTION / REQUIRES_NETWORK /
  ERROR_CLASS metadata and exposes `discover()` returning the
  standardized ProviderResult shape.
- `research_missions.py` — promoted from a buried fallback inside
  `discover_via_overpass` to a first-class provider. Pure-local, zero
  outbound calls. Now invokable standalone (`provider=research_missions`)
  as well as chained behind OSM.

**Provider interface** (duck-typed; modules, not classes):

```python
NAME              str  # kebab-case slug
DISPLAY_NAME      str  # human label
DESCRIPTION       str  # one-line UI hint
REQUIRES_NETWORK  bool # makes outbound HTTP calls?
ERROR_CLASS       type # exception this provider may raise

def is_available() -> bool: ...
def discover(category, city_state, count, **opts) -> ProviderResult: ...
```

`ProviderResult` standardized:

```python
{
  "candidates":  list[dict],   # rows ready for lead_candidates._clean()
  "total_found": int,
  "provider":    str,
  "message":     str,
  # optional passthrough extras (display_name, resolved_city, etc.)
}
```

**Backward-compatible refactor of `lead_candidates.py`:**

- `discover_via_overpass()` keeps its public signature and response
  shape — same `osm_added`, `research_missions_added`,
  `fallback_triggered`, `display_name`, spec-verbatim message lines
  — but routes through `discovery.discover_chain()` under the hood.
- `generate_research_missions()` delegates stub generation to the
  research_missions provider; persistence stays in the lead engine.
- New optional `provider` arg on both — `None` / `"auto"` runs the
  default chain; an explicit NAME runs only that provider.
- `do_it_all()` accepts the same `provider` arg.

**Hub API (`hub/app.py`):**

- `GET /api/lead-candidates/discovery-providers` (NEW) returns
  `{providers: [...], default_chain, auto_name}` so the UI can
  enumerate registered sources without hardcoding names.
- `CandidateFindIn` extended with optional `provider: str | None`.
- `/discover` and `/do-it-all` honor `body.provider`. Unknown
  provider → 404 with helpful detail listing registered names.

**UI:**

- Provider chip row under the one-click form, populated from
  `/discovery-providers`. Default chip is ⚡ Auto (chain). Each
  registered provider gets a chip with display_name + tooltip
  describing requires_network. Click to switch source.
- New providers show up here automatically the next time the page
  loads — no UI code change needed.
- Form submit sends `provider` field with the selected chip's name.
  In-flight status line names the active provider when not Auto.

**Live verification (8 tests):**

```
1. GET /discovery-providers returns osm + research_missions,
   default_chain = ["osm", "research_missions"]
2. provider=research_missions: 4 stubs added, zero OSM call
3. provider=osm: 3 OSM candidates, NO fallback even when count > result
4. provider=auto: 1 OSM + 4 RM = 5 total (chain fills gap)
5. No provider key: same as auto (v9.2 back-compat verified)
6. Unknown provider → 404 with helpful registered-names list
7. Picks endpoint still works after refactor
8. Full integration: research_mission → enrich → fill → convert →
   schedule-follow-up — every v9.0/v9.1/v9.2 surface intact
```

**Bug fixed during testing:** the chain's dedup key collapsed all
empty-name candidates into one bucket (`("", city)` collision). Fixed
to use `("phrase:" + search_phrase, city)` when business_name is empty,
matching the persist-time dedup in `lead_candidates.py`.

py_compile + node --check + module-init smoke all PASS. Leak scan
0/7 on the v9.3 diff. Christian Kovac safe across the whole cycle.

**Safety perimeter — every constraint preserved:**

- ❌ No new scraping, no paid APIs, no OAuth, no new Python deps.
- ❌ Pure-local providers (like research_missions) stay pure-local;
  network providers (like osm) keep the same two-call read-only flow.
- ✅ Per-provider errors in the chain are captured, not propagated —
  one provider's failure doesn't abort the whole chain (this is how
  v8.9.1's "OSM 502 → research missions take over" behavior survives
  the refactor).
- ✅ Default behavior with no `provider` field is **identical** to v9.2
  — same chain, same fallback semantics, same response shape.

---

## v9.2 — Follow-up tracking

v9.1's Mark Contacted button did nothing for follow-up tracking — it
just set `outreach_status='contacted'` and the user had to remember to
follow up manually. v9.2 closes that loop: Mark Contacted now
auto-schedules a 3-day follow-up, and Logan surfaces a Follow-Ups Due
section at the top of the Possible Leads panel so the cadence is
impossible to miss.

The v8.4 outreach pipeline already had `next_follow_up_at`,
`follow_up_count`, `last_contacted_at`, `write_follow_up`,
`snooze_follow_up`, and `_FOLLOW_UP_TMPL` (free-mockup CTA). v9.2
generalizes those helpers and surfaces them in the v9.1 UI flow —
no new outbound calls, no new Python deps.

**New `automation/leads.py` helpers:**

- `schedule_follow_up(lead_id, days=3)` — generalized
  `mark_outreach_sent`: stamps `last_contacted_at` + sets
  `next_follow_up_at` = today + days + bumps `follow_up_count` +
  flips `outreach_status`. Promotes `contacted` → `follow_up_due` on
  re-touch; never downgrades warm/hot/dead/won.
- `list_due_follow_ups(today=None)` — returns leads where
  `next_follow_up_at <= today` AND `outreach_status` ∈
  {contacted, follow_up_due, warm, hot}. Sorted most-overdue first.
- `write_follow_up_drafts(lead_id)` — preview-only multi-channel
  drafts (email subject+body, FB DM, SMS, phone notes) using the
  existing free-mockup CTA. Does NOT persist; the user calls
  `mark_followed_up` after they actually send.
- `mark_followed_up(lead_id, days=5)` — user just sent a follow-up.
  Increments `follow_up_count`, reschedules `next_follow_up_at` +days,
  sets `outreach_status='follow_up_due'`. Refuses to operate on
  dead/won leads (raises ValueError → HTTP 400).
- `mark_replied(lead_id, outcome)` — outcome ∈ {warm, hot, won}.
  Clears `next_follow_up_at` (lead exits auto-cadence) and updates
  `outreach_status`.

Defaults: first follow-up at +3 days, subsequent at +5 days (v8.4
implicit cadence preserved). Max snooze 30 days, max reschedule 60.

**New endpoints:**

- `POST /api/leads/{id}/schedule-follow-up` body `{days:int=3}`
- `GET  /api/leads/follow-ups-due`
- `POST /api/leads/{id}/follow-up-drafts` (preview only)
- `POST /api/leads/{id}/mark-followed-up` body `{days:int=5}`
- `POST /api/leads/{id}/mark-replied` body `{outcome:str}` (warm/hot/won)

**Wire-through:** v9.1's Ready-to-Send "Mark Contacted" button now
calls `/schedule-follow-up` (was: PUT outreach_status='contacted').
The follow-up is scheduled automatically without the user thinking
about it; status bar surfaces the new due date.

**New UI:**

- ⏰ **Follow-Ups Due** section above Logan's Picks in Possible Leads.
  Shows lead name, company/email, days overdue (red) or "due today",
  last-contact date, and follow-up number. Hidden when empty.
- Per-card buttons: **📝 Write Follow-Up** (primary), **⏸ Snooze 2 days**,
  **↩ Replied → Warm**, **✗ Dead** (with confirmation).
- **Write Follow-Up** panel mirrors the v9.1 Ready-to-Send shape:
  business info row, 4 stacked draft blocks with per-draft Copy buttons,
  and 6 outcome actions: **Mark Followed Up (+5 days)**,
  **Snooze 3 days**, **Replied → Warm**, **Replied → Hot**, **Mark Dead**,
  **Back to Leads**.
- Follow-up badge ("Follow-up #N") on the due cards so the user can
  see touch count at a glance.

**Today panel integration:** the existing "Leads needing attention"
card already opens the Logan section. The new Follow-Ups Due block
renders at the top of that section, so the natural flow is:
Today card → land in Logan → see Follow-Ups Due → click Write
Follow-Up. No Today-panel code change needed.

**Live verification (10 tests + integration):**

```
1. schedule-follow-up sets outreach_status=contacted, next+3, count=1
2. follow-ups-due empty when due date is 3 days out
3. force-due (yesterday) → appears in due list
4. follow-up-drafts returns 4 channels, zero "3 free fixes",
   free-mockup CTA in all; preview only (lead not mutated)
5. mark-followed-up: count=2, next+5, status=follow_up_due
6. snooze 3 days reschedules correctly
7. mark-replied warm → exits cadence (next_follow_up_at=None)
8. mark-replied bad outcome → 400
9. mark-followed-up on dead lead → 400 with helpful message
10. Integration: create candidate → enrich → convert → schedule-
    follow-up → force-due → appears in /api/leads/follow-ups-due
```

py_compile + node --check + module-init smoke all PASS. Leak scan
0/4 on the v9.2 diff. Christian Kovac safe across the whole cycle.

**Safety perimeter — every constraint preserved:**

- ❌ No auto-send. No auto-contact. No scraping. No paid APIs.
- ❌ No OAuth. No new Python deps. No email/SMS reminders.
- ❌ Zero "3 free fixes" language added — only forbidden-phrase
  guardrail comments. Free-mockup CTA verified in all 4 draft channels.
- ✅ All actions are local state mutation. Send is still manual —
  the user copies a draft, sends it from their own client, then
  clicks Mark Followed Up.
- ✅ Dead/won leads can't be force-followed-up — explicit refusal.
- ✅ `follow-up-drafts` is preview-only; doesn't mutate the lead.

---

## v9.1 — Logan One-Click Lead Desk

v9.0 added enrichment but the user still had to manage too many decisions:
which button to click, what to enrich, what to approve, what to convert,
what to prepare-outreach. v9.1 collapses the routine path into one
button — **🚀 Find Leads For Me** — and reorganizes everything around
status groups + Logan's Picks instead of filter chips.

The advanced v9.0 controls (multi-button form, filter chips, bulk
toolbar, raw candidate list) are still present under an **Advanced
controls** disclosure for power users. Nothing is removed.

**New backend pipeline:**

`POST /api/lead-candidates/do-it-all` runs in one round trip:
1. `discover_via_overpass` (OSM + research-mission fallback — unchanged from v8.9.1)
2. `bulk_enrich` on the just-added rows (unchanged from v9.0)
3. `compute_picks(k=5)` — top 5 across the whole queue, server-side

Response carries `discover` + `enrichment` counts + `picks` array.
Each pick is augmented with `pick_reason` (one sentence from
`opportunity_reasons[0]`) and `best_contact_route` (one-line summary).

New supporting endpoint `GET /api/lead-candidates/picks?k=5` lets the
UI refresh picks after manual edits without re-running discovery.

`compute_picks` ranks: `ready_for_outreach` first, then `score` desc.
Excludes `approval_status='converted' / 'rejected'` and
`confidence='Reject'` — verified live (converted rows drop out, a
corporate-tagged candidate scoring -5 stays out of picks).

**New UI shell (replaces the v9.0 filter-chip view as the default):**

- Big primary button **🚀 Find Leads For Me** with just 3 inputs
  (business type, location, count) — runs the whole pipeline
- "What do I do next?" callout appears after a run, copy-verbatim:
  *"Start with Logan's Picks. Click Use This Lead on the best one.
  Logan will prepare the outreach, but you still send it manually."*
- **🏆 Logan's Picks** section at the top — top 5 cards with
  pick_reason, best_contact_route, suggested offer, one main action
- Status group sections, each a collapsible `<details>`:
  **🔥 Hot Leads** (ready_for_outreach), **🌤️ Maybe Leads** (pending
  with name + score), **🔍 Needs Research** (needs_research approval
  or empty research-mission), **✗ Rejected**, **✓ Converted**
- Hot + Maybe open by default; Needs Research, Rejected, Converted
  collapsed by default

**New simplified card** — shows only:
- Name + score badge + Ready badge
- Category · location
- One-line "Why Logan picked it" (from `opportunity_reasons[0]`)
- One-line contact summary
- ONE primary action: **✓ Use This Lead** (when ready) or
  **🔍 Research This** (when missing name/contact) or **Reject**

All of v9.0's detail (missing-data chips, score math, weak presence
flags, raw editable fields, drafts panel, Enrich, Prepare Outreach,
Mark Researched, Delete, Save) collapses under
**⋯ More options** disclosure. Nothing is removed — just defaulted-hidden.

**New Ready-to-Send view** — when **Use This Lead** is clicked:
1. JS auto-approves the candidate if pending
2. Calls convert (creates a Logan lead with `source='Logan'`,
   `outreach_status='not_started'`)
3. Opens a focused panel that takes over the top of Possible Leads:
   - Business / Category / Contact route / Why this lead / Suggested offer
   - 4 draft blocks (Email, Facebook DM, Text message, Phone notes)
     each with **Copy** button (clipboard API + graceful fallback)
   - **✓ Mark Contacted** — updates the lead's `outreach_status` to
     `contacted` and closes the panel
   - **← Back to Leads** — closes the panel

If the candidate is unenriched at click time, Use This Lead enriches
first so drafts are guaranteed to exist when the panel opens. If the
candidate is already converted, conversion is skipped and the panel
opens directly.

**Research This** flow: flips the candidate to `needs_research`, opens
the Advanced disclosure, and scrolls the card's More Options open so
the search-link strip (Google / Facebook / Maps + per-field Find Email,
Find Phone, etc.) is immediately visible.

**Live verification (7 tests):**

```
1. do-it-all (Austin TX cafes, count=4)
   → 4 OSM + 0 fallback + 4 enriched + 3 picks; one round trip ~6s
2. GET /api/lead-candidates/picks?k=3 returns the same picks
3. PUT phone + re-enrich → ready_for_outreach=True, contact_routes=['phone']
4. Use This Lead flow: approve → convert succeeds, lead.source='Logan',
   outreach_status='not_started'
5. Mark Contacted: PUT outreach_status='contacted' → 200
6. picks/v after convert: converted row excluded
7. compute_picks excludes Reject-confidence rows (corporate, score=-5)
```

Christian Kovac safe across the cycle. Test candidates + test lead
all cleaned up; leads.json byte-identical to pre-test.

**Compile checks:**
- `py_compile hub/app.py automation/lead_candidates.py automation/lead_missions.py` → PASS
- `node --check hub/static/app.js` → PASS
- Module-init smoke (`/tmp/run_app.js`) → PASS

**Safety perimeter — every constraint preserved:**

- ❌ No auto-contact. No auto-send. No form submission. No scraping.
  No paid APIs. No OAuth. No new Python deps.
- ❌ Zero "3 free fixes" language added in the v9.1 diff (verified
  by `git diff | grep`).
- ✅ Use This Lead auto-collapses Approve → Convert → Prepare-Outreach
  into one click, but **send is still manual** — the user copies a
  draft, sends it from their own client, then clicks Mark Contacted.
- ✅ Discover still goes through Nominatim + Overpass only (the v8.9.1
  flow). No new outbound endpoints.

---

## v9.0 — Logan Lead Enrichment Engine

v8.9.1 prevented empty results but still left the user doing all the
work after Discover landed. v9.0 takes the next bite: Logan now takes
a candidate row and derives a structured analysis on top of it — the
"why this score" bullets, the missing-data checklist, the weak-presence
flags, the opportunity reasons, the suggested offer, the four outreach
drafts, and the Ready-for-Outreach gate.

**Honest framing first** — enrichment here is local derivation +
scaffolding, not external data fetching. We don't scrape, we don't pay
APIs, we don't crawl business websites to extract emails. What we
do compute, from data already on the row plus the spec's rule set:

- weak-presence flags (11 spec flags, internal notes only — never
  insulting copy)
- opportunity reasons in human-readable bullets
- score-explanation bullets that map 1-to-1 with the v8.8 scoring rules
- 5 missing-data chips: Website / Phone / Email / Facebook / Contact form,
  each tagged Found / Missing / Needs Check
- per-field targeted search URLs ("Find email" → `"{name}" "{city}" email`,
  etc.) for what's still missing
- standardized offer suggestions: **Free homepage mockup**, **Starter
  website fix from $150**, message angle from spec section 6
- four outreach drafts: email subject+body, Facebook DM, text message,
  phone call notes. Every draft uses the **free homepage mockup** CTA.
  ZERO "3 free fixes" language anywhere — verified by grep against the
  whole repo (the only occurrences are comments forbidding the phrase).
- `ready_for_outreach` boolean — true only when the row has
  business_name + category + city_state + at least one contact route
  + score ≥ 1 + an offer angle + generated email_body

**New endpoints:**

- `POST /api/lead-candidates/{cid}/enrich` — one row
- `POST /api/lead-candidates/bulk-enrich` body `{ids: [...]}` — many
  rows, per-row failure capture

**New candidate fields** (additive; legacy rows setdefault on load):

- `enrichment_status` enum: `not_started | enriched | partial | needs_research | failed`
- `enrichment_notes: str` — human-readable summary line
- `missing_fields: list[{field, status}]`
- `opportunity_reasons: list[str]`
- `weak_presence_flags: list[str]`
- `score_reasons: list[str]`
- `ready_for_outreach: bool`
- `outreach_drafts: dict` with 5 fixed keys
- `contact_routes: list[str]`
- `last_enriched_at: str | None`
- `facebook_url`, `instagram_url`, `contact_form_url`, `service_area: str`

`CandidateIn` Pydantic model extended with all 14 new fields. FastAPI
silently drops undeclared fields — added proactively to avoid the
v8.4.1 / v8.7 silent-drop pattern.

**UI:**

- Per-card **✨ Enrich** button (saves any pending edits first, runs
  enrichment, refreshes the card)
- Per-card **📝 Prepare Outreach** button (same endpoint — re-runs
  enrichment so drafts pick up fresh field data)
- Card body grows enrichment sections that only appear when populated:
  Missing data chips, Why this score, Opportunity, Weak presence,
  Suggested offers, Outreach drafts (4 stacked blocks with Copy buttons)
- **🚀 Ready for Outreach** badge next to the name when the gate passes
- Enrichment-status pill alongside source/approval badges
- Top toolbar: **✨ Enrich All Visible** + **⭐ Enrich Top 25**
- Bulk toolbar: **✨ Enrich selected** as a new action
- 7 new filter chips: Needs Email / Needs Phone / No Website /
  Facebook Only / Ready for Outreach / Needs Research / Rejected
- Empty-enrichment fallback panel on research-mission rows with no
  business_name uses the spec verbatim: *"Logan could not confirm more
  details yet. Use the search links above or mark this as Needs Research."*
- Copy-to-clipboard button on each draft (with graceful fallback when
  navigator.clipboard is unavailable)

**Live verification:**

```
1. OSM discover cafes in Austin TX → 3 OSM candidates added
2. Enrich one → enrichment_status=partial (no contact on OSM row);
   missing_fields = all 5 missing; 2 weak flags fired
3. Drafts spec compliance: zero "3 free fixes" in any draft;
   free-mockup CTA present in email_body, fb_message, sms_message,
   phone_notes
4. Discover thin OSM (Mountain View, AR) → research-mission row
5. Enrich empty research-mission → enrichment_status=needs_research,
   ready_for_outreach=False, enrichment_notes = spec-verbatim line
6. PUT business_name + phone, re-enrich → enrichment_status=enriched,
   ready_for_outreach=True, contact_routes=['phone']
7. Bulk enrich 6 rows → 6 enriched / 0 failed
8. Legacy row (no v8.9.1 / v9.0 fields) loads with all defaults:
   enrichment_status='not_started', ready_for_outreach=False,
   outreach_drafts={} — no crash, no silent corruption
```

**Compile checks:**

```
py_compile hub/app.py automation/lead_candidates.py automation/lead_missions.py → PASS
node --check hub/static/app.js                                                    → PASS
module-init smoke via /tmp/run_app.js                                             → PASS
```

**Safety perimeter — every constraint preserved:**

- ❌ No auto-contacting. No auto-sending. No scraping. No paid APIs.
- ❌ No OAuth. No new Python deps.
- ❌ Zero outbound calls in the enrichment path — pure local derivation.
  (The Discover call still goes to OSM, unchanged from v8.9.1.)
- ❌ Zero "3 free fixes" language in user-facing copy. Verified by
  whole-repo grep. The only occurrences are guardrail comments in
  `lead_candidates.py` explicitly forbidding the phrase.
- ✅ Approval still required before convert. Send still manual.
- ✅ Converted leads still arrive with `outreach_status='not_started'`.
- ✅ Christian Kovac untouched across the full test cycle.

---

## v8.9.1 — Logan discovery fallback when OSM is thin

v8.9 was honest about OSM coverage variance ("well-mapped metros return
10-30; thin areas may return fewer"), but it still left the user with
empty results when "fewer" meant zero. Small US towns, niche services,
and rural areas all hit this case. v8.9.1 promises: **Logan never ends
with an empty queue unless an actual error fires.**

If OSM returns fewer than the requested `count`, Logan tops up the gap
with **research missions** — candidate cards pre-loaded with Google,
Facebook, and Maps search links the user can click to finish the find
themselves. Each card lands as `approval_status='needs_research'`;
clicking **✓ Mark Researched** flips it to `pending`, then the existing
approve → convert path takes over.

**New candidate fields** (additive; legacy rows setdefault on load):

- `discovery_source: "osm" | "research_mission" | "manual"` — drives
  the source badge in the UI
- `search_phrase: str` — the rotating SERP phrase encoded into the
  search URLs (e.g. `"plumber Hot Springs AR email"`,
  `"site:facebook.com plumber Hot Springs AR"`)
- `search_urls: [{label, url}, ...]` — three platform links per card
  (Google + Facebook + Maps); both OSM and research-mission cards
  carry these so users can cross-check anything with one click

**Phrase rotation** — 10 templates covering the spec's verbatim examples:

```
{cat} {city} email
{cat} {city} gmail.com
{cat} {city} contact
{cat} {city} phone
{cat} {city} "call or text"
{cat} {city} "free estimate"
site:facebook.com {cat} {city}
{cat} {city} "find us on facebook"
{cat} {city} instagram.com
inurl:facebook.com {cat} {city}
```

**New state transition**: `mark_researched()` flips `needs_research → pending`.
Refuses to flip rows in other states (raises ValueError → HTTP 400).

**New / changed endpoints:**

- `POST /api/lead-candidates/discover` — response now carries
  `osm_added`, `research_missions_added`, `fallback_triggered`. When
  `osm_added=0 && fallback_triggered=true`, message reads exactly:
  *"OSM did not have enough businesses for this search, so Logan
  created research missions instead."*
- `POST /api/lead-candidates/research-missions` (new) — explicit
  fallback generator for the "Find More Anyway" button; reuses
  `CandidateFindIn`
- `POST /api/lead-candidates/{cid}/mark-researched` (new) — the
  needs_research → pending transition

**`CandidateIn` Pydantic model extended** with `search_phrase`,
`search_urls`, `discovery_source`. FastAPI silently drops undeclared
fields; missing these would have erased the research-mission payload
on the first PUT (the v8.4.1 / v8.7 silent-drop pattern, but applied
proactively this time).

**UI changes:**

- New third form button **🔍 Find More Anyway** — generates +N research
  missions for the current category/city without touching OSM
- Card header gets a third badge: **🌍 OSM** / **🔍 Research** / **✋ Manual**
- Card body grows a search-platform strip — italic phrase line + three
  one-click buttons (Google / Facebook / Maps) — visible on every card
  that has `search_urls` populated
- Research-mission cards show a primary **✓ Mark Researched** button
  while in `needs_research`; clicking it (after filling business_name)
  promotes the card to `pending` and surfaces Approve / Reject
- Placeholder name copy for research-mission cards reads
  *"— research mission — open Google/FB/Maps below"*
- Help callout rewritten to promise the never-empty behavior

**Live verification:**

```
1. Discover plumbers in Mountain View, AR (small town)
   → osm_added=0, research_missions_added=5, fallback_triggered=true
   → message exact-verbatim spec line
2. Discover cafes in Austin, TX (rich OSM)
   → osm_added=5, research_missions_added=0, fallback_triggered=false
   → no fallback, standard OSM message
3. POST research-missions for "pressure washing" in Hot Springs, AR
   → 4 rows added, each with Google/Facebook/Maps + needs_research
4. Mark Researched flips needs_research → pending; second flip → 400
5. Garbage city → 502 with Nominatim error
6. PUT round-trip preserves search_phrase, search_urls, discovery_source
   (no silent drop)
```

**Safety perimeter — every constraint preserved:**

- ❌ No auto-contacting. No auto-sending. No scraping. No paid APIs.
- ❌ No new Python deps. No outbound calls in the fallback path
  (research missions are pure URL string construction).
- ✅ Research missions land as `needs_research` — approval still
  required before convert
- ✅ Converted leads still arrive with `outreach_status='not_started'`
- ✅ Logan never lands on empty results unless an actual error
  (Nominatim 502, count cap 400) fires

---

## v8.9 — Logan actually discovers (OpenStreetMap)

The v8.8 "Possible Leads" queue was the right shape, but the wrong premise:
it asked Topher to do the hunting one stub at a time. v8.9 flips it. Logan
now actually finds real local businesses by querying OpenStreetMap, and
Topher just approves them.

**Two outbound HTTPS calls per "Discover" click**, both to OSM:

1. `nominatim.openstreetmap.org` — resolves "City, State" to a specific
   OSM relation_id. Required because multiple US cities share names
   (Hot Springs exists in AR, SD, MT, NC, VA) — name-only filters in
   Overpass alone produced cross-state leaks during testing.
2. `overpass-api.de` — Overpass QL query scoped to that exact relation_id,
   returning real businesses matching the category tag pair.

Both endpoints are part of the OpenStreetMap project. Free, public, no
auth, no key, no paid plan, no scraping. UA identifies the tool by name
+ version, no PII. One read-only call to each, no writes.

**New module: `automation/overpass_discovery.py`** (+450 LOC).

- `CATEGORY_TO_OSM` — 80+ entries mapping user category words to OSM
  tag pairs (`coffee shops → [amenity=cafe, shop=coffee]`,
  `plumbers → [craft=plumber]`, `dentists → [amenity=dentist, healthcare=dentist]`,
  etc.). Unknown categories fall back to `shop=<word>` + `amenity=<word>`.
- `US_STATE_NAMES` — accepts both `AR` and `Arkansas` input forms.
- `_parse_city_state("Hot Springs, AR")` → `("Hot Springs", "Arkansas")`,
  with friendly errors for unparseable / unknown inputs.
- `_call_nominatim()` — geocodes the city, returns the OSM osm_type + osm_id.
- `_overpass_area_id()` — converts osm_type/osm_id to Overpass's
  `3600000000 + relation_id` (or `2400000000 + way_id`) area ID format.
- `_build_overpass_query_by_area_id()` — primary path for cities resolved
  to a polygon (relations / ways).
- `_build_overpass_query_by_bbox()` — fallback when Nominatim returns a
  node (no polygon); queries within 8 km radius.
- `_map_to_candidate()` — extracts name, contact:phone/phone,
  contact:email/email, contact:website/website, addr:*, opening_hours.
  Sets `is_corporate=True` iff `brand` tag present (chain heuristic).
  Sets `is_active=False` iff any tag has `disused:` / `abandoned:` /
  `closed:` / `demolished:` prefix. Skips unnamed elements.
  Source URL links back to the OSM node/way for verification.
- `discover()` — orchestrates Nominatim → Overpass, dedupes by name,
  returns up to `count` real businesses. Never pads.

**`automation/lead_candidates.py`** — new `discover_via_overpass()` wrapper.
Calls `overpass_discovery.discover()`, dedupes against existing queue
rows by lowered (name, city_state) so re-running the same query is
idempotent, upserts with computed score, returns
`{added, added_count, found, skipped_duplicates, display_name, message}`.

**`hub/app.py`** — new `POST /api/lead-candidates/discover` endpoint
reusing the `CandidateFindIn` model. Maps `ValueError` → 400 and
`OverpassError` → 502 (helpful detail: "Nominatim found no city named
'Asdfqwerty' in Arkansas. Try a larger nearby city or check spelling.").

**`hub/templates/index.html`** — Possible Leads panel restructured:
- New primary button **🌍 Discover Real Businesses (OSM)**
- Secondary button **📋 Generate stubs (advanced)** keeps the v8.8 path
  for thin-coverage areas where OSM has nothing
- Both buttons share one form (category, city, count, web-status target)
  and route by `name="cand_action"` submitter value
- Warning callout rewritten — Logan now *can* collect; Topher reviews
- Help text honest about OSM coverage variance (well-mapped metros
  return 10–30; thin areas may return fewer or zero)

**`hub/static/app.js`** — form handler routes by `e.submitter.value`:
- `discover` → `POST /api/lead-candidates/discover`
- `find` → `POST /api/lead-candidates/find` (v8.8 stub path)
Optimistic in-flight status ("Asking OpenStreetMap…"), submit buttons
locked mid-flight to prevent double-fire, OSM error responses surface
the 502 detail to `#cmd-status` ("OSM rate-limited (429). Wait a
minute and try again.").

**Live verification:**

```
1. Discover coffee shops in Hot Springs, AR (count=8)
   → display_name: 'Hot Springs, Garland County, Arkansas, United States'
   → 5 OSM matches, 4 unique-named candidates added
   → Chipmunk Cafe, Argentinian Coffee & Wine Bar, Arlington Bar, Red Light Roastery
   → ALL Arkansas (no SD leak — disambiguation works)
2. Re-run same discover → 0 added, 4 dedup'd (idempotent)
3. count=26 → 400 with cap message
4. Garbage city → 502 "Nominatim found no city named 'Asdfqwerty'…"
5. Malformed city_state → 400 with parse error
6. Approve + Convert → Logan lead with source='Logan', outreach_status='not_started'
7. Cleanup → leads.json + candidates.json back to pre-test byte-state
```

**Safety perimeter — every constraint honored:**

- ❌ No scraping. Both endpoints are designed query APIs over open data.
- ❌ No paid APIs. Nominatim and Overpass are free, no-auth, public.
- ❌ No OAuth. No keys. No accounts. No cookies.
- ❌ No automated outreach. Discovered candidates land as `pending`.
  Topher reviews → approves → converts manually. The new Logan lead
  arrives with `outreach_status='not_started'`. Prepare Outreach is
  still a manual click. Send is still manual.
- ❌ No PII outbound. The query payload is category + city + state only.
  User-Agent identifies the tool by name + version, no email.
- ❌ No new Python dependencies. `urllib.request` + `json` only.
- ✅ One read-only call each to Nominatim + Overpass per Discover click.
- ✅ Idempotent: dedup against existing queue by (name, city_state).
- ✅ Honest about coverage: returns what OSM actually has; never pads.
- ✅ v8.8 stub path preserved as the "advanced" fallback for thin areas.

**Scope shift from v8.9 proposal:** I told you "one outbound HTTPS GET
per click" up front. The first live test revealed Overpass's nested
area-by-name filter doesn't strictly enforce geographic containment —
a `Hot Springs, AR` query leaked a `Hot Springs, SD` result. The clean
fix is Nominatim for unambiguous city resolution, which is one extra
call. Same OSM project, same trust model, but I want it on the record:
v8.9 ships as **two outbound calls per Discover click**, not one.

---

## v8.0

Pure reorganization, no new features. Goal: a first-time user should understand the page in under 30 seconds.

**New top-level shape**: `Top bar` → `Today` panel → `▶ Parker` → `▶ Logan` → `▶ Olivia` → `▶ System` (with 5 sub-collapsibles) → `Command Output`. All five partner / system sections collapsed by default.

**Top bar (sticky)**: Refresh Hub, Run Daily Ops, Verify All Connections. The rest of the old Control Panel buttons moved into context — Generate / Review / Approve Visible / Reject Visible live inside ▼ Parker; Connect LinkedIn / Setup .env / Wizard Help / Show Missing Setup live inside ▼ System › Connections; Show Diagnostics / Refresh Summary / Open Latest Report / Open Logs / Stop Hub live inside ▼ System › Diagnostics & Logs.

**Today panel**: four clickable cards that summarize what matters right now:

| Card | Source | Click target |
|---|---|---|
| Leads needing attention | overdue + due today via v7.24 dashboard math | Opens ▼ Logan |
| Ready to publish | `_readyPosts.length` | Opens ▼ Parker + scroll to Ready list |
| Hub health | `/api/status.health.status` (✓ PASS or ✗ FAIL) | Opens ▼ System › Diagnostics |
| Today's summary | today's date as a shortcut | Opens ▼ Olivia + scroll to summary |

**Section summaries show live metrics**: each collapsed partner header includes a one-line metric string (e.g. `Parker · Content + publishing · 37 pending · 13 approved · 2 posted`) so the user can read partner state without expanding.

**Everything still works**: every existing element id, endpoint, render function, event delegator — preserved. The old `#mission-control` and `#partner-rooms` divs are kept (hidden) so the legacy render paths still execute; their data is duplicated to the new surfaces via new `renderTodayPanel()` and `_updatePartnerSummaries()` helpers. No schema change, no API change, no OpenAI, no posting.

---

## v7.x

v7.31 — **Olivia summary archive**. A "Past Summaries" block under the existing Today's Summary section. Lists every `summaries/*.md` filename whose stem matches `^\d{4}-\d{2}-\d{2}$`, newest first. Click a date → fetches the content via `GET /api/summaries/{date}` and shows it in an inline viewer with a Close button. Two new read-only endpoints: `GET /api/summaries` (list) and `GET /api/summaries/{date}` (one). Date input is regex-gated server-side to block path traversal — `/api/summaries/../etc/passwd` and friends return 404/400, verified live. Pure stat/read; no schema change, no OpenAI, no DB write. Olivia's v7.30 "Open Today's Summary" button still lands the user in the same section — the archive sits right below the today panel.

v7.30 — **Make Olivia honest**. Same treatment as Logan got in v7.29:

1. `/api/partners` returns Olivia with `status: "active"` (was `"standby"`). She was always active — `daily_ops.py` has been writing her `summaries/*.md` + `status_history/*.json` every morning since v0.1 — the status label was the only thing lagging the truth.
2. `renderPartners` gives Olivia her own actionsHtml with a primary `Open Today's Summary` button.
3. New `olivia-open` click handler smooth-scrolls to the Today's Summary section (now bears an `id="summary-section"` for that hook).

All three Partner Rooms now show truthful status badges + real metrics + functional buttons. The disabled "Coming Soon" fallback path stays in the code for any future partner that hasn't been wired yet, but no current partner uses it.

v7.29 — **Logan partner room fix**. Logan is no longer "Coming Soon". Three changes:

1. `/api/partners` returns Logan with `status: "active"` (was `"standby"`), and adds a third metric `scout_queue` (count of active scout rows — anything not converted/rejected) alongside the existing `prospects_tracked` and `outreach_queue`.
2. `renderPartners` now branches three ways instead of two: Parker keeps its Refresh + View Drafts; Logan gets a new primary `Open Logan Leads` button; Olivia stays on the Coming Soon fallback (her surface is still placeholder).
3. Click handler delegates `logan-open` → smooth-scroll to `#leads-section` (which holds both the Logan list/board/dashboard AND the v7.28 Lead Scout Queue at the bottom).

Mission Control's partner strip also updates to show Logan as Active, since it reads `p.status` from the same `/api/partners` payload.

v7.28 — **Logan Lead Scout Queue**. Logan includes a Lead Scout Queue for manually capturing local businesses that may need web design, cleanup, tap hubs, or AI systems. Scout leads can be qualified and converted into regular Logan leads.

Under the hood: new `automation/scout_queue.py` (mirrors the `leads.py` atomic-write + whitelist pattern), separate `data/scout_queue.json` (gitignored), six-state lifecycle (`new` / `qualified` / `contacted` / `follow_up` / `converted` / `rejected`), three-priority enum (`low` / `medium` / `high`). Five endpoints: `GET/POST/PUT/DELETE /api/scout-leads/...` plus `POST /api/scout-leads/{id}/convert` which copies the row into the existing Logan leads registry as a cold lead (with notes that carry the scout evidence + offer angle + website status) and marks the scout row `converted` with a back-reference to the new lead's id. **No scraping. No browsing the web. No outreach. No OpenAI.** Pure local capture + qualification queue; the convert helper is the only cross-data-file write.

v7.27 — **Drag-and-drop board moves**. Each pipeline-board card is now `draggable="true"`; columns are drop targets. Drop on a different column → PUT `/api/leads/{id}` with the new status via the shared `_moveLeadToStatus` helper (same path the v7.23 buttons use, so safety gates, error handling, and the success toast stay consistent across both UIs). Visual cues: source card dims (`is-dragging` class, 0.4 opacity), target column highlights with a blue tint on hover. Same-column drops short-circuit before the network call to avoid a no-op PUT that would re-stamp `updated_at`. The v7.23 quick-move buttons remain — they're the keyboard/touch fallback since HTML5 DnD is mouse-only without polyfills.

v7.26 — **Clear filters link**. A subdued underline-styled "Clear filters" button in the leads toolbar, visible only when any of the three stackable filters is active (text search, v7.2 due-this-week chip, or v7.25 dashboard filter). Click resets all three at once, syncs the DOM controls (text input, chip aria-pressed), and re-renders dashboard + board + list. Visibility recomputes from `renderLeads()` which fires on every filter change, so no extra wiring per filter.

v7.25 — **Dashboard click-to-filter**. Each of the v7.24 cards is now a `<button>`. Click one → the matching predicate filters both the pipeline board (pre-grouping) AND the list (joins the existing text + due-this-week chain). Click the active card again to clear. Active state shows as a solid dark fill + `aria-pressed="true"`. Predicate stacks: text-search + due-this-week chip + dashboard filter can all be active at once. Not persisted across reloads — it's an action filter, not a preference.

v7.24 — **Lead Dashboard**. Six-card summary strip above the v7.23 pipeline board:

| Card | Source |
|---|---|
| Cold | leads with `status == 'cold'` |
| Warm | leads with `status == 'warm'` |
| Hot  | leads with `status == 'hot'` |
| Due Today | `follow_up_date == today` |
| Overdue | `follow_up_date < today` |
| Closed This Month | `status == 'closed'` AND `updated_at` is in the current YYYY-MM |

Pure-frontend derivation from the existing `_leads` cache — no new fetch, no new endpoint, no schema change. Cards flex-wrap on narrow viewports. Per-card tonal border-left matches the existing badge palette (overdue + hot share red; due today is blue; closed-this-month is green). Cards render on every `loadLeads`, so any move/edit/import updates the strip in lockstep with the board and list. No OpenAI, no posting, no LinkedIn API.

v7.23 — **Logan Lead Pipeline Board**. A 5-column board (Cold / Warm / Hot / Closed / Dropped) added to the LinkedIn Leads section, above the existing list. Same `_leads` cache — no new fetch, no new endpoint. Each board card shows name, company, follow-up date (with overdue cue), last template used (v7.18 field), and quick-move buttons sized to the lead's current status: from Cold you see *Move to Warm / Hot / Closed / Drop*; from Warm you see *Move to Hot / Closed / Drop*; etc. (the no-op button matching the current status is omitted). Per-status border tint matches the v6.9 list badge palette. Moves use the existing `PUT /api/leads/{id}` with a partial body; server-side `_clean_lead` still validates against ALLOWED_STATUSES, so a tampered request returns 400 with a helpful message. Pipeline counts per column live in a small pill badge. No schema change, no DB write outside `data/leads.json`, no OpenAI, no LinkedIn API.

v7.22 — **Fix: Hub stuck on "Loading…"**. Two changes:

1. **Root cause**: a v7.17 `change`-event handler was placed ABOVE the `const _leadsListEl = …` declaration it referenced. With `const`/`let` that's a Temporal Dead Zone access, which throws synchronously during module init — every event handler below the throw stayed unbound, and the page sat on the initial `Loading…` markup forever. Handler moved to right after the declaration.

2. **Defensive hardening of `refreshAll`**: each loader now runs through a `_runLoaderSafely(name, fn)` wrapper that catches per-section failures so one bad fetch can no longer short-circuit a `Promise.all` and leave 9 other sections stranded. Failures are collected and surfaced in Command Output as `FAIL <loader>: <error>` lines so the next-time-this-happens diagnostic is one click away instead of buried.

v7.21 — **Publishing-staleness mood + one-click bulk publish**. Two pieces:

1. Mission Control's mood flips to **`Ship stale`** (yellow) when there are ready posts AND nothing has been published in the last 24h. Was always green ("Ready to publish") even when the publish queue had been stalled for days. Uses a new `_lastHistory` module cache + `_hoursSinceLastPublish` helper; the existing posted_date local-time strings parse correctly without server changes.

2. A **`Publish N verified`** button next to the Ready to Post header. Hidden when zero verified+wired posts exist. Click → single up-front confirm with per-platform breakdown → sequential POST `/api/posts/{id}/publish` for each → progress streamed to Command Output ("OK #47 (LinkedIn)" / "FAIL #48 (Facebook): ..."). Uses the same `social_posters` path as the per-row buttons, so safety gates (verified-connection check at the API layer) are unchanged.

Only platforms with a wired publish path are eligible (LinkedIn, Facebook today). Verifying Instagram or GBP doesn't add them to bulk publish yet — those still need a per-row publish action shipped first.

v7.20 — **Bulk lead capture**. A "+ Bulk Add" button next to "+ Add Lead" opens a textarea; paste up to 50 LinkedIn URLs or handles (one per line), submit, and the server creates cold leads with `source="paste-import"`. New endpoint `POST /api/leads/batch` parses each line independently — accepts `https://www.linkedin.com/in/slug/`, `linkedin.com/in/slug`, with/without protocol/www/trailing-slash. Dedupes against existing leads AND within the same paste (case-insensitive by handle). Lines starting with `#` are treated as comments and skipped. Unrecognized non-blank lines are reported back. Name is guessed from the slug (`christian-kovac` → `Christian Kovac`); user can edit after import. Section-level toast reports the counts ("Added 3, 1 duplicate, 2 unrecognized."). Single atomic disk write per batch.

v7.19 **skips unconfigured platforms at generation time**. `daily_runner.py` now reads `connection_state` and only generates drafts for platforms whose live trust state is `verified`. The Parker prompt is rebuilt dynamically — hashtag picks, per-platform hashtag blocks, and the closing "Generate today's posts for X" sentence all reflect only the verified set. Defense-in-depth: even if Parker ignores the prompt and emits sections for unverified platforms, both the markdown-write loop and the SQLite insert loop drop them, and the cron log records what was skipped. If NO platforms are verified, the run short-circuits cleanly before any OpenAI call so the cron doesn't burn credits or pile up unshipping drafts.

v7.18 **persists the last-used template** per lead. New nullable field `last_template_key` on each row, written by `draft_message` whenever a template runs (auto-pick or explicit). On render, the per-card picker defaults to the lead's last_template_key if it still points to a registered template; otherwise falls through to Auto. One-time schema migration: existing rows get `last_template_key: null` the first time any save touches the file. No new endpoint, no API contract change beyond the extra field.

v7.17 adds **template preview on hover** to the v7.16 picker. `GET /api/leads/templates` now also returns each template's raw body. The frontend renders `{name}`/`{company}` substituted previews into `title=` attributes on every `<option>` *and* on the select itself (mirrored on `change` so the closed control shows the currently-selected template's preview). Pure native tooltips — no custom popup, no extra round-trips, degrades gracefully on browsers that don't show `<option>` titles in the dropdown.

v7.16 — **Logan Outreach Pipeline (multi-template messaging)**. Replaces the single fixed v7.0 outreach template with a stage-aware registry of four:

| Key | Label | Default for status |
|---|---|---|
| `intro` | Intro | cold |
| `check_in` | Check-in | warm |
| `value_add` | Value-add | (warm, by user choice) |
| `close_ask` | Close ask | hot |

The Write Message button now sits next to a per-card `<select>` — `Auto` (server picks the default for the lead's status) or any of the four templates explicitly. The API: `POST /api/leads/{id}/message-draft` now accepts an optional `{"template": "<key>"}` body and returns `{message, lead, template}` so the v7.9 toast can confirm which template ran (e.g., "Draft ready: Intro"). A new `GET /api/leads/templates` exposes the registry so the frontend picker stays in sync with `automation/leads.py` without hardcoding labels. Still NO OpenAI, NO outbound LinkedIn messaging, NO scraping — pure local string substitution, copy-paste workflow unchanged.

The Hub includes a live System Activity feed showing recent generation, review, verification, refresh, and publishing events. The feed is assembled read-only from existing sources (`posts`, `post_history`, the connection-state cache) — no new schema, no polling loop. System Activity shows date-aware timestamps when events span multiple days. Activity feed type filters let you scope the timeline to a single event type (Generation, Approval, Connection, Publish, Refresh, System). The chip row and day dividers stick to the top of the viewport while scrolling so the active filter and current day stay visible. Filter selection persists across page reloads via `localStorage` (`partnerdesk.activityFilter`). The feed surfaces a distinct `publish` event for each post whose status flips to `posted` (backed by a new nullable `posts.posted_at` column populated by `mark_status`). The active chip shows a `×` shortcut to clear the filter and return to All. `system` events surface from `logs/*.log` modification times (read-only `stat()`; log contents are never opened or parsed). A `refresh` event surfaces from `data/connection_status.json` mtime to mark the most recent trust-state refresh.

The Hub also includes a **Report Center** panel that surfaces `GET /api/history/analytics` with a window selector (7 / 30 / 90 / 365 days) and proportional bars per row for top topics, top platforms, and top topic × platform combos. Read-only; no schema change, no new endpoint.

The Hub also includes a **Report Inbox** that lists daily report files written by `automation/daily_report.py` (run by the cron each morning with `--yesterday`). Reports live at `reports/YYYY-MM-DD.md` and are summary-only (counts plus topic/platform labels — no post content, no secrets). Two read-only Hub endpoints back the inbox: `GET /api/reports` (metadata list) and `GET /api/reports/{YYYY-MM-DD.md}` (markdown content), both guarded with a strict filename regex against path traversal. The preview pane renders a small markdown subset (h1–h3, `**bold**`, `-` bullets, `---` rules) with HTML-escape-first XSS protection, and includes a Download button that saves the raw `.md` file locally. A filter row above the list supports date-substring search, a window selector (All / 7 / 30 / 90 days), and a "Hide empty days" toggle that drops rows with zero approvals and zero publishes. All three filter values persist across page reloads via `localStorage` (`partnerdesk.inboxFilters`). A **Clear filters** button in the row resets all three to defaults and removes the persisted state; it's only shown when at least one filter differs from its default. The row matching today's date is marked with a `· today` suffix and a small left-edge accent. The currently-selected report also persists across page reloads via `localStorage` (`partnerdesk.inboxSelected`); stale references to since-deleted reports are auto-cleared. The Report Inbox automatically scrolls the selected, today, or newest report row into view on load. Keyboard navigation: ↑/↓ (or `k`/`j` Vim-style) to move focus, Enter to open the focused report, Esc to clear focus, `/` to jump to the inbox search input. Press `?` anywhere on the page to toggle a keyboard shortcuts panel. The inbox list auto-focuses on first load so the keys work immediately (only when nothing else is focused, never steals focus from a user-clicked element). Each row also shows that day's approval and publish counts (derived server-side from `post_history` and `posts.posted_at`); zero-activity days have a dimmed counts line so busy days visually pop. To seed the inbox manually: `python3 automation/daily_report.py --backfill 14`.

The Hub shows PartnerDesk status, Parker Promo activity, today's summary, latest logs, and quick actions:

- **Refresh Hub** — re-reads status, summary, and logs (no scripts run).
- **Run Daily Ops** — runs `automation/daily_ops.py` (generate + snapshot + summary). Asks for confirmation because it calls OpenAI.
- **Refresh Summary Only** — runs `daily_ops.py --skip-generate` (no OpenAI).

Future partners (Logan Leads, Olivia Office) appear as "Coming soon" cards.

The Hub also shows Parker Promo's recent draft activity from the local SQLite database.

Recent Parker Work rows can be clicked to preview draft content directly in the Hub.

Drafts can be approved or rejected from the Hub preview modal. Approval updates the local database and post history only; it does not post publicly.

The Hub also shows an Approved History timeline from the local `post_history` table.

The Hub includes basic approval analytics from `post_history`, including top topics and platforms.

Recent Parker Work can be searched and filtered by platform or status.

The Recent Parker Work filters include a live "Showing X of Y" counter.

The Hub can approve all currently visible Recent Parker Work rows after filtering. Approval updates the local database and post history only; it does not post publicly.

The Hub can also reject all currently visible Recent Parker Work rows after filtering. Rejected drafts stay in the database.

Each Recent Parker Work row also has small ✓ / ✗ buttons for one-click approve or reject without opening the preview modal. Each click still requires a browser confirm.

Approved drafts appear in the Hub's Ready to Post queue. From there, Topher can copy the post text and manually publish it. Approval does not auto-post publicly.

The Ready to Post queue shows each approved post as a readable card with full content, copy controls, and platform-specific publish buttons. Before publishing, the Hub shows the exact text that will be posted and requires confirmation.

Ready to Post items can be marked as posted after manual publishing. This only updates local tracking and does not publish automatically.

Draft content can be edited directly in the Hub preview modal before approval, copying, or manual posting. Editing only updates the local SQLite content field.

Edited drafts track a local `edited_at` timestamp for review history. Editing remains local-only and does not publish publicly.

---

v7.15 normalizes the last filter-empty outlier: `'No matching Parker work.'` → `'No Parker work matches the filter.'`, matching the structure of `'No leads match the filter.'` and `'No reports match the current filter.'` The rest of the v7-walkthrough's empty-state findings turned out to be coherent on closer inspection (e.g. `'No data in this window.'` matches the section's own "Window:" selector label, and the duplicated "configured" strings live in different sections).

v7.14 wires the **Olivia Office partner card** to real data. `summaries_generated` now counts `summaries/*.md` (written by `automation/morning_summary.py`) and `snapshots_archived` counts `status_history/*.json` (written by `automation/status_snapshot.py`). Both are produced by `daily_ops.py`. A new `_count_partner_files` helper skips `.gitkeep`/`.DS_Store` via suffix filtering and returns 0 on missing dir. Olivia was the last partner card still showing hardcoded zeros; all three partner roster cards now show truthful counts.

v7.13 replaces the bare `—` placeholders in the Report Center's error branch (`renderReports(null)`) with `Data unavailable.` The dashes read like "loading" or "broken"; the new copy reads honestly as an error. Note: this is the *error* branch, not the empty-window branch — the latter already shows `No data in this window.` via `_renderReportList([])`.

v7.12 wires the **Logan Leads partner card** to real data. `prospects_tracked` now equals `len(leads_mod.load())` and `outreach_queue` equals the count of leads whose status is not `closed` or `dropped`. Logan was previously hardcoded to `0/0` even after the v6.9 leads tracker shipped — that surface lied for every build between v6.9 and v7.11. Olivia's card is still a placeholder (no real metric source exists yet).

v7.11 replaces all 8 leads-section `alert()` calls with the existing `_flashLeadToast` helper in an `'error'` variant. Per-card errors attach to the matching card; the Add Lead error (where no card exists yet) falls back to a section-level toast at the top of `#leads-list`. Error toasts use a red palette (`.lead-toast-error`) and a longer 5.0s/5.8s fade so the user has time to read them. Non-blocking — no more modal interruption when a request fails.

v7.10 polishes the **empty-state copy** for the v7.2 due-this-week filter. When the chip is on and zero leads qualify, the list now reads `Nothing due this week — nice.` instead of the generic `No leads match the filter.` — empty is *good news* under that filter, not a failed search.

v7.9 adds the same `_flashLeadToast` to **Write Message** (`Message draft ready`). The draft also lands in the Command Output panel (and on the card via the collapsible "Last message draft" details), but those are different regions on the page — the toast confirms the action where the click happened.

v7.8 extends the toast to the **manual Save Date and Clear buttons**: Save shows `Follow-up set to YYYY-MM-DD` (or `Follow-up cleared` if the user submitted an empty date), Clear shows `Follow-up cleared`. Now every code path that mutates `follow_up_date` from the UI surfaces matching feedback, closing the gap with the v7.5 auto-snooze and the v7.7 preset toasts.

v7.7 adds **toast feedback for follow-up presets**: after a successful preset click, the card briefly shows `Follow-up set to 2026-06-07` using the same `_flashLeadToast` helper as the v7.5 snooze indicator. Makes preset feedback consistent with snooze feedback — same palette, same fade timing. One-line change.

v7.6 adds **keyboard hotkeys** to the follow-up form. With the form open, pressing `1` / `2` / `3` / `4` fires the corresponding preset (Tomorrow / +1 week / +2 weeks / +1 month). The mapping is position-based — the keys match the buttons' left-to-right order, not the day counts (so `4` ≠ "4 days"). Opening the form now focuses the first preset button instead of the date input, so hotkeys work immediately; Shift+Tab lands on the date input for custom dates. Hotkeys are explicitly suppressed when focus is on any `<input>`, `<textarea>`, or `<select>` so typing a custom date isn't hijacked. Document-level listener; doesn't need re-binding on each render.

v7.5 adds a **snooze indicator** on Mark Contacted. When the v7.3 auto-snooze fires (the lead's `follow_up_date` was today or overdue and got cleared), the card briefly shows an amber toast like `Follow-up cleared (was 2026-05-10)` so the behavior is discoverable. Detection is purely client-side: the frontend captures `prevFollowUp` before the POST and diffs against the freshly loaded lead — if the prior date is non-null and the new date is null, the snooze fired. No API change. The toast fades after 2.5s and removes after 3.2s.

v7.4 adds **quick-set follow-up presets** to the per-card follow-up form: `Tomorrow`, `+1 week`, `+2 weeks`, `+1 month`. One click computes the date and saves it via the existing `POST /api/leads/{id}/follow-up` endpoint — no need to use the date picker for common cadences. The date picker + Save button stay for custom dates. Hovering a preset shows the resolved date as a tooltip. Pure frontend; no API change.

v7.3 adds **auto-snooze on Mark Contacted**: when you mark a lead contacted, the `follow_up_date` is cleared *only if* it was today or overdue — i.e., the reminder was satisfied by this contact. Future-dated follow-ups (e.g., "check in next week") are preserved because the user set them intentionally and today's contact doesn't satisfy them. The change is server-side in `automation/leads.py::mark_contacted`. No schema change; no frontend change (the page already re-renders from `/api/leads` after Mark Contacted, so the chip count and overdue badge update for free).

v7.2 adds a **"N due this week" chip** to the Leads toolbar. It counts leads whose `follow_up_date` falls in `[today, today+6]` (overdue is intentionally excluded — those already have a red on-card cue and the v7.1 sort surfaces them). The chip is hidden when the count is zero. Clicking it toggles a filter restricting the list to just those leads; it stacks with the text filter and the sort selector. Not persisted across reloads — it's an action filter, not a preference.

v7.1 adds a sort toggle to the Leads toolbar: **Newest updated** (default) or **Follow-up due first**. In follow-up mode, overdue leads come first (most-overdue → least-overdue), then today, then upcoming (nearest first), then leads with no follow-up date (sorted by `updated_at` desc). Overdue cards render the follow-up line in red with an `(overdue)` suffix; today shows `(today)`. The sort choice persists in `localStorage` (`partnerdesk.leadsSort`). Pure client-side over the cached `/api/leads` response — no API change, no schema change.

---

## Pre-v7

Earlier behavior — Mission Control, Control Panel, Meta Readiness Center, OAuth flows, LinkedIn Leads core (v6.9) — is documented inline in [README.md](./README.md) under the **PartnerDesk Hub** section.
