"""
Sends a message via a Telegram bot.
Setup (one-time):
  1. In Telegram, message @BotFather -> /newbot -> follow prompts -> copy the bot token.
  2. Message your new bot anything (e.g. "hi") so it can message you back.
  3. Get your chat_id: visit
       https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
     in a browser right after step 2, and read the "chat":{"id": ...} value.
  4. Set env vars TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see README).
"""
import os
import requests


def send_telegram_message(text, bot_token=None, chat_id=None):
    bot_token = bot_token or os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = chat_id or os.environ["TELEGRAM_CHAT_ID"]

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # Telegram messages are capped at 4096 chars -- split if needed
    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    for chunk in chunks:
        resp = requests.post(url, data={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
        }, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram send failed: {resp.status_code} {resp.text}")
    return True


if __name__ == "__main__":
    send_telegram_message("Test message from IPO GMP bot ✅")
    print("Sent.")
