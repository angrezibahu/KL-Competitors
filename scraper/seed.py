"""
Generate clearly-labelled SAMPLE data + placeholder screenshots so the
dashboard is fully explorable before the first real capture runs.

Every record produced here has  "sample": true  and the dashboard shows a
"SAMPLE DATA" banner until real captures arrive. Run:  python -m scraper.seed
"""

import json
import os
import random
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

from . import storage
from .colours import dominant_colours

random.seed(7)

BRANDS = [
    ("Katie Loxton", "katie-loxton", (244, 214, 205), True),
    ("Strathberry", "strathberry", (30, 30, 34), False),
    ("DeMellier", "demellier", (210, 225, 215), False),
    ("Charles & Keith", "charles-keith", (235, 232, 228), False),
    ("Polene", "polene", (212, 175, 55), False),
    ("Oliver Bonas", "oliver-bonas", (230, 90, 150), False),
    ("Mint Velvet", "mint-velvet", (40, 55, 95), False),
]

HEROES = [
    "Up to 50% Off Summer Sale", "New In: Summer Edit", "The Friendship Edit",
    "Personalised Just For You", "Free UK Delivery Over £40",
    "Birthstone Jewellery", "Summer Brights Have Landed", "Bestsellers Restocked",
]
OFFER_SETS = [
    (["up to 50% off", "summer sale"], "up to 50% off", 50),
    (["20% off", "flash sale"], "20% off", 20),
    ([], None, None),
    (["free gift", "gift with purchase"], "free gift", None),
    (["up to 30% off", "mid-season sale"], "up to 30% off", 30),
]
DELIVERIES = [
    ["free uk delivery over £40", "next day delivery", "order by 3pm"],
    ["free delivery over £50", "click and collect"],
    ["next day delivery"],
]
CODES = [["SUMMER20"], ["TREAT15"], [], ["WELCOME10"]]
CATS = ["bracelets", "necklaces", "earrings", "anklets", "rings",
        "charms", "personalised", "birthday", "friendship", "sentiment"]
KW_POOL = ["summer", "sale", "bracelet", "necklace", "gift", "personalised",
           "birthday", "friendship", "gold", "silver", "anklet", "charm",
           "new", "edit", "delivery", "bestseller", "pearl", "birthstone"]


# Mirrors the checks/weights in extractors.extract_accessibility so the sample
# scores look like the real thing before any live capture has run.
A11Y_CHECKS = [
    ("html_lang", "Page language declared (<html lang>)", 10),
    ("doc_title", "Document has a <title>", 8),
    ("viewport", "Responsive viewport meta tag", 6),
    ("img_alt", "Images have alt attributes", 20),
    ("link_text", "Links have discernible text", 15),
    ("button_name", "Buttons have accessible names", 8),
    ("form_labels", "Form fields have labels", 8),
    ("headings", "Clear heading structure (single H1)", 10),
    ("landmarks", "Landmark regions (main, nav)", 8),
    ("skip_link", "Skip-to-content link", 3),
]


def sample_accessibility():
    checks = []
    for cid, label, weight in A11Y_CHECKS:
        if cid in ("html_lang", "doc_title", "viewport"):
            ratio = 1.0 if random.random() > 0.12 else 0.0
        elif cid == "skip_link":
            ratio = 1.0 if random.random() > 0.6 else 0.0
        elif cid == "headings":
            ratio = random.choice([1.0, 1.0, 0.5])
        elif cid == "landmarks":
            ratio = random.choice([1.0, 1.0, 0.5])
        else:  # measured ratios (alt text, links, buttons, labels)
            ratio = round(random.uniform(0.55, 1.0), 3)
        checks.append({
            "id": cid, "label": label, "weight": weight,
            "ratio": ratio, "passed": ratio >= 0.9,
            "applicable": True, "detail": "sample",
        })
    total_w = sum(c["weight"] for c in checks)
    earned = sum(c["weight"] * c["ratio"] for c in checks)
    score = round(earned / total_w * 100)
    grade = ("A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70
             else "D" if score >= 60 else "E" if score >= 50 else "F")
    imgs = random.randint(20, 80)
    links = random.randint(60, 200)
    return {
        "score": score, "grade": grade, "checks": checks,
        "images_total": imgs, "images_with_alt": random.randint(int(imgs * 0.6), imgs),
        "links_total": links, "links_with_text": random.randint(int(links * 0.7), links),
    }


def make_screenshot(path, name, rgb):
    img = Image.new("RGB", (480, 640), rgb)
    d = ImageDraw.Draw(img)
    # simple banded "page" look
    d.rectangle([0, 0, 480, 80], fill=tuple(min(255, c + 20) for c in rgb))
    d.rectangle([40, 220, 440, 300], fill=(255, 255, 255))
    d.text((60, 30), name, fill=(60, 60, 60))
    d.text((60, 250), "SAMPLE homepage", fill=(120, 120, 120))
    for i in range(3):
        d.rectangle([40 + i * 140, 360, 150 + i * 140, 520],
                    fill=tuple(max(0, c - 15) for c in rgb))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "JPEG", quality=70)


def build():
    storage.ensure_dirs()
    today = datetime.now(timezone.utc).date()
    records = []
    for back in range(6, -1, -1):           # 7 days of history
        day = today - timedelta(days=back)
        date = day.strftime("%Y-%m-%d")
        for name, slug, rgb, is_self in BRANDS:
            shot_rel = os.path.join("screenshots", slug, f"{date}.jpg")
            shot_abs = os.path.join(storage.DOCS, shot_rel)
            make_screenshot(shot_abs, name, rgb)

            offers, headline, pct = random.choice(OFFER_SETS)
            mix_cats = random.sample(CATS, random.randint(4, 7))
            counts = {c: random.randint(2, 18) for c in mix_cats}
            total = sum(counts.values())
            product_mix = {c: {"count": n, "share": round(n / total, 4)}
                           for c, n in sorted(counts.items(), key=lambda kv: -kv[1])}
            kws = random.sample(KW_POOL, 12)
            keywords = [[w, random.randint(2, 15)] for w in kws]
            keywords.sort(key=lambda x: -x[1])

            lo = random.choice([15, 19, 25, 35, 45])
            band = [round(random.uniform(lo, lo * random.uniform(3, 9)), 2)
                    for _ in range(random.randint(8, 20))]
            band.sort()
            prices = {"count": len(band), "currency": "GBP", "min": band[0],
                      "median": band[len(band) // 2], "max": band[-1], "sample": band[:30]}

            # Sample homepage trading signals (conversion levers).
            fin_pool = random.sample(
                ["Klarna", "Clearpay", "Laybuy", "PayPal", "Apple Pay", "Google Pay"],
                random.randint(2, 5))
            trading = {
                "finance": fin_pool,
                "has_bnpl": any(f in {"Klarna", "Clearpay", "Laybuy", "Afterpay"} for f in fin_pool),
                "email_capture_offer": random.choice(["10% off", "15% off", "£5 off", None]),
                "free_delivery_threshold": random.choice([0, 25, 30, 40, 50, None]),
                "scarcity": random.choice([[], ["selling fast"], ["low in stock"], ["only 3 left"]]),
            }

            # Sample reputation / social-proof signals (homepage trust pillar).
            rep_platforms = random.sample(
                ["Trustpilot", "Yotpo", "Okendo", "Reviews.io", "Judge.me", "Feefo"],
                random.randint(0, 2))
            if rep_platforms or random.random() < 0.8:
                reputation = {
                    "rating": round(random.uniform(4.2, 4.95), 2),
                    "review_count": random.choice(
                        [random.randint(120, 900), random.randint(1000, 18000)]),
                    "platforms": rep_platforms,
                    "has_reviews": True,
                    "source": random.choice(["structured", "text"]),
                }
            else:
                reputation = {"rating": None, "review_count": None,
                              "platforms": [], "has_reviews": False, "source": None}

            # Sample marketplace presence (off-site channels, homepage-declared).
            # The owned brand is deliberately given no owned channel so the demo
            # shows the Marketplace opportunity; the pack varies.
            if is_self:
                amazon_state, tk_state = "none", "none"
            else:
                amazon_state = random.choice(["official", "official", "linked", "mentioned", "none"])
                tk_state = random.choice(["shop", "shop", "social", "none"])
            handle = "@" + slug.replace("-", "")
            marketplace = {
                "amazon": {
                    "state": amazon_state,
                    "url": (f"https://www.amazon.co.uk/stores/{slug}" if amazon_state == "official"
                            else f"https://www.amazon.co.uk/s?k={slug}" if amazon_state == "linked"
                            else None),
                },
                "tiktok": {
                    "state": tk_state,
                    "handle": handle if tk_state in ("shop", "social") else None,
                    "url": (f"https://www.tiktok.com/{handle}/shop" if tk_state == "shop"
                            else f"https://www.tiktok.com/{handle}" if tk_state == "social"
                            else None),
                },
            }

            # Sample listing-page trading data (real price distribution + sale depth).
            llo = random.choice([15, 19, 25, 35])
            lband = sorted(round(random.uniform(llo, llo * random.uniform(3, 10)), 2)
                           for _ in range(random.randint(18, 40)))
            n = len(lband)
            on_sale = random.randint(0, n // 2)
            listing = {
                "url": f"https://example.com/{slug}/collections/all",
                "products_seen": n,
                "prices": {
                    "count": n, "currency": "GBP", "min": lband[0],
                    "p25": lband[n // 4], "median": lband[n // 2],
                    "p75": lband[(3 * n) // 4], "max": lband[-1], "sample": lband[:40],
                },
                "on_sale_count": on_sale,
                "discounted_share": round(on_sale / n, 3),
                "sale_pairs": [],
                "new_in_mentions": random.randint(0, 6),
            }

            records.append({
                "date": date,
                "captured_at": day.strftime("%Y-%m-%dT08:") + f"{random.randint(0, 9):02d}:00Z",
                "brand": name, "slug": slug, "url": f"https://example.com/{slug}",
                "is_self": is_self, "sample": True,
                "status": "success", "error": None,
                "hero_message": random.choice(HEROES),
                "offers": offers, "headline_offer": headline, "max_discount_pct": pct,
                "delivery": random.choice(DELIVERIES),
                "discount_codes": random.choice(CODES),
                "product_mix": product_mix,
                "keywords": keywords,
                "prices": prices,
                "trading": trading,
                "reputation": reputation,
                "marketplace": marketplace,
                "listing": listing,
                "colours": dominant_colours(shot_abs),
                "seo": {
                    "title": f"{name} | Jewellery & Gifts",
                    "title_length": len(name) + 18,
                    "meta_description": f"Shop {name} bracelets, necklaces and personalised gifts.",
                    "meta_description_length": random.randint(110, 158),
                    "h1": [random.choice(HEROES)], "h1_count": 1,
                    "h2_count": random.randint(4, 12),
                    "structured_data_types": random.sample(
                        ["Organization", "WebSite", "BreadcrumbList", "Product"], 2),
                    "word_count": random.randint(400, 1600),
                    "image_count": random.randint(20, 80),
                    "internal_link_count": random.randint(80, 220),
                    "canonical": f"https://example.com/{slug}/",
                },
                "accessibility": sample_accessibility(),
                "screenshot": shot_rel,
            })

    storage.append_captures(records)
    with open(os.path.join(storage.DATA_DIR, "trends.json"), "w", encoding="utf-8") as fh:
        json.dump({"ok": False, "error": "sample seed - no live trends yet",
                   "data": {}}, fh, indent=1)
    storage.write_run_log({
        "date": today.strftime("%Y-%m-%d"), "ran_at": storage.now_iso(),
        "brands_total": len(BRANDS), "succeeded": len(BRANDS), "failed": 0,
        "failed_brands": [], "trends_ok": False, "sample": True,
    })
    build_aio_sample(today)
    build_catalogue_sample(today)
    # Derive the events timeline + opportunities from the sample history so the
    # Opportunities tab is populated in the demo too.
    from scraper import events as _events
    _events.build()
    print(f"Seeded {len(records)} sample records across {len(BRANDS)} brands.")


def build_catalogue_sample(today):
    """Sample assortment history so the Assortment tab is populated in the demo.

    Spans ~5 monthly snapshots then the last 7 daily ones, mirroring the real
    catalogue.build() output (append-only runs + a per-brand handle snapshot).
    Category weights DRIFT month to month so the range-mix trend has something
    real to show in the demo; the most recent 7 runs are daily so 'New (7d)' and
    the range-size leaderboard read off live-looking recent data."""
    from . import catalogue as _cat
    cat_cols = ["necklaces", "bracelets", "earrings", "rings", "charms",
                "personalised", "birthday", "friendship"]
    slugs = [slug for _, slug, _, _ in BRANDS]
    w0 = {s: [random.uniform(0.06, 0.34) for _ in cat_cols] for s in slugs}      # start mix
    drift = {s: [random.uniform(-0.025, 0.025) for _ in cat_cols] for s in slugs}  # monthly drift
    cnt0 = {s: random.randint(140, 900) for s in slugs}
    handles = {s: [f"{s}-{i}" for i in range(cnt0[s])] for s in slugs}

    # Timeline: 5 monthly snapshots (progress 0..4), then 7 daily (current month).
    timeline = [(today - timedelta(days=30 * mb), 5 - mb, False) for mb in range(5, 0, -1)]
    timeline += [(today - timedelta(days=db), 5, True) for db in range(6, -1, -1)]

    runs = []
    for idx, (day, prog, is_daily) in enumerate(timeline):
        date = day.strftime("%Y-%m-%d")
        first = idx == 0
        brands_out = {}
        for s in slugs:
            if is_daily and not first:           # grow the range on recent days
                for i in range(random.randint(0, 5)):
                    handles[s].append(f"{s}-x{date}-{i}")
            count = len(handles[s]) if is_daily else int(cnt0[s] * (0.82 + 0.04 * prog))
            cats = {}
            for ci, c in enumerate(cat_cols):
                w = max(0.02, min(0.5, w0[s][ci] + drift[s][ci] * prog))
                n = int(count * w)
                if n > 0:
                    cats[c] = n
            new_count = 0 if first else random.randint(0, 5)
            brands_out[s] = {
                "product_count": count, "ok": True, "first_seen": first, "error": None,
                "new_count": new_count, "removed_count": 0,
                "new_samples": ([f"{s}-x{date}-{i}" for i in range(new_count)]
                                if (is_daily and not first) else []),
                "categories": cats,
            }
        runs.append({"date": date, "captured_at": day.strftime("%Y-%m-%dT08:12:00Z"),
                     "brands": brands_out})
    storage._write_json(_cat.CATALOGUE_PATH, {"runs": runs})
    storage._write_json(_cat.SNAPSHOT_PATH,
                        {"cur_date": today.strftime("%Y-%m-%d"), "prev": {}, "cur": handles})


# Buyer-intent queries mirrored from config/aio_queries.json (kept short here).
AIO_QUERIES = [
    ("best personalised jewellery brands in the UK for gifts", "personalised"),
    ("best UK brands for meaningful birthday jewellery gifts for her", "birthday"),
    ("good affordable jewellery brands UK for a friendship gift", "friendship"),
    ("best brands for sentimental necklaces with a meaningful message UK", "necklaces"),
    ("where to buy a nice charm bracelet as a gift in the UK", "bracelets"),
    ("best jewellery brands for a 'little something' thoughtful gift UK", "sentiment"),
]


def build_aio_sample(today):
    """Sample AI-visibility runs so the 'AI Visibility' tab is explorable before
    a real (key-gated) run. Marked sample; mirrors scraper/aio.py's shape."""
    from scraper import aio  # reuse the real scorer so sample shapes stay honest
    brands = [{"name": n, "slug": s} for n, s, *_ in BRANDS]
    runs = []
    for back in (21, 14, 7, 0):                # four weekly snapshots
        date = (today - timedelta(days=back)).strftime("%Y-%m-%d")
        query_results = []
        for q, cat in AIO_QUERIES:
            k = random.randint(2, 4)
            picked = random.sample(brands, k)
            mentions = [{"slug": b["slug"], "brand": b["name"], "rank": i + 1, "position": i * 20}
                        for i, b in enumerate(picked)]
            query_results.append({
                "query": q, "category": cat,
                "answer_excerpt": "SAMPLE answer — " + ", ".join(b["name"] for b in picked) + " recommended.",
                "sources": ["https://example.com/guide"],
                "mentions": mentions,
            })
        runs.append({
            "date": date, "ran_at": storage.now_iso(), "provider": "sample",
            "ok": True, "queries_total": len(AIO_QUERIES), "market": "UK women's / gifting jewellery",
            "sample": True, "queries": query_results,
            "share_of_voice": aio.score_share_of_voice(query_results, brands),
        })
    with open(os.path.join(storage.DATA_DIR, "aio.json"), "w", encoding="utf-8") as fh:
        json.dump({"runs": runs}, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    build()
