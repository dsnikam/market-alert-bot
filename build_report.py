"""
Merges IPO GMP data from InvestorGain + IPOWatch (matched by name, kept
separately so you can cross-check them), filters to mainboard IPOs only,
and formats both a plain-text report (Telegram/WhatsApp) and a styled HTML
report (the bookmarkable webpage).
"""
import re
import os
import json
import requests
from datetime import datetime, date, timezone, timedelta
from scrape_investorgain import scrape_investorgain, scrape_investorgain_subscription
from scrape_ipowatch import scrape_ipowatch, scrape_ipowatch_subscription

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
    if year in _holiday_cache:
        return _holiday_cache[year]

    cached = _load_holiday_cache_file()
    if cached and cached["year"] == year:
        print(f"[holidays] Using cached {year} holiday list ({cached['source']}, "
              f"{len(cached['holidays'])} dates) -- no fetch needed.")
        _holiday_cache[year] = cached["holidays"]
        return cached["holidays"]

    print(f"[holidays] No cached data for {year} -- attempting live NSE fetch...")
    holidays = _fetch_live_nse_holidays(year)
    if holidays:
        print(f"[holidays] Live fetch succeeded ({len(holidays)} dates) -- updating cache.")
        _save_holiday_cache_file(year, holidays, source="live")
        _holiday_cache[year] = holidays
        return holidays

    if year in HARDCODED_HOLIDAYS_BY_YEAR:
        holidays = HARDCODED_HOLIDAYS_BY_YEAR[year]
        print(f"[holidays] Falling back to hardcoded {year} list ({len(holidays)} dates) -- updating cache.")
        _save_holiday_cache_file(year, holidays, source="hardcoded")
        _holiday_cache[year] = holidays
        return holidays

    print(f"[holidays] WARNING: no holiday data available for {year} -- "
          f"add a hardcoded NSE_HOLIDAYS_{year} set in build_report.py.")
    _holiday_cache[year] = set()
    return set()


def _add_working_days(start, n):
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in _get_nse_holidays(d.year):
            added += 1
    return d


def _parse_date_str(d):
    if not d:
        return None
    try:
        if "-" in d and d[:4].isdigit():
            return datetime.strptime(d, "%Y-%m-%d").date()
        return datetime.strptime(f"{d}-{date.today().year}", "%d-%b-%Y").date()
    except ValueError:
        return None


def _calculate_allotment_date(close_str):
    close_dt = _parse_date_str(close_str)
    if close_dt is None:
        return None
    return _add_working_days(close_dt, 1).strftime("%d-%b")


def _calculate_refund_date_from_allotment(allotment_str):
    allotment_dt = _parse_date_str(allotment_str)
    if allotment_dt is None:
        return None
    return _add_working_days(allotment_dt, 1).strftime("%d-%b")


def _is_current(entry):
    """Keep IPOs up through their listing date (i.e. until they've actually started trading)."""
    today = date.today()
    for field in ("listing", "allotment", "close"):
        dt = _parse_date_str(entry.get(field))
        if dt is not None:
            return dt >= today
    return True


def _normalize_name(name):
    name = name.lower()
    name = re.sub(r"\bipo\b", "", name)
    name = re.sub(r"\b(bse|nse)?\s*sme\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _gmp_value(gmp_pct_str):
    if not gmp_pct_str:
        return None
    try:
        return float(gmp_pct_str.replace("%", "").strip())
    except ValueError:
        return None


def _best_gmp(entry):
    vals = [v for v in (_gmp_value(entry.get("ig_gmp_pct")), _gmp_value(entry.get("iw_gmp_pct"))) if v is not None]
    return max(vals) if vals else 0


def _sort_key(v):
    close_dt = _parse_date_str(v.get("close")) or date.max
    return (close_dt, -_best_gmp(v))


def build_merged_data(min_gmp_pct=15):
    ig_data = scrape_investorgain()
    iw_data = scrape_ipowatch()
    ig_sub_data = scrape_investorgain_subscription()
    iw_sub_data = scrape_ipowatch_subscription()

    merged = {}
    for row in ig_data:
        key = _normalize_name(row["name"])
        merged.setdefault(key, {"name": row["name"]})
        merged[key]["ig_gmp_pct"] = row.get("gmp_pct")
        merged[key]["is_sme"] = row.get("is_sme", False)
        merged[key]["open"] = row.get("open")
        merged[key]["close"] = row.get("close")
        merged[key]["listing"] = row.get("listing")
        merged[key]["allotment"] = row.get("allotment")  # actual published date, not calculated

    for row in iw_data:
        key = _normalize_name(row["name"])
        merged.setdefault(key, {"name": row["name"]})
        merged[key]["iw_gmp_pct"] = row.get("gmp_pct")
        merged[key].setdefault("is_sme", row.get("is_sme", False))

    # Retail subscription, kept separately per source so they can be cross-checked --
    # NOT the "Sub"/Total column on InvestorGain's main GMP table (that's QIB+NII+Retail
    # blended, not retail-specific). These come from each site's dedicated
    # subscription report, which breaks QIB/NII/Retail out individually.
    for row in ig_sub_data:
        key = _normalize_name(row["name"])
        if key in merged:
            merged[key]["ig_retail_sub"] = row.get("retail_sub")

    for row in iw_sub_data:
        key = _normalize_name(row["name"])
        if key in merged:
            merged[key]["iw_retail_sub"] = row.get("retail_sub")

    # Allotment (internal use only, to derive refund -- not displayed): use InvestorGain's
    # actual published Basis of Allotment date when we have it; only calculate it
    # (close + 1 working day) for IPOWatch-only entries (no open/close from IPOWatch at all,
    # so this will rarely trigger -- IPOWatch doesn't supply dates we use for math).
    # Refund: always calculated as 1 working day after whichever allotment date we end
    # up with, per SEBI's T+3 timeline -- there's no published "refund date" field anywhere.
    for v in merged.values():
        if not v.get("allotment"):
            v["allotment"] = _calculate_allotment_date(v.get("close"))
        v["refund"] = _calculate_refund_date_from_allotment(v.get("allotment"))

    current = [
        v for v in merged.values()
        if _is_current(v) and not v.get("is_sme") and _best_gmp(v) > min_gmp_pct
    ]
    current.sort(key=_sort_key)
    return current


def format_report(entries, min_gmp_pct=15):
    today = datetime.now(timezone.utc).astimezone(IST).strftime("%d %b %Y")
    lines = [f"*IPO GMP Report (Mainboard, GMP > {min_gmp_pct}%) — {today}*", ""]

    if not entries:
        lines.append(f"No active mainboard IPOs with GMP above {min_gmp_pct}% right now.")
        return "\n".join(lines)

    for e in entries:
        lines.append(f"*{e['name']}*")
        lines.append(f"  InvestorGain: {e.get('ig_gmp_pct') or 'N/A'}")
        lines.append(f"  IPOWatch: {e.get('iw_gmp_pct') or 'N/A'}")
        if e.get("ig_retail_sub") or e.get("iw_retail_sub"):
            lines.append(f"  Retail Sub (IG): {e.get('ig_retail_sub') or 'N/A'}")
            lines.append(f"  Retail Sub (IW): {e.get('iw_retail_sub') or 'N/A'}")
        details = []
        if e.get("open"):
            details.append(f"Open: {e['open']}")
        if e.get("close"):
            details.append(f"Close: {e['close']}")
        if e.get("refund"):
            details.append(f"Refund: {e['refund']}")
        if e.get("listing"):
            details.append(f"Listing: {e['listing']}")
        if details:
            lines.append("  " + " | ".join(details))
        lines.append("")

    lines.append("_Source: investorgain.com, ipowatch.in — informational only, not investment advice._")
    return "\n".join(lines)


def format_html_report(entries, min_gmp_pct=15):
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    generated_at = now_ist.strftime("%d %b %Y, %H:%M IST")

    def is_closed(entry):
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
        ig, iw = gmp_num(entry.get("ig_gmp_pct")), gmp_num(entry.get("iw_gmp_pct"))
        return f"{max(ig, iw):.0f}%" if max(ig, iw) >= 0 else "N/A"

    cards = ""
    for e in entries:
        ig = e.get("ig_gmp_pct") or "N/A"
        iw = e.get("iw_gmp_pct") or "N/A"
        closed_class = " closed" if is_closed(e) else ""
        closed_tag = '<span class="closed-tag">CLOSED</span>' if is_closed(e) else ""
        retail_block = ""
        if e.get("ig_retail_sub") or e.get("iw_retail_sub"):
            ig_sub = e.get("ig_retail_sub") or "N/A"
            iw_sub = e.get("iw_retail_sub") or "N/A"
            retail_block = f"""
              <div class="sources-caption">Retail Sub</div>
              <div class="sources">
                <div class="src"><span class="src-label">IG</span><span class="src-val">{ig_sub}</span></div>
                <div class="src"><span class="src-label">IW</span><span class="src-val">{iw_sub}</span></div>
              </div>"""
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
                <span><b>Listing</b> {e.get('listing') or '—'}</span>
              </div>
            </div>
            <div class="slip-gmp">
              <div class="stamp">{stamp(e)}</div>
              <div class="sources">
                <div class="src"><span class="src-label">IG</span><span class="src-val">{ig}</span></div>
                <div class="src"><span class="src-label">IW</span><span class="src-val">{iw}</span></div>
              </div>
              {retail_block}
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
  .sub-row {{
    margin-top: 8px;
    font-size: 0.75rem;
    color: #4a4436;
  }}
  .sub-row b {{ color: var(--ink-black); }}
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
  .sources-caption {{
    font-size: 0.6rem;
    color: #7a7256;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-top: 10px;
    margin-bottom: 2px;
  }}
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
      <span class="legend">IG</span> = InvestorGain &nbsp;·&nbsp; <span class="legend">IW</span> = IPOWatch<br>
      Source: investorgain.com, ipowatch.in — informational only, not investment advice.
    </footer>
  </div>
</body>
</html>"""


if __name__ == "__main__":
    data = build_merged_data()
    print(format_report(data))
