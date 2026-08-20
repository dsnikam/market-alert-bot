"""
Merges IPO GMP data from InvestorGain + InvestorZone (matched by name, kept
separately so you can cross-check them), filters to mainboard IPOs only, and
formats both a plain-text report (Telegram/WhatsApp) and a styled HTML report
(the bookmarkable webpage).
"""
import re
import os
import json
import requests
from datetime import datetime, date, timezone, timedelta
from scrape_investorgain import scrape_investorgain
from scrape_investorzone import fetch_investorzone

IST = timezone(timedelta(hours=5, minutes=30))

# NSE/BSE trading holidays for 2026 (source: official NSE holiday circular).
# Used as a fallback if the live NSE API fetch fails (which it usually will --
# NSE's anti-bot protection blocks most automated requests, including from
# GitHub Actions). Update this set at the start of each year regardless.
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 15), date(2026, 1, 26), date(2026, 3, 3), date(2026, 3, 26),
    date(2026, 3, 31), date(2026, 4, 3), date(2026, 4, 14), date(2026, 5, 1),
    date(2026, 5, 28), date(2026, 6, 26), date(2026, 9, 14), date(2026, 10, 2),
    date(2026, 10, 20), date(2026, 11, 10), date(2026, 11, 24), date(2026, 12, 25),
}

HARDCODED_HOLIDAYS_BY_YEAR = {2026: NSE_HOLIDAYS_2026}

HOLIDAY_CACHE_PATH = "nse_holidays_cache.json"
_holiday_cache = {}  # in-memory, per-process only


def _load_holiday_cache_file():
    if not os.path.exists(HOLIDAY_CACHE_PATH):
        return None
    try:
        with open(HOLIDAY_CACHE_PATH) as f:
            data = json.load(f)
        if data.get("year") and data.get("holidays"):
            return {
                "year": data["year"],
                "source": data.get("source", "unknown"),
                "holidays": {datetime.strptime(d, "%Y-%m-%d").date() for d in data["holidays"]},
            }
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def _save_holiday_cache_file(year, holidays, source):
    with open(HOLIDAY_CACHE_PATH, "w") as f:
        json.dump({
            "year": year,
            "source": source,
            "holidays": sorted(d.strftime("%Y-%m-%d") for d in holidays),
        }, f, indent=2)


def _fetch_live_nse_holidays(year):
    """Tries NSE's official holiday API. Usually blocked by their anti-bot
    protection from datacenter IPs (incl. GitHub Actions) -- returns None on
    any failure so the caller can fall back to the hardcoded list."""
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        })
        session.get("https://www.nseindia.com", timeout=10)
        resp = session.get("https://www.nseindia.com/api/holiday-master?type=trading", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        holidays = set()
        for item in data.get("CM", []):
            d = datetime.strptime(item["tradingDate"], "%d-%b-%Y").date()
            if d.year == year:
                holidays.add(d)
        return holidays or None
    except Exception as e:
        print(f"[holidays] Live NSE fetch failed ({e}).")
        return None


def _get_nse_holidays(year):
    # 1) Already resolved earlier in this same process run
    if year in _holiday_cache:
        return _holiday_cache[year]

    # 2) Cache file on disk -- only usable if its year matches what we need
    cached = _load_holiday_cache_file()
    if cached and cached["year"] == year:
        print(f"[holidays] Using cached {year} holiday list ({cached['source']}, "
              f"{len(cached['holidays'])} dates) -- no fetch needed.")
        _holiday_cache[year] = cached["holidays"]
        return cached["holidays"]

    # 3) Cache is missing or stale for this year -- attempt a live fetch
    print(f"[holidays] No cached data for {year} -- attempting live NSE fetch...")
    holidays = _fetch_live_nse_holidays(year)
    if holidays:
        print(f"[holidays] Live fetch succeeded ({len(holidays)} dates) -- updating cache.")
        _save_holiday_cache_file(year, holidays, source="live")
        _holiday_cache[year] = holidays
        return holidays

    # 4) Live fetch failed -- fall back to a hardcoded list if we have one for this year
    if year in HARDCODED_HOLIDAYS_BY_YEAR:
        holidays = HARDCODED_HOLIDAYS_BY_YEAR[year]
        print(f"[holidays] Falling back to hardcoded {year} list ({len(holidays)} dates) -- updating cache.")
        _save_holiday_cache_file(year, holidays, source="hardcoded")
        _holiday_cache[year] = holidays
        return holidays

    # 5) Nothing available at all -- warn loudly, don't cache, so it retries next run
    print(f"[holidays] WARNING: no holiday data available for {year} -- "
          f"add a hardcoded NSE_HOLIDAYS_{year} set in build_report.py.")
    _holiday_cache[year] = set()
    return set()


def _parse_date_str(d):
    """Parses a date string in either 'YYYY-MM-DD' or 'DD-Mon' form. Returns None if unparseable."""
    if not d:
        return None
    try:
        if "-" in d and d[:4].isdigit():
            return datetime.strptime(d, "%Y-%m-%d").date()
        return datetime.strptime(f"{d}-{date.today().year}", "%d-%b-%Y").date()
    except ValueError:
        return None


def _add_working_days(start, n):
    """Adds n NSE/BSE working days to start, skipping weekends and market holidays."""
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in _get_nse_holidays(d.year):
            added += 1
    return d


def _calculate_refund_date(close_str):
    """Refund initiation is generally close date + 2 NSE/BSE working days."""
    close_dt = _parse_date_str(close_str)
    if close_dt is None:
        return None
    return _add_working_days(close_dt, 2).strftime("%d-%b")


def _is_current(entry):
    """
    Keep IPOs up through their refund date -- i.e. drop an IPO once its refund
    date has passed. Falls back to the close date if no refund date is available
    (InvestorZone-only entries don't have one).
    """
    today = date.today()
    refund_dt = _parse_date_str(entry.get("refund"))
    if refund_dt is not None:
        return refund_dt >= today
    close_dt = _parse_date_str(entry.get("close"))
    if close_dt is not None:
        return close_dt >= today
    return True  # no dates at all -- keep rather than accidentally drop


def _normalize_name(name):
    name = name.lower()
    name = re.sub(r"\bipo\b", "", name)
    name = re.sub(r"\b(bse|nse)?\s*sme\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _gmp_value(gmp_pct_str):
    """Parses '21.67%' -> 21.67. Returns None if missing/unparseable."""
    if not gmp_pct_str:
        return None
    try:
        return float(gmp_pct_str.replace("%", "").strip())
    except ValueError:
        return None


def _best_gmp(entry):
    """Highest available GMP% across both sources -- used for filtering/sorting only."""
    vals = [v for v in (_gmp_value(entry.get("ig_gmp_pct")), _gmp_value(entry.get("iz_gmp_pct"))) if v is not None]
    return max(vals) if vals else 0


def _sort_key(v):
    # Ascending close date, then descending best-available GMP% within the same date
    close_dt = _parse_date_str(v.get("close")) or date.max
    return (close_dt, -_best_gmp(v))


def build_merged_data(min_gmp_pct=10):
    ig_data = scrape_investorgain()
    iz_data = fetch_investorzone()

    merged = {}
    for row in ig_data:
        key = _normalize_name(row["name"])
        merged.setdefault(key, {"name": row["name"]})
        merged[key]["ig_gmp_pct"] = row.get("gmp_pct")
        merged[key]["is_sme"] = row.get("is_sme", False)
        merged[key]["open"] = row.get("open")
        merged[key]["close"] = row.get("close")

    for row in iz_data:
        key = _normalize_name(row["name"])
        merged.setdefault(key, {"name": row["name"]})
        merged[key]["iz_gmp_pct"] = row.get("gmp_pct")
        merged[key].setdefault("is_sme", row.get("is_sme", False))
        merged[key].setdefault("open", row.get("open"))
        merged[key].setdefault("close", row.get("close"))

    # Refund date is always calculated (close date + 2 NSE/BSE working days),
    # not scraped -- this is consistent regardless of which source(s) had the IPO.
    for v in merged.values():
        v["refund"] = _calculate_refund_date(v.get("close"))

    # Keep only: still-current (not past refund date), mainboard (not SME), best GMP % above threshold
    current = [
        v for v in merged.values()
        if _is_current(v)
        and not v.get("is_sme")
        and _best_gmp(v) > min_gmp_pct
    ]
    current.sort(key=_sort_key)
    return current



def format_report(entries, min_gmp_pct=10):
    """Plain-text report for Telegram / WhatsApp."""
    today = datetime.now(timezone.utc).astimezone(IST).strftime("%d %b %Y")
    lines = [f"*IPO GMP Report (Mainboard, GMP > {min_gmp_pct}%) — {today}*", ""]

    if not entries:
        lines.append(f"No active mainboard IPOs with GMP above {min_gmp_pct}% right now.")
        return "\n".join(lines)

    for e in entries:
        lines.append(f"*{e['name']}*")
        lines.append(f"  InvestorGain: {e.get('ig_gmp_pct') or 'N/A'}")
        lines.append(f"  InvestorZone: {e.get('iz_gmp_pct') or 'N/A'}")
        details = []
        if e.get("open"):
            details.append(f"Open: {e['open']}")
        if e.get("close"):
            details.append(f"Close: {e['close']}")
        if e.get("refund"):
            details.append(f"Refund: {e['refund']}")
        if details:
            lines.append("  " + " | ".join(details))
        lines.append("")

    lines.append("_Source: investorgain.com, investorzone.in — informational only, not investment advice._")
    return "\n".join(lines)


def format_html_report(entries, min_gmp_pct=10):
    """Styled HTML report for the bookmarkable GitHub Pages webpage."""
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    generated_at = now_ist.strftime("%d %b %Y, %H:%M IST")

    def is_closed(entry):
        """True once close date has passed, or it's closing today past 17:00 IST."""
        close_dt = _parse_date_str(entry.get("close"))
        if close_dt is None:
            return False
        if close_dt < now_ist.date():
            return True
        if close_dt == now_ist.date() and now_ist.hour >= 17:
            return True
        return False

    def gmp_num(pct_str):
        v = _gmp_value(pct_str)
        return v if v is not None else -1

    def stamp(entry):
        ig, iz = gmp_num(entry.get("ig_gmp_pct")), gmp_num(entry.get("iz_gmp_pct"))
        return f"{max(ig, iz):.0f}%" if max(ig, iz) >= 0 else "N/A"

    cards = ""
    for e in entries:
        ig = e.get("ig_gmp_pct") or "N/A"
        iz = e.get("iz_gmp_pct") or "N/A"
        closed_class = " closed" if is_closed(e) else ""
        closed_tag = '<span class="closed-tag">CLOSED</span>' if is_closed(e) else ""
        cards += f"""
        <div class="slip{closed_class}">
          <div class="perf"></div>
          <div class="slip-body">
            <div class="slip-main">
              <h2>{e['name']} {closed_tag}</h2>
              <div class="dates">
                <span><b>Open</b> {e.get('open') or '—'}</span>
                <span><b>Close</b> {e.get('close') or '—'}</span>
                <span><b>Refund</b> {e.get('refund') or '—'}</span>
              </div>
            </div>
            <div class="slip-gmp">
              <div class="stamp">{stamp(e)}</div>
              <div class="sources">
                <div class="src"><span class="src-label">IG</span><span class="src-val">{ig}</span></div>
                <div class="src"><span class="src-label">IZ</span><span class="src-val">{iz}</span></div>
              </div>
            </div>
          </div>
        </div>"""

    if not entries:
        cards = f'<p class="empty">No active mainboard IPOs with GMP above {min_gmp_pct}% right now.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>IPO GMP Ledger</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Special+Elite&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink-navy: #101b2d;
    --paper: #ede6d3;
    --stamp: #8b2a2a;
    --gold: #b8923f;
    --line: #c7bfa6;
    --ink-black: #201c14;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--ink-navy);
    color: var(--paper);
    font-family: 'IBM Plex Mono', monospace;
    padding: 28px 16px 60px;
  }}
  .wrap {{ max-width: 640px; margin: 0 auto; }}
  header {{
    border-bottom: 2px solid var(--gold);
    padding-bottom: 16px;
    margin-bottom: 28px;
  }}
  h1 {{
    font-family: 'Special Elite', monospace;
    font-size: 1.7rem;
    letter-spacing: 0.04em;
    margin: 0 0 6px;
    color: var(--paper);
  }}
  .sub {{
    font-size: 0.8rem;
    color: var(--gold);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }}
  .updated {{
    font-size: 0.72rem;
    color: #8a95a8;
    margin-top: 6px;
  }}
  .slip {{
    background: var(--paper);
    color: var(--ink-black);
    border-radius: 2px;
    margin-bottom: 18px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.35);
    animation: rise 0.4s ease backwards;
  }}
  .slip:nth-child(odd) {{ transform: rotate(-0.3deg); }}
  .slip:nth-child(even) {{ transform: rotate(0.3deg); }}
  .slip.closed {{
    opacity: 0.5;
    filter: grayscale(70%);
  }}
  .closed-tag {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    font-weight: 700;
    color: #fff;
    background: #6b6558;
    padding: 2px 6px;
    border-radius: 3px;
    letter-spacing: 0.06em;
    vertical-align: middle;
  }}
  @keyframes rise {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; }} }}
  @media (prefers-reduced-motion: reduce) {{ .slip {{ animation: none; }} }}
  .perf {{
    height: 8px;
    background-image: radial-gradient(circle, var(--ink-navy) 2.5px, transparent 2.6px);
    background-size: 14px 8px;
    background-position: center;
  }}
  .slip-body {{
    display: flex;
    justify-content: space-between;
    gap: 14px;
    padding: 16px 18px 18px;
  }}
  .slip-main h2 {{
    font-family: 'Special Elite', monospace;
    font-size: 1.02rem;
    margin: 0 0 10px;
    line-height: 1.3;
  }}
  .dates {{
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 0.75rem;
    color: #4a4436;
  }}
  .dates b {{
    color: var(--stamp);
    font-weight: 600;
    margin-right: 5px;
  }}
  .slip-gmp {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    min-width: 84px;
  }}
  .stamp {{
    font-family: 'Special Elite', monospace;
    font-size: 1.5rem;
    color: var(--stamp);
    border: 3px solid var(--stamp);
    border-radius: 6px;
    padding: 4px 8px;
    transform: rotate(-4deg);
    opacity: 0.88;
  }}
  .sources {{ display: flex; gap: 8px; }}
  .src {{
    display: flex;
    flex-direction: column;
    align-items: center;
    font-size: 0.68rem;
  }}
  .src-label {{
    color: #7a7256;
    letter-spacing: 0.05em;
  }}
  .src-val {{
    font-weight: 600;
    color: var(--ink-black);
  }}
  footer {{
    font-size: 0.7rem;
    color: #6b7688;
    margin-top: 22px;
    border-top: 1px solid #263349;
    padding-top: 14px;
    line-height: 1.5;
  }}
  .legend {{ color: var(--gold); }}
  .empty {{ color: var(--paper); font-size: 0.9rem; }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>IPO GMP Ledger</h1>
      <div class="sub">Mainboard · GMP above {min_gmp_pct}%</div>
      <div class="updated">Last updated {generated_at} · refreshes every 2 min</div>
    </header>
    {cards}
    <footer>
      <span class="legend">IG</span> = InvestorGain &nbsp;·&nbsp; <span class="legend">IZ</span> = InvestorZone<br>
      Source: investorgain.com, investorzone.in — informational only, not investment advice.
    </footer>
  </div>
</body>
</html>"""


if __name__ == "__main__":
    data = build_merged_data()
    print(format_report(data))
