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
from urllib.parse import urlparse

from . import catalogue, storage
from .colours import dominant_colours
from .extractors import (detect_block, extract_all, extract_listing,
                         extract_marketplace_presence, merge_marketplace)
from .trends import fetch_trends

CONFIG_PATH = os.path.join(storage.ROOT, "config", "competitors.json")

# Fallback only: the real UA is derived from the RUNNING Chromium's version at
# launch (see user_agent_for), so the UA header agrees with the Sec-CH-UA
# client hints the browser actually emits -- a version mismatch there is a
# classic Cloudflare bot tell.
FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def user_agent_for(browser):
    """A Chrome UA string whose major version matches the bundled Chromium."""
    try:
        major = (browser.version or "").split(".")[0]
        if major.isdigit():
            return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
    except Exception:
        pass
    return FALLBACK_USER_AGENT


# Patch the headless tells Cloudflare's JS challenge probes, before any page
# script runs: the webdriver flag, empty plugin/language lists and the missing
# window.chrome object. Best-effort -- each patch is independent.
STEALTH_INIT_JS = """
(() => {
  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch (e) {}
  try {
    if (!navigator.plugins || navigator.plugins.length === 0) {
      Object.defineProperty(navigator, 'plugins', {
        get: () => [{ name: 'Chrome PDF Viewer' }, { name: 'Native Client' }],
      });
    }
  } catch (e) {}
  try {
    if (!navigator.languages || !navigator.languages.length) {
      Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
    }
  } catch (e) {}
  try { if (!window.chrome) window.chrome = { runtime: {} }; } catch (e) {}
})();
"""

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

# Known consent-manager accept buttons, tried before any label scan -- an exact
# CMP selector is faster and safer than text matching.
_CMP_SELECTORS = [
    "#onetrust-accept-btn-handler",                            # OneTrust
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # Cookiebot
    "#CybotCookiebotDialogBodyButtonAccept",
    ".shopify-pc__banner__btn-accept",                         # Shopify native
    "#shopify-pc__banner__btn-accept",
    "#truste-consent-button",                                  # TrustArc
    "#didomi-notice-agree-button",                             # Didomi
]

# Button labels commonly used to accept cookies / dismiss popups, lower-cased.
# "allow cookies" matters: Katie Loxton (and Joma) run a custom "WE USE COOKIES"
# modal whose button literally reads "ALLOW COOKIES" -- and it's an <a> styled
# as a button, which is why the scan below covers anchors too.
_DISMISS_LABELS = [
    "accept all cookies", "accept all", "allow all", "allow cookies",
    "accept cookies", "accept & close", "accept and close", "accept",
    "i agree", "agree", "got it", "continue", "no thanks", "close",
]

# Click a consent control inside ONE document (run per frame -- consent
# managers mount late and often live in iframes). CMP selectors first, then a
# visibility-checked label scan over buttons, role=button elements AND anchors.
_CLICK_CONSENT_JS = """
(args) => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return false;
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && cs.opacity !== '0';
  };
  for (const sel of args.selectors) {
    let el = null;
    try { el = document.querySelector(sel); } catch (e) {}
    if (el && visible(el)) { el.click(); return 'selector:' + sel; }
  }
  const cands = document.querySelectorAll('button, [role="button"], a');
  for (const el of cands) {
    const txt = (el.innerText || el.textContent || '')
      .trim().toLowerCase().replace(/\\s+/g, ' ');
    if (!txt || txt.length > 40) continue;
    for (const label of args.labels) {
      if (txt === label || (label.length > 6 && txt.includes(label))) {
        if (visible(el)) { el.click(); return 'label:' + txt; }
      }
    }
  }
  return null;
}
"""

# Answer a geo/region/shipping prompt with the UK, inside ONE document.
# Preference order: an explicit "United Kingdom" control, a <select> country
# picker, then a decline/"stay" option when the prompt defaults elsewhere.
_REGION_JS = """
() => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return false;
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && cs.opacity !== '0';
  };
  const prompt = /(shipping to|ship to|shipping country|shopping from|you are (?:visiting|shopping|browsing)|select (?:your )?(?:country|region|location)|choose (?:your )?(?:country|region|location)|looks like you|change (?:your )?(?:country|region)|delivery (?:country|destination))/;
  const boxes = [];
  for (const el of document.querySelectorAll('div,section,aside,dialog,form')) {
    const cs = getComputedStyle(el);
    const overlayish = cs.position === 'fixed' || cs.position === 'sticky'
      || parseInt(cs.zIndex || '0', 10) >= 1000;
    if (!overlayish || !visible(el)) continue;
    const txt = (el.innerText || '').toLowerCase();
    if (!txt || txt.length > 1500) continue;
    if (prompt.test(txt)) boxes.push(el);
  }
  for (const box of boxes) {
    for (const el of box.querySelectorAll('button,[role="button"],a,li')) {
      const t = (el.innerText || '').trim().toLowerCase();
      if (t && t.length < 60 && /(united kingdom|great britain|\\buk\\b)/.test(t)
          && visible(el)) { el.click(); return 'uk:' + t; }
    }
    for (const sel of box.querySelectorAll('select')) {
      for (const opt of sel.options) {
        const t = (opt.text || '').toLowerCase();
        if (/(united kingdom|great britain)/.test(t) || opt.value === 'GB') {
          sel.value = opt.value;
          sel.dispatchEvent(new Event('change', { bubbles: true }));
          const go = box.querySelector('button[type="submit"],button');
          if (go && visible(go)) go.click();
          return 'select:' + (opt.value || t);
        }
      }
    }
    for (const el of box.querySelectorAll('button,[role="button"],a')) {
      const t = (el.innerText || '').trim().toLowerCase();
      if (t && t.length < 60 && visible(el)
          && /(stay (?:on|in)|no thanks|continue (?:to|shopping|on)|keep shopping|remain)/.test(t)) {
        el.click(); return 'stay:' + t;
      }
    }
  }
  return null;
}
"""

# Scroll the page to fire IntersectionObserver lazy-loaders (bounded).
_SETTLE_SCROLL_JS = """
async () => {
  const doc = document.scrollingElement || document.documentElement;
  const step = Math.max(300, Math.round(window.innerHeight * 0.8));
  const limit = Math.min(doc ? doc.scrollHeight : 0, step * 40);
  for (let y = 0; y <= limit; y += step) {
    window.scrollTo(0, y);
    await new Promise(r => setTimeout(r, 60));
  }
}
"""

# Wait (bounded ~4s) for images to finish loading after the scroll pass.
_WAIT_IMAGES_JS = """
() => {
  const imgs = Array.from(document.images).slice(0, 200);
  return Promise.race([
    Promise.all(imgs.map(im => im.complete ? Promise.resolve()
      : new Promise(r => {
          im.addEventListener('load', r, { once: true });
          im.addEventListener('error', r, { once: true });
        }))),
    new Promise(r => setTimeout(r, 4000)),
  ]).then(() => true);
}
"""


def dismiss_overlays(page, attempts=3):
    """Best-effort consent clear. Polls EVERY frame (consent managers mount
    late, often in iframes), trying known CMP selectors first and then a
    visibility-checked label scan that includes <a> elements styled as buttons.
    Returns the matched selector/label, or None."""
    for attempt in range(attempts):
        for frame in page.frames:
            try:
                hit = frame.evaluate(_CLICK_CONSENT_JS,
                                     {"selectors": _CMP_SELECTORS, "labels": _DISMISS_LABELS})
            except Exception:
                hit = None
            if hit:
                page.wait_for_timeout(400)
                return hit
        if attempt < attempts - 1:
            page.wait_for_timeout(700)      # mounts late; poll again
    return None


def ensure_uk_region(page, attempts=2):
    """Answer a geo/region/shipping overlay with the UK, in any frame.

    Must run AFTER consent but BEFORE the generic overlay-hide sweep: the
    sweep's pattern also matches "region", so hiding first would bury the
    prompt unanswered and leave the page showing US/EUR content."""
    for attempt in range(attempts):
        for frame in page.frames:
            try:
                hit = frame.evaluate(_REGION_JS)
            except Exception:
                hit = None
            if hit:
                page.wait_for_timeout(600)
                return hit
        if attempt < attempts - 1:
            page.wait_for_timeout(600)
    return None


def hide_overlays(page):
    """Hide any leftover fixed/high-z overlays before screenshotting."""
    try:
        page.evaluate(HIDE_OVERLAYS_JS)
    except Exception:
        pass


def clear_page_chrome(page):
    """Full pre-screenshot sweep, in the order that matters: consent first,
    then the region prompt (which the hide-sweep regex would otherwise bury),
    then hide whatever overlay chrome is left."""
    dismiss_overlays(page)
    ensure_uk_region(page)
    hide_overlays(page)


def settle_before_screenshot(page):
    """Scroll the full page height to fire lazy-loaders, wait (bounded) for
    images, scroll back to top. Callers should RE-READ the DOM afterwards so
    extraction sees lazy-loaded content too."""
    try:
        page.evaluate(_SETTLE_SCROLL_JS)
        page.evaluate(_WAIT_IMAGES_JS)
    except Exception:
        pass
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
    except Exception:
        pass


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def price_rules_for(brand):
    """Per-brand price-exclusion overrides from config, for anything the
    generic add-on filter in extractors misses."""
    return {"keywords": brand.get("price_exclude_keywords") or [],
            "values": brand.get("price_exclude_values") or []}


def new_brand_context(browser, brand):
    """A fresh, stealth-patched, UK-pinned context for one brand.

    Timezone is pinned to Europe/London and Shopify Markets' localization
    cookie pre-seeded to GB -- GitHub's US-based runners otherwise get served
    USD pricing before any region prompt even appears."""
    context = browser.new_context(
        user_agent=user_agent_for(browser),
        locale="en-GB",
        timezone_id="Europe/London",
        viewport={"width": 1366, "height": 900},
        extra_http_headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    context.add_init_script(STEALTH_INIT_JS)
    try:
        host = urlparse(brand["url"]).hostname or ""
        base = host[4:] if host.startswith("www.") else host
        if base:
            context.add_cookies([{"name": "localization", "value": "GB",
                                  "domain": "." + base, "path": "/"}])
    except Exception:
        pass
    return context


def wait_out_challenge(page, html, visible_text):
    """If the page is a bot-challenge interstitial, wait ~6s for the challenge
    JS to clear and reload once. Returns (html, visible_text, block_reason);
    block_reason is None when the real page came back."""
    reason = detect_block(html, visible_text)
    if not reason:
        return html, visible_text, None
    print(f"  [challenge] waiting out: {reason}")
    try:
        page.wait_for_timeout(6000)
        page.reload(wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        html = page.content()
        visible_text = page.inner_text("body")
        reason = detect_block(html, visible_text)
    except Exception:
        pass
    return html, visible_text, reason


def make_sitemap_getter(context):
    """A getter for sitemap XML that prefers the FULL BROWSER stack.

    Many Shopify/Cloudflare-protected stores (Katie Loxton, Charles & Keith, Oliver Bonas...)
    serve a 403/challenge to a header-light HTTP request but pass the real
    rendered browser -- exactly the path the homepage capture already clears. So
    we navigate to the sitemap with `page.goto` and read the raw *response body*
    (`response.text()` is the network payload, not the rendered XML tree), which
    returns genuine XML when the challenge is cleared. We accept the body only if
    it actually looks like a sitemap; otherwise (and on any error) we fall back to
    the plain request API, which still works for permissive hosts. If everything
    fails we wait out a possible challenge (~6s, same as the homepage capture)
    and retry the browser path once. Best-effort: returns None when nothing
    yields a real sitemap, so the brand is honestly logged as having no readable
    sitemap. IMPORTANT: pass the SAME context that already cleared this brand's
    challenge -- clearance sticks to the session, not just the cookie jar."""
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
            resp = context.request.get(url, timeout=30000)
            if resp.ok:
                body = resp.text()
                if catalogue.looks_like_sitemap(body):
                    return body
        except Exception:
            pass
        return None

    def get(url):
        body = _via_browser(url) or _via_request(url)
        if body:
            return body
        # Possibly a challenge page: give the session ~6s to clear, retry once.
        page = context.new_page()
        try:
            page.wait_for_timeout(6000)
        except Exception:
            pass
        finally:
            page.close()
        return _via_browser(url)
    return get


def make_text_getter(context):
    """Raw text fetch (for robots.txt) through the same cleared session."""
    def get_text(url):
        page = context.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
            if resp and resp.ok:
                return resp.text()
        except Exception:
            pass
        finally:
            page.close()
        return None
    return get_text


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
        clear_page_chrome(page)
        html = page.content()
        visible_text = page.inner_text("body")
        if detect_block(html, visible_text):
            print(f"  [listing blocked] {brand['name']}")
            return None
        listing = extract_listing(html, visible_text, price_rules_for(brand))
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
        clear_page_chrome(page)
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


MOBILE_VIEWPORT = {"width": 390, "height": 844}   # iPhone-class CSS viewport
MOBILE_MAX_SCREENS = 25                            # cap the full-page scroll


def capture_mobile_screenshot(context, brand, date):
    """A second, phone-rendered full-page screenshot per brand.

    Uses CDP Emulation.setDeviceMetricsOverride with mobile:true for REAL phone
    rendering (device pixel ratio, <meta viewport> honoured, touch emulation),
    falling back to a plain viewport resize when CDP isn't available. Reuses
    the already-cleared/consented desktop session rather than a fresh mobile
    context, so it doesn't re-trigger the Cloudflare challenge or the consent
    modal. Non-fatal by design: a missing mobile shot for a day is NOT a failed
    capture. Returns the relative screenshot path, or None."""
    slug = brand["slug"]
    rel = os.path.join("screenshots", slug, f"{date}-mobile.jpg")
    abs_path = os.path.join(storage.DOCS, rel)
    page = context.new_page()
    try:
        try:
            cdp = context.new_cdp_session(page)
            cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": MOBILE_VIEWPORT["width"], "height": MOBILE_VIEWPORT["height"],
                "deviceScaleFactor": 2, "mobile": True,
            })
            cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True})
        except Exception:
            page.set_viewport_size(MOBILE_VIEWPORT)
        page.goto(brand["url"], wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        clear_page_chrome(page)
        html = page.content()
        visible_text = page.inner_text("body")
        if detect_block(html, visible_text):
            print(f"  [mobile blocked]  {brand['name']}")
            return None
        settle_before_screenshot(page)
        hide_overlays(page)                 # sweep scroll-triggered popups
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        cap_px = MOBILE_VIEWPORT["height"] * MOBILE_MAX_SCREENS
        try:
            height = page.evaluate(
                "() => (document.scrollingElement || document.documentElement).scrollHeight")
        except Exception:
            height = None
        if height and height > cap_px:
            page.screenshot(path=abs_path, type="jpeg", quality=60,
                            clip={"x": 0, "y": 0,
                                  "width": MOBILE_VIEWPORT["width"], "height": cap_px})
        else:
            page.screenshot(path=abs_path, full_page=True, type="jpeg", quality=60)
        print(f"  [mobile OK]       {brand['name']}")
        return rel
    except Exception as exc:
        print(f"  [mobile skipped]  {brand['name']}: {type(exc).__name__}: {exc}")
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
        dismiss_overlays(page)              # consent first...
        ensure_uk_region(page)              # ...then answer any region prompt...
        hide_overlays(page)                 # ...then sweep leftover overlays
        page.wait_for_timeout(500)

        html = page.content()
        visible_text = page.inner_text("body")

        # If we got a bot-challenge/interstitial (e.g. Cloudflare "Just a
        # moment...") wait it out and reload once; if it STILL blocks, record an
        # HONEST failure rather than polluting the data with junk.
        html, visible_text, block_reason = wait_out_challenge(page, html, visible_text)
        if block_reason:
            base["status"] = "failed"
            base["error"] = block_reason
            base["screenshot"] = None
            print(f"  [BLOCKED] {brand['name']}: {block_reason}")
            return base
        clear_page_chrome(page)             # the reload may have re-raised chrome

        # Fire lazy-loaders and let images land, THEN re-read the DOM so
        # extraction sees lazy-loaded content too; sweep any scroll-triggered
        # popups before the shot.
        settle_before_screenshot(page)
        hide_overlays(page)
        html = page.content()
        visible_text = page.inner_text("body")

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
                             known_platforms=brand.get("review_platforms"),
                             price_rules=price_rules_for(brand))
        colours = dominant_colours(shot_abs)

        base.update(fields)
        base["colours"] = colours
        base["screenshot"] = shot_rel
        base["status"] = "success"
        base["error"] = None

        # Optional second shot at a phone viewport (never fatal).
        base["screenshot_mobile"] = capture_mobile_screenshot(context, brand, date)

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
    cat_results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        for brand in brands:
            # Fresh context per brand => no shared cache/cookies => fresh data.
            context = new_brand_context(browser, brand)
            records.append(capture_brand(context, brand, categories, date))
            # Walk this brand's product sitemaps INSIDE the same context that
            # just cleared its challenge -- Cloudflare clearance sticks to the
            # browsing session, not just the cookie jar, so a fresh context
            # would hit the challenge all over again.
            try:
                cat_results[brand["slug"]] = catalogue.collect(
                    make_sitemap_getter(context), brand["url"],
                    get_text=make_text_getter(context))
            except Exception as exc:
                cat_results[brand["slug"]] = {
                    "ok": False, "product_count": 0, "handles": [],
                    "sitemaps_used": [], "error": f"{type(exc).__name__}: {exc}"}
            context.close()
        browser.close()

    # Best-effort assortment/catalogue from the per-brand sitemap walks above.
    print("== Catalogue / assortment (best-effort) ==")
    try:
        catalogue.build_from_results(cat_results, brands, categories, date=date)
    except Exception as exc:
        print(f"  catalogue step failed (non-fatal): {type(exc).__name__}: {exc}")

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
