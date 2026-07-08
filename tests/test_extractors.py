"""
Offline tests for the rules-based extractors. No browser, no network.
Run:  python -m pytest -q   (or)   python tests/test_extractors.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import extractors  # noqa: E402

SAMPLE_HTML = """
<html><head>
  <title>Katie Loxton | Handbags, Jewellery & Gifts</title>
  <meta name="description" content="Shop bracelets, necklaces and personalised gifts.">
  <meta property="og:title" content="Summer Sale Now On">
  <link rel="canonical" href="https://www.katieloxton.com/">
  <script type="application/ld+json">{"@type":"Organization","name":"x"}</script>
</head><body>
  <h1>Up to 50% Off Summer Sale</h1>
  <h2>New In</h2><h2>Bestsellers</h2>
  <p>Free UK delivery over £50. Order by 3pm for next day delivery.</p>
  <p>Use code SUMMER20 for an extra treat.</p>
  <nav>Bracelets Necklaces Earrings Anklets Personalised Birthday gifts</nav>
  <p>Bracelets bracelets bracelets necklaces personalised birthday</p>
</body></html>
"""

VISIBLE = (
    "Up to 50% Off Summer Sale New In Bestsellers "
    "Free UK delivery over £50. Order by 3pm for next day delivery. "
    "Use code SUMMER20 for an extra treat. "
    "Bracelets Necklaces Earrings Anklets Personalised Birthday gifts "
    "Bracelets bracelets bracelets necklaces personalised birthday"
)

CATEGORIES = {
    "anklets": ["anklet"],
    "bracelets": ["bracelet", "bangle"],
    "necklaces": ["necklace"],
    "earrings": ["earring"],
    "personalised": ["personalised"],
    "birthday": ["birthday"],
}


def test_offers():
    res = extractors.extract_offers(VISIBLE)
    assert res["max_discount_pct"] == 50
    assert res["headline_offer"].startswith("up to")
    assert any("summer sale" in o for o in res["offers"])


def test_delivery():
    res = extractors.extract_delivery(VISIBLE)
    assert any("next day" in d for d in res)
    assert any("free uk delivery" in d or "free" in d for d in res)
    assert any("order by 3pm" in d for d in res)


def test_codes():
    codes = extractors.extract_discount_codes(VISIBLE)
    assert "SUMMER20" in codes


def test_product_mix():
    mix = extractors.extract_product_mix(VISIBLE, CATEGORIES)
    assert "bracelets" in mix
    # bracelet mentioned most -> should be top share
    assert mix["bracelets"]["count"] >= mix["necklaces"]["count"]
    assert abs(sum(v["share"] for v in mix.values()) - 1.0) < 0.01


def test_seo():
    seo = extractors.extract_seo(SAMPLE_HTML)
    assert "Katie Loxton" in seo["title"]
    assert seo["h1_count"] == 1
    assert seo["h2_count"] == 2
    assert "Organization" in seo["structured_data_types"]
    assert seo["meta_description"].startswith("Shop bracelets")


def test_hero_prefers_provided():
    assert extractors.extract_hero(SAMPLE_HTML, "BIG HERO LINE") == "BIG HERO LINE"
    assert extractors.extract_hero(SAMPLE_HTML) == "Up to 50% Off Summer Sale"


# A split-banner homepage: the PRIMARY panel is a sale *image* (copy only in
# alt text), the SECONDARY panel is live text, and a smaller live birthday offer
# sits elsewhere. This is a real-world failure mode: hero read as "July Birthday
# Girl" and promo read as "15% off" because the 50% sale was image-baked.
SPLIT_BANNER_HTML = """
<html><head><title>Sample Store</title></head><body>
  <a class="hero" title="Shop the sale">
    <img src="/banners/summer.jpg" alt="Up to 50% Off Summer Sale">
  </a>
  <div class="hero-secondary"><h2>July Birthday Girl</h2></div>
  <p>Treat yourself: 15% off in your birthday month.</p>
  <img src="/logo.svg" alt="Sample Store logo">
</body></html>
"""
# The browser-side largest-visible-text picks the live secondary panel.
SPLIT_BANNER_VISIBLE = "July Birthday Girl Treat yourself: 15% off in your birthday month."
SPLIT_BANNER_PROVIDED_HERO = "July Birthday Girl"


def test_hero_recovers_image_baked_sale():
    # Baseline (live text) is the birthday panel; the loud sale is in an alt.
    hero = extractors.extract_hero(SPLIT_BANNER_HTML, SPLIT_BANNER_PROVIDED_HERO)
    assert "50% Off Summer Sale" in hero
    assert "Birthday" not in hero


def test_offers_read_image_baked_discount():
    fields = extractors.extract_all(
        SPLIT_BANNER_HTML, SPLIT_BANNER_VISIBLE, SPLIT_BANNER_HTML, CATEGORIES,
        provided_hero=SPLIT_BANNER_PROVIDED_HERO)
    assert fields["max_discount_pct"] == 50          # not the live 15%
    assert fields["headline_offer"].startswith("up to")
    assert "50% Off Summer Sale" in (fields["hero_message"] or "")


# The harder real-world case: the sale banner image has NO alt text at all -- the only
# trace of the offer is the link target ('/summer-sale-50-off') and the image
# filename. alt/aria recovery sees nothing, so the offer must come from the URL.
ALTLESS_BANNER_HTML = """
<html><head><title>Sample Store</title></head><body>
  <a class="hero" href="/collections/summer-sale-50-off">
    <img src="/cdn/banners/summer-sale-50-off.jpg">
  </a>
  <div class="hero-secondary"><h2>July Birthday Girl</h2></div>
  <p>Treat yourself: 15% off in your birthday month.</p>
  <img src="/logo.svg" alt="Sample Store logo">
</body></html>
"""
ALTLESS_BANNER_VISIBLE = "July Birthday Girl Treat yourself: 15% off in your birthday month."


def test_offers_read_from_alt_less_banner_url():
    fields = extractors.extract_all(
        ALTLESS_BANNER_HTML, ALTLESS_BANNER_VISIBLE, ALTLESS_BANNER_HTML, CATEGORIES,
        provided_hero="July Birthday Girl")
    assert fields["max_discount_pct"] == 50          # recovered from the URL, not the live 15%
    assert "50% off" in (fields["headline_offer"] or "")


def test_url_offer_text_recovers_and_normalises():
    assert "50% off" in extractors._url_offer_text("/collections/summer-sale-50-off")
    assert "50% off" in extractors._url_offer_text("/cdn/banners/summer-sale-50-off.jpg")
    # 'percent' spelled out, and a leading scheme/host, are handled too.
    assert "30% off" in extractors._url_offer_text("https://x.com/winter-sale-30-percent-off")


def test_url_offer_text_ignores_non_sale_and_product_slugs():
    # No sale context -> not an offer, even though '20 off' appears.
    assert extractors._url_offer_text("/products/20-off-shoulder-top") is None
    # Plain navigation paths recover nothing.
    assert extractors._url_offer_text("/collections/bestsellers") is None
    assert extractors._url_offer_text("/cdn/images/logo.svg") is None
    assert extractors._url_offer_text("") is None


def test_hero_ignores_chrome_alt_text():
    # A logo/payment-icon alt must never become the hero, and a normal live hero
    # (no louder image promo) is left untouched.
    html = '<body><img src="/logo.svg" alt="Brand logo"><h1>New In: Summer Edit</h1></body>'
    assert extractors.extract_hero(html, "New In: Summer Edit") == "New In: Summer Edit"


# A realistic header nav: utility links (search/account/bag) sit alongside the
# real shopping taxonomy, and there's a separate footer nav full of policy links.
MENU_HTML = """
<html><body>
  <header>
    <a href="/search">Search</a>
    <a href="/account">Account</a>
    <a href="/cart">Bag</a>
    <nav class="main">
      <a href="/new">New In</a>
      <a href="/necklaces">Necklaces</a>
      <a href="/bracelets">Bracelets</a>
      <a href="/earrings">Earrings</a>
      <a href="/sale">Sale</a>
    </nav>
  </header>
  <footer>
    <nav>
      <a href="/about">About us</a>
      <a href="/returns">Returns</a>
      <a href="/privacy">Privacy policy</a>
      <a href="/terms">Terms</a>
    </nav>
  </footer>
</body></html>
"""


def test_menu_first_three_taxonomy_items():
    menu = extractors.extract_menu(MENU_HTML)
    assert menu == ["New In", "Necklaces", "Bracelets"]


def test_menu_skips_utility_links():
    # Even reading the whole nav, chrome links must never appear.
    full = extractors.extract_menu(MENU_HTML, limit=99)
    assert "Search" not in full and "Account" not in full and "Bag" not in full
    # The big footer nav must not win over the main header menu.
    assert full[0] == "New In"


def test_menu_takes_top_level_not_submenu_links():
    # A mega-menu: each top-level item opens a submenu. We must return the
    # top-level taxonomy, not the deeper submenu links.
    html = """
    <header><nav>
      <ul>
        <li><a href="/new">New In</a>
            <div class="sub"><a href="/new/necklaces">New Necklaces</a>
                             <a href="/new/rings">New Rings</a></div></li>
        <li><a href="/jewellery">Jewellery</a></li>
        <li><a href="/gifts">Gifts</a></li>
        <li><a href="/sale">Sale</a></li>
      </ul>
    </nav></header>"""
    assert extractors.extract_menu(html) == ["New In", "Jewellery", "Gifts"]


def test_menu_empty_when_no_nav():
    assert extractors.extract_menu("<html><body><p>hi</p></body></html>") == []


def test_extract_all_has_menu():
    fields = extractors.extract_all(MENU_HTML, VISIBLE, MENU_HTML, CATEGORIES)
    assert fields["menu"] == ["New In", "Necklaces", "Bracelets"]


def test_keywords():
    kws = dict(extractors.extract_keywords(VISIBLE))
    assert "bracelets" in kws


def test_prices_from_visible():
    res = extractors.extract_prices("", "Bracelet £25.00 Necklace £45 Earrings £19.99 Ring £120")
    assert res["count"] == 4
    assert res["min"] == 19.99
    assert res["max"] == 120
    assert res["currency"] == "GBP"


def test_prices_prefers_structured_data():
    html = '<script>{"price":"39.00"}</script><script>{"price":"59.00"}</script>'
    html += '<script>{"price":"99.00"}</script><script>{"price":"29.00"}</script>'
    res = extractors.extract_prices(html, "ignored £9999")
    assert res["min"] == 29.0 and res["max"] == 99.0
    assert res["count"] == 4  # used structured data, not the visible £9999


def test_extract_all_has_prices():
    fields = extractors.extract_all(SAMPLE_HTML, VISIBLE, SAMPLE_HTML, CATEGORIES)
    assert "prices" in fields and "median" in fields["prices"]


def test_detect_block_cloudflare_title():
    html = ("<html><head><title>Just a moment...</title></head>"
            "<body>Enable JavaScript and cookies to continue</body></html>")
    reason = extractors.detect_block(html, "Enable JavaScript and cookies to continue")
    assert reason and "blocked" in reason


def test_detect_block_challenge_marker():
    html = ('<html><head><title>Loading</title></head><body>'
            '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page">'
            '</script></body></html>')
    assert extractors.detect_block(html) is not None


def test_detect_block_passes_real_page():
    # A genuine homepage must NOT be flagged as a challenge page.
    assert extractors.detect_block(SAMPLE_HTML, VISIBLE) is None


def test_trading_signals_finance_and_bnpl():
    html = '<div class="klarna-badge"></div><img alt="Pay with Clearpay">'
    visible = "Pay in 3 with Klarna or Clearpay. Apple Pay and PayPal accepted."
    t = extractors.extract_trading_signals(html, visible)
    assert "Klarna" in t["finance"] and "Clearpay" in t["finance"]
    assert "PayPal" in t["finance"] and "Apple Pay" in t["finance"]
    assert t["has_bnpl"] is True


def test_trading_signals_no_bnpl():
    t = extractors.extract_trading_signals("", "We accept Visa, Mastercard and PayPal.")
    assert t["has_bnpl"] is False
    assert "PayPal" in t["finance"]


def test_trading_email_capture_offer():
    t = extractors.extract_trading_signals(
        "", "Sign up to our newsletter for 10% off your first order.")
    assert t["email_capture_offer"] == "10% off"
    t2 = extractors.extract_trading_signals(
        "", "Join the club and get £5 off when you sign up.")
    assert t2["email_capture_offer"] == "£5 off"


def test_trading_free_delivery_threshold():
    a = extractors.extract_trading_signals("", "Free UK delivery over £50.")
    assert a["free_delivery_threshold"] == 50
    b = extractors.extract_trading_signals("", "Free next day delivery on everything!")
    assert b["free_delivery_threshold"] == 0
    c = extractors.extract_trading_signals("", "Delivery from £3.95.")
    assert c["free_delivery_threshold"] is None


def test_trading_scarcity():
    t = extractors.extract_trading_signals("", "Selling fast. Only 3 left in stock.")
    assert any("selling fast" in s for s in t["scarcity"])
    assert any("only 3 left" in s for s in t["scarcity"])


def test_extract_all_includes_trading():
    fields = extractors.extract_all(SAMPLE_HTML, VISIBLE, SAMPLE_HTML, CATEGORIES)
    assert "trading" in fields and "finance" in fields["trading"]


LISTING_HTML = """
<html><body>
  <script type="application/ld+json">
  {"@type":"Product","offers":{"price":"25.00"}}
  </script>
  <div class="card">{"price":"45.00","compare_at_price":"60.00"}</div>
  <div class="card">{"price":"19.99","compare_at_price":"19.99"}</div>
  <div class="card">{"price":"120.00"}</div>
  <span class="badge">New In</span>
</body></html>
"""
LISTING_VISIBLE = "Necklace £25.00 Bracelet was £60 now £45 Earrings £19.99 Ring £120 New In"


def test_listing_price_distribution():
    L = extractors.extract_listing(LISTING_HTML, LISTING_VISIBLE)
    assert L["prices"]["count"] >= 4
    assert L["prices"]["min"] == 19.99
    assert L["prices"]["max"] == 120.0
    assert L["prices"]["median"] is not None
    assert L["prices"]["p25"] is not None and L["prices"]["p75"] is not None


def test_listing_detects_discounted_lines():
    L = extractors.extract_listing(LISTING_HTML, LISTING_VISIBLE)
    # One structured compare_at_price (60>45) plus one visible was/now (60>45).
    assert L["on_sale_count"] >= 1
    assert 0.0 < L["discounted_share"] <= 1.0
    assert L["new_in_mentions"] >= 1


def test_listing_empty_is_graceful():
    L = extractors.extract_listing("<html><body>no prices here</body></html>", "nothing")
    assert L["prices"]["count"] == 0
    assert L["on_sale_count"] == 0
    assert L["discounted_share"] == 0.0


def test_reputation_structured_aggregate_rating():
    html = ('<script type="application/ld+json">{"@type":"Organization",'
            '"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.8",'
            '"reviewCount":"12453"}}</script>')
    rep = extractors.extract_reputation(html, "")
    assert rep["rating"] == 4.8
    assert rep["review_count"] == 12453
    assert rep["source"] == "structured"
    assert rep["has_reviews"] is True


def test_reputation_normalises_best_rating_scale():
    # A /100 scale rating must be normalised onto /5.
    html = ('<script>{"aggregateRating":{"ratingValue":"96","bestRating":"100",'
            '"reviewCount":"500"}}</script>')
    rep = extractors.extract_reputation(html, "")
    assert rep["rating"] == 4.8
    assert rep["review_count"] == 500


def test_reputation_prefers_site_wide_count():
    # Two blobs (a single product card + the brand-wide trust number): pick the
    # one with the larger review count.
    html = ('<div>{"aggregateRating":{"ratingValue":"5.0","reviewCount":"3"}}</div>'
            '<div>{"aggregateRating":{"ratingValue":"4.6","reviewCount":"9000"}}</div>')
    rep = extractors.extract_reputation(html, "")
    assert rep["rating"] == 4.6 and rep["review_count"] == 9000


def test_reputation_detects_platforms():
    html = '<div class="yotpo-widget"></div><script src="https://widget.trustpilot.com/x"></script>'
    rep = extractors.extract_reputation(html, "")
    assert "Yotpo" in rep["platforms"] and "Trustpilot" in rep["platforms"]
    assert rep["has_reviews"] is True


def test_reputation_text_fallback():
    rep = extractors.extract_reputation("", "Rated 4.7 out of 5 based on 8,210 reviews")
    assert rep["rating"] == 4.7 and rep["review_count"] == 8210
    assert rep["source"] == "text"
    # Text rating WITH a review count is trustworthy.
    assert rep["confidence"] == "high"


def test_reputation_confidence_reflects_evidence():
    # A bare "5 stars" with no count is a stray badge, not the brand aggregate —
    # under the strict rule it yields NO rating at all (so no confidence).
    rep = extractors.extract_reputation("", "Our customers love us — 5 stars!")
    assert rep["rating"] is None and rep["confidence"] is None
    # A text rating backed by a real count is trustworthy.
    counted = extractors.extract_reputation("", "Rated 4.8 out of 5 from 2,000 reviews")
    assert counted["rating"] == 4.8 and counted["confidence"] == "high"
    # A structured AggregateRating is trustworthy even without a count.
    structured = extractors.extract_reputation(
        '<script>{"aggregateRating":{"ratingValue":"4.9"}}</script>', "")
    assert structured["confidence"] == "high"
    # No rating at all -> no confidence.
    none = extractors.extract_reputation("<body>no reviews</body>", "")
    assert none["confidence"] is None


def test_reputation_known_platforms_are_merged():
    # A homepage that injects its review widget client-side won't expose the
    # platform name in the server HTML — but a config-declared platform should
    # still surface (and not be duplicated when it is also detected).
    rep = extractors.extract_reputation("<html><body>5 out of 5 stars</body></html>", "",
                                        known_platforms=["Feefo"])
    assert rep["platforms"] == ["Feefo"] and rep["has_reviews"] is True

    html = '<div class="yotpo-widget"></div>'
    rep2 = extractors.extract_reputation(html, "", known_platforms=["Yotpo", "Feefo"])
    assert rep2["platforms"] == ["Yotpo", "Feefo"]


def test_reputation_absent_is_graceful():
    rep = extractors.extract_reputation("<html><body>no reviews here</body></html>",
                                        "Beautiful hand-stamped jewellery")
    assert rep["rating"] is None and rep["review_count"] is None
    assert rep["platforms"] == [] and rep["has_reviews"] is False
    assert rep["source"] is None


def test_reputation_text_rating_requires_a_count():
    # A bare "5 stars" with no review tally is marketing copy, not an aggregate —
    # we must NOT surface it as the brand's rating (a real-world marketing-copy case).
    rep = extractors.extract_reputation("", "Loved by all — rated 5 stars!")
    assert rep["rating"] is None
    # Paired with a real count, the same rating is trustworthy.
    rep2 = extractors.extract_reputation("", "Rated 5 stars from 1,204 reviews")
    assert rep2["rating"] == 5.0 and rep2["review_count"] == 1204


def test_extract_all_includes_reputation():
    fields = extractors.extract_all(SAMPLE_HTML, VISIBLE, SAMPLE_HTML, CATEGORIES)
    assert "reputation" in fields and "rating" in fields["reputation"]

def test_trading_signals_urgency_and_levers():
    visible = ("SALE ENDS MIDNIGHT — last chance! 3 for 2 on all charms. "
               "Free gift with purchase over £60. Join our rewards club to earn points. "
               "Add a monogram for free. Sign up for SMS offers.")
    html = '<script src="https://cdn.gorgias.chat/x.js"></script>'
    t = extractors.extract_trading_signals(html, visible)
    assert any("ends midnight" in u for u in t["urgency"])
    assert any("last chance" in u for u in t["urgency"])
    assert any("3 for 2" in m for m in t["multibuy"])
    assert t["gift_with_purchase"] is not None
    assert t["loyalty"] is not None
    assert t["personalisation_upsell"] is not None
    assert t["sms_capture"] is True
    assert t["live_chat"] == "Gorgias"


def test_trading_signals_levers_absent_degrade():
    t = extractors.extract_trading_signals("<html></html>", "Plain homepage copy.")
    assert t["urgency"] == [] and t["multibuy"] == []
    assert t["gift_with_purchase"] is None and t["loyalty"] is None
    assert t["personalisation_upsell"] is None
    assert t["sms_capture"] is False and t["live_chat"] is None


def test_find_policy_links_from_footer():
    html = """<html><body><footer>
      <a href="/pages/delivery-information">Delivery Information</a>
      <a href="/pages/returns-and-refunds">Returns &amp; Refunds</a>
      <a href="/pages/contact">Contact us</a>
    </footer></body></html>"""
    links = extractors.find_policy_links(html, "https://shop.example/")
    assert links["delivery"] == "https://shop.example/pages/delivery-information"
    assert links["returns"] == "https://shop.example/pages/returns-and-refunds"


def test_find_policy_links_absent_is_graceful():
    links = extractors.find_policy_links("<html><body>nothing</body></html>", "https://x.example/")
    assert links == {"delivery": None, "returns": None}


def test_extract_delivery_page():
    text = ("UK Standard Delivery 3-5 working days £3.95\n"
            "Express Delivery next working day £5.95 — order by 8pm\n"
            "Free UK standard delivery on orders over £60.\n"
            "Click and collect available in store.")
    d = extractors.extract_delivery_page(text)
    assert d["free_threshold"] == 60
    assert d["express"] is True
    assert d["express_cutoff"] == "8pm"
    assert d["click_collect"] is True
    assert any("Standard Delivery" in o["name"] and o["price"] == "£3.95" for o in d["options"])
    assert any("Express Delivery" in o["name"] for o in d["options"])


def test_extract_returns_page():
    text = ("You have 30 days to return your order. Free UK returns via our portal. "
            "We are happy to offer exchanges on unworn items.")
    r = extractors.extract_returns_page(text)
    assert r["window_days"] == 30
    assert r["free_returns"] is True
    assert r["exchanges"] is True


def test_extract_returns_page_paid_and_silent():
    paid = extractors.extract_returns_page(
        "Returns accepted within 14 days. Return postage is the responsibility of the customer.")
    assert paid["window_days"] == 14 and paid["free_returns"] is False
    silent = extractors.extract_returns_page("Our products are lovely.")
    assert silent["window_days"] is None and silent["free_returns"] is None


def test_price_scan_excludes_addon_items_structured():
    # A £1.50 photo card and £2 gift wrap must not fake a near-zero floor price.
    html = ('{"title":"Photo Card","price":"1.50"}'
            '{"title":"Gift Wrap","price":"2.00"}'
            '{"title":"Gold Bracelet","price":"49.00"}'
            '{"title":"Tote Bag","price":"89.00"}')
    p = extractors.extract_prices(html, "")
    assert p["min"] == 49.0 and p["max"] == 89.0 and p["count"] == 2


def test_price_scan_excludes_addon_items_visible():
    text = "Gift wrap £2.00 ... Gold Bracelet £49.00 ... Personalised Pouch £22.00"
    p = extractors.extract_prices("", text)
    assert p["min"] == 22.0        # 'pouch' is a real product line, NOT filtered
    assert 2.0 not in (p["sample"] or [])


def test_price_scan_per_brand_overrides():
    html = ('{"title":"Charity Pin","price":"3.00"}'
            '{"title":"Gold Bracelet","price":"49.00"}'
            '{"title":"Tote Bag","price":"89.00"}'
            '{"title":"Purse","price":"35.00"}')
    rules = {"keywords": ["charity pin"], "values": [35.0]}
    p = extractors.extract_prices(html, "", rules)
    assert p["min"] == 49.0 and p["count"] == 2


def test_listing_excludes_addons_too():
    html = ('{"title":"Photo Card","price":"1.50"}'
            '{"title":"Bag","price":"40.00"}{"title":"Bag 2","price":"60.00"}')
    res = extractors.extract_listing(html, "")
    assert res["prices"]["min"] == 40.0
    assert res["products_seen"] == 2


def test_accessibility():
    a = extractors.extract_accessibility(SAMPLE_HTML)
    assert 0 <= a["score"] <= 100
    assert a["grade"] in {"A", "B", "C", "D", "E", "F"}
    checks = {c["id"]: c for c in a["checks"]}
    # SAMPLE_HTML has exactly one <h1> -> heading check passes...
    assert checks["headings"]["ratio"] == 1.0
    # ...but <html> has no lang attribute -> that check fails.
    assert checks["html_lang"]["ratio"] == 0.0
    # It has a <title> and a <nav> landmark.
    assert checks["doc_title"]["ratio"] == 1.0
    assert checks["landmarks"]["ratio"] >= 0.5


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{'ALL PASSED' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)
