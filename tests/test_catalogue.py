"""
Offline tests for the assortment / catalogue (product-sitemap) pillar.
No browser, no network — the network getter is faked in-memory.
Run:  python tests/test_catalogue.py   (or)   python -m pytest -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import catalogue  # noqa: E402

# A Shopify-style sitemap index + a product sitemap, the common real shape.
INDEX_XML = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://shop.example/sitemap_products_1.xml?from=1&amp;to=9</loc></sitemap>
  <sitemap><loc>https://shop.example/sitemap_collections_1.xml</loc></sitemap>
  <sitemap><loc>https://shop.example/sitemap_pages_1.xml</loc></sitemap>
</sitemapindex>"""

PRODUCTS_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example/products/gold-bracelet</loc></url>
  <url><loc>https://shop.example/products/silver-necklace</loc></url>
  <url><loc>https://shop.example/products/birthstone-ring/</loc></url>
  <url><loc>https://shop.example/collections/sale</loc></url>
</urlset>"""

COLLECTIONS_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example/collections/bestsellers</loc></url>
</urlset>"""


def fake_get(mapping):
    return lambda url: mapping.get(url)


def test_extract_locs_and_unescape():
    locs = catalogue.extract_locs(INDEX_XML)
    assert "https://shop.example/sitemap_products_1.xml?from=1&to=9" in locs  # &amp; decoded
    assert len(locs) == 3


def test_is_sitemap_index():
    assert catalogue.is_sitemap_index(INDEX_XML) is True
    assert catalogue.is_sitemap_index(PRODUCTS_XML) is False


def test_looks_like_sitemap_accepts_real_xml():
    assert catalogue.looks_like_sitemap(INDEX_XML) is True
    assert catalogue.looks_like_sitemap(PRODUCTS_XML) is True


def test_looks_like_sitemap_rejects_challenge_and_empty():
    # A Cloudflare/HTML interstitial must NOT be mistaken for a sitemap.
    challenge = ("<!doctype html><html><head><title>Just a moment...</title></head>"
                 "<body>Checking your browser before accessing the store.</body></html>")
    assert catalogue.looks_like_sitemap(challenge) is False
    assert catalogue.looks_like_sitemap("") is False
    assert catalogue.looks_like_sitemap(None) is False


def test_handle_and_product_url():
    assert catalogue.looks_like_product_url("https://x/products/gold-bracelet") is True
    assert catalogue.looks_like_product_url("https://x/collections/sale") is False
    assert catalogue.handle_from_url("https://x/products/Birthstone-Ring/") == "birthstone-ring"


def test_collect_walks_index_to_products():
    get = fake_get({
        "https://shop.example/sitemap.xml": INDEX_XML,
        "https://shop.example/sitemap_products_1.xml?from=1&to=9": PRODUCTS_XML,
        "https://shop.example/sitemap_collections_1.xml": COLLECTIONS_XML,
    })
    res = catalogue.collect(get, "https://shop.example")
    assert res["ok"] is True
    # 3 product handles; the /collections/ URL is excluded.
    assert res["product_count"] == 3
    assert "gold-bracelet" in res["handles"] and "birthstone-ring" in res["handles"]
    assert "sale" not in res["handles"]


def test_collect_missing_sitemap_is_graceful():
    res = catalogue.collect(fake_get({}), "https://shop.example")
    assert res["ok"] is False and res["error"] == "no sitemap.xml"
    assert res["product_count"] == 0 and res["handles"] == []


def test_collect_no_products_is_graceful():
    get = fake_get({"https://shop.example/sitemap.xml": COLLECTIONS_XML})  # flat, no products
    res = catalogue.collect(get, "https://shop.example")
    assert res["ok"] is False and "no product" in res["error"]


CATS = {
    "necklaces": ["necklace", "pendant"],
    "earrings": ["earring", "hoop"],
    "rings": ["ring"],
    "personalised": ["personalised", "initial"],
    "birthday": ["birthstone"],
}


def test_classify_handles_basic_and_multimatch():
    handles = ["gold-necklace", "silver-hoop-earrings", "birthstone-ring",
               "personalised-initial-necklace", "plain-bangle"]
    c = catalogue.classify_handles(handles, CATS)
    assert c["necklaces"] == 2           # gold-necklace + personalised-initial-necklace
    assert c["earrings"] == 1
    assert c["personalised"] == 1        # one handle, two keywords -> counted once
    assert c["rings"] == 1
    assert c["birthday"] == 1            # birthstone
    assert "plain-bangle" not in c       # bangle isn't in this taxonomy -> no key


def test_classify_handles_ring_does_not_match_earring():
    # The \\b-prefixed match must NOT count 'earrings' as a ring (the classic trap).
    c = catalogue.classify_handles(["diamond-earrings"], CATS)
    assert c.get("rings", 0) == 0
    assert c["earrings"] == 1


def test_classify_handles_matches_plurals():
    c = catalogue.classify_handles(["stacking-rings", "gold-necklaces"], CATS)
    assert c["rings"] == 1 and c["necklaces"] == 1


def test_diff_new_and_removed():
    d = catalogue.diff(["a", "b", "c"], ["b", "c", "d", "e"])
    assert d["new"] == ["d", "e"]
    assert d["removed"] == ["a"]


def test_brand_entry_first_seen_reports_zero_velocity():
    res = {"ok": True, "product_count": 400, "handles": ["a", "b"], "error": None}
    e = catalogue._brand_entry(res, None)           # never seen before
    assert e["first_seen"] is True
    assert e["new_count"] == 0 and e["removed_count"] == 0
    assert e["product_count"] == 400


def test_brand_entry_counts_new_against_prior():
    res = {"ok": True, "product_count": 3, "handles": ["a", "b", "c"], "error": None}
    e = catalogue._brand_entry(res, ["a"])          # b, c are new
    assert e["first_seen"] is False
    assert e["new_count"] == 2 and "b" in e["new_samples"]


def test_brand_entry_failure_is_graceful():
    e = catalogue._brand_entry({"ok": False, "error": "no sitemap.xml"}, ["a"])
    assert e["ok"] is False and e["product_count"] is None and e["new_count"] == 0


ROBOTS_TXT = """User-agent: *
Disallow: /checkout
Sitemap: https://shop.example/sitemap_products_1.xml?from=1&to=9
Sitemap: https://shop.example/sitemap_extra.xml
sitemap: https://shop.example/sitemap_products_1.xml?from=1&to=9
"""

# Magento/SFCC-style sitemap: product URLs with NO /products/ path segment,
# distinguishable only by their <image:image> children.
IMAGE_SITEMAP_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url><loc>https://shop.example/gold-bracelet.html</loc>
    <image:image><image:loc>https://cdn.example/g.jpg</image:loc></image:image></url>
  <url><loc>https://shop.example/silver-necklace.html</loc>
    <image:image><image:loc>https://cdn.example/s.jpg</image:loc></image:image></url>
  <url><loc>https://shop.example/about-us</loc></url>
  <url><loc>https://shop.example/blog/summer-edit</loc></url>
</urlset>"""


def test_sitemaps_from_robots_merges_and_dedupes():
    urls = catalogue.sitemaps_from_robots(ROBOTS_TXT)
    assert urls == [
        "https://shop.example/sitemap_products_1.xml?from=1&to=9",
        "https://shop.example/sitemap_extra.xml",
    ]
    assert catalogue.sitemaps_from_robots("") == []
    assert catalogue.sitemaps_from_robots(None) == []


def test_product_urls_with_images():
    urls = catalogue.product_urls_with_images(IMAGE_SITEMAP_XML)
    assert "https://shop.example/gold-bracelet.html" in urls
    assert "https://shop.example/about-us" not in urls
    assert len(urls) == 2


def test_collect_uses_robots_declared_sitemaps():
    # No /sitemap.xml at all -- discovery must come from robots.txt.
    get = fake_get({
        "https://shop.example/sitemap_products_1.xml?from=1&to=9": PRODUCTS_XML,
        "https://shop.example/sitemap_extra.xml": COLLECTIONS_XML,
    })
    get_text = lambda url: ROBOTS_TXT if url.endswith("/robots.txt") else None
    res = catalogue.collect(get, "https://shop.example", get_text=get_text)
    assert res["ok"] is True and res["product_count"] == 3


def test_collect_image_entry_fallback_when_paths_undercount():
    get = fake_get({"https://shop.example/sitemap.xml": IMAGE_SITEMAP_XML})
    res = catalogue.collect(get, "https://shop.example")
    # Zero /products/ paths, but two image-bearing entries -> the fallback wins.
    assert res["ok"] is True and res["product_count"] == 2
    assert "gold-bracelet.html" in res["handles"]


def test_collect_path_heuristic_still_preferred():
    # When the path heuristic finds MORE products than image entries, keep it.
    get = fake_get({
        "https://shop.example/sitemap.xml": INDEX_XML,
        "https://shop.example/sitemap_products_1.xml?from=1&to=9": PRODUCTS_XML,
        "https://shop.example/sitemap_collections_1.xml": COLLECTIONS_XML,
    })
    res = catalogue.collect(get, "https://shop.example")
    assert res["product_count"] == 3 and "gold-bracelet" in res["handles"]


def test_build_from_results_matches_build():
    # build() is now a thin wrapper: collect per brand, then build_from_results.
    import tempfile
    brands = [{"name": "Shop", "slug": "shop", "url": "https://shop.example"}]
    get = fake_get({
        "https://shop.example/sitemap.xml": INDEX_XML,
        "https://shop.example/sitemap_products_1.xml?from=1&to=9": PRODUCTS_XML,
    })
    with tempfile.TemporaryDirectory() as tmp:
        old_cat, old_snap = catalogue.CATALOGUE_PATH, catalogue.SNAPSHOT_PATH
        catalogue.CATALOGUE_PATH = os.path.join(tmp, "catalogue.json")
        catalogue.SNAPSHOT_PATH = os.path.join(tmp, "snapshot.json")
        try:
            run = catalogue.build(get, brands, date="2026-07-01")
            assert run["brands"]["shop"]["ok"] is True
            assert run["brands"]["shop"]["product_count"] == 3
            assert run["brands"]["shop"]["first_seen"] is True
            # Second day via build_from_results directly, one new handle.
            res = catalogue.collect(get, "https://shop.example")
            res["handles"] = res["handles"] + ["new-charm"]
            res["product_count"] += 1
            run2 = catalogue.build_from_results({"shop": res}, brands, date="2026-07-02")
            assert run2["brands"]["shop"]["new_count"] == 1
        finally:
            catalogue.CATALOGUE_PATH, catalogue.SNAPSHOT_PATH = old_cat, old_snap


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
