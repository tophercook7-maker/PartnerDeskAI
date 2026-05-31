# PartnerDeskAI

A local-first AI Business Partner system for **MixedMakerShop**.

PartnerDeskAI is a collection of AI "partners" — each one a focused role with its own prompt, memory, workflows, and reusable assets. Everything runs locally, writes to plain markdown + SQLite, and **requires human approval before any public action.**

## v0.1 — Parker Promo

The first partner. Parker Promo generates daily social media drafts (Google Business Profile, Facebook, Instagram, LinkedIn) using the OpenAI API and saves them to a dated folder for human review.

Nothing is auto-posted.

---

## Partners

PartnerDeskAI is evolving into a multi-partner local AI operating system.

Current partners:
- **Parker Promo** — content + publishing
- **Logan Leads** — lead generation (in progress)
- **Olivia Office** — operations/admin (in progress)

The Hub is the shared station where partners report activity and expose actions.

---

## Open the Hub

```bash
bash automation/open_hub.sh
```

Starts the local Hub server if needed and opens `http://127.0.0.1:8787`.

## Desktop Hub Icon

```bash
bash automation/create_desktop_launcher.sh
```

Creates `PartnerDesk Hub.command` on the Desktop. Double-click it to start/open the Hub.

## PartnerDesk Desktop App (v6.0)

```bash
bash automation/create_desktop_app.sh
```

Creates a proper macOS `.app` bundle (`PartnerDesk Hub.app`) on the Desktop. Unlike the `.command` launcher above, double-clicking the `.app` does NOT flash a Terminal window — it launches the Hub natively, shows the right name in Spotlight and the Dock, and can be dragged to the Dock for one-click access. Pure shell + bundle structure, no new dependencies.

The launcher captures startup output to `/tmp/partnerdesk-hub-launch.log` and shows a native macOS alert if the server fails to come up within 10 seconds (avoids the silent "browser opens to a dead page" failure mode). `open_hub.sh` actively probes for a python3 that has `uvicorn`+`fastapi` installed — so the .app works even though macOS launchd strips PATH down to a minimal set that doesn't include framework Python.

### First-launch macOS permission

The project lives under `~/Documents/`, which macOS Privacy & Security protects via TCC. The first time you `open` the `.app`, you may see:

- **A macOS permission prompt** asking whether `PartnerDesk Hub` may access your Documents folder → click **Allow**, then double-click the .app again. Done.
- **Or, no prompt at all** — the alert from the .app shows the launch log with `Operation not permitted`. In that case, open System Settings → Privacy & Security → **Files and Folders**, find `PartnerDesk Hub` (you may need to click `+` and add it from the Desktop), and toggle on **Documents Folder**. Or, alternatively, move the repo outside `~/Documents/` (e.g. to `~/Projects/PartnerDeskAI`) and re-run `bash automation/create_desktop_app.sh` so the new path is embedded.

The wrapper exits 0 even on failure (so macOS doesn't show its generic "unexpectedly quit" dialog on top of ours), and the full log is at `/tmp/partnerdesk-hub-launch.log`.

## PartnerDesk Hub

```bash
uvicorn hub.app:app --reload --port 8787
```

Open:

```
http://127.0.0.1:8787
```

The Hub includes a Mission Control section at the top that summarizes drafts, pending review, ready-to-post items, verified connections, partner status, and system mood at a glance.

Mission Control also includes a Quick Actions bar for running daily ops, refreshing the Hub, refreshing summaries, jumping to draft review, and jumping to Ready to Post.

The Hub includes a Control Panel for common PartnerDeskAI actions, reducing the need to use terminal commands during normal operation. Clicked Control Panel buttons briefly dim as visual feedback and lock against double-clicks for ~800ms. The Control Panel is the canonical action surface; the previous standalone Refresh Hub / Run Daily Ops / Refresh Summary buttons have been retired in favor of named action functions called directly by Mission Control and the Control Panel. The Hub / System group also includes a **Stop Hub** button (v6.5) that sends `SIGTERM` to the PID in `logs/hub.pid`; the endpoint validates the target is actually a `uvicorn hub.app` process before signaling (defense against PID reuse). The Hub Control Panel includes a **Show Hub Diagnostics** button (v6.6) that runs the local hub doctor and displays safe server/log status — output is redacted against any `.env` value, OAuth code/state query params, and Bearer tokens before being shown. The Hub also includes a **Meta Readiness Center** (v6.7) section with side-by-side cards for Facebook + Instagram showing setup status, required env keys (with present/absent ✓/✗ — never values), step-by-step setup checklists, and per-platform "Verify now" buttons. Backed by `GET /api/meta/readiness` which returns key NAMES only. Each Meta card has a free-text **App approval notes** textarea (v6.8, capped at 4000 chars, persisted atomically to `data/meta_app_state.json` which is gitignored; never stores anything fetched from Meta APIs) so you can track app-review status, granted permissions, and reviewer feedback per platform. Updates via `POST /api/meta/notes`.

The Hub also includes a **LinkedIn Leads** section (v6.9) — an outbound prospect tracker / CRM-lite. Add prospects with name, company, LinkedIn handle, source, status (`cold`/`warm`/`hot`/`closed`/`dropped`), and free-text notes. Pure local storage: no LinkedIn API, no auto-sync. Persisted atomically to `data/leads.json` (gitignored). CRUD via `GET /api/leads`, `POST /api/leads`, `PUT /api/leads/{id}`, `DELETE /api/leads/{id}` — all writes go through `automation/leads.py` which whitelists fields and clamps lengths. Filter by name/company/status from the in-section search box.

LinkedIn Leads includes a local follow-up queue with contacted status, follow-up dates, and simple message drafts. It does not message leads automatically. v7.0 adds three per-card actions backed by `POST /api/leads/{id}/contacted` (stamps `contacted_at`, auto-promotes cold→warm), `POST /api/leads/{id}/follow-up` (sets `follow_up_date` after validating YYYY-MM-DD), and `POST /api/leads/{id}/message-draft` (returns a fixed-template message — no OpenAI — and stores it in `last_message`). The message is shown in the Command Output panel with a Copy button; the user copies and pastes into LinkedIn manually.

v7.1 adds a sort toggle to the Leads toolbar: **Newest updated** (default) or **Follow-up due first**. In follow-up mode, overdue leads come first (most-overdue → least-overdue), then today, then upcoming (nearest first), then leads with no follow-up date (sorted by `updated_at` desc). Overdue cards render the follow-up line in red with an `(overdue)` suffix; today shows `(today)`. The sort choice persists in `localStorage` (`partnerdesk.leadsSort`). Pure client-side over the cached `/api/leads` response — no API change, no schema change.

v7.2 adds a **"N due this week" chip** to the Leads toolbar. It counts leads whose `follow_up_date` falls in `[today, today+6]` (overdue is intentionally excluded — those already have a red on-card cue and the v7.1 sort surfaces them). The chip is hidden when the count is zero. Clicking it toggles a filter restricting the list to just those leads; it stacks with the text filter and the sort selector. Not persisted across reloads — it's an action filter, not a preference.

v7.3 adds **auto-snooze on Mark Contacted**: when you mark a lead contacted, the `follow_up_date` is cleared *only if* it was today or overdue — i.e., the reminder was satisfied by this contact. Future-dated follow-ups (e.g., "check in next week") are preserved because the user set them intentionally and today's contact doesn't satisfy them. The change is server-side in `automation/leads.py::mark_contacted`. No schema change; no frontend change (the page already re-renders from `/api/leads` after Mark Contacted, so the chip count and overdue badge update for free).

v7.4 adds **quick-set follow-up presets** to the per-card follow-up form: `Tomorrow`, `+1 week`, `+2 weeks`, `+1 month`. One click computes the date and saves it via the existing `POST /api/leads/{id}/follow-up` endpoint — no need to use the date picker for common cadences. The date picker + Save button stay for custom dates. Hovering a preset shows the resolved date as a tooltip. Pure frontend; no API change.

v7.5 adds a **snooze indicator** on Mark Contacted. When the v7.3 auto-snooze fires (the lead's `follow_up_date` was today or overdue and got cleared), the card briefly shows an amber toast like `Follow-up cleared (was 2026-05-10)` so the behavior is discoverable. Detection is purely client-side: the frontend captures `prevFollowUp` before the POST and diffs against the freshly loaded lead — if the prior date is non-null and the new date is null, the snooze fired. No API change. The toast fades after 2.5s and removes after 3.2s.

v7.6 adds **keyboard hotkeys** to the follow-up form. With the form open, pressing `1` / `2` / `3` / `4` fires the corresponding preset (Tomorrow / +1 week / +2 weeks / +1 month). The mapping is position-based — the keys match the buttons' left-to-right order, not the day counts (so `4` ≠ "4 days"). Opening the form now focuses the first preset button instead of the date input, so hotkeys work immediately; Shift+Tab lands on the date input for custom dates. Hotkeys are explicitly suppressed when focus is on any `<input>`, `<textarea>`, or `<select>` so typing a custom date isn't hijacked. Document-level listener; doesn't need re-binding on each render.

v7.7 adds **toast feedback for follow-up presets**: after a successful preset click, the card briefly shows `Follow-up set to 2026-06-07` using the same `_flashLeadToast` helper as the v7.5 snooze indicator. Makes preset feedback consistent with snooze feedback — same palette, same fade timing. One-line change.

v7.8 extends the toast to the **manual Save Date and Clear buttons**: Save shows `Follow-up set to YYYY-MM-DD` (or `Follow-up cleared` if the user submitted an empty date), Clear shows `Follow-up cleared`. Now every code path that mutates `follow_up_date` from the UI surfaces matching feedback, closing the gap with the v7.5 auto-snooze and the v7.7 preset toasts.

v7.9 adds the same `_flashLeadToast` to **Write Message** (`Message draft ready`). The draft also lands in the Command Output panel (and on the card via the collapsible "Last message draft" details), but those are different regions on the page — the toast confirms the action where the click happened.

v7.10 polishes the **empty-state copy** for the v7.2 due-this-week filter. When the chip is on and zero leads qualify, the list now reads `Nothing due this week — nice.` instead of the generic `No leads match the filter.` — empty is *good news* under that filter, not a failed search.

v7.11 replaces all 8 leads-section `alert()` calls with the existing `_flashLeadToast` helper in an `'error'` variant. Per-card errors attach to the matching card; the Add Lead error (where no card exists yet) falls back to a section-level toast at the top of `#leads-list`. Error toasts use a red palette (`.lead-toast-error`) and a longer 5.0s/5.8s fade so the user has time to read them. Non-blocking — no more modal interruption when a request fails.

v7.12 wires the **Logan Leads partner card** to real data. `prospects_tracked` now equals `len(leads_mod.load())` and `outreach_queue` equals the count of leads whose status is not `closed` or `dropped`. Logan was previously hardcoded to `0/0` even after the v6.9 leads tracker shipped — that surface lied for every build between v6.9 and v7.11. Olivia's card is still a placeholder (no real metric source exists yet).

v7.13 replaces the bare `—` placeholders in the Report Center's error branch (`renderReports(null)`) with `Data unavailable.` The dashes read like "loading" or "broken"; the new copy reads honestly as an error. Note: this is the *error* branch, not the empty-window branch — the latter already shows `No data in this window.` via `_renderReportList([])`.

v7.14 wires the **Olivia Office partner card** to real data. `summaries_generated` now counts `summaries/*.md` (written by `automation/morning_summary.py`) and `snapshots_archived` counts `status_history/*.json` (written by `automation/status_snapshot.py`). Both are produced by `daily_ops.py`. A new `_count_partner_files` helper skips `.gitkeep`/`.DS_Store` via suffix filtering and returns 0 on missing dir. Olivia was the last partner card still showing hardcoded zeros; all three partner roster cards now show truthful counts.

v7.15 normalizes the last filter-empty outlier: `'No matching Parker work.'` → `'No Parker work matches the filter.'`, matching the structure of `'No leads match the filter.'` and `'No reports match the current filter.'` The rest of the v7-walkthrough's empty-state findings turned out to be coherent on closer inspection (e.g. `'No data in this window.'` matches the section's own "Window:" selector label, and the duplicated "configured" strings live in different sections).

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

## Connections

The Hub shows which publishing platforms are configured by checking required `.env` keys. It never displays secret values.

The Connections card lists every supported publishing platform (LinkedIn, Facebook, Google Business Profile, Instagram) along with its status (`Connected` or `Missing setup`). Missing platforms show the *names* of the env keys that still need to be set — values are never returned by the API or rendered in the page.

### Connection Wizard

```bash
python3 automation/connect_wizard.py            # interactive menu
python3 automation/connect_wizard.py status     # one-shot status report
```

The wizard helps Topher connect publishing platforms by showing missing `.env` keys and opening the correct setup pages (via stdlib `webbrowser`). It never prints secret values, never auto-logs in, never bypasses OAuth, and never posts publicly. Each Connections card row in the Hub also exposes an **Open Setup Help** button that opens the same setup URL directly in a new tab.

The Connection Wizard can also verify configured publishing connections with read-only API calls:

```bash
python3 automation/connect_wizard.py verify
python3 automation/connect_wizard.py verify facebook
```

Verification never publishes content and never prints secret values. Facebook and Instagram run a real Graph API probe (`GET /{id}?fields=id,name|username`) using the `Authorization: Bearer` header so the token never appears in a URL. LinkedIn and Google Business Profile currently report `configured (live verification not implemented yet)` — their read endpoints depend on OAuth scopes / API surfaces that vary per setup, and a conservative placeholder avoids false-negative auth errors on a perfectly good posting token. The Hub Connections card exposes the same probe via per-row **Verify** buttons that call `POST /api/connections/verify`.

### Verified publishing connections

Verified connections are required before publishing is enabled.

Connection states:
- **verified** — env keys present AND the latest verify probe succeeded. Publish buttons are enabled.
- **configured** — env keys present, but verify has never run or the last verify failed. Publish buttons are disabled with the tooltip *"Verify this connection before publishing."*
- **not_configured** — env keys missing. Publish buttons are disabled, and the Connections card lists which env keys to set.

The publish endpoint (`POST /api/posts/{id}/publish`) also enforces the same gate server-side, so a manually-stripped disabled attribute on a button can't bypass safety. State is persisted to `data/connection_status.json` (gitignored — only the empty `data/.gitkeep` placeholder is tracked). The cache stores the state, the last verify timestamp, and the human-readable message — never tokens.

Verified connections show a warning when their last verification is older than 7 days (`⚠ Verified N days ago — recheck soon.`) or 30 days (`⚠ Verification is stale (N days old) — verify again before publishing.`). Warnings appear in the Hub Connections card and in the wizard's `status` output. Warnings do not block publishing yet — re-running `python3 automation/connect_wizard.py verify <platform>` or clicking the Hub's per-row **Verify** button refreshes the timestamp and clears the warning.

---

## Environment Setup Wizard

```bash
python3 automation/setup_env.py
```

Creates `.env` if missing (from `.env.example`) and prompts only for missing values. Secrets are never printed or committed. Existing values are masked (e.g. `sk-XXXX...YYYY`) and require explicit confirm to overwrite.

CLI subcommands:

```bash
python3 automation/setup_env.py status      # read-only report, no prompts
python3 automation/setup_env.py core        # walk just the Core section
python3 automation/setup_env.py linkedin    # walk just LinkedIn
python3 automation/setup_env.py facebook
python3 automation/setup_env.py instagram
python3 automation/setup_env.py gbp
```

The Hub's Control Panel has a **Setup .env** button that displays terminal guidance (the wizard itself runs only in the terminal — secret entry uses `getpass` and is never exposed to the browser).

## LinkedIn OAuth connect flow

The Hub's Control Panel has a **Connect LinkedIn** button that runs the OAuth code-grant flow end-to-end:

1. Click → confirm → browser is redirected to LinkedIn
2. Authenticate with LinkedIn (you authorize the `openid profile w_member_social` scopes)
3. LinkedIn redirects back to `/api/oauth/linkedin/callback` with the authorization code
4. Hub exchanges the code for an access token (POST with client secret in the body, never in a URL)
5. Hub calls `/v2/userinfo` with the new token to auto-fetch the member URN (best-effort)
6. Both `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_AUTHOR_URN` are written in a single atomic update to `.env` via `automation/env_writer.py` (a `.env.bak` snapshot is saved first; file mode preserved)
7. Hub triggers a verify probe

Prerequisites in `.env`:

```bash
LINKEDIN_CLIENT_ID=<your LinkedIn app's client id>
LINKEDIN_CLIENT_SECRET=<your LinkedIn app's client secret>
LINKEDIN_REDIRECT_URI=http://127.0.0.1:8787/api/oauth/linkedin/callback
```

The redirect URI must match exactly what's registered in your LinkedIn Developer App. The app must have BOTH products enabled: **"Sign In with LinkedIn using OpenID Connect"** (so `openid`/`profile` scopes are accepted, enabling URN auto-fetch) and **"Share on LinkedIn"** (so `w_member_social` is accepted, enabling posting). If the OpenID product isn't enabled, the OAuth flow still completes for posting — only the URN auto-fetch is skipped and you'll need to set `LINKEDIN_AUTHOR_URN` manually. Tokens and secrets are never logged or rendered in any HTTP response.

## LinkedIn publishing

Approved LinkedIn drafts can be published manually from the Hub using the official LinkedIn Posts API.

Publishing is never automatic. A post is only published after Topher clicks "Post to LinkedIn" in the Ready to Post queue and confirms the action in the browser prompt.

After a successful publish, the platform's response is captured as a **publish receipt** and stored in the `posts` row (`published_platform`, `published_external_id`, `published_url`, `published_response_summary` — four nullable columns added in v6.3 via the existing `_migrate_posts_columns` idempotent migration). The receipt surfaces in three places: the System Activity feed adds a `View →` link on publish events with a known URL; the Recent Parker Work row adds a `Posted →` link inline; the Draft Preview modal shows a full receipt block (posted time, platform id, public URL, response summary). Receipt fields never contain tokens, response headers, or full request bodies — `social_posters.extract_publish_receipt()` enforces what's safe to persist.

Configure:

- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_AUTHOR_URN`

inside `.env`. Optional `LINKEDIN_VERSION` (defaults to `202605`).

If either of the required vars is unset, the Hub returns `LinkedIn posting is not configured.` and never makes an outbound call. On a successful publish, the local `posts.status` flips to `posted` so the item drops out of the Ready to Post queue. On any failure (network, auth, API error) the status is left at `approved` and the error is shown in the Hub's Command Output panel.

Facebook Page publishing is also supported for approved Facebook drafts when `FACEBOOK_PAGE_ID` and `FACEBOOK_PAGE_ACCESS_TOKEN` are configured. Posting is never automatic and only happens after clicking "Post to Facebook" and confirming. Same safety contract as LinkedIn — missing config returns `Facebook posting is not configured.` and never makes an outbound call; only a successful publish flips local status to `posted`. The Hub also rejects platform/post mismatches (e.g. trying to publish a Facebook draft via the LinkedIn connector) with HTTP 400.

---

## Daily ops runner

```bash
python3 automation/daily_ops.py
```

Runs the daily generation, writes a status snapshot, and writes the morning summary. This is the command launchd can eventually call instead of running individual scripts.

For refreshing the snapshot and summary later in the day without generating new drafts (or burning another OpenAI call), use:

```bash
python3 automation/daily_ops.py --skip-generate
```

This skips `daily_runner.py` entirely and only re-runs `status_snapshot.py` and `morning_summary.py`. No new drafts are created, no bank usage counters change, and no OpenAI call is made.

---

## Status snapshot

```bash
python3 automation/status_snapshot.py
```

Writes a local JSON snapshot to `status_history/YYYY-MM-DD.json` using the same data as `status.py --json`. It does not call OpenAI or change the database.

---

## Morning summary

```bash
python3 automation/morning_summary.py
```

Writes a local markdown summary to `summaries/YYYY-MM-DD.md` using status data. It does not call OpenAI or change the database.

---

## Daily checklist

```bash
python3 automation/daily_checklist.py
```

Shows the daily action list: generate drafts, review pending posts, clean hashtags, and run status. Read-only.

Checklist boxes are automatically marked `[x]` when that part of the daily workflow is complete.

---

## Daily status

```bash
python3 automation/status.py
```

Shows health, post counts, warning counts, memory bank counts, today's draft folder, latest log file, and the suggested next action. Read-only — never writes files, never calls OpenAI.

To monitor live while a manually-triggered run is in flight (or after `launchctl start ...`), use watch mode — the human dashboard refreshes every N seconds (default 30) until Ctrl+C:

```bash
python3 automation/status.py --watch       # every 30s
python3 automation/status.py --watch 10    # every 10s
```

Watch mode clears the terminal between refreshes and prints `Watching every Ns. Press Ctrl+C to stop.` at the bottom. Ctrl+C exits cleanly with `Stopped.`.

For automation, scripts, or future dashboards, add `--json` to get the same data as machine-readable JSON (nothing else is printed):

```bash
python3 automation/status.py --json
```

The JSON shape is stable: `health`, `posts`, `review`, `memory_banks`, `today`, `latest_log` (or `null`), `next_action`, and `checklist`.

The JSON output also includes a `checklist` block with booleans for generate drafts, review drafts, clean hashtags, and status pass. These match the `[x] / [ ]` markers in `daily_checklist.py`.

`review.top_missing_hashtags` contains up to five missing hashtags from pending drafts with use counts (`[{"tag": "#example", "uses": 3}, ...]`). Empty list when the curated bank covers every tag Parker is using.

---

## Health Check

Before running the daily generator (or after pulling new changes), verify the project is set up correctly:

```bash
python3 automation/health_check.py
```

The check verifies, in order: required folders, required files (including `daily_runner.py`), that `OPENAI_API_KEY` and `OPENAI_MODEL` are set in `.env`, the SQLite database connects and has the `posts` and `post_history` tables, all four memory banks exist and have at least one entry, and the approval queue is readable. It also reports how many drafts are currently pending and how many of those have warnings.

Exits `0` if everything passes, `1` if anything fails. Read-only — never modifies files, the database, or environment variables, and never calls OpenAI.

---

## Folder Structure

```
PartnerDeskAI/
├── automation/                   # Python pipeline modules
│   ├── daily_ops.py              # canonical daily entry point (scheduled by launchd)
│   ├── daily_runner.py           # generates drafts (step 1 of daily_ops)
│   ├── memory_manager.py
│   ├── content_parser.py
│   ├── file_manager.py
│   └── approval_manager.py
├── partners/
│   └── parker_promo/
│       ├── parker_promo_prompt.md
│       ├── posting_schedule.json
│       ├── templates/
│       └── logs/
├── memory/
│   ├── business_profile.md
│   ├── posting_history/
│   ├── hashtags/
│   └── workflows/
├── daily_posts/                  # generated drafts, by date
├── approval_queue/               # pointers to batches awaiting review
├── database/
│   └── partnerdesk.db            # SQLite database
├── logs/                         # daily log files
├── archive/
├── .env
├── requirements.txt
└── README.md
```

---

## Setup

1. Clone the repo.
2. Copy `.env.example` to `.env`.
3. Add your real OpenAI API key to `.env`.
4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Run the health check:

   ```bash
   python3 automation/health_check.py
   ```

6. Generate drafts:

   ```bash
   python3 automation/daily_runner.py
   ```

> **Never commit `.env` or API keys.** The repo's `.gitignore` already excludes `.env`, but verify with `git check-ignore .env` if you're not sure.

---

## Reviewing drafts

```bash
python automation/approval_cli.py                  # interactive review of pending drafts
python automation/approval_cli.py list             # multi-line summary of pending drafts
python automation/approval_cli.py status           # counts by status
python automation/approval_cli.py status --warnings  # also: warning summary for pending drafts
python automation/approval_cli.py preview <id>     # full content for one post (any status)
```

Each `list` entry shows the post id, platform, status, topic, resolved markdown file path, and hashtags detected in the body. The interactive review surfaces the same fields in each draft's header.

Hashtag detection uses a simple `#[A-Za-z0-9_]+` regex on the stored draft body, so what you see is what Parker actually wrote — useful for spotting an off-brand or duplicated tag before approving.

In the interactive review you can press:
- `a` — approve (sets `status='approved'` + adds row to `post_history`)
- `r` — reject (sets `status='rejected'`)
- `s` — skip (leaves as `draft`)
- `v` — view the full markdown file
- `q` — quit early

Approved topics are written to `post_history`, which the daily generator reads on the next run so Parker won't repeat the same topic.

### Approval warnings

The approval CLI warns about possible issues before approval, including too many hashtags, tags outside the curated bank, missing CTA language, and very short drafts.

These warnings do not block approval. They are review helpers only.

If a draft has warnings, interactive approval asks for one extra confirmation before approving. Pressing Enter defaults to No. This prevents accidental approval of drafts with obvious issues while still allowing Topher to approve intentionally.

For a batch-level view without entering the review loop, run:

```bash
python3 automation/approval_cli.py status --warnings
```

This prints the normal status counts followed by a summary of how many pending drafts have warnings, a breakdown by warning type, and a list of the drafts with the most warnings. Read-only — no statuses or database rows are changed.

Specifically, `_audit_draft` checks each draft for:

- **Too many hashtags** — Instagram > 6, Facebook > 3, LinkedIn > 3, Google Business Profile > 0
- **Hashtag not in bank** — any tag in the body that isn't in `memory/hashtag_bank.json` (case-insensitive comparison)
- **No obvious CTA found** — none of a short list of CTA phrases (`message me`, `reply`, `contact`, `book`, `dm`, `learn more`, `let's talk`, etc.) appears in the body
- **Very short content** — body under 120 characters

Warnings appear in `list`, `preview <id>`, and the interactive review header, in this format:

```
Warnings:
- Too many hashtags for LinkedIn: 5 found, max 3.
- Hashtag not in bank: #RandomTag
- No obvious CTA found.
```

That's it.

---

## Scheduling (macOS)

The canonical scheduled entry point is `automation/daily_ops.py`, wired to run automatically at **9:00 AM daily** via `launchd`. Each scheduled run executes:

1. **Generate daily drafts** (`automation/daily_runner.py`) — calls OpenAI, writes today's markdown drafts, inserts draft rows, updates bank usage counters.
2. **Write status snapshot** (`automation/status_snapshot.py`) — `status_history/YYYY-MM-DD.json`.
3. **Write morning summary** (`automation/morning_summary.py`) — `summaries/YYYY-MM-DD.md`.

If any step fails, the orchestrator prints `[FAIL] <step>` and exits non-zero; later steps don't run.

The agent definition lives at:
```
~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
```

### Install or update with one command

```bash
bash automation/install_launchd.sh
```

This installs (or updates) the launchd agent so it runs `automation/daily_ops.py` every day at 09:00 local time. It is idempotent — safe to re-run any time. It writes the plist, then unloads and reloads the agent automatically. It does **not** run `daily_ops.py` itself; it only installs the schedule.

The installer captures stdout/stderr to `logs/launchd.out.log` and `logs/launchd.err.log` and resolves the absolute path to your current `python3` so launchd (which doesn't search `PATH`) can run it.

If you'd rather edit the plist by hand, the manual commands below still work.

> **Migrating from an older install:** If you already installed the older launchd plist that points at `automation/daily_runner.py`, run `bash automation/install_launchd.sh` to overwrite it with the new `daily_ops.py`-based version (the installer handles unload + reload). Or, if you want to do it manually, update the plist `ProgramArguments` to use `automation/daily_ops.py`, then:
> ```bash
> launchctl unload ~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
> launchctl load   ~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
> ```

### Inspect / verify
```bash
launchctl list | grep partnerdeskai
```
Output `-  0  com.mixedmakershop.partnerdeskai.daily` means it's loaded and hasn't failed.

### Change the time
Edit the `StartCalendarInterval` block in the plist (`Hour` / `Minute`), then reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
launchctl load   ~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
```

### Stop / uninstall
```bash
launchctl unload ~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
rm ~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
```

### Where the scheduled run logs go
- `logs/YYYY-MM-DD.log` — the app's own log (same as a manual run)
- `logs/launchd.out.log` — stdout captured by launchd
- `logs/launchd.err.log` — stderr captured by launchd

> **Note:** launchd user agents run only while you're logged in. If the Mac is asleep at 9 AM, the missed run fires as soon as it wakes.

### Plist template (in case you ever delete it)
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mixedmakershop.partnerdeskai.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Library/Frameworks/Python.framework/Versions/3.14/bin/python3</string>
        <string>/path/to/PartnerDeskAI/automation/daily_ops.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/PartnerDeskAI</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key>
    <string>/path/to/PartnerDeskAI/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/PartnerDeskAI/logs/launchd.err.log</string>
</dict>
</plist>
```

The example above uses `/path/to/PartnerDeskAI` as a placeholder. `automation/install_launchd.sh` fills in the actual repo path automatically, derived from the script's own location — so just run `bash automation/install_launchd.sh` from your repo and the plist is written correctly regardless of where you've checked the repo out.

---

## Environment Variables

| Variable          | Purpose                          | Default          |
| ----------------- | -------------------------------- | ---------------- |
| `OPENAI_API_KEY`  | OpenAI API key                   | _required_       |
| `OPENAI_MODEL`    | Model to use for generation      | `gpt-4.1-mini`   |

---

## What a Run Does

1. Loads `memory/business_profile.md`
2. Loads `partners/parker_promo/parker_promo_prompt.md`
3. Loads the posting schedule
4. Loads recent post history from SQLite (to avoid repeats)
5. Calls the OpenAI API
6. Parses the structured response into 6 sections
7. Creates `daily_posts/YYYY-MM-DD/`
8. Saves a markdown file per platform plus CTA + image-idea files
9. Inserts a draft row into the `posts` table for each platform
10. Drops a pointer in `approval_queue/` so a human knows there's a batch to review
11. Appends a log entry in `logs/YYYY-MM-DD.log`

Every draft starts with `status = 'draft'`. Approval is manual.

---

## Database

SQLite at `database/partnerdesk.db`.

- **posts** — every generated draft (platform, topic, content, hashtags, image idea, status, created_at)
- **post_history** — topics that have actually been posted (populated when drafts are approved, not at generation time)

---

## Topic Intelligence

Parker uses `memory/topic_bank.json` to rotate content topics, avoid repeating recent ideas, and improve consistency over time.

Each entry has a `topic`, `category`, `score` (higher = preferred), plus `times_used` and `last_used` that the runner updates automatically. On each run the system:

1. Reads the bank and the recent `post_history`.
2. Picks a topic that hasn't been used in the last 7 days, weighted by score.
3. Passes the chosen topic to Parker as the day's recommended focus.
4. Increments `times_used` and sets `last_used` after a successful run.

Edit `memory/topic_bank.json` any time to add, remove, or re-score topics. The file is plain JSON — no migration needed.

### Topic bank CLI

For convenience, `automation/topic_cli.py` is a small command-line tool for managing the bank without hand-editing JSON:

```bash
python3 automation/topic_cli.py list                                     # show all topics
python3 automation/topic_cli.py show "Digital Business Cards"            # full details for one topic
python3 automation/topic_cli.py add "QR Code Menus" --score 8 \
    --category service --notes "Good for restaurants and cafes."         # add a new topic
python3 automation/topic_cli.py rescore "AI Business Systems" 10         # change a topic's score
python3 automation/topic_cli.py renote "Website Cleanup" "Updated angle" # replace notes
python3 automation/topic_cli.py remove "Old Topic"                       # delete a topic
python3 automation/topic_cli.py reset                                    # zero all usage counters
```

Topic names are matched case-insensitively. Scores must be 1–10.

---

## CTA and Offer Rotation

Parker also rotates two other things alongside topics:

- `memory/cta_bank.json` — calls-to-action ("DM us to learn more", "Book a free 15-minute consult", etc.)
- `memory/offer_bank.json` — offer angles ("Free initial consultation", "Complimentary website audit", etc.)

Both banks share the same shape as `topic_bank.json` and follow the same rules: high-score items are preferred, anything used in the last 7 days is skipped, and `times_used` / `last_used` are updated automatically after each run. On each generation Parker receives:

1. One **recommended topic** for the day
2. One **recommended CTA** (woven into the platform posts)
3. One **recommended offer angle** (referenced where it fits naturally)

Recently used CTAs and offers are also passed in so Parker actively avoids repeating them.

### CTA bank CLI

```bash
python3 automation/cta_cli.py list                                       # show all CTAs
python3 automation/cta_cli.py show "DM us to learn more"                 # full details
python3 automation/cta_cli.py add "Schedule a free call" --score 8 \
    --category direct --notes "Strong intent CTA."                       # add a new CTA
python3 automation/cta_cli.py rescore "DM us to learn more" 9            # change score
python3 automation/cta_cli.py renote  "DM us to learn more" "New notes"  # replace notes
python3 automation/cta_cli.py remove  "Old CTA"                          # delete a CTA
python3 automation/cta_cli.py reset                                      # zero usage counters
```

### Offer bank CLI

```bash
python3 automation/offer_cli.py list
python3 automation/offer_cli.py show "Free initial consultation"
python3 automation/offer_cli.py add "30-day money-back guarantee" --score 7 --category trust
python3 automation/offer_cli.py rescore "Complimentary website audit" 10
python3 automation/offer_cli.py renote  "Free initial consultation" "Now 30 minutes."
python3 automation/offer_cli.py remove  "Limited spots open this month"
python3 automation/offer_cli.py reset
```

Same rules as the topic CLI: names matched case-insensitively, scores 1–10.

---

## Hashtag Bank

Parker uses `memory/hashtag_bank.json` to rotate curated hashtags by platform. Each entry has a `tag`, a `platforms` list, `category`, `score`, `times_used`, `last_used`, and `notes`.

On each run, Parker receives a curated set per platform (counts in `daily_runner.py` via `HASHTAG_COUNTS`):

- **Instagram**: up to 6 hashtags
- **Facebook**: up to 3 hashtags
- **LinkedIn**: up to 3 hashtags
- **Google Business Profile**: 0 — Parker's prompt skips hashtags here

Hashtags are picked score-weighted and rotated by recency (anything used in the last 7 days is skipped first, then falls back if the bank is too small). After a successful run, `times_used` and `last_used` are updated only for hashtags that were actually recommended.

Use `automation/hashtag_cli.py` to list, add, edit, remove, and reset hashtags.

```bash
python3 automation/hashtag_cli.py list
python3 automation/hashtag_cli.py list --platform instagram
python3 automation/hashtag_cli.py show "#SmallBusiness"
python3 automation/hashtag_cli.py add "#LocalSEO" --score 8 --category seo \
    --platforms instagram facebook linkedin --notes "Good for local search posts"
python3 automation/hashtag_cli.py rescore "#LocalSEO" 9
python3 automation/hashtag_cli.py renote "#LocalSEO" "Updated local search tag"
python3 automation/hashtag_cli.py setplatforms "#LocalSEO" instagram linkedin
python3 automation/hashtag_cli.py remove "#LocalSEO"
python3 automation/hashtag_cli.py reset
```

Tags can be entered with or without a leading `#` (always stored with one). Tag matching is case-insensitive. Scores must be 1–10. `--platforms` accepts space-separated values from: `instagram`, `facebook`, `linkedin`, `google_business_profile`.

### Auditing missing hashtags

A read-only audit scans all pending drafts and lists hashtags that Parker has used but that aren't currently in `memory/hashtag_bank.json` — useful for deciding which invented tags to absorb into the curated bank.

```bash
python3 automation/hashtag_cli.py audit-missing                # show everything
python3 automation/hashtag_cli.py audit-missing --min-count 2  # hide one-off tags
```

The command never writes to the bank, the database, or any post statuses. It groups tags case-insensitively and shows both an at-a-glance summary and a per-tag detail block with the posts where each tag appeared.

### Absorbing a missing hashtag

Once a tag from `audit-missing` looks worth keeping, absorb it into the bank with an explicit, named approval step:

```bash
python3 automation/hashtag_cli.py absorb "#mixedmakershop" \
    --platforms instagram facebook linkedin \
    --score 8 --category brand \
    --notes "Brand tag used in Parker drafts"
```

Rules:
- The tag is normalized (leading `#` added if missing).
- If the tag appears in any pending draft, the casing Parker actually used is preserved (`#mixedmakershop` becomes `#MixedMakerShop` if that's how it was emitted).
- If the tag is **not** found in pending drafts, the command asks `Add anyway? [y/N]:` — Enter cancels.
- Duplicates are refused with exit code 1; use `rescore`, `renote`, or `setplatforms` to modify an existing entry.
- Required flags: `tag`, `--platforms`. Optional: `--score` (default 7), `--category` (default `general`), `--notes` (default mentions audit origin).

---

## Roadmap (Not Yet Built)

These are intentionally **not** part of v0.1. Don't add them until they're actually needed:

- **Logan Leads** — lead generation partner
- **Olivia Office** — admin / organization partner
- **Approval UI** — a small local tool to approve drafts and write to `post_history`
- **Dashboard** — overview of partner activity
- **Playwright automation** — actual posting once approved
- **Analytics** — post performance tracking

Each future partner should follow the same rules: local ownership, reusable assets, saved history, approval workflows, modular structure.

---

## Build Philosophy

- Simple > clever
- Local-first
- Approval-based, never autonomous
- Plain markdown + SQLite, no vector stores, no agent frameworks
- Readable code over architectural elegance
