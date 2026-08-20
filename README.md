# Daily IPO GMP Report → Telegram + WhatsApp (100% free)

Scrapes today's active IPO GMP data from **investorgain.com** and **investorzone.in**,
merges them so you can cross-check, and sends the report automatically every day
to Telegram and WhatsApp — no server, no paid API.

---

## How it works

1. `scrape_investorgain.py` — pulls the live GMP table from investorgain.com (JS-rendered,
   so this uses a headless browser via Playwright).
2. `scrape_investorzone.py` — pulls the same info from investorzone.in's public JSON API
   (no browser needed, much faster).
3. `build_report.py` — merges both by IPO name and formats one readable message.
4. `send_telegram.py` / `send_whatsapp.py` — deliver the message.
5. `main.py` — runs all of the above in order.
6. `.github/workflows/daily_report.yml` — runs `main.py` automatically every day at
   08:30 IST using GitHub Actions' free scheduled runs (2,000 free minutes/month on
   a public repo, effectively unlimited for a job this short).

---

## One-time setup

### Step 1 — Put this code in a GitHub repo

1. Create a free GitHub account if you don't have one: https://github.com/signup
2. Create a new repository (e.g. `ipo-gmp-bot`) — Public is fine, or Private if you prefer
   (Private repos also get free Action minutes, just a smaller monthly quota).
3. Upload all the files in this folder to that repo (drag-and-drop on github.com works,
   or use `git push` if you're comfortable with git).

### Step 2 — Create your Telegram bot

1. Open Telegram, search for **@BotFather**, start a chat.
2. Send `/newbot`, give it a name and a username (must end in "bot", e.g. `digvijay_ipo_bot`).
3. BotFather replies with a **token** like `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`. Save it.
4. Now message **your own new bot** anything (e.g. "hi") — a bot can't message you until
   you've messaged it first.
5. In your browser, visit (replace `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
6. Look for `"chat":{"id":123456789,...}` in the response — that number is your **chat ID**.

You now have: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### Step 3 — Set up free WhatsApp sending (CallMeBot)

1. Save this number in your phone's contacts: **+34 644 66 42 89**
2. From your WhatsApp (the number you want reports sent TO), message that contact
   exactly: `I allow callmebot to send me messages`
3. Within a minute or two you'll get a reply with your personal **apikey** (a number).
4. Note your phone number in international format with no `+` or spaces, e.g. `919876543210`.

You now have: `WHATSAPP_PHONE`, `CALLMEBOT_APIKEY`.

> CallMeBot is a free, widely-used personal-WhatsApp-notification service — no company
> account or Meta approval needed. It's meant for exactly this kind of personal daily alert.

### Step 4 — Add these as GitHub Secrets (so your tokens aren't public)

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these four, one at a time:

| Secret name          | Value                                  |
|-----------------------|-----------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | from Step 2.3                          |
| `TELEGRAM_CHAT_ID`    | from Step 2.6                          |
| `WHATSAPP_PHONE`      | from Step 3.4                          |
| `CALLMEBOT_APIKEY`    | from Step 3.3                          |

### Step 5 — Test it

Go to your repo's **Actions** tab → click "Daily IPO GMP Report" on the left →
click **Run workflow** (the manual trigger button) → wait ~1-2 minutes → check
Telegram and WhatsApp. If something failed, click into the run to see the error log.

Once that works, you're done — it'll run automatically every day at 08:30 IST.

---

## Running it locally first (optional, to test before pushing to GitHub)

```bash
pip install requests playwright
playwright install chromium

export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export WHATSAPP_PHONE="919876543210"
export CALLMEBOT_APIKEY="..."

python3 main.py
```

---

## Changing the schedule

Edit the `cron` line in `.github/workflows/daily_report.yml`. GitHub Actions cron times
are in **UTC**. IST is UTC+5:30, so:

- `0 3 * * *` → 08:30 IST
- `30 1 * * *` → 07:00 IST
- `0 12 * * *` → 17:30 IST

(GitHub's free scheduler can be a few minutes late during high-traffic periods — that's
normal and not something to worry about.)

## Troubleshooting

- **No message arrives**: check the Actions run log first (Actions tab → click the run →
  click the "Run daily report" step) — it prints exactly which platform failed and why.
- **WhatsApp stops working after a while**: CallMeBot occasionally requires re-verifying
  by sending the activation message again if you've been inactive a long time.
- **Investorgain scraping returns 0 rows**: their page structure occasionally changes;
  re-check `scrape_investorgain.py`'s CSS selectors against the live site.
- **Telegram message garbled**: the report uses Markdown (`*bold*`); if you edit the
  report format, keep `*` pairs balanced or switch `parse_mode` to `None` in
  `send_telegram.py`.
