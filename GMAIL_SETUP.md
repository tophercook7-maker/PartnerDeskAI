# Gmail send setup — PartnerDeskAI v12.11

PartnerDeskAI can send email as you via Gmail. This is **Layer 2**:
you explicitly authorized OAuth + auto-send for this integration.

The Hub does NOT carry shared Gmail credentials. You connect **your own**
Google Cloud project, and the tokens live only in `data/gmail_tokens.json`
on your machine (gitignored).

## One-time setup (5-10 minutes)

### 1. Create a Google Cloud project

- Open https://console.cloud.google.com/
- Top bar → project picker → **New Project**
- Name it `PartnerDeskAI` (or anything you like). No org needed.

### 2. Enable the Gmail API

- Left nav → **APIs & Services → Library**
- Search **Gmail API** → **Enable**

### 3. Configure the OAuth consent screen

- Left nav → **APIs & Services → OAuth consent screen**
- User type: **External** → Create
- App information:
  - App name: `PartnerDeskAI`
  - User support email: your email
  - Developer contact information: your email
- **Scopes** → Add or Remove Scopes → search and tick
  `https://www.googleapis.com/auth/gmail.send`
- **Test users** → **+ Add Users** → add your own Gmail address
  (and any others you want to be able to send as)
- Save. You can leave the app in "Testing" mode — that's fine for
  personal use. Test mode means only added test users can authorize,
  but lifetime of refresh tokens is 7 days (re-authorize weekly).
  To get permanent refresh tokens, publish the app — Google requires
  verification for sensitive scopes, which can take 1-2 weeks.

### 4. Create OAuth client credentials

- Left nav → **APIs & Services → Credentials**
- **+ Create Credentials → OAuth client ID**
- Application type: **Web application**
- Name: `PartnerDeskAI Hub`
- Authorized redirect URIs → **+ Add URI**:
  ```
  http://127.0.0.1:8000/api/gmail/oauth/callback
  ```
- Click **Create**
- A dialog appears with your **Client ID** and **Client secret**.
  Copy both. (You can come back to this later via the Credentials page.)

### 5. Paste into PartnerDeskAI

- Open the Hub (`http://127.0.0.1:8000/`)
- In the chat header click **✉ Gmail**
- Paste the Client ID + Client Secret → **Save credentials**
- Click **Connect Gmail** → a Google sign-in tab opens
- Pick your Gmail account → review the scopes → **Continue**
- You'll see a "✓ Connected" page; the Hub status pill flips to
  **✉ your@gmail.com**

## How sending works

When Parker drafts an outreach email in the chat, the message bubble
gets a green **✉ Send via Gmail** button. Click it →

- A modal opens with **To / Subject / Body** all editable
- Confirm and click **Send now**
- The email leaves from your Gmail account
- Olivia appends a confirmation message to the chat
- If the draft was tied to a Logan lead, the lead's outreach status
  flips to `contacted` and a follow-up is scheduled (+3 days)

**No batch send.** One email per click. The preview modal always
appears.

## Security notes

- `data/google_oauth_client.json` — your Client ID + Secret
- `data/gmail_tokens.json` — access + refresh tokens
- `data/gmail_send_log.json` — local audit log of every send

All three are gitignored. **Never commit them**. If you share `data/`
or back it up to a public location, anyone with the tokens can send
mail as you until you revoke.

To revoke: https://myaccount.google.com/permissions → find
PartnerDeskAI → Remove access. Then click **Disconnect** in the Hub.

## Disconnect

Click **✉ Gmail** in the chat header → **Disconnect**. Tokens are
deleted; client credentials are kept so you can reconnect with one
click. Use **Change credentials** to swap to a different Google Cloud
project.

## Troubleshooting

**"Token exchange failed: HTTP 400: invalid_grant"** — the code
expired (they're single-use, ~5 min). Try Connect again.

**"Token refresh failed"** — refresh token expired (7 days in test
mode) or revoked. Disconnect, then Connect.

**Authorization screen says "This app isn't verified"** — that's
expected for unverified apps. Click **Advanced → Go to PartnerDeskAI
(unsafe)**. Safe because the app is your own Google Cloud project
that you control.

**Browser tab doesn't auto-close after authorization** — it tries to,
but some browsers block `window.close()` on tabs not opened by JS.
Close it manually. The Hub auto-detects the connection within a few
seconds.

## What this DOES NOT do

- Read or list your emails (out of scope for v12.11)
- Add Outlook, Calendar, social, or any other Layer 2 integration
- Send without your per-message click
- Send as anyone except the connected account
