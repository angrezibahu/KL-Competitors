"""
Build a weekly HTML digest from the capture history.

Run:  python -m scraper.digest
Writes docs/digest.html (also linked from the dashboard) and prints the path.
The weekly-digest GitHub workflow emails the contents of that file.

It compares each brand's latest capture against its capture ~7 days earlier and
surfaces what CHANGED -- new/ended sales, deeper discounts, hero rewrites, new
codes -- plus the price-band leaderboard. All best-effort: missing
fields just don't appear.
"""

import html as _html
import json
import os
from datetime import datetime, timezone

from . import storage


def _latest_per_brand(records, on_or_before=None):
    out = {}
    for r in sorted(records, key=lambda x: x.get("date", "")):
        if r.get("status") != "success":
            continue
        if on_or_before and r.get("date", "") > on_or_before:
            continue
        out[r["slug"]] = r
    return out


def _esc(s):
    return _html.escape(str(s)) if s is not None else "—"


def build_html():
    records = storage.load_captures()
    if not records:
        return "<p>No data yet.</p>", "No data yet."

    dates = sorted({r["date"] for r in records})
    today = dates[-1]
    # nearest capture date at least ~7 days before the latest
    prior_candidates = [d for d in dates if d <= _shift(today, 7)]
    prior = prior_candidates[-1] if prior_candidates else dates[0]

    now = _latest_per_brand(records)
    then = _latest_per_brand(records, on_or_before=prior)

    brands = sorted(now.values(), key=lambda r: (not r.get("is_self"), r["brand"]))
    on_sale = [r for r in brands if r.get("headline_offer")]
    discounts = [r["max_discount_pct"] for r in brands if r.get("max_discount_pct")]
    avg_disc = round(sum(discounts) / len(discounts)) if discounts else None

    # changes vs prior
    changes = []
    for r in brands:
        p = then.get(r["slug"])
        if not p:
            continue
        if bool(r.get("headline_offer")) != bool(p.get("headline_offer")):
            changes.append(f"<b>{_esc(r['brand'])}</b> "
                           + ("started a sale: " + _esc(r.get("headline_offer"))
                              if r.get("headline_offer") else "ended its sale"))
        elif (r.get("max_discount_pct") or 0) != (p.get("max_discount_pct") or 0) and r.get("max_discount_pct"):
            changes.append(f"<b>{_esc(r['brand'])}</b> discount moved "
                           f"{p.get('max_discount_pct') or 0}% → {r.get('max_discount_pct')}%")
        if (r.get("hero_message") or "") != (p.get("hero_message") or "") and r.get("hero_message"):
            changes.append(f"<b>{_esc(r['brand'])}</b> changed its hero to “{_esc(r['hero_message'])}”")
        new_codes = set(r.get("discount_codes") or []) - set(p.get("discount_codes") or [])
        for c in new_codes:
            changes.append(f"<b>{_esc(r['brand'])}</b> new code: <code>{_esc(c)}</code>")

    joma = next((r for r in brands if r.get("is_self")), None)

    def row_offer(r):
        return (f'<span style="color:#b46a83;font-weight:600">{_esc(r["headline_offer"])}</span>'
                if r.get("headline_offer") else '<span style="color:#999">no offer</span>')

    price_sorted = sorted([r for r in brands if (r.get("prices") or {}).get("median")],
                          key=lambda r: r["prices"]["median"])

    style = ("font-family:system-ui,Arial,sans-serif;color:#2a2430;max-width:680px;"
             "margin:auto;line-height:1.55")
    parts = [f'<div style="{style}">']
    parts.append(f'<h1 style="color:#b46a83">Katie Loxton Competitor Radar — weekly digest</h1>')
    parts.append(f'<p style="color:#857c87">Week to <b>{today}</b> (vs {prior}). '
                 f'{len(on_sale)}/{len(brands)} brands on offer · avg headline discount '
                 f'{avg_disc if avg_disc is not None else "—"}%.</p>')

    if joma:
        jp = joma.get("prices") or {}
        parts.append('<div style="background:#faf2f5;border-radius:12px;padding:14px 16px;margin:14px 0">'
                     '<h2 style="margin:0 0 6px">★ Katie Loxton right now</h2>'
                     f'<p style="margin:4px 0">Hero: “{_esc(joma.get("hero_message"))}”</p>'
                     f'<p style="margin:4px 0">Offer: {row_offer(joma)} · '
                     f'Price band: £{jp.get("min","—")}–£{jp.get("max","—")} (median £{jp.get("median","—")})</p></div>')

    parts.append("<h2>What changed this week</h2>")
    parts.append("<ul>" + ("".join(f"<li>{c}</li>" for c in changes[:25])
                           or "<li>No notable changes.</li>") + "</ul>")

    parts.append("<h2>Who's discounting</h2><table style='border-collapse:collapse;width:100%'>")
    parts.append("<tr><th scope='col' align=left>Brand</th><th scope='col' align=left>Offer</th>"
                 "<th scope='col' align=right>Max %</th></tr>")
    for r in sorted(brands, key=lambda r: -(r.get("max_discount_pct") or 0)):
        star = " ★" if r.get("is_self") else ""
        parts.append(f"<tr><td>{_esc(r['brand'])}{star}</td><td>{row_offer(r)}</td>"
                     f"<td align=right>{r.get('max_discount_pct') or '—'}</td></tr>")
    parts.append("</table>")

    if price_sorted:
        parts.append("<h2>Price bands (median, cheapest first)</h2><ol>")
        for r in price_sorted:
            p = r["prices"]
            parts.append(f"<li>{_esc(r['brand'])}{' ★' if r.get('is_self') else ''} — "
                         f"median £{p['median']} (£{p['min']}–£{p['max']})</li>")
        parts.append("</ol>")

    parts.append('<p style="color:#aaa;font-size:12px;margin-top:24px">Rules-based capture — '
                 'figures are directional. Open the dashboard for full detail.</p></div>')

    h = "".join(parts)
    text = (f"Katie Loxton Competitor Radar weekly digest — week to {today}.\n"
            f"{len(on_sale)}/{len(brands)} brands on offer, avg discount "
            f"{avg_disc if avg_disc is not None else '-'}%.\n"
            + "\n".join("- " + _strip(c) for c in changes[:25]))
    return h, text


def _strip(s):
    import re
    return re.sub(r"<[^>]+>", "", s)


def _shift(date_str, days):
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    from datetime import timedelta
    return (d - timedelta(days=days)).strftime("%Y-%m-%d")


def main():
    storage.ensure_dirs()
    html_out, text_out = build_html()
    path = os.path.join(storage.DOCS, "digest.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<!doctype html><html lang='en-GB'><head><meta charset='utf-8'>"
                 "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                 "<title>Weekly digest — Katie Loxton Competitor Radar</title></head><body>"
                 + html_out + "</body></html>")
    txt = os.path.join(storage.DATA_DIR, "digest.txt")
    with open(txt, "w", encoding="utf-8") as fh:
        fh.write(text_out)
    print(f"Wrote {path}")
    return path


if __name__ == "__main__":
    main()
