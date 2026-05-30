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

The Hub includes a Control Panel for common PartnerDeskAI actions, reducing the need to use terminal commands during normal operation. Clicked Control Panel buttons briefly dim as visual feedback and lock against double-clicks for ~800ms.

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

## LinkedIn publishing

Approved LinkedIn drafts can be published manually from the Hub using the official LinkedIn Posts API.

Publishing is never automatic. A post is only published after Topher clicks "Post to LinkedIn" in the Ready to Post queue and confirms the action in the browser prompt.

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
        <string>/Users/christophercook/Documents/PartnerDeskAI/automation/daily_ops.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/christophercook/Documents/PartnerDeskAI</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key>
    <string>/Users/christophercook/Documents/PartnerDeskAI/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/christophercook/Documents/PartnerDeskAI/logs/launchd.err.log</string>
</dict>
</plist>
```

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
