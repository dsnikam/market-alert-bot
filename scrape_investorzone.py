"""
Fetches currently-active IPO GMP data from investorzone.in's public JSON API.
No browser needed here -- investorzone exposes clean REST endpoints.
"""
import requests

BASE = "https://investorzone.in/api"
ACTIVE_STATUSES = "UPCOMING,ANALYSIS_PENDING,UNDER_REVIEW,READY,LIVE"


def fetch_investorzone():
    # 1) Get active IPOs (not yet listed / currently trading in grey market)
    ipos_url = (
        f"{BASE}/ipos?is_active=1&status__in={ACTIVE_STATUSES}"
        "&order=open_date.desc"
        "&select=id,slug,ipo_name,price_band_high,status,open_date,close_date,listing_date,category"
    )
    r = requests.get(ipos_url, timeout=20)
    r.raise_for_status()
    ipos = r.json().get("data", [])
    if not ipos:
        return []

    ipo_ids = [ipo["id"] for ipo in ipos]

    # 2) Get latest GMP value for those IPOs (order desc so first hit per id = latest)
    gmp_url = (
        f"{BASE}/ipo_gmp?ipo_id__in={','.join(ipo_ids)}"
        "&order=created_at.desc&limit=1000&select=ipo_id,gmp_value,created_at"
    )
    r2 = requests.get(gmp_url, timeout=20)
    r2.raise_for_status()
    gmp_rows = r2.json().get("data", [])

    latest_gmp = {}
    for row in gmp_rows:
        iid = row["ipo_id"]
        if iid not in latest_gmp:  # first occurrence = most recent (desc order)
            latest_gmp[iid] = row["gmp_value"]

    results = []
    for ipo in ipos:
        gmp_val = latest_gmp.get(ipo["id"])
        price = ipo.get("price_band_high")
        gmp_pct = None
        if gmp_val is not None and price:
            try:
                gmp_pct = round((float(gmp_val) / float(price)) * 100, 2)
            except (TypeError, ZeroDivisionError):
                pass
        results.append({
            "source": "InvestorZone",
            "name": ipo["ipo_name"].strip(),
            "gmp": f"₹{gmp_val} ({gmp_pct}%)" if gmp_val is not None else "N/A",
            "price": price,
            "open": ipo.get("open_date"),
            "close": ipo.get("close_date"),
            "listing": ipo.get("listing_date"),
            "category": ipo.get("category"),
        })
    return results


if __name__ == "__main__":
    import json
    data = fetch_investorzone()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nTotal: {len(data)} IPOs")
