"""
Daily IPO GMP report: scrape -> build report -> send to Telegram + WhatsApp.
Run manually with: python3 main.py
Run automatically via the GitHub Actions workflow in .github/workflows/daily_report.yml
"""
import sys
from build_report import build_merged_data, format_report
from send_telegram import send_telegram_message
from send_whatsapp import send_whatsapp_message


def main():
    print("Fetching IPO GMP data...")
    data = build_merged_data()
    report = format_report(data)
    print(report)
    print(f"\n{len(data)} active IPOs found.\n")

    errors = []

    try:
        send_telegram_message(report)
        print("✅ Sent to Telegram")
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")
        errors.append(("Telegram", e))

    try:
        send_whatsapp_message(report)
        print("✅ Sent to WhatsApp")
    except Exception as e:
        print(f"❌ WhatsApp send failed: {e}")
        errors.append(("WhatsApp", e))

    if errors:
        sys.exit(1)  # non-zero exit so GitHub Actions flags the run as failed


if __name__ == "__main__":
    main()
