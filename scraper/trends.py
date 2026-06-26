"""
Google Trends signal (BEST-EFFORT, OPTIONAL).

Honesty note: pytrends is an UNOFFICIAL, unsupported scraper of Google Trends.
Google rate-limits and occasionally blocks it, especially from datacenter IPs
like GitHub Actions runners. So this is wrapped to NEVER crash the daily run --
if it fails we just record ok=False and carry on. Treat the numbers as
directional, not gospel.
"""

import time


def fetch_trends(brand_names, geo="GB", timeframe="today 3-m"):
    try:
        from pytrends.request import TrendReq
    except Exception as exc:
        return {"ok": False, "error": f"pytrends not installed: {exc}", "data": {}}

    try:
        py = TrendReq(hl="en-GB", tz=0)
        data = {}
        # Trends compares max 5 terms at once; chunk the brand list.
        for i in range(0, len(brand_names), 5):
            chunk = brand_names[i:i + 5]
            py.build_payload(chunk, timeframe=timeframe, geo=geo)
            df = py.interest_over_time()
            if df is not None and not df.empty:
                for name in chunk:
                    if name in df.columns:
                        series = df[name].tolist()
                        data[name] = {
                            "latest": int(series[-1]) if series else None,
                            "mean": round(sum(series) / len(series), 1) if series else None,
                            "series": [int(v) for v in series][-13:],
                        }
            time.sleep(2)  # be polite / reduce block risk
        return {"ok": True, "geo": geo, "timeframe": timeframe, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": {}}
