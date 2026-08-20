"""
Scrapes currently-active (open/upcoming) IPO GMP data from investorgain.com.
Uses a headless browser because the table is loaded via JavaScript.
"""
import re
from playwright.sync_api import sync_playwright

URL = "https://www.investorgain.com/report/live-ipo-gmp/331/nonzero/"  # "Only Active GMP" view

# Status suffixes appended to the IPO name in the NAME column (order matters: longest first)
_STATUS_SUFFIXES = ["CT", "U", "O", "C"]


def _clean_name(raw):
    name = raw
    # Drop "L@<price> (<pct>%)" listed-price suffix if present
    name = re.sub(r"L@[\d.]+\s*\([-\d.]+%\)\s*$", "", name).strip()
    # Drop "ALLOTTED" marker
    name = re.sub(r"ALLOTTED\s*$", "", name).strip()
    # Drop trailing single-letter status flags (U=upcoming, O=open, C=closed, CT=closing today)
    for suf in _STATUS_SUFFIXES:
        if name.endswith(suf):
            name = name[: -len(suf)].strip()
            break
    return name.strip()


def _clean_date(raw):
    # Date cells sometimes carry a "\nGMP: n" tooltip line — keep only the date itself
    return raw.split("\n")[0].strip()


def scrape_investorgain():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(ignore_https_errors=True)
        page.goto(URL, timeout=60000)
        try:
            page.wait_for_selector("table tbody tr", timeout=20000)
        except Exception:
            browser.close()
            return results  # no active GMP rows right now

        page.wait_for_timeout(1500)  # let all rows settle
        rows = page.query_selector_all("table tbody tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 11:
                continue
            texts = [c.inner_text().strip() for c in cells]
            gmp_block = texts[1]  # e.g. "₹30 (29.70%)\n20 ↓ / 30 ↑"
            gmp_line = gmp_block.split("\n")[0].strip()
            results.append({
                "source": "InvestorGain",
                "name": _clean_name(texts[0]),
                "gmp": gmp_line,
                "price": texts[4],
                "open": _clean_date(texts[7]),
                "close": _clean_date(texts[8]),
                "listing": _clean_date(texts[10]),
            })
        browser.close()
    return results


if __name__ == "__main__":
    import json
    data = scrape_investorgain()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nTotal: {len(data)} IPOs")
