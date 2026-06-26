"""
Assortment & new-product velocity from product sitemaps.

Why sitemaps: every Shopify store (and most modern shops) exposes /sitemap.xml ->
product sitemaps in plain XML that are SERVED TO BOTS BY DESIGN. So this is
reliable where shop-page scraping isn't, adds no new blocking surface, and is
light (XML, no rendering). It answers a question the rest of the radar can't:
how BIG is each competitor's range, who's EXPANDING it, and who's DROPPING new
products -- merchandising/assortment velocity, not just marketing.

Honesty (same ethos as everywhere here): best-effort and never fatal. A brand
whose sitemap 404s, blocks us, or isn't in a recognised product format simply
gets ok=False for that day and is shown as such -- never hidden, never guessed.
The very first time we see a brand we record its catalogue size but report ZERO
new/removed (we have no prior snapshot to diff against, so we don't invent a
"+400 products" spike) -- that day is flagged first_seen.

The parsing functions are PURE (xml string in, data out) and unit-tested
offline; only the thin orchestrator touches the network, through an injected
`get(url) -> str|None` so even it can be tested without a browser.

Storage:
  docs/data/catalogue.json           append-only history of runs (small: counts +
                                      a few sample new-product handles per brand)
  docs/data/catalogue_snapshot.json  the latest handle set per brand, OVERWRITTEN
                                      each run -- the baseline the next diff uses
"""

import os
import re
from urllib.parse import urljoin, urlparse

from . import storage

CATALOGUE_PATH = os.path.join(storage.DATA_DIR, "catalogue.json")
SNAPSHOT_PATH = os.path.join(storage.DATA_DIR, "catalogue_snapshot.json")

MAX_CHILD_SITEMAPS = 12      # bound work on a huge sitemap index
MAX_HANDLES = 8000           # bound memory/output for very large catalogues

_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)


def _unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'"))


def extract_locs(xml):
    """Every <loc> URL in a sitemap or sitemap-index, in document order."""
    return [_unescape(m.strip()) for m in _LOC_RE.findall(xml or "") if m.strip()]


def is_sitemap_index(xml):
    """True if this is a <sitemapindex> (a list of child sitemaps), not a urlset."""
    return bool(re.search(r"<sitemapindex", xml or "", re.I))


def looks_like_sitemap(body):
    """True if a fetched body is actually a sitemap (index or urlset), not a
    bot-challenge / HTML error page. Lets the fetcher reject a Cloudflare
    interstitial (which a header-light request returns but a full browser
    clears) instead of trying to parse it as XML. Pure."""
    low = (body or "").lower()
    return "<sitemapindex" in low or "<urlset" in low


def is_product_sitemap_url(url):
    """Does this child-sitemap URL look like it holds products?"""
    u = url.lower()
    return ("sitemap_products" in u or "/products" in u
            or u.endswith("products.xml") or "product" in u)


def looks_like_product_url(url):
    """Is this a product detail page (vs a collection/page/blog URL)?"""
    p = urlparse(url).path.lower()
    return "/products/" in p or "/product/" in p


def handle_from_url(url):
    """The product 'handle' (last path segment), lower-cased -- a stable id that
    survives query strings and trailing slashes."""
    path = urlparse(url).path.rstrip("/")
    seg = path.rsplit("/", 1)[-1] if "/" in path else path
    return seg.lower()


def _fail(msg):
    return {"ok": False, "product_count": 0, "handles": [],
            "sitemaps_used": [], "error": msg}


def collect(get, base_url):
    """Walk a site's sitemaps into a sorted, de-duplicated set of product handles.

    `get(url) -> str|None` is injected (network lives outside this module).
    Returns {ok, product_count, handles, sitemaps_used, error}. Best-effort: any
    failure yields ok=False with a short reason and no handles."""
    root = base_url if base_url.endswith("/") else base_url + "/"
    index_url = urljoin(root, "sitemap.xml")
    xml = get(index_url)
    if not xml:
        return _fail("no sitemap.xml")

    if is_sitemap_index(xml):
        children = extract_locs(xml)
        # Prefer obviously-product child sitemaps; if none are recognisable, fall
        # back to scanning all of them (and we still filter to /products/ URLs).
        prod = [c for c in children if is_product_sitemap_url(c)]
        sitemaps_used = (prod or children)[:MAX_CHILD_SITEMAPS]
        urls = []
        for sm in sitemaps_used:
            cx = get(sm)
            if cx:
                urls.extend(extract_locs(cx))
    else:
        # A flat urlset already lists page URLs; filter to products below.
        sitemaps_used = [index_url]
        urls = extract_locs(xml)

    handles = sorted({handle_from_url(u) for u in urls
                      if looks_like_product_url(u) and handle_from_url(u)})
    handles = handles[:MAX_HANDLES]
    if not handles:
        return _fail("no product URLs in sitemap")
    return {"ok": True, "product_count": len(handles), "handles": handles,
            "sitemaps_used": sitemaps_used, "error": None}


def diff(prev_handles, cur_handles):
    """New & removed product handles between two snapshots (order-independent)."""
    prev, cur = set(prev_handles or []), set(cur_handles or [])
    return {"new": sorted(cur - prev), "removed": sorted(prev - cur)}


def classify_handles(handles, categories):
    """Count how many product handles fall in each jewellery category.

    Range mix (the actual published assortment) -- distinct from the homepage
    product_mix, which counts category *mentions* in marketing copy. A handle may
    fall in several categories ('personalised-birthstone-necklace' is all three),
    so shares are 'of the catalogue', not mutually exclusive. Uses the SAME
    `\\bkeyword` matching as extractors.extract_product_mix, so 'ring' catches
    'rings' but not 'ea*rring*'. Pure (handles + taxonomy in, counts out)."""
    counts = {cat: 0 for cat in (categories or {})}
    for h in handles or []:
        text = (h or "").replace("-", " ").replace("_", " ").lower()
        for cat, kws in (categories or {}).items():
            if any(re.search(r"\b" + re.escape((kw or "").lower()), text) for kw in kws):
                counts[cat] += 1
    return {c: n for c, n in counts.items() if n}


def _brand_entry(res, prev):
    """One brand's catalogue record for today, diffed against its prior snapshot.

    prev is None when we've never seen the brand before (first_seen): record the
    size but report zero velocity so we don't invent a spike."""
    if not res["ok"]:
        return {"product_count": None, "new_count": 0, "removed_count": 0,
                "new_samples": [], "ok": False, "first_seen": False,
                "error": res["error"]}
    if prev is None:
        return {"product_count": res["product_count"], "new_count": 0,
                "removed_count": 0, "new_samples": [], "ok": True,
                "first_seen": True, "error": None}
    d = diff(prev, res["handles"])
    return {"product_count": res["product_count"], "new_count": len(d["new"]),
            "removed_count": len(d["removed"]), "new_samples": d["new"][:8],
            "ok": True, "first_seen": False, "error": None}


def build(get, brands, categories=None, date=None, captured_at=None):
    """Fetch each brand's catalogue, diff vs the prior day's snapshot, append a
    dated run to catalogue.json and update the snapshot. Idempotent per day.

    The snapshot keeps BOTH the latest handle set (`cur`) and the previous day's
    (`prev`), so today's "new products" always diffs against YESTERDAY even on a
    manual same-day re-run (which only refreshes `cur`, never advancing the
    baseline). Pure-ish: all network is via the injected `get`, so build() is
    exercised in tests with an in-memory fake. Returns the appended run dict."""
    storage.ensure_dirs()
    date = date or storage.today()
    snap = storage._load_json(SNAPSHOT_PATH, {})
    cur_date = snap.get("cur_date")
    prev = dict(snap.get("prev") or {})
    cur = dict(snap.get("cur") or {})

    # A run for a later date advances the baseline (yesterday's `cur` -> the diff
    # base). A same-date re-run diffs against `prev` (the real day-before) and
    # only refreshes `cur`, so velocity is stable no matter how often it re-runs.
    advancing = cur_date is None or date > cur_date
    baseline = cur if advancing else prev

    hist = storage._load_json(CATALOGUE_PATH, {"runs": []})
    if not isinstance(hist, dict) or "runs" not in hist:
        hist = {"runs": []}

    new_cur = dict(cur)
    brands_out = {}
    for b in brands:
        slug = b["slug"]
        res = collect(get, b["url"])
        brands_out[slug] = _brand_entry(res, baseline.get(slug))
        if res["ok"]:
            new_cur[slug] = res["handles"]        # refresh latest on success only
            if categories:                        # range mix by category
                brands_out[slug]["categories"] = classify_handles(res["handles"], categories)
        # On failure we KEEP the prior handles so a one-day block doesn't make
        # every product look "new" the day the brand comes back.

    if advancing:
        # Moving to a new day: yesterday's `cur` becomes the new `prev` baseline.
        new_snap = {"cur_date": date, "prev": (cur if cur_date is not None else prev),
                    "cur": new_cur}
    else:
        new_snap = {"cur_date": cur_date, "prev": prev, "cur": new_cur}

    run = {"date": date, "captured_at": captured_at or storage.now_iso(),
           "brands": brands_out}
    hist["runs"] = [r for r in hist["runs"] if r.get("date") != date] + [run]
    hist["runs"].sort(key=lambda r: r.get("date", ""))
    hist["runs"] = hist["runs"][-400:]
    storage._write_json(CATALOGUE_PATH, hist)
    storage._write_json(SNAPSHOT_PATH, new_snap)

    ok = sum(1 for v in brands_out.values() if v["ok"])
    print(f"  catalogue: {ok}/{len(brands)} brands OK, "
          f"{sum(v['new_count'] for v in brands_out.values())} new products seen")
    return run
