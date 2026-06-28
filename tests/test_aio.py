"""
Offline tests for the AIO (AI-overview visibility) parsing + scoring.
No browser, no network, no API key. Run:  python tests/test_aio.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import aio  # noqa: E402

BRANDS = [
    {"name": "Katie Loxton", "slug": "katie-loxton", "is_self": True},
    {"name": "Charles & Keith", "slug": "charles-keith"},
    {"name": "Strathberry", "slug": "strathberry"},
    {"name": "Mint Velvet", "slug": "mint-velvet"},
    {"name": "Polene", "slug": "polene"},
]


def test_extract_mentions_basic_order_and_rank():
    answer = ("For a meaningful gift I'd suggest Strathberry first, then Katie Loxton, "
              "and Mint Velvet is great for everyday.")
    hits = aio.extract_brand_mentions(answer, BRANDS)
    slugs = [h["slug"] for h in hits]
    assert slugs == ["strathberry", "katie-loxton", "mint-velvet"]
    # ranks assigned by appearance order
    assert {h["slug"]: h["rank"] for h in hits} == {"strathberry": 1, "katie-loxton": 2, "mint-velvet": 3}


def test_extract_mentions_ampersand_and_and():
    # "Charles & Keith" must match when written "Charles and Keith".
    hits = aio.extract_brand_mentions("Try Charles and Keith for everyday pieces.", BRANDS)
    assert [h["slug"] for h in hits] == ["charles-keith"]


def test_extract_mentions_word_boundary_no_false_positive():
    # 'Polene' should not be matched inside an unrelated longer word.
    hits = aio.extract_brand_mentions("The polenes were ripe and plentiful.", BRANDS)
    assert all(h["slug"] != "polene" for h in hits)


def test_extract_mentions_none():
    assert aio.extract_brand_mentions("I'd just go to a local shop.", BRANDS) == []


def test_share_of_voice_weights_rank_and_counts():
    query_results = [
        {"mentions": [{"slug": "strathberry", "rank": 1}, {"slug": "katie-loxton", "rank": 2}]},
        {"mentions": [{"slug": "katie-loxton", "rank": 1}]},
        {"mentions": []},
    ]
    sov = aio.score_share_of_voice(query_results, BRANDS)
    # Katie Loxton appears in 2/3 queries -> visibility 0.667
    assert sov["katie-loxton"]["mentions"] == 2
    assert sov["katie-loxton"]["queries"] == 3
    assert sov["katie-loxton"]["visibility"] == 0.667
    # Katie Loxton avg rank = (2 + 1)/2 = 1.5
    assert sov["katie-loxton"]["avg_rank"] == 1.5
    # Katie Loxton points = 1/2 + 1/1 = 1.5; Strathberry points = 1/1 = 1.0 -> Katie Loxton higher SoV
    assert sov["katie-loxton"]["sov"] > sov["strathberry"]["sov"]
    # A brand never mentioned has zero everywhere and no avg rank
    assert sov["polene"]["mentions"] == 0
    assert sov["polene"]["sov"] == 0.0
    assert sov["polene"]["avg_rank"] is None
    # Shares across mentioned brands sum to ~1
    assert abs(sum(v["sov"] for v in sov.values()) - 1.0) < 0.01


def test_share_of_voice_empty_is_graceful():
    sov = aio.score_share_of_voice([], BRANDS)
    assert sov["katie-loxton"]["visibility"] == 0.0
    assert sov["katie-loxton"]["queries"] == 0


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
