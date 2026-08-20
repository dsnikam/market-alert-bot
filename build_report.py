"""
Merges IPO GMP data from InvestorGain + InvestorZone (matched by name, kept
separately so you can cross-check them), filters to mainboard IPOs only, and
formats both a plain-text report (Telegram/WhatsApp) and a styled HTML report
(the bookmarkable webpage).
"""
import re
from datetime import datetime, date, timezone, timedelta
from scrape_investorgain import scrape_investorgain
from scrape_investorzone import fetch_investorzone

IST = timezone(timedelta(hours=5, minutes=30))


def _is_current(close_date_str):
    """Keep IPOs that haven't closed yet (or closed very recently, within listing window)."""
    if not close_date_str:
        return True
    try:
        if "-" in close_date_str and close_date_str[:4].isdigit():
            close_dt = datetime.strptime(close_date_str, "%Y-%m-%d").date()
        else:
            close_dt = datetime.strptime(f"{close_date_str}-{date.today().year}", "%d-%b-%Y").date()
        return close_dt >= date.today()
    except ValueError:
        return True


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


def _parse_close(c):
    try:
        if "-" in c and c[:4].isdigit():
            return datetime.strptime(c, "%Y-%m-%d").date()
        return datetime.strptime(f"{c}-{date.today().year}", "%d-%b-%Y").date()
    except (ValueError, TypeError):
        return date.max


def _sort_key(v):
    # Ascending close date, then descending best-available GMP% within the same date
    return (_parse_close(v.get("close") or ""), -_best_gmp(v))


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
        merged[key]["refund"] = row.get("refund")

    for row in iz_data:
        key = _normalize_name(row["name"])
        merged.setdefault(key, {"name": row["name"]})
        merged[key]["iz_gmp_pct"] = row.get("gmp_pct")
        merged[key].setdefault("is_sme", row.get("is_sme", False))
        merged[key].setdefault("open", row.get("open"))
        merged[key].setdefault("close", row.get("close"))
        merged[key].setdefault("refund", None)  # investorzone doesn't expose refund date

    # Keep only: still-current (not yet closed), mainboard (not SME), best GMP % above threshold
    current = [
        v for v in merged.values()
        if _is_current(v.get("close"))
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
    generated_at = datetime.now(timezone.utc).astimezone(IST).strftime("%d %b %Y, %H:%M IST")

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
        cards += f"""
        <div class="slip">
          <div class="perf"></div>
          <div class="slip-body">
            <div class="slip-main">
              <h2>{e['name']}</h2>
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
    
