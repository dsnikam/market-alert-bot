"""
Scrapes fresh IPO GMP data and writes it to docs/latest_report.txt (plain text,
read by the Telegram listener and the daily sender) and docs/index.html (a styled
webpage you can bookmark for instant, zero-delay viewing).

Run on a schedule via .github/workflows/scrape_and_publish.yml
"""
import os
from build_report import build_merged_data, format_report, format_html_report

OUTPUT_DIR = "docs"
TXT_PATH = os.path.join(OUTPUT_DIR, "latest_report.txt")
HTML_PATH = os.path.join(OUTPUT_DIR, "index.html")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    data = build_merged_data()

    with open(TXT_PATH, "w") as f:
        f.write(format_report(data))

    with open(HTML_PATH, "w") as f:
        f.write(format_html_report(data))

    print(f"Published latest report ({len(data)} entries)")


if __name__ == "__main__":
    main()
