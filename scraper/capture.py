"""
Daily capture orchestrator.

Run:  python -m scraper.capture

For EVERY brand it:
  1. opens a fresh, cache-busted browser context (no stale results),
  2. screenshots the homepage (JPEG, downscaled to keep the repo lean),
  3. extracts trading fields with the rules in extractors.py,
  4. records an EXPLICIT success/failed status with a timestamp.

The exit code is non-zero only if EVERY brand failed, so a flaky single site
doesn't fail the whole workflow -- but the per-brand status is always written
so the dashboard can show exactly what worked and what didn't. No silent
'all done' lies.
"""

import json
import os
import sys
import traceback

from . import catalogue, storage
from .colours import dominant_colours
from .extractors import (detect_block, extract_all, extract_listing,
                         extract_marketplace_presence, merge_marketplace)
from .trends import fetch_trends

CONFIG_PATH = os.path.join(storage.ROOT, "config", "competitors.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Regex of container/text patterns that indicate a cookie banner / popup, so
# they don't get mistaken for the hero and can be hidden before screenshotting.
_OVERLAY_PATTERN = "cookie|consent|gdpr|newsletter|popup|pop-up|modal|subscribe|privacy|overlay|interstitial|klaviyo|age-gate|region"

# Alt/aria text that is chrome, not a hero banner (mirrors extractors._BANNER_SKIP)
# so a logo or payment icon never becomes the headline.
_BANNER_SKIP_PATTERN = (
    "logo|icon|payment|visa|mastercard|amex|paypal|klarna|clearpay|apple ?pay|"
    "google ?pay|social|instagram|facebook|tiktok|pinterest|youtube|twitter|"
    "trustpilot|review|star rating|avatar|thumbnail|swatch|placeholder|spinner|"
    "loading|menu|search|basket|cart|wishlist|account"
)

# JS to grab the best hero guess. Primarily the single largest piece of visible
# text, skipping cookie/popup/newsletter containers. But big banners often render
# their headline ("Up to 50% off summer sale") INSIDE an image, so the words only
# live in the image's alt/aria/title -- invisible to the text scan. We therefore
# also look at banner-sized images and, mirroring extractors._offer_strength,
# prefer one whose alt advertises a louder offer than the largest live text.
LARGEST_TEXT_JS = """
() => {
  const bad = new RegExp(%r, 'i');
  const skip = new RegExp(%b, 'i');
  const inBad = (el) => {
    let n = el;
    for (let i = 0; i < 6 && n; i++) {
      const cls = (typeof n.className === 'string') ? n.className : '';
      if (bad.test((n.id || '') + ' ' + cls)) return true;
      n = n.parentElement;
    }
    return false;
  };
  const offerStrength = (s) => {
    s = (s || '').toLowerCase();
    const pcts = (s.match(/\\d{1,3}\\s*%/g) || [])
      .map(x => parseInt(x, 10)).filter(n => n <= 90);
    if (pcts.length) return Math.max.apply(null, pcts);
    if (/\\b(sale|clearance|outlet|black friday|cyber monday)\\b/.test(s)) return 5;
    return 0;
  };
  // 1) Largest live text -- the most reliable hero for most sites.
  let best = {area: 0, text: ''};
  const els = document.querySelectorAll('h1,h2,p,span,div,a');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.top > window.innerHeight || r.width < 50 || r.height < 20) continue;
    if (inBad(el)) continue;
    const txt = (el.innerText || '').trim();
    if (!txt || txt.length < 3 || txt.length > 160) continue;
    if (bad.test(txt)) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize) || 0;
    const score = fs * fs;            // weight strongly toward big type
    if (score > best.area) best = {area: score, text: txt};
  }
  // 2) Banner-sized images: recover the loudest-offer alt/aria/title copy.
  let promo = '';
  const imgs = document.querySelectorAll(
    'img[alt],img[title],[role="img"][aria-label],[aria-label]');
  for (const el of imgs) {
    const r = el.getBoundingClientRect();
    if (r.top > window.innerHeight || r.width < 120 || r.height < 60) continue;
    if (inBad(el)) continue;
    const txt = (el.getAttribute('alt') || el.getAttribute('aria-label')
                 || el.getAttribute('title') || '').trim();
    if (!txt || txt.length < 6 || txt.length > 160) continue;
    if (bad.test(txt) || skip.test(txt)) continue;
    if (offerStrength(txt) > offerStrength(promo)) promo = txt;
  }
  // Prefer the banner image only when it shouts a stronger offer than the text.
  return offerStrength(promo) > offerStrength(best.text) ? promo : best.text;
}
""".replace("%r", repr(_OVERLAY_PATTERN)).replace("%b", repr(_BANNER_SKIP_PATTERN))

# JS to hide cookie/newsletter overlays so they don't dominate the screenshot
# (or the dominant-colour extraction).
HIDE_OVERLAYS_JS = """
() => {
  const bad = new RegExp(%r, 'i');
  for (const el of document.querySelectorAll('div,section,aside,dialog')) {
    const cls = (typeof el.className === 'string') ? el.className : '';
    const cs = getComputedStyle(el);
    const fixed = cs.position === 'fixed' || cs.position === 'sticky';
    const high = parseInt(cs.zIndex || '0', 10) >= 1000;
    if (bad.test((el.id || '') + ' ' + cls) && (fixed || high)) el.style.display = 'none';
  }
}
""".replace("%r", repr(_OVERLAY_PATTERN))

# Button labels commonly used to accept cookies / dismiss popups.
_DISMISS_LABELS = ["Accept all", "Accept All Cookies", "Accept all cookies",
                   "Accept", "Allow all", "Allow All", "I agree", "Agree",
                   "Got it", "Continue", "No thanks", "Close"]


def dismiss_overlays(page):
    """Best-effort: click a consent button, then hide any leftover overlays."""
    for label in _DISMISS_LABELS:
        try:
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count() > 0:
                btn.first.click(timeout=1200)
                page.wait_for_timeout(300)
                break
        except Exception:
            pass
    try:
        page.evaluate(HIDE_OVERLAYS_JS)
    except Exception:
        pass


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def make_sitemap_getter(context):
    """A getter for sitemap XML that prefers the FULL BROWSER stack.

    Many Shopify/Cloudflare-protected stores (Katie Loxton, Charles & Keith, Oliver Bonas...)
    serve a 403/challenge to a header-light HTTP request but pass the real
    rendered browser -- exactly the path the homepage capture already clears. So
    we navigate to the sitemap with `page.goto` and read the raw *response body*
    (`response.text()` is the network payload, not the rendered XML tree), which
    returns genuine XML when the challenge is cleared. We accept the body only if
    it actually looks like a sitemap; otherwise (and on any error) we fall back to
    the plain request API, which still works for permissive hosts. Best-effort:
    returns None when neither yields a real sitemap, so the brand is honestly
    logged as having no readable sitemap."""
    def _via_browser(url):
        page = context.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if resp:
                body = resp.text()
                if catalogue.looks_like_sitemap(body):
                    return body
        except Exception:
            pass
        finally:
            page.close()
        return None

    def _via_request(url):
        try:
            resp = context.request.get(
                url, timeout=30000, headers={"User-Agent": USER_AGENT})
            if resp.ok:
                body = resp.text()
                if catalogue.looks_like_sitemap(body):
                    return body
        except Exception:
            pass
        return None

    def get(url):
        return _via_browser(url) or _via_request(url)
    return get


def capture_listing(context, brand):
    """Sample a brand's product-listing/bestsellers page for REAL trading data.

    Entirely optional and never fatal: a brand with no `listing_url`, a page that
    blocks us, or one with no readable prices simply yields no `listing` block --
    the homepage capture's success is unaffected. This is where rough homepage
    price *bands* become real price *distributions* and promotional *intensity*.
    """
    url = brand.get("listing_url")
    if not url:
        return None
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("load", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2500)         # let lazy product grids settle
        dismiss_overlays(page)
        html = page.content()
        visible_text = page.inner_text("body")
        if detect_block(html, visible_text):
            print(f"  [listing blocked] {brand['name']}")
            return None
        listing = extract_listing(html, visible_text)
        if not listing["prices"]["count"]:
            print(f"  [listing empty]   {brand['name']}: no readable prices")
            return None
        listing["url"] = url
        p = listing["prices"]
        print(f"  [listing OK]      {brand['name']}: {listing['products_seen']} items "
              f"£{p['min']}-£{p['max']} (med £{p['median']}), "
              f"{round(listing['discounted_share'] * 100)}% on sale")
        return listing
    except Exception as exc:
        print(f"  [listing FAILED]  {brand['name']}: {type(exc).__name__}: {exc}")
        return None
    finally:
        page.close()


def capture_stockists(context, brand):
    """Scan a brand's optional `stockists_url` ("where to buy" / stockists page)
    for OFF-SITE marketplace links the homepage doesn't carry.

    Off-site channels (an Amazon storefront, a TikTok Shop) are often linked from
    a stockists/where-to-buy page rather than the homepage. This fetches that one
    page on the brand's OWN site (so no Amazon/TikTok request, no new blocking
    surface) and runs the same homepage marketplace extractor over it. Entirely
    optional and never fatal: no `stockists_url`, a blocked page, or one with no
    marketplace links simply yields None and the homepage read stands. Returns a
    marketplace dict to merge, or None."""
    url = brand.get("stockists_url")
    if not url:
        return None
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("load", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        dismiss_overlays(page)
        html = page.content()
        visible_text = page.inner_text("body")
        if detect_block(html, visible_text):
            print(f"  [stockists blocked] {brand['name']}")
            return None
        mk = extract_marketplace_presence(html, visible_text)
        if mk["amazon"]["state"] == "none" and mk["tiktok"]["state"] == "none":
            print(f"  [stockists OK]    {brand['name']}: no marketplace links on stockists page")
            return None
        print(f"  [stockists OK]    {brand['name']}: amazon={mk['amazon']['state']} "
              f"tiktok={mk['tiktok']['state']}")
        return mk
    except Exception as exc:
        print(f"  [stockists FAILED] {brand['name']}: {type(exc).__name__}: {exc}")
        return None
    finally:
        page.close()


def capture_brand(context, brand, categories, date):
    """Capture a single brand. Returns a record dict (status success/failed)."""
    slug = brand["slug"]
    base = {
        "date": date,
        "captured_at": storage.now_iso(),
        "brand": brand["name"],
        "slug": slug,
        "url": brand["url"],
        "is_self": brand.get("is_self", False),
    }

    page = context.new_page()
    try:
        # 'domcontentloaded' instead of 'networkidle': many sites never go idle
        # (chat widgets, analytics) and would time out even though they loaded.
        page.goto(brand["url"], wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)         # let lazy hero content settle
        dismiss_overlays(page)              # clear cookie/newsletter popups
        page.wait_for_timeout(500)

        html = page.content()
        visible_text = page.inner_text("body")

        # If we got a bot-challenge/interstitial (e.g. Cloudflare "Just a
        # moment...") instead of the real homepage, record an HONEST failure
        # rather than polluting the data with junk keywords/SEO/colours.
        block_reason = detect_block(html, visible_text)
        if block_reason:
            base["status"] = "failed"
            base["error"] = block_reason
            base["screenshot"] = None
            print(f"  [BLOCKED] {brand['name']}: {block_reason}")
            return base

        # Screenshot -> JPEG, downscaled, to keep git size sane.
        shot_rel = os.path.join("screenshots", slug, f"{date}.jpg")
        shot_abs = os.path.join(storage.DOCS, shot_rel)
        os.makedirs(os.path.dirname(shot_abs), exist_ok=True)
        page.screenshot(path=shot_abs, full_page=True, type="jpeg", quality=70)
        try:
            provided_hero = page.evaluate(LARGEST_TEXT_JS)
        except Exception:
            provided_hero = None

        fields = extract_all(html, visible_text, html, categories, provided_hero,
                             known_platforms=brand.get("review_platforms"))
        colours = dominant_colours(shot_abs)

        base.update(fields)
        base["colours"] = colours
        base["screenshot"] = shot_rel
        base["status"] = "success"
        base["error"] = None

        # Optional: sample a real listing page for trading data. Never fatal --
        # a None just means no `listing` block for this brand today.
        listing = capture_listing(context, brand)
        if listing:
            base["listing"] = listing

        # Optional: scan a stockists/"where to buy" page for off-site marketplace
        # links the homepage doesn't carry, and merge (stronger state per channel
        # wins -- a stockists 'official' upgrades a homepage 'none', never the
        # reverse). Never fatal: None leaves the homepage marketplace read intact.
        stockists_mk = capture_stockists(context, brand)
        if stockists_mk:
            base["marketplace"] = merge_marketplace(base.get("marketplace"), stockists_mk)

        price = fields.get("prices", {})
        print(f"  [OK]     {brand['name']}: '{(fields.get('hero_message') or '')[:50]}' "
              f"| prices {price.get('count', 0)} (£{price.get('min')}-£{price.get('max')})")
    except Exception as exc:
        base["status"] = "failed"
        base["error"] = f"{type(exc).__name__}: {exc}"
        base["screenshot"] = None
        print(f"  [FAILED] {brand['name']}: {base['error']}")
        traceback.print_exc()
    finally:
        page.close()
    return base


def main():
    from playwright.sync_api import sync_playwright

    storage.ensure_dirs()
    config = load_config()
    brands = config["brands"]
    categories = config["product_categories"]
    date = storage.today()

    print(f"== Competitor capture {date} ({len(brands)} brands) ==")

    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        for brand in brands:
            # Fresh context per brand => no shared cache/cookies => fresh data.
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="en-GB",
                viewport={"width": 1366, "height": 900},
                extra_http_headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
            records.append(capture_brand(context, brand, categories, date))
            context.close()

        # Best-effort assortment/catalogue from product sitemaps (never fatal).
        # Reliable where shop-page scraping isn't: plain XML, served to bots.
        print("== Catalogue / assortment (best-effort) ==")
        try:
            cat_ctx = browser.new_context(user_agent=USER_AGENT, locale="en-GB")
            catalogue.build(make_sitemap_getter(cat_ctx), brands, categories, date=date)
            cat_ctx.close()
        except Exception as exc:
            print(f"  catalogue step failed (non-fatal): {type(exc).__name__}: {exc}")

        browser.close()

    # Best-effort Google Trends (never fatal).
    print("== Google Trends (best-effort) ==")
    trends = fetch_trends([b["name"] for b in brands])
    trends_path = os.path.join(storage.DATA_DIR, "trends.json")
    with open(trends_path, "w", encoding="utf-8") as fh:
        json.dump(trends, fh, indent=1, ensure_ascii=False)
    print(f"  trends ok={trends.get('ok')}")

    total = storage.append_captures(records)
    succeeded = [r for r in records if r["status"] == "success"]
    failed = [r for r in records if r["status"] == "failed"]
    storage.write_run_log({
        "date": date,
        "ran_at": storage.now_iso(),
        "brands_total": len(brands),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "failed_brands": [r["brand"] for r in failed],
        "trends_ok": trends.get("ok", False),
    })

    print(f"== Done: {len(succeeded)}/{len(brands)} succeeded, "
          f"{len(failed)} failed. Total records on file: {total} ==")
    if failed:
        print("   Failed:", ", ".join(r["brand"] for r in failed))

    # Only hard-fail if literally everything failed.
    sys.exit(0 if succeeded else 1)


if __name__ == "__main__":
    main()
