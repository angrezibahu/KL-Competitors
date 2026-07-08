"""
Offline tests for the events timeline + opportunities rules.
No browser, no network. Run:  python tests/test_events.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import events  # noqa: E402


def cap(slug, date, brand=None, is_self=False, **fields):
    base = {"slug": slug, "date": date, "brand": brand or slug.title(),
            "is_self": is_self, "status": "success"}
    base.update(fields)
    return base


def test_events_sale_start_and_discount_change():
    caps = [
        cap("missoma", "2026-06-01", headline_offer=None, max_discount_pct=None),
        cap("missoma", "2026-06-02", headline_offer="up to 20% off", max_discount_pct=20),
        cap("missoma", "2026-06-03", headline_offer="up to 30% off", max_discount_pct=30),
    ]
    evs = events.compute_events(caps)
    types = {e["type"] for e in evs}
    assert "sale_started" in types
    assert "discount_changed" in types
    # newest first
    assert evs[0]["date"] >= evs[-1]["date"]


def test_events_hero_code_and_bnpl():
    caps = [
        cap("katie-loxton", "2026-06-01", hero_message="A little gift", discount_codes=[],
            trading={"finance": ["PayPal"]}),
        cap("katie-loxton", "2026-06-02", hero_message="Summer Sale", discount_codes=["SUMMER20"],
            trading={"finance": ["PayPal", "Klarna"]}),
    ]
    evs = events.compute_events(caps)
    types = {e["type"] for e in evs}
    assert "hero_changed" in types
    assert "code_added" in types
    assert "bnpl_added" in types  # Klarna appeared


def test_events_price_shift_uses_listing_median():
    caps = [
        cap("x", "2026-06-01", listing={"prices": {"median": 40}}),
        cap("x", "2026-06-02", listing={"prices": {"median": 50}}),  # +25% >= 15%
    ]
    evs = events.compute_events(caps)
    assert any(e["type"] == "price_shift" for e in evs)
    # a small move should NOT fire
    caps2 = [
        cap("y", "2026-06-01", listing={"prices": {"median": 40}}),
        cap("y", "2026-06-02", listing={"prices": {"median": 42}}),  # +5%
    ]
    assert not any(e["type"] == "price_shift" for e in events.compute_events(caps2))


def test_opportunities_promo_and_bnpl_gap():
    caps = [
        cap("katie-loxton", "2026-06-03", is_self=True, headline_offer=None, max_discount_pct=None,
            trading={"finance": ["PayPal"]}),
        cap("a", "2026-06-03", headline_offer="20% off", max_discount_pct=20,
            trading={"finance": ["Klarna"]}),
        cap("b", "2026-06-03", headline_offer="30% off", max_discount_pct=30,
            trading={"finance": ["Clearpay"]}),
        cap("c", "2026-06-03", headline_offer="25% off", max_discount_pct=25,
            trading={"finance": ["Klarna"]}),
    ]
    opps = events.compute_opportunities(caps)
    kinds = {o["kind"] for o in opps}
    assert "promo" in kinds        # Katie Loxton not discounting, pack is
    assert "finance" in kinds      # pack has BNPL, Katie Loxton doesn't
    # high-priority items sort first
    assert opps[0]["priority"] == "high"


def test_opportunities_ai_visibility_gap():
    caps = [
        cap("katie-loxton", "2026-06-03", is_self=True),
        cap("a", "2026-06-03"),
    ]
    aio = {"runs": [{
        "queries": [
            {"query": "best friendship jewellery uk",
             "mentions": [{"slug": "a", "brand": "A", "rank": 1}]},  # Katie Loxton absent
        ],
    }]}
    opps = events.compute_opportunities(caps, aio)
    assert any(o["kind"] == "ai_visibility" for o in opps)


def test_events_reputation_rating_and_platform():
    caps = [
        cap("missoma", "2026-06-01", reputation={"rating": 4.5, "platforms": ["Yotpo"]}),
        cap("missoma", "2026-06-02", reputation={"rating": 4.8, "platforms": ["Yotpo", "Trustpilot"]}),
    ]
    evs = events.compute_events(caps)
    types = {e["type"] for e in evs}
    assert "rating_changed" in types       # 4.5 -> 4.8 is >= 0.2
    assert "reviews_added" in types        # Trustpilot widget appeared
    # a tiny rating move should NOT fire
    caps2 = [
        cap("x", "2026-06-01", reputation={"rating": 4.5, "platforms": []}),
        cap("x", "2026-06-02", reputation={"rating": 4.55, "platforms": []}),
    ]
    assert not any(e["type"] == "rating_changed" for e in events.compute_events(caps2))


def test_opportunities_reputation_gap_when_pack_rates_higher():
    caps = [
        cap("katie-loxton", "2026-06-03", is_self=True, reputation={"rating": 4.2, "platforms": []}),
        cap("a", "2026-06-03", reputation={"rating": 4.8, "platforms": ["Trustpilot"]}),
        cap("b", "2026-06-03", reputation={"rating": 4.7, "platforms": ["Yotpo"]}),
        cap("c", "2026-06-03", reputation={"rating": 4.9, "platforms": ["Okendo"]}),
    ]
    opps = events.compute_opportunities(caps)
    assert any(o["kind"] == "reputation" for o in opps)


def test_opportunities_reputation_gap_when_self_shows_none():
    caps = [
        cap("katie-loxton", "2026-06-03", is_self=True, reputation={"rating": None, "platforms": []}),
        cap("a", "2026-06-03", reputation={"rating": 4.8, "platforms": ["Trustpilot"]}),
        cap("b", "2026-06-03", reputation={"rating": 4.7, "platforms": ["Yotpo"]}),
    ]
    opps = events.compute_opportunities(caps)
    rep = [o for o in opps if o["kind"] == "reputation"]
    assert rep and "isn't detected" in rep[0]["title"]


def test_catalogue_events_skip_first_seen_and_subthreshold():
    cat = {"runs": [
        {"date": "2026-06-01", "brands": {
            "a": {"ok": True, "first_seen": True, "new_count": 0, "product_count": 100}}},
        {"date": "2026-06-02", "brands": {
            "a": {"ok": True, "first_seen": False, "new_count": 4, "product_count": 104},
            "b": {"ok": True, "first_seen": False, "new_count": 1, "product_count": 50}}},
    ]}
    evs = events.compute_catalogue_events(cat, {"a": "Brand A", "b": "Brand B"})
    texts = " ".join(e["text"] for e in evs)
    assert "Brand A added 4 new products" in texts   # >= threshold of 2
    assert "Brand B" not in texts                     # only +1, below threshold
    assert all(e["type"] == "products_added" for e in evs)


def test_opportunities_assortment_shortfall():
    caps = [
        cap("katie-loxton", "2026-06-03", is_self=True),
        cap("a", "2026-06-03"),
        cap("b", "2026-06-03"),
    ]
    cat = {"runs": [{"date": "2026-06-03", "brands": {
        "katie-loxton": {"ok": True, "product_count": 90},
        "a": {"ok": True, "product_count": 400},
        "b": {"ok": True, "product_count": 500},
    }}]}
    opps = events.compute_opportunities(caps, catalogue=cat)
    assert any(o["kind"] == "assortment" for o in opps)
    # If Katie Loxton's range is healthy vs the pack, no assortment gap fires.
    cat2 = {"runs": [{"date": "2026-06-03", "brands": {
        "katie-loxton": {"ok": True, "product_count": 450},
        "a": {"ok": True, "product_count": 400},
        "b": {"ok": True, "product_count": 500},
    }}]}
    assert not any(o["kind"] == "assortment"
                   for o in events.compute_opportunities(caps, catalogue=cat2))


def test_opportunities_category_mix_gap():
    caps = [
        cap("katie-loxton", "2026-06-03", is_self=True),
        cap("a", "2026-06-03"),
        cap("b", "2026-06-03"),
    ]
    # Pack's range is ~40% charms; Katie Loxton's is ~3% -> a clear mix gap.
    cat = {"runs": [{"date": "2026-06-03", "brands": {
        "katie-loxton": {"ok": True, "product_count": 100, "categories": {"charms": 3, "necklaces": 50}},
        "a": {"ok": True, "product_count": 100, "categories": {"charms": 40, "necklaces": 30}},
        "b": {"ok": True, "product_count": 100, "categories": {"charms": 42, "necklaces": 28}},
    }}]}
    opps = events.compute_opportunities(caps, catalogue=cat)
    mix = [o for o in opps if o["kind"] == "assortment_mix"]
    assert mix and "charms" in mix[0]["title"]
    # When Katie Loxton matches the pack, no mix gap fires.
    cat2 = {"runs": [{"date": "2026-06-03", "brands": {
        "katie-loxton": {"ok": True, "product_count": 100, "categories": {"charms": 38, "necklaces": 40}},
        "a": {"ok": True, "product_count": 100, "categories": {"charms": 40, "necklaces": 30}},
        "b": {"ok": True, "product_count": 100, "categories": {"charms": 42, "necklaces": 28}},
    }}]}
    assert not any(o["kind"] == "assortment_mix"
                   for o in events.compute_opportunities(caps, catalogue=cat2))


def test_opportunities_empty_is_graceful():
    assert events.compute_opportunities([]) == []
    # No Katie Loxton record -> nothing to compare.
    assert events.compute_opportunities([cap("a", "2026-06-03")]) == []


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
