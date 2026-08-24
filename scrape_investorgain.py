"""
Scrapes currently-active (open/upcoming) IPO GMP data from investorgain.com.
Uses a headless browser because the table is loaded via JavaScript.
"""
import re
from playwright.sync_api import sync_playwright

URL = "https://www.investorgain.com/report/live-ipo-gmp/331/nonzero/"  # "Only Active GMP" view


def _is_sme(raw_name):
    return "SME" in raw_name


def _clean_name(raw):
    name = raw
    name = re.sub(r"L@[\d.]+\s*\([-\d.]+%\)\s*$", "", name).strip()
    name = re.sub(r"ALLOTTED\s*$", "", name).strip()
    # Status flags (U=upcoming, O=open, C=closed, CT=closing today) are glued directly
    # onto "IPO"/"SME" with no space -- only strip them from that exact position, so we
    # don't accidentally eat the trailing "O" of a legitimately-named "...IPO" with no flag.
    name = re.sub(r"(IPO|SME)(U|O|C|CT)$", r"\1", name)
    return name.strip()


def _clean_date(raw):
    return raw.split("\n")[0].strip()


def _extract_gmp_pct(gmp_line):
    m = re.search(r"\(([-\d.]+)%\)", gmp_line)
    return f"{m.group(1)}%" if m else None


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
            return results

        page.wait_for_timeout(1500)
        rows = page.query_selector_all("table tbody tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 11:
                continue
            texts = [c.inner_text().strip() for c in cells]
            # Columns: NAME(0) GMP(1) RATING(2) SUB(3) PRICE(4) IPO SIZE(5) LOT(6)
            #          OPEN(7) CLOSE(8) BOA DT / ALLOTMENT(9) LISTING(10) UPDATED-ON(11) ANCHOR(12)
            raw_name = texts[0]
            gmp_line = texts[1].split("\n")[0].strip()
            results.append({
                "source": "InvestorGain",
                "name": _clean_name(raw_name),
                "is_sme": _is_sme(raw_name),
                "gmp_pct": _extract_gmp_pct(gmp_line),
                "open": _clean_date(texts[7]),
                "close": _clean_date(texts[8]),
                "allotment": _clean_date(texts[9]),  # actual published Basis of Allotment date
                "listing": _clean_date(texts[10]),
            })
        browser.close()
    return results


if __name__ == "__main__":
    import json
    data = scrape_investorgain()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nTotal: {len(data)} IPOs")
