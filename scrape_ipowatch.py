"""
Scrapes currently-active IPO GMP data from ipowatch.in.
This is a static HTML table (TablePress plugin) -- no headless browser needed,
unlike investorgain.com.

Note: used as a secondary GMP cross-check source per user's explicit choice,
despite the site showing signs of being compromised elsewhere (unrelated
injected spam content found outside the GMP table itself). The table data
itself matches known-good values from other sources.
"""
import re
import requests
from bs4 import BeautifulSoup

URL = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}


def _extract_gmp_pct(est_gain_text):
    # e.g. "₹91 (10.98%)" -> "10.98%"
    m = re.search(r"\(([-\d.]+)%\)", est_gain_text)
    return f"{m.group(1)}%" if m else None


def _parse_table(table, is_sme):
    results = []
    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        name_cell = cells[0]
        link = name_cell.find("a")
        if not link:
            continue
        name = link.get_text(strip=True)
        if not name:
            continue
        gmp_pct = _extract_gmp_pct(cells[4].get_text(strip=True))
        results.append({
            "source": "IPOWatch",
            "name": f"{name} IPO",  # ipowatch omits the "IPO" suffix our naming convention expects
            "is_sme": is_sme,
            "gmp_pct": gmp_pct,
        })
    return results


def scrape_ipowatch():
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table", class_="tablepress")
    if len(tables) < 2:
        return []

    mainboard = _parse_table(tables[0], is_sme=False)
    sme = _parse_table(tables[1], is_sme=True)
    return mainboard + sme


SUBSCRIPTION_URL = "https://ipowatch.in/ipo-subscription-status-today/"


def scrape_ipowatch_subscription():
    """
    Scrapes the genuine *retail* subscription multiple (separate from QIB/NII/Total)
    from ipowatch.in's dedicated subscription table.
    """
    resp = requests.get(SUBSCRIPTION_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="tablepress")
    if not table:
        return []

    results = []
    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header row
        cells = row.find_all("td")
        if len(cells) < 7:
            continue
        name = cells[0].get_text(strip=True)
        ipo_type = cells[1].get_text(strip=True)
        retail_raw = cells[5].get_text(strip=True)
        if not name or not retail_raw:
            continue
        try:
            retail_val = float(retail_raw)
        except ValueError:
            continue
        results.append({
            "source": "IPOWatch",
            "name": f"{name} IPO",
            "is_sme": (ipo_type.strip().upper() == "SME"),
            "retail_sub": f"{retail_val}x",
        })
    return results


if __name__ == "__main__":
    import json
    data = scrape_ipowatch()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nTotal: {len(data)} IPOs")

    sub_data = scrape_ipowatch_subscription()
    print(json.dumps(sub_data[:5], indent=2, ensure_ascii=False))
    print(f"\nSubscription rows: {len(sub_data)}")
