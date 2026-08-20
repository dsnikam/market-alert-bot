"""
Scrapes fresh IPO GMP data and writes it to docs/latest_report.txt (plain text,
read by the Telegram listener and the daily sender) and docs/index.html (a simple
auto-refreshing webpage you can bookmark for instant, zero-delay viewing).

Run on a schedule via .github/workflows/scrape_and_publish.yml
"""
import os
from datetime import datetime
from build_report import build_merged_data, format_report

OUTPUT_DIR = "docs"
TXT_PATH = os.path.join(OUTPUT_DIR, "latest_report.txt")
HTML_PATH = os.path.join(OUTPUT_DIR, "index.html")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    data = build_merged_data()
    report = format_report(data)

    with open(TXT_PATH, "w") as f:
        f.write(report)

    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="120">
<title>IPO GMP Report</title>
<style>
  body {{ font-family: -apple-system, monospace; background:#0d1117; color:#e6edf3;
          padding:24px; max-width:640px; margin:0 auto; line-height:1.5; }}
  .updated {{ color:#8b949e; font-size:0.85em; margin-bottom:16px; }}
  pre {{ white-space: pre-wrap; word-wrap: break-word; }}
</style>
</head>
<body>
  <div class="updated">Last updated: {generated_at} (auto-refreshes every 2 min)</div>
  <pre>{report.replace('*', '')}</pre>
</body>
</html>"""
    with open(HTML_PATH, "w") as f:
        f.write(html)

    print(f"Published latest report ({len(data)} entries) at {generated_at}")


if __name__ == "__main__":
    main()
