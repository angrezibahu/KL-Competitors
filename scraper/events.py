"""
Turn the accumulating capture history into two things you can act on:

  1. an EVENTS TIMELINE  -- a dated, permanent record of what *changed*
     (sales starting/ending, discounts moving, heroes rewritten, new codes,
     BNPL appearing, price bands shifting). The weekly digest already computes
     week-on-week diffs and then throws them away; this persists them across the
     whole history so "when did everyone go on sale last summer?" is answerable.

  2. an OPPORTUNITIES list -- deterministic rules over the latest snapshot that
     surface concrete, actionable gaps, framed owned-brand-vs-pack (the owned
     brand is whichever capture is flagged `is_self`, so the copy uses its real
     name, e.g. Katie Loxton):
     "3 competitors show Klarna, Katie Loxton doesn't", "the pack's avg discount
     is 28% and Katie Loxton is flat", "competitors are named in AI answers for a
     buyer-intent query and Katie Loxton isn't".

Both are PURE derivations of data we already have -- no new scraping. Everything
here is (data in, data out) so it is unit-tested offline. Output is recomputed
from the full history each run (idempotent), written to docs/data/events.json.

Run:  python -m scraper.events
"""

import json
import os

from . import storage

AIO_PATH = os.path.join(storage.DATA_DIR, "aio.json")
CATALOGUE_PATH = os.path.join(storage.DATA_DIR, "catalogue.json")
EVENTS_PATH = os.path.join(storage.DATA_DIR, "events.json")

PRICE_SHIFT_PCT = 0.15        # flag a median price move of >= 15%
BNPL = {"Klarna", "Clearpay", "Laybuy", "Afterpay"}

# Marketplace states that count as "a channel is surfaced on the homepage".
MARKETPLACE_PRESENT = {"official", "linked", "mentioned", "shop", "social"}
# The states that count as a brand-OWNED channel (vs a bare mention) per market.
MARKETPLACE_OWNED = {"amazon": {"official", "linked"}, "tiktok": {"shop", "social"}}
# Marketplace presence is homepage-DECLARED only, so it false-negatives a channel
# a brand runs but doesn't link from its homepage (e.g. Katie Loxton on Amazon). Until
# detection is accurate (config-declared known URLs + stockists-page scan), we keep
# the rule/event code + tests but DON'T surface them on the live dashboard, so the
# Opportunities tab never claims "Katie Loxton shows none" for a channel we know exists.
SHOW_MARKETPLACE = False


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------

def _ok(captures):
    return [r for r in captures if r.get("status") == "success"]


def _by_brand_sorted(captures):
    out = {}
    for r in sorted(_ok(captures), key=lambda x: x.get("date", "")):
        out.setdefault(r["slug"], []).append(r)
    return out


def _latest_per_brand(captures):
    out = {}
    for r in sorted(_ok(captures), key=lambda x: x.get("date", "")):
        out[r["slug"]] = r            # last (newest) wins
    return out


def _median(rec):
    """Best available median price: prefer real listing data, else homepage."""
    listing = (rec.get("listing") or {}).get("prices") or {}
    if listing.get("median") is not None:
        return listing["median"]
    return (rec.get("prices") or {}).get("median")


def _finance(rec):
    return set((rec.get("trading") or {}).get("finance") or [])


def _rating(rec):
    return (rec.get("reputation") or {}).get("rating")


REPUTATION_SHIFT = 0.2        # flag a homepage rating move of >= 0.2 stars


# ---------------------------------------------------------------------------
# Events timeline (pure)
# ---------------------------------------------------------------------------

def compute_events(captures):
    """Diff each brand's consecutive successful captures into dated change events.

    Returns a list of {date, slug, brand, type, text} newest-first."""
    events = []
    for slug, recs in _by_brand_sorted(captures).items():
        for prev, cur in zip(recs, recs[1:]):
            brand = cur.get("brand", slug)
            date = cur.get("date")

            def add(etype, text):
                events.append({"date": date, "slug": slug, "brand": brand,
                               "type": etype, "text": text})

            # Sale starting / ending.
            had = bool(prev.get("headline_offer"))
            has = bool(cur.get("headline_offer"))
            if has and not had:
                add("sale_started", f"{brand} started a sale: {cur.get('headline_offer')}")
            elif had and not has:
                add("sale_ended", f"{brand} ended its sale")
            else:
                pd, cd = prev.get("max_discount_pct") or 0, cur.get("max_discount_pct") or 0
                if cd and cd != pd:
                    arrow = "deepened" if cd > pd else "eased"
                    add("discount_changed", f"{brand} discount {arrow} {pd}% → {cd}%")

            # Hero rewrite.
            if (cur.get("hero_message") or "") != (prev.get("hero_message") or "") and cur.get("hero_message"):
                add("hero_changed", f"{brand} changed its hero to “{cur.get('hero_message')}”")

            # New discount codes.
            for code in set(cur.get("discount_codes") or []) - set(prev.get("discount_codes") or []):
                add("code_added", f"{brand} new code: {code}")

            # BNPL / finance appearing or disappearing.
            new_fin = _finance(cur) - _finance(prev)
            gone_fin = _finance(prev) - _finance(cur)
            for f in sorted(new_fin & BNPL):
                add("bnpl_added", f"{brand} added {f} (buy-now-pay-later)")
            for f in sorted(gone_fin & BNPL):
                add("bnpl_removed", f"{brand} dropped {f}")

            # Reputation: homepage rating moving, or a review platform appearing.
            pr, cr = _rating(prev), _rating(cur)
            if pr and cr and abs(cr - pr) >= REPUTATION_SHIFT:
                arrow = "up" if cr > pr else "down"
                add("rating_changed",
                    f"{brand} homepage rating moved {arrow} {pr}★ → {cr}★")
            prev_plat = set((prev.get("reputation") or {}).get("platforms") or [])
            cur_plat = set((cur.get("reputation") or {}).get("platforms") or [])
            for p in sorted(cur_plat - prev_plat):
                add("reviews_added", f"{brand} added a {p} review widget to its homepage")

            # Marketplace presence: an off-site channel (Amazon / TikTok)
            # appearing on, or vanishing from, the homepage. Hidden from the live
            # dashboard (SHOW_MARKETPLACE) until detection is accurate.
            for mk, label in (("amazon", "Amazon"), ("tiktok", "TikTok")) if SHOW_MARKETPLACE else ():
                ps = ((prev.get("marketplace") or {}).get(mk) or {}).get("state")
                cs = ((cur.get("marketplace") or {}).get(mk) or {}).get("state")
                if cs in MARKETPLACE_PRESENT and ps not in MARKETPLACE_PRESENT:
                    add("marketplace_added",
                        f"{brand} surfaced a {label} channel on its homepage ({cs})")
                elif ps in MARKETPLACE_PRESENT and cs not in MARKETPLACE_PRESENT:
                    add("marketplace_removed",
                        f"{brand} no longer surfaces a {label} channel")

            # Price-band shift (uses real listing median when present).
            pm, cm = _median(prev), _median(cur)
            if pm and cm and pm > 0:
                change = (cm - pm) / pm
                if abs(change) >= PRICE_SHIFT_PCT:
                    arrow = "up" if change > 0 else "down"
                    add("price_shift",
                        f"{brand} median price moved {arrow} £{pm} → £{cm} ({round(change * 100):+d}%)")

    events.sort(key=lambda e: (e["date"], e["slug"]), reverse=True)
    return events


# ---------------------------------------------------------------------------
# Opportunities (pure, rules-based)
# ---------------------------------------------------------------------------

def _latest_aio(aio):
    runs = (aio or {}).get("runs") or []
    return runs[-1] if runs else None


# ---------------------------------------------------------------------------
# Catalogue / assortment (pure) — built on the product-sitemap snapshots
# ---------------------------------------------------------------------------

CATALOGUE_NEW_MIN = 2          # only log a drop of >= 2 new products (cut noise)
ASSORTMENT_SHORTFALL = 0.5     # flag the owned brand's range being <= half the pack median


def compute_catalogue_events(catalogue, names=None):
    """Dated 'added N new products' events from each catalogue run.

    Skips a brand's first_seen day (no prior snapshot => no real velocity) and
    sub-threshold churn. `names` maps slug -> display brand name."""
    names = names or {}
    events = []
    for run in (catalogue or {}).get("runs") or []:
        date = run.get("date")
        for slug, b in (run.get("brands") or {}).items():
            if not b.get("ok") or b.get("first_seen"):
                continue
            n = b.get("new_count") or 0
            if n >= CATALOGUE_NEW_MIN:
                brand = names.get(slug, slug)
                events.append({"date": date, "slug": slug, "brand": brand,
                               "type": "products_added",
                               "text": f"{brand} added {n} new products to its range"})
    return events


def _latest_catalogue(catalogue):
    runs = (catalogue or {}).get("runs") or []
    return runs[-1] if runs else None


def _catalogue_count(run, slug):
    b = (run.get("brands") or {}).get(slug) if run else None
    return b.get("product_count") if b and b.get("ok") else None


def _cat_shares(run, slug):
    """Per-category share of a brand's own catalogue, or None if unavailable.

    A handle can fall in several categories, so shares are 'of the range' and
    need not sum to 1."""
    b = (run.get("brands") or {}).get(slug) if run else None
    if not b or not b.get("ok"):
        return None
    cats = b.get("categories") or {}
    total = b.get("product_count") or 0
    if not cats or total <= 0:
        return None
    return {c: n / total for c, n in cats.items()}


def compute_opportunities(captures, aio=None, catalogue=None):
    """Deterministic, actionable gaps from the latest snapshot, owned-brand-vs-pack.

    The owned brand is whichever capture is flagged `is_self` in the config, so
    every line below is phrased with that brand's real name (never hard-coded).
    Returns a list of {priority, kind, title, detail}, highest priority first.
    Each rule degrades gracefully when its inputs are missing."""
    latest = _latest_per_brand(captures)
    if not latest:
        return []
    recs = list(latest.values())
    self_brand = next((r for r in recs if r.get("is_self")), None)
    if not self_brand:
        return []
    others = [r for r in recs if not r.get("is_self")]
    if not others:
        return []
    self_name = self_brand.get("brand") or "the brand"

    opps = []

    def add(priority, kind, title, detail):
        opps.append({"priority": priority, "kind": kind, "title": title, "detail": detail})

    # 1. Promotional pressure: pack discounting, the owned brand not.
    on_sale = [r for r in others if r.get("headline_offer")]
    disc = [r.get("max_discount_pct") for r in others if r.get("max_discount_pct")]
    avg_disc = round(sum(disc) / len(disc)) if disc else 0
    if not self_brand.get("headline_offer") and len(on_sale) >= max(2, len(others) // 3):
        add("high", "promo",
            f"{len(on_sale)}/{len(others)} competitors are running an offer — {self_name} isn't",
            f"Pack average headline discount is {avg_disc}%. Consider matching or a counter-message.")
    elif self_brand.get("max_discount_pct") and avg_disc and self_brand["max_discount_pct"] < avg_disc - 10:
        add("medium", "promo",
            f"{self_name}'s {self_brand['max_discount_pct']}% discount is well below the pack ({avg_disc}%)",
            f"{self_name} may be leaving promotional pressure on the table this week.")

    # 2. BNPL gap.
    self_bnpl = _finance(self_brand) & BNPL
    pack_bnpl = [r for r in others if _finance(r) & BNPL]
    if not self_bnpl and len(pack_bnpl) >= max(2, len(others) // 3):
        names = sorted({f for r in pack_bnpl for f in (_finance(r) & BNPL)})
        add("high", "finance",
            f"{len(pack_bnpl)}/{len(others)} competitors offer buy-now-pay-later — {self_name}'s homepage shows none",
            f"Seen across the pack: {', '.join(names)}. A strong conversion lever in this category.")

    # 3. Free-delivery threshold.
    def thr(r):
        return (r.get("trading") or {}).get("free_delivery_threshold")
    self_thr = thr(self_brand)
    pack_free = [r for r in others if thr(r) == 0]
    if self_thr not in (0,) and len(pack_free) >= max(2, len(others) // 3):
        add("medium", "delivery",
            f"{len(pack_free)} competitors advertise free delivery with no threshold — {self_name}'s is "
            + (f"over £{self_thr}" if self_thr else "not advertised"),
            "Free-delivery messaging is a visible basket-conversion lever.")

    # 4. Sign-up / first-order offer.
    def signup(r):
        return (r.get("trading") or {}).get("email_capture_offer")
    pack_signup = [r for r in others if signup(r)]
    if not signup(self_brand) and len(pack_signup) >= max(2, len(others) // 3):
        add("medium", "acquisition",
            f"{len(pack_signup)} competitors dangle a first-order sign-up offer — {self_name}'s isn't detected",
            "An email/SMS-capture incentive is a cheap list-growth lever.")

    # 5. Accessibility gap vs market.
    def a11y(r):
        return (r.get("accessibility") or {}).get("score")
    pack_a = [a11y(r) for r in others if a11y(r) is not None]
    self_a = a11y(self_brand)
    if self_a is not None and pack_a:
        market_a = round(sum(pack_a) / len(pack_a))
        if self_a < market_a - 8:
            add("low", "accessibility",
                f"{self_name}'s accessibility score ({self_a}) is below the market average ({market_a})",
                "Rules-based homepage check — a cheap directional signal, see the Accessibility tab.")

    # 6. Reputation / social proof gap vs the pack.
    pack_rated = [r for r in others if _rating(r)]
    self_rating = _rating(self_brand)
    if self_rating and len(pack_rated) >= 2:
        pack_ratings = sorted(_rating(r) for r in pack_rated)
        med = pack_ratings[len(pack_ratings) // 2]
        better = [r for r in pack_rated if _rating(r) > self_rating + 0.1]
        if med - self_rating >= REPUTATION_SHIFT and len(better) >= 2:
            add("medium", "reputation",
                f"{self_name}'s homepage rating ({self_rating}★) trails the pack (median {med}★)",
                f"{len(better)} competitors show a higher star rating — a visible trust/conversion lever.")
    elif not self_rating and len(pack_rated) >= max(2, len(others) // 3):
        add("medium", "reputation",
            f"{len(pack_rated)} competitors surface a star rating on the homepage — {self_name}'s isn't detected",
            "A visible review rating is a cheap trust signal at the top of the funnel — see the Reputation tab.")

    # 7. Assortment: the owned brand's range materially smaller than the pack.
    crun = _latest_catalogue(catalogue)
    if crun:
        self_count = _catalogue_count(crun, self_brand.get("slug"))
        pack_counts = sorted(c for c in
                             (_catalogue_count(crun, r.get("slug")) for r in others)
                             if c)
        if self_count and len(pack_counts) >= 2:
            med = pack_counts[len(pack_counts) // 2]
            if med and self_count <= med * ASSORTMENT_SHORTFALL:
                add("low", "assortment",
                    f"{self_name}'s catalogue ({self_count} products) is well below the pack median ({med})",
                    "A narrower range than the market — see the Assortment tab for who's expanding.")

        # 7b. Category-mix gap: a category the pack stocks deeply and the owned
        #     brand is thin on (share of each brand's own range).
        self_cats = _cat_shares(crun, self_brand.get("slug"))
        if self_cats is not None:
            gaps = []
            all_cats = set()
            pack_shares = {}
            for r in others:
                rc = _cat_shares(crun, r.get("slug"))
                if rc is None:
                    continue
                for cat, sh in rc.items():
                    pack_shares.setdefault(cat, []).append(sh)
                    all_cats.add(cat)
            for cat in all_cats:
                shares = pack_shares.get(cat, [])
                if len(shares) < 2:
                    continue
                pack_mean = sum(shares) / len(shares)
                self_sh = self_cats.get(cat, 0.0)
                if pack_mean >= 0.12 and pack_mean - self_sh >= 0.10:
                    gaps.append((pack_mean - self_sh, cat, pack_mean, self_sh))
            if gaps:
                gaps.sort(reverse=True)
                _, cat, pack_mean, self_sh = gaps[0]
                add("medium", "assortment_mix",
                    f"Competitors stock {cat} far more deeply than {self_name} "
                    f"({round(pack_mean * 100)}% of their range vs {self_name}'s {round(self_sh * 100)}%)",
                    "A range-mix gap in a category buyers are shopping — see the Assortment tab's range mix.")

    # 8. Marketplace presence — off-site channels the pack surfaces and the owned
    #    brand doesn't. Homepage-declared (£0/public); the reseller/outlet case needs a
    #    live probe (roadmap), so this reads "owned channel" gaps, never "absent".
    #    Hidden from the live dashboard (SHOW_MARKETPLACE) until detection is
    #    accurate enough not to false-negative a channel we KNOW a brand runs.
    def _mk(rec, channel):
        return ((rec.get("marketplace") or {}).get(channel) or {}).get("state")

    amazon_pack = [r for r in others if _mk(r, "amazon") in MARKETPLACE_OWNED["amazon"]]
    if (SHOW_MARKETPLACE and _mk(self_brand, "amazon") not in MARKETPLACE_OWNED["amazon"]
            and len(amazon_pack) >= max(2, len(others) // 3)):
        official = sum(1 for r in amazon_pack if _mk(r, "amazon") == "official")
        add("medium", "marketplace",
            f"{len(amazon_pack)}/{len(others)} competitors surface an Amazon presence — {self_name}'s homepage shows none",
            (f"{official} run an official Amazon storefront. " if official else "")
            + "A second B2C shelf shoppers already search — see the Marketplace tab "
            "(homepage-declared; reseller/outlet detection needs a live probe).")

    tiktok_pack = [r for r in others if _mk(r, "tiktok") == "shop"]
    if SHOW_MARKETPLACE and _mk(self_brand, "tiktok") != "shop" and len(tiktok_pack) >= max(2, len(others) // 3):
        add("medium", "marketplace",
            f"{len(tiktok_pack)}/{len(others)} competitors surface a TikTok Shop — {self_name}'s isn't detected",
            "TikTok Shop is the fast-growing social-commerce channel in this category — see the Marketplace tab.")

    # 9. AI visibility gaps (ties in the AIO pillar when present).
    run = _latest_aio(aio)
    if run:
        self_slug = self_brand.get("slug")
        absent = [q for q in run.get("queries", [])
                  if q.get("mentions") and not any(m["slug"] == self_slug for m in q["mentions"])]
        if absent:
            sample = absent[0]["query"]
            add("high", "ai_visibility",
                f"Competitors are named in AI answers for {len(absent)} buyer-intent quer"
                + ("y" if len(absent) == 1 else "ies") + f" where {self_name} is absent",
                f"e.g. “{sample}”. Each is a content brief — see the AI Visibility tab.")

    order = {"high": 0, "medium": 1, "low": 2}
    opps.sort(key=lambda o: order.get(o["priority"], 3))
    return opps


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build():
    storage.ensure_dirs()
    captures = storage.load_captures()
    aio = storage._load_json(AIO_PATH, {"runs": []})
    catalogue = storage._load_json(CATALOGUE_PATH, {"runs": []})
    names = {r.get("slug"): r.get("brand") for r in captures if r.get("slug")}
    events = compute_events(captures) + compute_catalogue_events(catalogue, names)
    events.sort(key=lambda e: (e["date"], e["slug"]), reverse=True)
    opportunities = compute_opportunities(captures, aio, catalogue)
    payload = {
        "generated_at": storage.now_iso(),
        "events": events[:400],            # cap the on-disk timeline
        "opportunities": opportunities,
    }
    with open(EVENTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    print(f"Wrote {EVENTS_PATH}: {len(events)} events, {len(opportunities)} opportunities.")
    return payload


if __name__ == "__main__":
    build()
