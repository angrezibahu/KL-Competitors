"""
Offline tests for the AIO (AI-overview visibility) parsing + scoring.
No browser, no network, no API key. Run:  python tests/test_aio.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import aio  # noqa: E402

BRANDS = [
    {"name": "Joma Jewellery", "slug": "joma", "is_self": True},
    {"name": "Astrid & Miyu", "slug": "astrid-miyu"},
    {"name": "Missoma", "slug": "missoma"},
    {"name": "Katie Loxton", "slug": "katie-loxton"},
    {"name": "Pandora", "slug": "pandora"},
]


def test_extract_mentions_basic_order_and_rank():
    answer = ("For meaningful gifts I'd suggest Missoma first, then Joma Jewellery, "
              "and Katie Loxton is great for sentiment.")
    hits = aio.extract_brand_mentions(answer, BRANDS)
    slugs = [h["slug"] for h in hits]
    assert slugs == ["missoma", "joma", "katie-loxton"]
    # ranks assigned by appearance order
    assert {h["slug"]: h["rank"] for h in hits} == {"missoma": 1, "joma": 2, "katie-loxton": 3}


def test_extract_mentions_ampersand_and_and():
    # "Astrid & Miyu" must match when written "Astrid and Miyu".
    hits = aio.extract_brand_mentions("Try Astrid and Miyu for everyday pieces.", BRANDS)
    assert [h["slug"] for h in hits] == ["astrid-miyu"]


def test_extract_mentions_word_boundary_no_false_positive():
    # 'Pandora' should not be matched inside an unrelated longer word.
    hits = aio.extract_brand_mentions("The pandoras box of options is huge.", BRANDS)
    assert all(h["slug"] != "pandora" for h in hits)


def test_extract_mentions_none():
    assert aio.extract_brand_mentions("I'd just go to a local shop.", BRANDS) == []


def test_share_of_voice_weights_rank_and_counts():
    query_results = [
        {"mentions": [{"slug": "missoma", "rank": 1}, {"slug": "joma", "rank": 2}]},
        {"mentions": [{"slug": "joma", "rank": 1}]},
        {"mentions": []},
    ]
    sov = aio.score_share_of_voice(query_results, BRANDS)
    # Joma appears in 2/3 queries -> visibility 0.667
    assert sov["joma"]["mentions"] == 2
    assert sov["joma"]["queries"] == 3
    assert sov["joma"]["visibility"] == 0.667
    # Joma avg rank = (2 + 1)/2 = 1.5
    assert sov["joma"]["avg_rank"] == 1.5
    # Joma points = 1/2 + 1/1 = 1.5; Missoma points = 1/1 = 1.0 -> Joma has higher SoV
    assert sov["joma"]["sov"] > sov["missoma"]["sov"]
    # A brand never mentioned has zero everywhere and no avg rank
    assert sov["pandora"]["mentions"] == 0
    assert sov["pandora"]["sov"] == 0.0
    assert sov["pandora"]["avg_rank"] is None
    # Shares across mentioned brands sum to ~1
    assert abs(sum(v["sov"] for v in sov.values()) - 1.0) < 0.01


def test_share_of_voice_empty_is_graceful():
    sov = aio.score_share_of_voice([], BRANDS)
    assert sov["joma"]["visibility"] == 0.0
    assert sov["joma"]["queries"] == 0


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
