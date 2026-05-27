# PartnerDeskAI

A local-first AI Business Partner system for **MixedMakerShop**.

PartnerDeskAI is a collection of AI "partners" — each one a focused role with its own prompt, memory, workflows, and reusable assets. Everything runs locally, writes to plain markdown + SQLite, and **requires human approval before any public action.**

## v0.1 — Parker Promo

The first partner. Parker Promo generates daily social media drafts (Google Business Profile, Facebook, Instagram, LinkedIn) using the OpenAI API and saves them to a dated folder for human review.

Nothing is auto-posted.

---

## Folder Structure

```
PartnerDeskAI/
├── automation/                   # Python pipeline modules
│   ├── daily_runner.py           # entry point
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

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set your OpenAI key** in `.env`:
   ```env
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4.1-mini
   ```

3. **Run the daily generator**
   ```bash
   python automation/daily_runner.py
   ```

4. **Review drafts and approve**
   ```bash
   python automation/approval_cli.py            # interactive review
   python automation/approval_cli.py list       # non-interactive list
   python automation/approval_cli.py status     # counts by status
   ```

   In the interactive review you can press:
   - `a` — approve (sets `status='approved'` + adds row to `post_history`)
   - `r` — reject (sets `status='rejected'`)
   - `s` — skip (leaves as `draft`)
   - `v` — view the full markdown file
   - `q` — quit early

   Approved topics are written to `post_history`, which the daily generator reads on the next run so Parker won't repeat the same topic.

That's it.

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
