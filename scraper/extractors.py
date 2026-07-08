"""
Rules-based extraction of trading-relevant fields from a homepage.

IMPORTANT (honesty note): these are heuristics, not magic. They are deliberately
written to DEGRADE GRACEFULLY -- if a field can't be found we return an empty
value rather than guessing. Every function is pure (html string in, data out),
so they can be unit-tested offline without a browser or network. When a
competitor redesigns their site, the regexes here are the most likely thing to
need a tweak. That is the trade-off for running with no paid AI extraction.
"""

import re
from collections import Counter
from urllib.parse import urljoin

from bs4 import BeautifulSoup
# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_OFFER_PATTERNS = [
    r"up to\s*\d{1,3}\s*%\s*off",
    r"\d{1,3}\s*%\s*off",
    r"extra\s*\d{1,3}\s*%",
    r"summer sale", r"winter sale", r"spring sale", r"autumn sale",
    r"mid[- ]?season sale", r"end of season sale", r"flash sale",
    r"black friday", r"cyber monday", r"clearance", r"outlet",
    r"\bsale\b",
    r"buy one get one", r"\bbogof\b", r"\b\d for [£$€]?\d+\b",
    r"free gift", r"gift with purchase", r"free .{0,15} when you spend",
]

_DELIVERY_PATTERNS = [
    r"next day delivery",
    r"free (?:uk )?(?:next day |standard |express )?(?:delivery|shipping)(?: over\s*[£$€]?\s*\d+)?",
    r"free (?:delivery|shipping) (?:on orders )?over\s*[£$€]?\s*\d+",
    r"order (?:by|before)\s*\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)",
    r"delivery (?:in )?\d+\s*[-–to]+\s*\d+\s*(?:working )?days",
    r"same day delivery",
    r"click (?:&|and) collect",
]

# Codes are matched against ORIGINAL-CASE text (codes are usually upper-case).
_CODE_PATTERNS = [
    r"use code[:\s]+([A-Z0-9]{3,15})",
    r"with code[:\s]+([A-Z0-9]{3,15})",
    r"discount code[:\s]+([A-Z0-9]{3,15})",
    r"\bcode[:\s]+([A-Z][A-Z0-9]{2,14})\b",
]

# Common words to ignore when working out trending keywords.
_STOPWORDS = set("""
a an the and or but for nor so yet of to in on at by with from up out off over under
is are was were be been being am do does did have has had will would can could should
this that these those it its their your you we our us my mi me he she they them his her
new shop now all more your gift gifts free uk see view here home menu cart bag account
search login sign back next add to set buy get use code about how what when where why
""".split())

_MONEY = r"[£$€]?\s*\d{1,4}(?:[.,]\d{2})?"

# ---------------------------------------------------------------------------
# Bot-challenge / interstitial detection
# ---------------------------------------------------------------------------
# Cloudflare (and friends) sometimes serve a "Just a moment..." JavaScript
# challenge instead of the real homepage -- especially to well-known datacenter
# IPs like GitHub Actions runners. That page renders a few words ("Checking your
# browser", "Enable JavaScript and cookies") and NO real content, so if we store
# it as a successful capture it pollutes keywords/SEO/colours with junk. We
# detect it here so capture.py can record an honest FAILED status (a visible gap)
# instead. These are high-precision signals chosen to avoid flagging real pages.
_BLOCK_TITLE_PATTERNS = [
    r"just a moment",
    r"attention required",
    r"checking your browser",
    r"checking if the site connection is secure",
    r"verifying you are human",
    r"are you (?:a )?(?:human|robot)",
    r"access (?:to this page )?(?:has been )?denied",
    r"please wait while we verify",
]
# Substrings that only appear on challenge / anti-bot interstitials.
_BLOCK_HTML_MARKERS = [
    "/cdn-cgi/challenge-platform/",   # Cloudflare challenge bootstrap
    "cf-mitigated",
    "_cf_chl_opt", "__cf_chl_", "cf_chl_",
    "enable javascript and cookies to continue",
    "px-captcha", "_pxhd",            # PerimeterX / HUMAN
    "_incapsula_", "incap_ses",       # Imperva Incapsula
    "request unsuccessful. incapsula incident",
]


def detect_block(html, visible_text=""):
    """Return a short reason string if the captured page looks like a bot
    challenge / interstitial rather than the real homepage, else None.

    Pure function (string in, string/None out) so it can be unit-tested offline.
    """
    low_html = (html or "").lower()

    m = re.search(r"<title[^>]*>(.*?)</title>", low_html, re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    for pat in _BLOCK_TITLE_PATTERNS:
        if re.search(pat, title):
            return f"blocked: bot-challenge page (title: {title[:60]!r})"

    for marker in _BLOCK_HTML_MARKERS:
        if marker in low_html:
            return f"blocked: bot-challenge page (marker: {marker!r})"

    return None


def _text_lower(visible_text):
    return re.sub(r"\s+", " ", (visible_text or "")).lower().strip()


# Alt/aria text that is clearly chrome, not a hero banner -- skip it so a logo or
# payment icon never becomes the headline.
_BANNER_SKIP = re.compile(
    r"logo|icon|payment|visa|mastercard|amex|paypal|klarna|clearpay|apple ?pay|"
    r"google ?pay|social|instagram|facebook|tiktok|pinterest|youtube|twitter|"
    r"trustpilot|review|star rating|avatar|thumbnail|swatch|placeholder|spinner|"
    r"loading|menu|search|basket|cart|wishlist|account",
    re.I,
)


def _collect_banner_text(html):
    """Hero/offer copy that lives in IMAGES, invisible to visible-text scraping.

    Big homepage banners routinely render their headline ("Up to 50% off summer
    sale") inside a JPEG, with the words only available as the image's `alt`,
    an `aria-label`, or a link/image `title`. The largest-visible-text heuristic
    in capture.py can't see those, so we recover them here from the captured
    HTML. Obvious chrome (logos, payment icons, social links) is filtered out.
    """
    soup = BeautifulSoup(html or "", "lxml")
    out = []

    def add(s):
        s = re.sub(r"\s+", " ", (s or "")).strip()
        if 6 <= len(s) <= 160 and re.search(r"[a-zA-Z]", s) \
                and not _BANNER_SKIP.search(s) and s not in out:
            out.append(s)

    for img in soup.find_all("img"):
        add(img.get("alt"))
        add(img.get("title"))
    for el in soup.find_all(attrs={"aria-label": True}):
        add(el.get("aria-label"))
    for el in soup.find_all(attrs={"role": "img"}):
        add(el.get("aria-label"))
    for a in soup.find_all("a"):
        add(a.get("title"))
        if a.find("img"):                       # image links are where hero banners live
            add(_url_offer_text(a.get("href")))
    for img in soup.find_all("img"):            # offer copy can hide in the filename
        add(_url_offer_text(img.get("src")))
        add(_url_offer_text(img.get("data-src")))   # lazy-loaded banners
    return out[:30]


def _offer_strength(s):
    """Rough 'how loud is this promo' score: biggest % off, else a sale keyword."""
    s = (s or "").lower()
    pcts = [int(p) for p in re.findall(r"(\d{1,3})\s*%", s) if int(p) <= 90]
    if pcts:
        return max(pcts)
    if re.search(r"\b(sale|clearance|outlet|black friday|cyber monday)\b", s):
        return 5  # a worded sale beats a non-offer hero, loses to any explicit %
    return 0


# Sale/season context that justifies reading a bare 'N off' in a URL as a %.
_SALE_HINT = re.compile(
    r"\b(sale|clearance|outlet|black ?friday|cyber ?monday|summer|winter|spring|"
    r"autumn|festive|mid[- ]?season|flash|discount|save|offer|deal)\b",
    re.I,
)


def _url_offer_text(url):
    """Recover offer copy baked into a link `href` or image filename.

    Some homepages carry a hero sale banner that is an *alt-less* image wrapped
    in a link to a slug like `/summer-sale-50-off` (with an img src like
    `.../summer-sale-50-off.jpg`).
    The alt/aria recovery in _collect_banner_text can't see those, so we turn the
    slug into words. URLs are noisy, so we are deliberately strict: we only
    surface the text when a sale/season word is present, and only then read a
    bare `50 off` (or `50 percent off`) as `50% off`. This keeps a product slug
    like `20-off-shoulder-top` from being misread as a 20% discount.
    """
    if not url:
        return None
    path = re.split(r"[?#]", url)[0]                          # drop query/fragment
    path = re.sub(r"^[a-z][\w+.-]*://[^/]+", "", path, flags=re.I)  # drop scheme + host
    path = re.sub(r"\.(jpe?g|png|webp|gif|svg|avif)$", "", path, flags=re.I)  # drop ext
    words = re.sub(r"[^a-z0-9]+", " ", path, flags=re.I).strip().lower()
    if not words or not _SALE_HINT.search(words):
        return None
    words = re.sub(r"\b(\d{1,3})\s*(?:percent|pct)?\s*off\b", r"\1% off", words)
    words = re.sub(r"\s+", " ", words).strip()
    return words if _offer_strength(words) > 0 else None


def extract_offers(visible_text, extra_texts=None):
    """Return {offers:[...], headline_offer:str|None, max_discount_pct:int|None}.

    `extra_texts` lets callers fold in copy that isn't in the visible body --
    chiefly banner image alt/aria text (see _collect_banner_text) -- so an
    image-baked "up to 50% off" is caught instead of a smaller live offer.
    """
    combined = " ".join([visible_text or ""] + list(extra_texts or []))
    text = _text_lower(combined)
    found = []
    for pat in _OFFER_PATTERNS:
        for m in re.finditer(pat, text):
            phrase = m.group(0).strip()
            if phrase not in found:
                found.append(phrase)

    # Strongest discount percentage seen anywhere.
    pcts = [int(p) for p in re.findall(r"(\d{1,3})\s*%", text) if int(p) <= 90]
    max_pct = max(pcts) if pcts else None

    headline = None
    # Prefer an explicit "up to N% off", else the biggest %, else first offer.
    up_to = [f for f in found if f.startswith("up to")]
    if up_to:
        headline = up_to[0]
    elif max_pct is not None:
        headline = f"{max_pct}% off"
    elif found:
        headline = found[0]

    return {
        "offers": found[:12],
        "headline_offer": headline,
        "max_discount_pct": max_pct,
    }


def extract_delivery(visible_text):
    """Return a de-duplicated list of delivery/shipping promises."""
    text = _text_lower(visible_text)
    found = []
    for pat in _DELIVERY_PATTERNS:
        for m in re.finditer(pat, text):
            phrase = re.sub(r"\s+", " ", m.group(0)).strip()
            if phrase not in found:
                found.append(phrase)
    return found[:8]


def extract_discount_codes(raw_text):
    """Return distinct voucher/affiliate-style codes (matched in original case)."""
    codes = []
    for pat in _CODE_PATTERNS:
        for m in re.finditer(pat, raw_text):
            code = m.group(1)
            # Filter obvious false positives.
            if code.upper() in {"HTTPS", "HTML", "CODE", "THE"}:
                continue
            if code not in codes:
                codes.append(code)
    return codes[:8]


def extract_product_mix(visible_text, categories):
    """Count category keyword hits and turn into share-of-mentions."""
    text = _text_lower(visible_text)
    counts = {}
    for cat, keywords in categories.items():
        n = 0
        for kw in keywords:
            n += len(re.findall(r"\b" + re.escape(kw.lower()), text))
        if n:
            counts[cat] = n
    total = sum(counts.values()) or 1
    mix = {
        cat: {"count": n, "share": round(n / total, 4)}
        for cat, n in sorted(counts.items(), key=lambda kv: -kv[1])
    }
    return mix


def extract_keywords(visible_text, top_n=20):
    """Most frequent meaningful words on the page (cheap 'keyword trend' signal)."""
    text = _text_lower(visible_text)
    words = re.findall(r"[a-z][a-z'’]{2,}", text)
    words = [w for w in words if w not in _STOPWORDS]
    common = Counter(words).most_common(top_n)
    return [[w, c] for w, c in common]


def extract_seo(html):
    """Pull SEO-relevant metadata from raw HTML."""
    soup = BeautifulSoup(html or "", "lxml")

    def meta(name=None, prop=None):
        if name:
            tag = soup.find("meta", attrs={"name": name})
        else:
            tag = soup.find("meta", attrs={"property": prop})
        return (tag.get("content") or "").strip() if tag else None

    title = (soup.title.string.strip() if soup.title and soup.title.string else None)
    h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
    h2_count = len(soup.find_all("h2"))

    canonical_tag = soup.find("link", rel="canonical")
    canonical = canonical_tag.get("href") if canonical_tag else None

    jsonld_types = []
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = s.string or s.get_text() or ""
        for t in re.findall(r'"@type"\s*:\s*"([^"]+)"', raw):
            if t not in jsonld_types:
                jsonld_types.append(t)

    body_text = soup.get_text(" ", strip=True)
    word_count = len(body_text.split())

    return {
        "title": title,
        "title_length": len(title) if title else 0,
        "meta_description": meta(name="description"),
        "meta_description_length": len(meta(name="description") or ""),
        "og_title": meta(prop="og:title"),
        "og_image": meta(prop="og:image"),
        "h1": h1s[:5],
        "h1_count": len(h1s),
        "h2_count": h2_count,
        "canonical": canonical,
        "structured_data_types": jsonld_types[:12],
        "word_count": word_count,
        "image_count": len(soup.find_all("img")),
        "internal_link_count": len(soup.find_all("a")),
    }


def _link_has_name(a):
    """A link is 'accessible' if it has visible text, an aria-label/title, or
    wraps an image with alt text."""
    if a.get_text(strip=True):
        return True
    if (a.get("aria-label") or "").strip() or (a.get("title") or "").strip():
        return True
    img = a.find("img")
    if img is not None and (img.get("alt") or "").strip():
        return True
    return False


def extract_accessibility(html):
    """Rules-based, 'Lighthouse-lite' accessibility audit of the homepage HTML.

    HONESTY NOTE: this is NOT a full WCAG audit. It checks a handful of common,
    high-signal issues that can be reliably detected from static HTML (alt text,
    page language, labels, landmarks, heading structure...). It cannot judge
    colour contrast, keyboard traps, focus order or anything requiring a live
    render. Treat the 0-100 score as a cheap directional signal, not a
    compliance grade. Each check degrades gracefully: a category with no
    applicable elements (e.g. a page with no forms) is treated as passing
    rather than penalised.
    """
    soup = BeautifulSoup(html or "", "lxml")
    checks = []

    def add(cid, label, weight, ratio, detail, applicable=True):
        ratio = max(0.0, min(1.0, float(ratio)))
        checks.append({
            "id": cid, "label": label, "weight": weight,
            "ratio": round(ratio, 3), "passed": ratio >= 0.9,
            "applicable": applicable, "detail": detail,
        })

    # 1. Page language declared.
    html_tag = soup.find("html")
    lang = ((html_tag.get("lang") if html_tag else "") or "").strip()
    add("html_lang", "Page language declared (<html lang>)", 10,
        1.0 if lang else 0.0, f'lang="{lang}"' if lang else "missing lang attribute")

    # 2. Document title.
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    add("doc_title", "Document has a <title>", 8,
        1.0 if title else 0.0, title or "missing title")

    # 3. Responsive viewport.
    vp = soup.find("meta", attrs={"name": "viewport"})
    add("viewport", "Responsive viewport meta tag", 6,
        1.0 if vp else 0.0, "present" if vp else "missing")

    # 4. Images have alt attributes (alt="" is valid for decorative images).
    imgs = soup.find_all("img")
    with_alt = [i for i in imgs if i.has_attr("alt")]
    ratio = len(with_alt) / len(imgs) if imgs else 1.0
    add("img_alt", "Images have alt attributes", 20, ratio,
        f"{len(with_alt)}/{len(imgs)} images" if imgs else "no images on page",
        applicable=bool(imgs))

    # 5. Links have discernible text.
    links = [a for a in soup.find_all("a") if a.get("href")]
    good_links = [a for a in links if _link_has_name(a)]
    ratio = len(good_links) / len(links) if links else 1.0
    add("link_text", "Links have discernible text", 15, ratio,
        f"{len(good_links)}/{len(links)} links" if links else "no links",
        applicable=bool(links))

    # 6. Buttons have accessible names.
    btns = list(soup.find_all("button"))
    for inp in soup.find_all("input"):
        if (inp.get("type") or "").lower() in ("submit", "button"):
            btns.append(inp)

    def btn_named(b):
        if b.name == "button":
            return bool(b.get_text(strip=True) or (b.get("aria-label") or "").strip()
                        or (b.get("title") or "").strip())
        return bool((b.get("value") or "").strip() or (b.get("aria-label") or "").strip())

    good_btn = [b for b in btns if btn_named(b)]
    ratio = len(good_btn) / len(btns) if btns else 1.0
    add("button_name", "Buttons have accessible names", 8, ratio,
        f"{len(good_btn)}/{len(btns)} buttons" if btns else "no buttons",
        applicable=bool(btns))

    # 7. Form fields have labels.
    fields = []
    for inp in soup.find_all("input"):
        if (inp.get("type") or "text").lower() in (
                "hidden", "submit", "button", "image", "reset"):
            continue
        fields.append(inp)
    fields += soup.find_all(["select", "textarea"])
    label_for = {l.get("for") for l in soup.find_all("label") if l.get("for")}

    def field_labelled(f):
        if (f.get("aria-label") or "").strip() or f.get("aria-labelledby"):
            return True
        fid = f.get("id")
        if fid and fid in label_for:
            return True
        if f.find_parent("label") is not None:
            return True
        return bool((f.get("title") or "").strip())

    good_fields = [f for f in fields if field_labelled(f)]
    ratio = len(good_fields) / len(fields) if fields else 1.0
    add("form_labels", "Form fields have labels", 8, ratio,
        f"{len(good_fields)}/{len(fields)} fields" if fields else "no form fields",
        applicable=bool(fields))

    # 8. Heading structure (ideally exactly one H1).
    h1s = soup.find_all("h1")
    any_heading = soup.find(["h1", "h2", "h3"]) is not None
    if len(h1s) == 1 and any_heading:
        h_ratio, h_detail = 1.0, "exactly one <h1>"
    elif any_heading:
        h_ratio, h_detail = 0.5, f"{len(h1s)} <h1> tags"
    else:
        h_ratio, h_detail = 0.0, "no headings found"
    add("headings", "Clear heading structure (single H1)", 10, h_ratio, h_detail)

    # 9. Landmark regions.
    has_main = soup.find("main") or soup.find(attrs={"role": "main"})
    has_nav = soup.find("nav") or soup.find(attrs={"role": "navigation"})
    present = " + ".join([n for n, ok in (("main", has_main), ("nav", has_nav)) if ok])
    add("landmarks", "Landmark regions (main, nav)", 8,
        ((1 if has_main else 0) + (1 if has_nav else 0)) / 2.0,
        present or "no landmarks")

    # 10. Skip-to-content link.
    skip = None
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("#") and "skip" in a.get_text(strip=True).lower():
            skip = a
            break
    add("skip_link", "Skip-to-content link", 3,
        1.0 if skip else 0.0, "present" if skip else "none found")

    total_w = sum(c["weight"] for c in checks)
    earned = sum(c["weight"] * c["ratio"] for c in checks)
    score = round(earned / total_w * 100) if total_w else 0
    grade = ("A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70
             else "D" if score >= 60 else "E" if score >= 50 else "F")

    return {
        "score": score,
        "grade": grade,
        "checks": checks,
        "images_total": len(imgs),
        "images_with_alt": len(with_alt),
        "links_total": len(links),
        "links_with_text": len(good_links),
    }


def extract_hero(html, provided_hero=None):
    """Best guess at the hero/headline message.

    `provided_hero` is the largest visible text on screen, computed in the
    browser (see capture.py) -- that is the most reliable signal. We fall back
    to the first H1, then og:title, then <title>.

    Split-banner fix: when a site's primary panel is a *sale image* and the
    secondary panel is live text (e.g. an "Up to 50% Off Summer Sale" banner image
    next to a smaller live-text promo panel), the largest-visible-text rule
    picks the text panel and misses the sale entirely. So if a *banner image's*
    alt/aria copy advertises a stronger offer than the baseline hero, we surface
    that instead. This is scoped to image-sourced text only -- H1/og:title were
    already visible to the largest-text heuristic, so we don't second-guess them.
    """
    soup = BeautifulSoup(html or "", "lxml")

    base = None
    if provided_hero and provided_hero.strip():
        base = provided_hero.strip()
    else:
        h1 = soup.find("h1")
        og = soup.find("meta", attrs={"property": "og:title"})
        if h1 and h1.get_text(strip=True):
            base = h1.get_text(strip=True)
        elif og and og.get("content"):
            base = og["content"].strip()
        elif soup.title and soup.title.string:
            base = soup.title.string.strip()

    banner = _collect_banner_text(html)
    if banner:
        loudest = max(banner, key=_offer_strength)
        if _offer_strength(loudest) > _offer_strength(base or ""):
            return loudest[:300]

    return base[:300] if base else None


# ---------------------------------------------------------------------------
# Price sense-checking — keep add-on items out of the floor price
# ---------------------------------------------------------------------------
# Non-standalone add-ons (a £1.50 photo card, £2 gift wrap, an e-gift top-up)
# were dragging brands' entry/floor prices to near-zero, so any price whose
# nearby product title/copy matches one of these is excluded from the scan.
# Deliberately conservative: real product words ("pouch" is a real Katie
# Loxton line) stay OUT of the generic list — brands with an oddball add-on
# the generic filter misses declare per-brand `price_exclude_keywords` /
# `price_exclude_values` in config/competitors.json instead.
_ADDON_PRICE_KEYWORDS = [
    "photo card", "photocard", "gift wrap", "gift-wrap", "gift wrapping",
    "e-gift", "egift", "gift card", "giftcard", "gift note", "gift tag",
    "greeting card", "donation",
]

_TITLE_NEAR_RE = re.compile(r'"(?:title|name)"\s*:\s*"([^"]{1,120})"')


def _price_exclusion(brand_rules=None):
    """Merged exclusion rules: the generic add-on list plus any per-brand
    overrides from config. Returns (keywords_lowered, values_set)."""
    rules = brand_rules or {}
    kws = [k.lower() for k in _ADDON_PRICE_KEYWORDS + list(rules.get("keywords") or [])]
    vals = {round(float(v), 2) for v in (rules.get("values") or [])}
    return kws, vals


def _structured_excluded(html, start, keywords):
    """Does the JSON price match at `start` belong to an add-on product?

    Product JSON blobs keep the title within a few hundred chars of the price,
    so we take the NEAREST preceding "title"/"name" string (falling forward
    when the price comes first) — the nearest one is this product's; scanning
    a whole window would wrongly pick up neighbouring blobs' titles."""
    back = (html or "")[max(0, start - 300):start]
    title = None
    for m in _TITLE_NEAR_RE.finditer(back):
        title = m.group(1)                    # keep the last (nearest) one
    if title is None:
        m = _TITLE_NEAR_RE.search((html or "")[start:start + 300])
        if m:
            title = m.group(1)
    if title is None:
        return False
    t = title.lower()
    return any(kw in t for kw in keywords)


def _visible_excluded(text, start, prev_end, keywords):
    """Is the visible '£' amount at `start` labelled with add-on copy?

    The window is this price's own label only: it stops at the previous price
    match and at line breaks, so 'Gift wrap £2.00' can't bleed into the next
    product's price on the same line."""
    lo = max(0, start - 80, prev_end)
    window = (text or "")[lo:start]
    nl = max(window.rfind("\n"), window.rfind("\r"))
    if nl >= 0:
        window = window[nl + 1:]
    window = window.lower()
    return any(kw in window for kw in keywords)


def _scan_structured_prices(html, keywords, values):
    """Embedded-JSON prices, minus excluded values and add-on-titled blobs."""
    prices = []
    for m in re.finditer(r'"price"\s*:\s*"?(\d{1,5}(?:\.\d{1,2})?)"?', html or ""):
        try:
            p = round(float(m.group(1)), 2)
        except ValueError:
            continue
        if p in values or _structured_excluded(html, m.start(), keywords):
            continue
        prices.append(p)
    return prices


def _scan_visible_prices(text, keywords, values):
    """Visible '£' amounts, minus excluded values and add-on-labelled lines."""
    prices = []
    prev_end = 0
    for m in re.finditer(r"£\s?(\d{1,4}(?:\.\d{2})?)", text or ""):
        start, prev = m.start(), prev_end
        prev_end = m.end()
        try:
            p = round(float(m.group(1)), 2)
        except ValueError:
            continue
        if p in values or _visible_excluded(text, start, prev, keywords):
            continue
        prices.append(p)
    return prices


def scan_prices(html, visible_text, brand_rules=None):
    """All plausible product prices on a page, with add-on items filtered out.

    Returns the raw list (unsorted, unbounded) so callers can summarise. Pure
    and offline-testable. `brand_rules` is {"keywords": [...], "values": [...]}
    from a brand's config overrides."""
    keywords, values = _price_exclusion(brand_rules)
    # Structured data is the trustworthy source; fall back to visible amounts.
    prices = _scan_structured_prices(html, keywords, values)
    if len(prices) < 4:
        prices += _scan_visible_prices(visible_text, keywords, values)
    return prices


def extract_prices(html, visible_text, brand_rules=None):
    """Rough price-point sampling.

    Honesty note: a homepage isn't a price list, so this is APPROXIMATE. We
    prefer structured data (JSON-LD Product/Offer prices, which are reliable),
    and fall back to scanning visible '£' amounts. We drop implausible values,
    add-on items (see scan_prices) and obvious noise, so treat min/median/max
    as a price *band*, not gospel; the listing-page sample is the real read.
    """
    prices = scan_prices(html, visible_text, brand_rules)

    # Keep plausible product prices only.
    prices = sorted(p for p in prices if 1 <= p <= 2000)
    if not prices:
        return {"count": 0, "currency": "GBP", "min": None,
                "median": None, "max": None, "sample": []}

    n = len(prices)
    median = prices[n // 2] if n % 2 else round((prices[n // 2 - 1] + prices[n // 2]) / 2, 2)
    return {
        "count": n,
        "currency": "GBP",
        "min": prices[0],
        "median": median,
        "max": prices[-1],
        "sample": prices[:30],
    }


# ---------------------------------------------------------------------------
# Trading signals (homepage) — conversion levers a merchandiser actually acts on
# ---------------------------------------------------------------------------
# These read straight from the homepage HTML/visible text we ALREADY fetch, so
# they add no extra network call and no new failure mode. BNPL widgets, payment
# wallets and email-capture popups all leave reliable fingerprints in the markup.
_FINANCE_PATTERNS = {
    # name -> regex (matched against lowercased html+visible text)
    "Klarna":     r"klarna",
    "Clearpay":   r"clearpay",
    "Laybuy":     r"laybuy",
    "Afterpay":   r"afterpay",
    "PayPal":     r"paypal",
    "Apple Pay":  r"apple ?pay",
    "Google Pay": r"google ?pay",
    "Amazon Pay": r"amazon ?pay",
}
# The BNPL ("buy now, pay later") subset — the genuine conversion lever in this
# category, as opposed to wallets which are table stakes.
_BNPL_PROVIDERS = {"Klarna", "Clearpay", "Laybuy", "Afterpay"}

_SCARCITY_PATTERNS = [
    r"low (?:in )?stock",
    r"selling fast",
    r"almost gone",
    r"nearly sold out",
    r"only \d+ left",
    r"back in stock",
    r"limited stock",
    r"while stocks last",
]

# Countdown / urgency copy — a sale with a clock on it converts differently
# from an open-ended one, and "ends midnight" says the competitor expects a
# demand spike now, not eventually.
_URGENCY_PATTERNS = [
    r"ends (?:at )?midnight",
    r"ends (?:to)?night",
    r"ends (?:this )?(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday|weekend|today|tomorrow)",
    r"ends in \d+",
    r"ends soon",
    r"last (?:chance|day|few days)",
    r"final (?:hours?|day|reductions?)",
    r"today only",
    r"\d+ ?(?:hours?|hrs) (?:left|only|to go)",
    r"limited time(?: only)?",
    r"don'?t miss out",
    r"hurry\b",
]

# Bundle / multi-buy offers ("3 for 2", "2 for £30", "buy 2 save 10%").
_MULTIBUY_PATTERNS = [
    r"\b\d ?for ?\d\b",
    r"\b\d ?for ?[£$€] ?\d+\b",
    r"buy \d,? (?:get|save)[^.!?]{0,25}",
    r"buy one,? get one[^.!?]{0,20}",
    r"\bbogof\b",
    r"multi[- ]?buy",
    r"\bbundle (?:and save|offer|deal)s?\b",
    r"save (?:£ ?\d+|\d{1,2} ?%) when you buy \d",
]

_GWP_PATTERNS = [
    r"free gift with (?:your )?(?:purchase|order)",
    r"gift with purchase",
    r"free [^.!?]{0,30}when you (?:spend|buy|purchase)",
    r"complimentary [^.!?]{0,30}when you (?:spend|buy|purchase)",
]

_LOYALTY_PATTERNS = [
    r"loyalty (?:scheme|programme|program|points|club)",
    r"rewards? (?:club|scheme|programme|program)\b",
    r"earn points",
    r"\bvip (?:club|list|access|members?)\b",
    r"refer a friend",
]

_PERSONALISATION_UPSELL_PATTERNS = [
    r"free personalis(?:ation|ing)",
    r"free personaliz(?:ation|ing)",
    r"free engraving",
    r"add (?:a )?(?:monogram|initials?|engraving)",
    r"personalise (?:it|yours|your)",
    r"personalize (?:it|yours|your)",
    r"make it (?:yours|personal)",
]

# SMS capture: platform fingerprints in markup, or explicit sign-up copy.
_SMS_MARKERS = r"attentivemobile|attentive\.com|postscript\.io|smsbump"
_SMS_COPY = (r"(?:sign up|subscribe|join)[^.!?]{0,50}\b(?:sms|texts?)\b"
             r"|\b(?:sms|texts?)\b[^.!?]{0,50}(?:sign up|subscribe|updates|offers)")

# Live-chat widgets leave reliable fingerprints in the markup. Patterns are
# host/asset-specific so ordinary copy can't false-positive a platform.
_CHAT_PLATFORMS = {
    "Gorgias":  r"gorgias",
    "Zendesk":  r"zdassets|zendesk",
    "Intercom": r"intercom",
    "Tidio":    r"tidio",
    "LiveChat": r"livechatinc|livechat\.com",
    "Tawk":     r"tawk\.to",
    "Kustomer": r"kustomer",
    "HubSpot":  r"hs-chat|hubspot-messages",
}
_CHAT_COPY = r"\blive ?chat\b|chat (?:with|to) us"


def _find_phrases(text, patterns, limit=6):
    """De-duplicated matches of `patterns` over already-lowered text."""
    found = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            phrase = re.sub(r"\s+", " ", m.group(0)).strip()
            if phrase and phrase not in found:
                found.append(phrase)
    return found[:limit]


def _first_order_offer(visible_text):
    """The email/SMS-capture incentive (e.g. '10% off your first order').

    This is the offer that normally lives in the newsletter popup we hide before
    screenshotting -- a direct read on each competitor's acquisition aggression.
    """
    text = _text_lower(visible_text)
    near = r"first order|sign ?up|subscrib|newsletter|join (?:our|the)|when you (?:sign|subscribe|join)"
    m = re.search(r"(\d{1,2})\s*%\s*off[^.!?]{0,40}(?:" + near + ")", text)
    if not m:
        m = re.search(r"(?:" + near + r")[^.!?]{0,40}?(\d{1,2})\s*%\s*off", text)
    if not m:
        # Flat-amount incentives ("£5 off when you sign up").
        m2 = re.search(r"£\s?(\d{1,3})\s*off[^.!?]{0,40}(?:" + near + ")", text)
        if m2:
            return f"£{m2.group(1)} off"
        return None
    pct = int(m.group(1))
    return f"{pct}% off" if 1 <= pct <= 60 else None


def _free_delivery_threshold(visible_text):
    """The spend needed to unlock free delivery, e.g. 50 for 'free UK delivery
    over £50'. Returns an int (GBP) or None. A lower threshold is a sharper
    conversion lever; 'free delivery' with no threshold returns 0."""
    text = _text_lower(visible_text)
    m = re.search(r"free (?:uk )?(?:standard |express |next day )?(?:delivery|shipping)"
                  r"\s*(?:on orders?)?\s*over\s*£\s?(\d{1,4})", text)
    if m:
        return int(m.group(1))
    if re.search(r"free (?:uk )?(?:standard |express |next day )?(?:delivery|shipping)\b", text):
        return 0
    return None


def extract_trading_signals(html, visible_text):
    """Homepage trading/conversion signals: finance options (BNPL + wallets),
    the email-capture offer, the free-delivery threshold, scarcity language,
    urgency/countdown copy, bundle/multi-buy offers, gift-with-purchase,
    loyalty prompts, personalisation upsells, SMS capture and live chat.

    Pure function (strings in, dict out) so it is unit-testable offline. Every
    field degrades to a falsy default when its signal is absent."""
    low = _text_lower(visible_text) + " " + (html or "").lower()
    finance = [name for name, pat in _FINANCE_PATTERNS.items() if re.search(pat, low)]
    stext = _text_lower(visible_text)
    gwp = _find_phrases(stext, _GWP_PATTERNS, limit=3)
    chat_platform = next((name for name, pat in _CHAT_PLATFORMS.items()
                          if re.search(pat, low)), None)
    return {
        "finance": finance,
        "has_bnpl": any(p in _BNPL_PROVIDERS for p in finance),
        "email_capture_offer": _first_order_offer(visible_text),
        "free_delivery_threshold": _free_delivery_threshold(visible_text),
        "scarcity": _find_phrases(stext, _SCARCITY_PATTERNS),
        "urgency": _find_phrases(stext, _URGENCY_PATTERNS),
        "multibuy": _find_phrases(stext, _MULTIBUY_PATTERNS),
        "gift_with_purchase": gwp[0] if gwp else None,
        "loyalty": (_find_phrases(stext, _LOYALTY_PATTERNS, limit=1) or [None])[0],
        "personalisation_upsell": (_find_phrases(
            stext, _PERSONALISATION_UPSELL_PATTERNS, limit=1) or [None])[0],
        "sms_capture": bool(re.search(_SMS_MARKERS, low) or re.search(_SMS_COPY, stext)),
        "live_chat": chat_platform or ("copy" if re.search(_CHAT_COPY, stext) else None),
    }


# ---------------------------------------------------------------------------
# Delivery & returns pages — the service proposition, read from each brand's
# own policy pages (one extra same-site page each; no new blocking surface).
# ---------------------------------------------------------------------------
# The homepage only ever carries the headline ("free delivery over £50"); the
# real service proposition — express + cutoff time, the returns window, whether
# returns cost the shopper money — lives on the delivery/returns pages. Both
# extractors are pure (strings in, dict out) and degrade field-by-field.

_DELIVERY_LINK_RE = re.compile(r"delivery|shipping", re.I)
_RETURNS_LINK_RE = re.compile(r"returns?\b|refunds?\b|exchanges?\b", re.I)


def find_policy_links(html, base_url):
    """Discover a brand's delivery and returns page URLs from its homepage
    links (usually in the footer). Config `delivery_url` / `returns_url`
    overrides win in capture.py; this is the zero-config fallback. Returns
    {"delivery": url|None, "returns": url|None}. Pure."""
    soup = BeautifulSoup(html or "", "lxml")
    out = {"delivery": None, "returns": None}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        hay = href + " " + a.get_text(" ", strip=True)
        if out["delivery"] is None and _DELIVERY_LINK_RE.search(hay) \
                and not _RETURNS_LINK_RE.search(hay):
            out["delivery"] = urljoin(base_url, href)
        if out["returns"] is None and _RETURNS_LINK_RE.search(hay):
            out["returns"] = urljoin(base_url, href)
        if out["delivery"] and out["returns"]:
            break
    return out


# A delivery option line: "Standard Delivery ... £3.95" / "Express shipping — free".
_DELIVERY_OPTION_RE = re.compile(
    r"((?:free |standard |express |next[- ]day |named[- ]day |nominated[- ]day |same[- ]day |"
    r"premium |saturday |sunday |evening |uk |international |worldwide |tracked |signed )+"
    r"(?:delivery|shipping))[^£\n.!?]{0,60}?(free|£ ?\d{1,3}(?:\.\d{2})?)",
    re.I)
_EXPRESS_RE = re.compile(r"next[- ]?day|express|same[- ]?day", re.I)
_CUTOFF_RE = re.compile(
    r"order(?:ed)? (?:by|before)\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|noon|midday|midnight))", re.I)


def extract_delivery_page(visible_text):
    """Service proposition from a brand's delivery/shipping page: the priced
    option list, the free-delivery threshold, whether an express/next-day
    service exists and its order cutoff, and click & collect. Pure."""
    text = _text_lower(visible_text)
    options = []
    for m in _DELIVERY_OPTION_RE.finditer(visible_text or ""):
        name = re.sub(r"\s+", " ", m.group(1)).strip().title()
        price = m.group(2).lower().replace(" ", "")
        entry = {"name": name, "price": ("free" if price == "free" else price)}
        if entry not in options:
            options.append(entry)
    cutoff = _CUTOFF_RE.search(visible_text or "")
    return {
        "options": options[:8],
        "free_threshold": _free_delivery_threshold(visible_text),
        "express": bool(_EXPRESS_RE.search(text)),
        "express_cutoff": re.sub(r"\s+", "", cutoff.group(1)).lower() if cutoff else None,
        "click_collect": bool(re.search(r"click (?:&|and) collect", text)),
    }


_RETURNS_WINDOW_RE = re.compile(
    r"(?:within|up to|have|you have)?\s*(\d{1,3})\s*days?\b[^.!?]{0,60}?"
    r"\b(?:return|exchange|refund)"
    r"|\b(?:return|exchange|refund)[^.!?]{0,60}?\bwithin\s*(\d{1,3})\s*days?", re.I)
_FREE_RETURNS_RE = re.compile(r"free (?:uk )?returns?\b|returns? (?:are|is) free", re.I)
_PAID_RETURNS_RE = re.compile(
    r"(?:£ ?\d{1,2}(?:\.\d{2})?\s*(?:will be|is)? ?deducted)|cost of return"
    r"|return (?:postage|shipping) (?:is|are|costs?|will)"
    r"|at (?:your|the customer'?s?) (?:own )?(?:cost|expense)", re.I)


def extract_returns_page(visible_text):
    """Returns policy from a brand's returns/refunds page: the returns window
    in days, free-vs-paid returns (None when the page doesn't say), and
    whether exchanges are offered. Pure."""
    text = visible_text or ""
    low = _text_lower(text)
    m = _RETURNS_WINDOW_RE.search(text)
    window = int(m.group(1) or m.group(2)) if m else None
    if window is not None and not (1 <= window <= 365):
        window = None
    free = None
    if _FREE_RETURNS_RE.search(text):
        free = True
    elif _PAID_RETURNS_RE.search(text):
        free = False
    return {
        "window_days": window,
        "free_returns": free,
        "exchanges": bool(re.search(r"\bexchanges?\b", low)),
    }


# ---------------------------------------------------------------------------
# Reputation / social proof — the trust pillar, read from the homepage we
# already fetch (no extra request, no new blocking surface).
# ---------------------------------------------------------------------------
# A star rating + review volume is one of the strongest conversion levers in
# this category, and most DTC jewellery homepages surface it via a review
# platform (Trustpilot, Yotpo, Okendo, Reviews.io, …) and/or JSON-LD
# `AggregateRating`. We read whatever is already in the HTML — so this degrades
# the same honest way the rest does: no rating in the markup => rating is null.
#
# Honesty note: these are SELF-REPORTED, on-page numbers (a brand chooses what to
# show), not an independent audit. Read it as "what trust signal does each
# competitor put in front of a shopper", and as a directional trend over time.

# Review/trust platforms commonly embedded on these homepages. Detecting the
# widget is itself a social-proof signal (the brand chose to surface reviews),
# even when no aggregate number is exposed in the server HTML. Patterns are kept
# specific (e.g. `stamped\.io`, not bare "stamped") to avoid matching ordinary
# jewellery copy like "hand-stamped".
_REVIEW_PLATFORMS = {
    "Trustpilot":  r"trustpilot",
    "Yotpo":       r"yotpo",
    "Okendo":      r"okendo",
    "Reviews.io":  r"reviews\.io|reviewsio",
    "Judge.me":    r"judge\.me|judgeme",
    "Loox":        r"\bloox\b",
    "Feefo":       r"\bfeefo\b",
    "Stamped":     r"stamped\.io",
    "Bazaarvoice": r"bazaarvoice",
    "Trustspot":   r"trustspot",
}


def _aggregate_ratings(html):
    """All JSON-LD-style AggregateRating blobs as (rating_out_of_5, count) pairs.

    Parses the common `"aggregateRating":{...}` shape with a tolerant regex (the
    codebase already reads structured data this way). `ratingValue` is normalised
    to a /5 scale using `bestRating` when present (defaults to 5)."""
    out = []
    for m in re.finditer(r'aggregateRating"\s*:\s*\{([^{}]*)\}', html or "", re.I):
        inner = m.group(1)
        rv = re.search(r'"ratingValue"\s*:\s*"?(\d+(?:\.\d+)?)"?', inner)
        if not rv:
            continue
        rating = float(rv.group(1))
        best = re.search(r'"bestRating"\s*:\s*"?(\d+(?:\.\d+)?)"?', inner)
        scale = float(best.group(1)) if best and float(best.group(1)) > 0 else 5.0
        rating = round(rating / scale * 5, 2)
        cnt = re.search(r'"(?:reviewCount|ratingCount)"\s*:\s*"?(\d[\d,]*)"?', inner)
        count = int(cnt.group(1).replace(",", "")) if cnt else None
        if 0 < rating <= 5:
            out.append((rating, count))
    return out


def _rating_from_text(visible_text):
    """Fallback rating/count from visible copy, e.g. '4.8 / 5 from 12,345 reviews'.

    Returns (rating_or_None, count_or_None). Deliberately strict: a homepage star
    rating is only credible when it comes with a review *count*. A bare "5 stars"
    or "5/5" in marketing copy (a single testimonial, a UI flourish, a "rated 5
    stars by…" pull-quote) is NOT a brand-wide aggregate, and surfacing it as one
    flatters the brand with a number we can't stand behind. So we read a count
    first and only trust a text rating when that count is present. Structured
    JSON-LD `AggregateRating` is handled separately and stays trusted on its own."""
    text = _text_lower(visible_text)
    count = None
    m = re.search(r"(?:based on|from|over|across)?\s*([\d][\d,]{1,})\s*\+?\s*(?:reviews|ratings)", text)
    if m:
        try:
            n = int(m.group(1).replace(",", ""))
            if n >= 5:
                count = n
        except ValueError:
            pass
    rating = None
    if count is not None:                 # no count -> don't trust a text rating
        m = re.search(r"(\d(?:\.\d{1,2})?)\s*(?:/\s*5|out of\s*5|stars?\b)", text)
        if m:
            val = float(m.group(1))
            if 1 <= val <= 5:
                rating = val
    return rating, count


def extract_reputation(html, visible_text, known_platforms=None):
    """Social-proof signals from the homepage: an aggregate star rating, the
    review volume behind it, and which review platforms the brand surfaces.

    Pure (strings in, dict out) and offline-testable. Prefers structured
    `AggregateRating` (most reliable), then visible-text patterns; the review
    *count* is used to pick the most representative rating when several blobs
    appear (a brand-wide trust number usually has the largest count). Every field
    degrades to a falsy default when the signal is absent.

    `known_platforms` is an optional list of review platforms a brand is KNOWN to
    use (declared per-brand in config). Many homepages inject their review widget
    client-side, so the platform name never appears in the server HTML and we'd
    false-negative a signal we've confirmed elsewhere (e.g. a homepage whose star
    rating is rendered by a client-side Feefo widget). When a competitor surfaces a platform, it's worth checking the
    others do too — so config-declared platforms are merged with detected ones."""
    low = (html or "").lower()
    platforms = [name for name, pat in _REVIEW_PLATFORMS.items() if re.search(pat, low)]
    # Union in config-declared platforms (preserving detected order first).
    for name in (known_platforms or []):
        if name and name not in platforms:
            platforms.append(name)

    rating, review_count, source = None, None, None
    aggs = _aggregate_ratings(html)
    if aggs:
        # Prefer the blob with the largest review count (the site-wide rating),
        # falling back to the first when counts are absent.
        best = max(aggs, key=lambda rc: (rc[1] or -1))
        rating, review_count, source = best[0], best[1], "structured"
    if rating is None:
        rating, review_count = _rating_from_text(visible_text)
        if rating is not None or review_count is not None:
            source = "text"

    # Confidence: a star rating is only dependable when review VOLUME backs it.
    # A structured AggregateRating is trustworthy; so is a visible-text rating
    # that comes with a review count. But a bare "5/5" pulled from copy with no
    # count is almost always a stray badge or single testimonial, not the brand's
    # aggregate — flag it 'low' so the dashboard can keep it visible yet exclude
    # it from market averages instead of letting a junk 5.0 flatter the numbers.
    if rating is None:
        confidence = None
    elif source == "structured" or review_count is not None:
        confidence = "high"
    else:
        confidence = "low"

    return {
        "rating": rating,                 # out of 5, or None
        "review_count": review_count,     # int, or None
        "platforms": platforms,           # review/trust platforms surfaced
        "has_reviews": bool(rating or review_count or platforms),
        "source": source,                 # 'structured' | 'text' | None
        "confidence": confidence,         # 'high' | 'low' | None (no rating)
    }


# ---------------------------------------------------------------------------
# Listing-page trading data — the "real" prices a homepage can't give you
# ---------------------------------------------------------------------------
# A homepage is a marketing poster; the actual trading picture lives on a
# product-listing/bestsellers page. Sampling one of those per brand turns a rough
# price *band* into a real price *distribution* and lets us measure promotional
# *intensity* (what share of the range is actually marked down), not just whether
# a sale banner exists.

def _percentile(sorted_vals, q):
    """Linear-interpolated percentile of an already-sorted list (q in 0..1)."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac, 2)


def _price_distribution(prices):
    """Summarise a list of prices into count/min/p25/median/p75/max + sample."""
    prices = sorted(p for p in prices if 1 <= p <= 2000)
    if not prices:
        return {"count": 0, "currency": "GBP", "min": None, "p25": None,
                "median": None, "p75": None, "max": None, "sample": []}
    return {
        "count": len(prices),
        "currency": "GBP",
        "min": prices[0],
        "p25": _percentile(prices, 0.25),
        "median": _percentile(prices, 0.5),
        "p75": _percentile(prices, 0.75),
        "max": prices[-1],
        "sample": prices[:40],
    }


def _detect_sale_pairs(html, visible_text):
    """Count discounted lines on a listing page.

    Two reliable fingerprints: Shopify-style `compare_at_price` in embedded JSON
    that is higher than `price`, and visible 'was £X now £Y' strikethrough pairs.
    Returns (on_sale_count, sample_pairs)."""
    on_sale = 0
    pairs = []

    # Structured: compare_at_price > price (per product blob).
    for m in re.finditer(
            r'"price"\s*:\s*"?(\d{1,5}(?:\.\d{1,2})?)"?[^{}]*?'
            r'"compare_at_price"\s*:\s*"?(\d{1,5}(?:\.\d{1,2})?)"?', html or ""):
        try:
            price, was = float(m.group(1)), float(m.group(2))
            if was > price > 0:
                on_sale += 1
                if len(pairs) < 20:
                    pairs.append([round(was, 2), round(price, 2)])
        except ValueError:
            pass

    # Visible: "was £40 now £25" / "£40 £25" strikethrough copy.
    text = _text_lower(visible_text)
    for m in re.finditer(r"was\s*£\s?(\d{1,4}(?:\.\d{2})?)\s*(?:now\s*)?£\s?(\d{1,4}(?:\.\d{2})?)", text):
        try:
            was, now = float(m.group(1)), float(m.group(2))
            if was > now > 0:
                on_sale += 1
                if len(pairs) < 20:
                    pairs.append([round(was, 2), round(now, 2)])
        except ValueError:
            pass

    return on_sale, pairs


def extract_listing(html, visible_text, brand_rules=None):
    """Trading data from a real product-listing/bestsellers page.

    Returns a price distribution, an approximate product count, how many lines
    are on sale and the resulting discounted share, plus a 'new in' mention
    count. Honest about being a sample: counts are approximate (one card can
    yield several prices), so read discounted_share as 'how promotional is this
    range', not an exact figure. Add-on items (photo cards, gift wrap...) are
    kept out of the distribution so they can't fake a near-zero floor price.
    Pure/offline-testable."""
    keywords, values = _price_exclusion(brand_rules)
    structured = _scan_structured_prices(html, keywords, values)
    structured_n = len(structured)
    prices = structured + _scan_visible_prices(visible_text, keywords, values)

    dist = _price_distribution(prices)
    on_sale, pairs = _detect_sale_pairs(html, visible_text)
    # Approximate the number of products on the page: prefer the structured
    # count (one price per product), else the visible price count.
    products_seen = structured_n or dist["count"]
    discounted_share = round(min(1.0, on_sale / products_seen), 3) if products_seen else 0.0
    new_in = len(re.findall(r"\bnew in\b", _text_lower(visible_text)))

    return {
        "products_seen": products_seen,
        "prices": dist,
        "on_sale_count": on_sale,
        "discounted_share": discounted_share,
        "sale_pairs": pairs,
        "new_in_mentions": new_in,
    }


# Chrome/utility links that sit in the nav but aren't part of the shopping
# taxonomy (account, search, basket...). Matched case-insensitively against the
# whole, cleaned label so we don't accidentally drop real categories.
_MENU_SKIP = re.compile(
    r"^(?:menu|search|account|my account|log ?in|sign ?in|sign ?up|register|"
    r"basket|bag|my bag|cart|wishlist|wish ?list|favourites?|"
    r"contact(?: us)?|help|faqs?|stores?|store ?locator|find a store|"
    r"track(?: my)? order|skip to (?:content|main(?: content)?)|"
    r"currency|language|home|gbp|usd|eur|£|\$|€)$",
    re.I,
)


def _clean_menu_label(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _menu_labels(container):
    """Ordered, de-duplicated top-level labels from a nav-like container.

    Prefers the structured top-level list -- direct `<li>` children of the
    nav's primary (outermost) `<ul>`, each represented by its first link -- so a
    mega-menu's submenu links don't leak in. Falls back to the nav's anchors for
    navs that render flat links. Drops empties, over-long strings (not menu
    labels) and utility/chrome links."""
    nodes = []
    ul = container.find("ul")          # outermost <ul> comes first in source
    if ul is not None:
        lis = ul.find_all("li", recursive=False)
        nodes = [(li.find("a") or li) for li in lis]
    if not nodes:
        nodes = [a for a in container.find_all("a") if a.get("href")]
    labels, seen = [], set()
    for node in nodes:
        label = _clean_menu_label(node.get_text(" "))
        if not label or len(label) > 40:
            continue
        if _MENU_SKIP.match(label):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return labels


def extract_menu(html, limit=3):
    """Top-level site navigation ('taxonomy') labels, in document order.

    A brand's primary nav is the clearest statement of how it wants shoppers to
    slice its range -- what it leads with ('New In', 'Necklaces', 'Sale...').
    We score every navigation container and take the one with the most
    qualifying labels (the main menu almost always has more top-level items than
    a footer/utility nav), preferring navs inside the <header>. Returns the
    first `limit` labels.

    HONESTY NOTE: heuristic. A mega-menu rendered entirely client-side, or one
    hidden behind a hamburger with no server HTML, can yield nothing -- in which
    case we return an empty list rather than guessing."""
    soup = BeautifulSoup(html or "", "lxml")

    candidates = list(soup.find_all("nav"))
    candidates += [t for t in soup.find_all(attrs={"role": "navigation"})
                   if t.name != "nav"]

    # Prefer header navs (the main menu); fall back to any nav, then <header>.
    header_navs = [c for c in candidates if c.find_parent("header") is not None]
    best = []
    for pool in (header_navs, candidates):
        for c in pool:
            labels = _menu_labels(c)
            if len(labels) > len(best):
                best = labels
        if best:
            break
    if not best:
        header = soup.find("header")
        if header is not None:
            best = _menu_labels(header)

    return best[:limit]


def extract_all(html, visible_text, raw_text, categories, provided_hero=None,
                known_platforms=None, price_rules=None):
    """Run every extractor and return one flat dict of fields."""
    banner_text = _collect_banner_text(html)
    offers = extract_offers(visible_text, extra_texts=banner_text)
    return {
        "hero_message": extract_hero(html, provided_hero),
        "menu": extract_menu(html),
        "offers": offers["offers"],
        "headline_offer": offers["headline_offer"],
        "max_discount_pct": offers["max_discount_pct"],
        "delivery": extract_delivery(visible_text),
        "discount_codes": extract_discount_codes(raw_text),
        "product_mix": extract_product_mix(visible_text, categories),
        "keywords": extract_keywords(visible_text),
        "prices": extract_prices(html, visible_text, price_rules),
        "trading": extract_trading_signals(html, visible_text),
        "reputation": extract_reputation(html, visible_text, known_platforms),
        "seo": extract_seo(html),
        "accessibility": extract_accessibility(html),
    }
