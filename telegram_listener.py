"""
Polls Telegram for new messages and responds to /fetch by sending the cached
report (written by scraper.py, refreshed every 10 minutes) -- no live scraping
happens here, so the reply goes out in a second or two once this workflow runs.
Designed to run every few minutes via GitHub Actions (see
.github/workflows/telegram_listener.yml) since there's no always-on server.

State (which updates have already been handled) is tracked in offset.txt,
which this script updates and the workflow commits back to the repo.
"""
import os
import requests
from send_telegram import send_telegram_message

OFFSET_FILE = "offset.txt"
CACHED_REPORT_PATH = os.path.join("docs", "latest_report.txt")


def _read_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            content = f.read().strip()
            return int(content) if content else 0
    return 0


def _write_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))


def _read_cached_report():
    if not os.path.exists(CACHED_REPORT_PATH):
        return "No cached report available yet -- the scraper hasn't run yet. Try again shortly."
    with open(CACHED_REPORT_PATH) as f:
        return f.read()


def main():
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    my_chat_id = os.environ["TELEGRAM_CHAT_ID"]

    offset = _read_offset()
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": 0}, timeout=20)
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    if not updates:
        print("No new messages.")
        return

    highest_update_id = offset
    for update in updates:
        highest_update_id = max(highest_update_id, update["update_id"] + 1)

        msg = update.get("message", {})
        text = msg.get("text", "").strip().lower()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Only respond to your own chat, and only to /fetch
        if chat_id != str(my_chat_id):
            print(f"Ignoring message from unknown chat_id {chat_id}")
            continue

        if text.startswith("/fetch"):
            print("Received /fetch -- sending cached report...")
            report = _read_cached_report()
            send_telegram_message(report, bot_token=bot_token, chat_id=my_chat_id)
            print("Sent cached report.")
        else:
            print(f"Ignoring non-command message: {text!r}")

    _write_offset(highest_update_id)


if __name__ == "__main__":
    main()

