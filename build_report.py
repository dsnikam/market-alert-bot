"""
Merges IPO GMP data from InvestorGain + InvestorZone (matched by name),
filters to mainboard IPOs only, and formats a minimal daily report showing
just: name, GMP %, open date, close date, refund date.
"""
import re
from datetime import datetime, date
from scrape_investorgain import scrape_investorgain
from scrape_investorzone import fetch_investorzone


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


def _sort_key(v):
    c = v.get("close") or ""
    try:
        if "-" in c and c[:4].isdigit():
            close_dt = datetime.strptime(c, "%Y-%m-%d").date()
        else:
            close_dt = datetime.strptime(f"{c}-{date.today().year}", "%d-%b-%Y").date()
    except ValueError:
        close_dt = date.max

    gmp = _gmp_value(v.get("gmp_pct")) or 0
    # Ascending close date, then descending GMP% within the same date
    return (close_dt, -gmp)


def build_merged_data(min_gmp_pct=10):
    ig_data = scrape_investorgain()
    iz_data = fetch_investorzone()

    merged = {}
    for row in ig_data:
        key = _normalize_name(row["name"])
        merged.setdefault(key, {"name": row["name"]})
        merged[key]["gmp_pct"] = row.get("gmp_pct")
        merged[key]["is_sme"] = row.get("is_sme", False)
        merged[key]["open"] = row.get("open")
        merged[key]["close"] = row.get("close")
        merged[key]["refund"] = row.get("refund")

    for row in iz_data:
        key = _normalize_name(row["name"])
        merged.setdefault(key, {"name": row["name"]})
        merged[key].setdefault("gmp_pct", row.get("gmp_pct"))
        merged[key].setdefault("is_sme", row.get("is_sme", False))
        merged[key].setdefault("open", row.get("open"))
        merged[key].setdefault("close", row.get("close"))
        merged[key].setdefault("refund", None)  # investorzone doesn't expose refund date

    # Keep only: still-current (not yet closed), mainboard (not SME), GMP % above threshold
    current = [
        v for v in merged.values()
        if _is_current(v.get("close"))
        and not v.get("is_sme")
        and (_gmp_value(v.get("gmp_pct")) or 0) > min_gmp_pct
    ]
    current.sort(key=_sort_key)
    return current


def format_report(entries, min_gmp_pct=10):
    today = datetime.now().strftime("%d %b %Y")
    lines = [f"*IPO GMP Report (Mainboard, GMP > {min_gmp_pct}%) — {today}*", ""]

    if not entries:
        lines.append(f"No active mainboard IPOs with GMP above {min_gmp_pct}% right now.")
        return "\n".join(lines)

    for e in entries:
        lines.append(f"*{e['name']}*")
        lines.append(f"  GMP: {e.get('gmp_pct') or 'N/A'}")
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


if __name__ == "__main__":
    data = build_merged_data()
    print(format_report(data))
    
