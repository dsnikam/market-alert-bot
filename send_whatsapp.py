"""
Sends a WhatsApp message to yourself via CallMeBot's free API.

Setup (one-time, from your phone -- must be the number you want reports sent to):
  1. Save this contact on your phone:  +34 644 66 42 89  (CallMeBot's number)
  2. Send it this exact WhatsApp message:  "I allow callmebot to send me messages"
  3. Wait for a reply containing your personal apikey (a number).
  4. Set env vars WHATSAPP_PHONE (with country code, e.g. 919876543210)
     and CALLMEBOT_APIKEY (from step 3).

Notes:
  - Free tier is meant for personal/low-volume use (this is one message/day, so it's fine).
  - If CallMeBot ever stops responding, wait a few minutes and retry -- it occasionally
    rate-limits new senders in bursts.
"""
import os
import time
import requests

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def send_whatsapp_message(text, phone=None, apikey=None, max_retries=3):
    phone = phone or os.environ["WHATSAPP_PHONE"]
    apikey = apikey or os.environ["CALLMEBOT_APIKEY"]

    # CallMeBot messages work best under ~2000 chars; split long reports
    max_len = 1800
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [text]

    for chunk in chunks:
        params = {"phone": phone, "text": chunk, "apikey": apikey}
        for attempt in range(max_retries):
            resp = requests.get(CALLMEBOT_URL, params=params, timeout=20)
            if resp.status_code == 200 and "queued" in resp.text.lower():
                break
            time.sleep(5)
        else:
            raise RuntimeError(f"WhatsApp send failed after retries: {resp.status_code} {resp.text}")
        time.sleep(2)  # be polite to the free API between chunks
    return True


if __name__ == "__main__":
    send_whatsapp_message("Test message from IPO GMP bot ✅")
    print("Sent.")
