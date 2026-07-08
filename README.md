# Katie Loxton Competitor Radar 🔍

A daily competitor-tracking tool for Katie Loxton. Every morning it visits
each brand's homepage, screenshots it, and logs the trading signals that matter
— hero messaging, offers, delivery promises, discount codes, product mix,
colours, keywords and SEO — then stores it forever and shows it in an installable
dashboard (PWA).

It is built specifically to avoid the four ways the old ChatGPT version failed:

| Old failure | How this fixes it |
|---|---|
| Couldn't schedule itself | A **GitHub Actions cron** runs it daily — real infrastructure, not an AI pressing go. |
| New file each time, no history | Data is **append-only**. History is the whole point. |
| Claimed success after checking 2–3 | A **deterministic script** logs explicit `success`/`failed` **per brand**; the dashboard shows gaps. No self-grading. |
| Returned stale/cached answers | A **fresh, cache-busted browser session per brand** every run, with the real fetch timestamp stored. |

---

## 🧭 Editorial principles (the lore)

These shape every figure and sentence the dashboard puts in front of someone. New
features should hold to them.

1. **Thoughtful, helpful observations only.** Surface what we *genuinely know*, not
   what's easy to compute. Don't headline a number that misleads at a glance — e.g.
   a "52% average discount" when eight brands sit at 50% and a single outlier at
   65% drags the mean up. Prefer the **median**, **name the outlier explicitly**,
   and lead with the real story ("nearly every brand is in a summer sale; 50% is the
   going rate; here's the fast-shipping and free-delivery picture"). If a stat needs
   a caveat to not mislead, either give the caveat plainly or don't show the stat.
2. **Cross-check a signal across brands before calling it absent.** If one
   competitor surfaces something (a Feefo review widget, a delivery promise, a
   channel), check whether the others do too rather than false-negativing a signal
   we've confirmed elsewhere. Many sites inject widgets client-side, so a signal can
   be real even when it isn't in the server HTML — known-true facts can be declared
   per brand in `config/competitors.json` (e.g. `review_platforms`) and are merged
   with whatever is detected, so a confirmed signal is never dropped.
3. **Plain language, no filler.** Write hints the way you'd brief a colleague —
   short and concrete. Skip the self-justifying copy ("no new requests", "reads the
   trove you're already collecting", "read honestly"). State the limitation once, in
   ordinary words, and move on.

---

## ⚠️ Honest limitations — read this first

This is genuinely useful, but it is not magic. Please hold these expectations:

1. **Some sites will block us some days.** We use free GitHub-hosted runners
   whose IP ranges are well known. Cloudflare-protected sites (Astrid & Miyu,
   Monica Vinader and others) may intermittently return a block page instead of
   their homepage. When that happens the brand is logged as **`failed` for that
   day and shown as such** — never hidden. If the gaps become annoying, the fix
   is a paid scraping proxy (~£30–50/mo); the code is structured so that can be
   slotted in later.
2. **Extraction is rules-based, not AI.** You chose the free path, so fields are
   pulled with pattern-matching, not a language model. This is reliable for
   clear signals (e.g. "up to 50% off", "next day delivery", "use code X") but
   will occasionally miss an unusually-worded promo or mis-read product mix, and
   **a competitor redesign can break a rule** until the patterns in
   `scraper/extractors.py` are tweaked. That is the trade-off for £0/mo.
3. **Cron timing is "9am-ish", not to the second.** GitHub's scheduler runs in
   UTC and can be delayed by hours — or dropped entirely — under load,
   especially at the top of the hour. We run the primary capture at `08:11 UTC`
   (~9am UK summer / 8am UK winter) off the busy round-number slot, plus a
   **self-healing backup at `11:41 UTC`** that re-runs only if the morning run
   didn't already succeed. So a dropped/delayed morning slot self-corrects the
   same day instead of leaving a gap. The schedule also pauses if the repo gets
   no commits for 60 days — our daily data commits prevent that.
4. **Google Trends is best-effort.** `pytrends` is unofficial and often blocked
   from datacenter IPs. If it fails, the run still succeeds; trends just show as
   unavailable.
5. **Screenshots grow the repo.** ~8 JPEGs/day (~1–2 MB/day). Fine for a good
   while; in a year or two you may want to move older screenshots to external
   storage. Flagged so it's not a surprise.

---

## 🚀 One-time setup (you do this once)

1. **Merge this branch to `main`.**
2. **Enable GitHub Pages:** repo → *Settings → Pages* → Source = *GitHub
   Actions*. The `Deploy dashboard to Pages` workflow then publishes `docs/`
   on every dashboard/data change and after each daily capture. After a minute
   your dashboard is live at `https://<your-org>.github.io/KL-Competitors/`
   (the path is case-sensitive). On your phone, open that URL and *Add to Home
   Screen* to install the app. (The older *Deploy from a branch* source also
   works, but can silently stop building after a default-branch change — the
   Actions source avoids that.)
3. **Check Actions are allowed to write:** repo → *Settings → Actions → General*
   → *Workflow permissions* → select *Read and write permissions* → Save.
   (This lets the daily job commit new data back.)
4. **Run it once now** to replace the sample data: repo → *Actions* → *Daily
   competitor capture* → *Run workflow*. Watch the log — you'll see `[OK]` /
   `[FAILED]` per brand.

That's it. From then on it runs every morning on its own.

---

## 🗂️ What's in here

```
config/competitors.json     # brands + homepage URLs + optional listing_url + product-category keywords (edit me)
config/aio_queries.json     # buyer-intent questions for the AI-visibility job (edit me)
scraper/
  capture.py                # daily orchestrator (Playwright)
  extractors.py             # rules-based field extraction inc. price sampling, reputation & accessibility
  colours.py                # dominant-colour extraction from screenshots
  trends.py                 # Google Trends (best-effort)
  digest.py                 # builds the weekly HTML digest
  aio.py                    # AI-overview visibility (share of voice in AI answers; key-gated)
  catalogue.py              # assortment & new-product velocity from product sitemaps
  events.py                 # derives the change timeline + opportunities from history
  storage.py                # append-only data writing
  seed.py                   # generates the SAMPLE data you see before first real run
docs/                       # the PWA dashboard (served by GitHub Pages)
  index.html, app.js, styles.css, sw.js, manifest.webmanifest
  data/captures.json        # the append-only history (the treasure trove)
  data/aio.json             # append-only AI-visibility history (weekly)
  data/catalogue.json       # append-only assortment history (range size + newness)
  data/catalogue_snapshot.json  # latest product handles per brand (the diff baseline)
  data/events.json          # derived change timeline + current opportunities
  screenshots/<brand>/<date>.jpg
tests/test_extractors.py    # offline tests for the extraction rules
tests/test_catalogue.py     # offline tests for the sitemap parsing + diff
tests/test_aio.py           # offline tests for AI-visibility parsing & scoring
tests/test_events.py        # offline tests for the timeline + opportunity rules
.github/workflows/daily.yml          # the 9am capture schedule
.github/workflows/weekly-digest.yml  # Monday digest build + optional email
.github/workflows/aio.yml            # weekly AI-visibility capture (needs ANTHROPIC_API_KEY)
.github/workflows/ci.yml             # runs extractor + AIO tests on every PR
```

The dashboard tabs: **Overview** (market snapshot + Katie Loxton vs pack),
**Opportunities** (rules-based actionable gaps + a timeline of what changed),
**Market Map** (positioning: price × range size, value/premium × niche/broad),
**W/M/Q overview** (weekly/monthly/quarterly trends by brand and by jewellery category),
**By competitor** (per-brand card: hero, top-of-nav taxonomy, offer, prices,
product mix & palette), **Offer trends** (promotional pressure over time), **Trading**
(real listing-page prices & discount depth + conversion levers: BNPL, sign-up
offers, free-delivery thresholds, scarcity), **Reputation** (homepage star
ratings, review volume & review platforms — the social-proof/trust pillar),
**Assortment** (catalogue size & new-product velocity from product sitemaps),
**Pricing**, **Colour trends**,
**Keyword trends**, **SEO**, **AI Visibility** (share of voice in AI-assistant
answers — see below), **Accessibility** (rules-based homepage score per brand),
and **Screenshots** (flick by date).

> **Note on the newer tabs.** The **W/M/Q overview** aggregates over time, so it
> only becomes meaningful once history accumulates — weekly within ~a week,
> monthly within ~a month, quarterly within ~3 months. The **Accessibility**
> score is a "Lighthouse-lite", rules-based check read straight from the HTML
> (alt text, page language, form labels, landmarks, heading structure…). It is
> **not** a full WCAG audit — it can't judge colour contrast, keyboard order or
> anything needing a live render — so treat it as a cheap directional signal.
> Both populate automatically as the daily capture runs.

---

## 🔧 Common tasks

**Add or remove a competitor:** edit `config/competitors.json` (give it a
unique `slug`). Done.

**Adjust what counts as a product category:** edit `product_categories` in the
same file.

**Change the run time:** edit the `cron` in `.github/workflows/daily.yml`
(it's in UTC).

**Run locally (needs open internet, unlike the GitHub runner):**
```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m scraper.capture
```

**Run the tests:**
```bash
python tests/test_extractors.py
```

**Regenerate sample data (for a demo):** `python -m scraper.seed`

---

## 📈 Pricing & the weekly digest

Two enrichments run as part of the pipeline:

- **Price-point sampling** — an approximate price band (min / median / max) per
  brand, on the *Pricing* tab. **Read this honestly:** a homepage is not a price
  list, so it's a rough band, preferring structured data (JSON-LD prices) and
  falling back to visible "£" amounts. It can include the odd delivery threshold
  or sale "was" price. Good for spotting *who sits where* and *shifts over time*,
  not for exact RRPs. For a sharper read, see the **Trading** tab below.
- **Weekly email digest** — every Monday a summary is built (`scraper/digest.py`),
  saved to `docs/digest.html` (linked in the dashboard footer), and emailed if
  you've configured SMTP. It highlights what *changed* week-on-week: new/ended
  sales, deeper discounts, hero rewrites, new codes, plus the price
  leaderboard and where Katie Loxton sits.

### Turning on the digest email (optional)
The digest HTML is always produced. To also *email* it, add these repo secrets
(*Settings → Secrets and variables → Actions*). Use an **app password**, never
your real one:

| Secret | Example / notes |
|---|---|
| `MAIL_USERNAME` | your sending Gmail/Outlook address (also the default recipient) |
| `MAIL_PASSWORD` | a Gmail **app password** (not your login password) |
| `MAIL_TO` | (optional) where to send it — defaults to `MAIL_USERNAME` |
| `MAIL_SERVER` | (optional) defaults to `smtp.gmail.com` |
| `MAIL_PORT` | (optional) defaults to `465` |

If `MAIL_USERNAME` isn't set, the email step is skipped silently — the digest
page is still committed and viewable.

## 🛒 Trading data (the *real* prices)

The **Trading** tab goes deeper than the homepage. Two layers:

- **Real listing-page sampling.** If a brand has an optional `listing_url` in
  `config/competitors.json` (its "shop all jewellery" / bestsellers page), the
  daily job also visits that page and reads a real **price distribution**
  (min / 25th / median / 75th / max) plus **discount depth** — what share of the
  visible range is actually marked down (`compare_at_price` in structured data,
  or "was £X now £Y" copy). This turns the rough homepage *band* into a real
  *distribution* and measures promotional *intensity*, not just "is there a
  banner". It is **best-effort and never fatal:** a missing/blocked/price-less
  listing page just means no listing block for that brand that day — the
  homepage capture is unaffected. Read `% on sale` as "how promotional is this
  range", not an exact count (one page is a sample).
- **Conversion levers (homepage).** Read from the homepage we already fetch, so
  no extra requests: **BNPL/finance** (Klarna, Clearpay, Laybuy + wallets),
  the **email-capture offer** (e.g. "10% off your first order" — usually hidden
  in the newsletter popup), the **free-delivery threshold** (e.g. "over £50"),
  and **scarcity** language ("selling fast", "only 3 left").

**Tuning the listing URLs:** the ones shipped are best-guesses. If a brand shows
homepage-only data on the Trading tab, point its `listing_url` at a page that
actually lists products with prices and re-run.

## 🤖 AI Visibility (AIO) — share of voice in AI answers

The newest signal, and the one shoppers increasingly act on. When someone asks
an AI assistant *"best personalised birthday jewellery UK"*, **which brands does
it name, and in what order?** The **AI Visibility** tab tracks that over time.

How it works (`scraper/aio.py`, weekly via `.github/workflows/aio.yml`):

- A list of **buyer-intent queries** lives in `config/aio_queries.json` (seeded
  from the same gifting/sentiment themes as `product_categories` — edit freely).
- For each query the job asks **Claude with live web search** to recommend
  brands like a shopping assistant would, then records **which tracked brands are
  named and in what position**. Being named first counts for more.
- It computes a **share of voice** per brand (named more, and named first = higher
  SoV), plus per-query "who's named" — the dashboard surfaces queries where
  *competitors appear and Katie Loxton doesn't*, which is a ready-made content brief.
- History is append-only (`docs/data/aio.json`), so the tab shows both this
  week's leaderboard and the **trend**.

**Honesty note:** AI answers are non-deterministic and depend on the model and
live web results, so read this as *directional share-of-voice over time*, not a
fixed ranking — the same way price bands and Google Trends are directional here.

### Turning it on (optional)
Add one repo secret (*Settings → Secrets and variables → Actions*):

| Secret | Notes |
|---|---|
| `ANTHROPIC_API_KEY` | an [Anthropic API key](https://console.anthropic.com/). The weekly job uses it to query an answer engine with web search. |

Without the secret the workflow **skips cleanly** (writes nothing) and the tab
shows a "not set up yet" note — nothing else is affected. The brand-mention
parsing and share-of-voice scoring are pure and covered by `tests/test_aio.py`,
so they're tested even with no key.

## ⭐ Reputation — the social-proof / trust pillar

A star rating and review volume are among the strongest top-of-funnel trust
levers in this category, and they were the one off-site pillar the radar didn't
cover. The **Reputation** tab now tracks, per brand and over time, the rating,
review count and review platforms each competitor surfaces on its homepage.

How it works (`extract_reputation` in `scraper/extractors.py`):

- It reads the **homepage HTML we already fetch** — so there's **no extra
  request and no new surface to get blocked**, the same design as the Trading
  tab's conversion levers.
- It prefers structured **JSON-LD `AggregateRating`** (normalised to a /5 scale,
  picking the site-wide number when several appear), falls back to visible-text
  patterns ("4.8 out of 5 from 12,345 reviews"), and fingerprints the **review
  platform** in use (Trustpilot, Yotpo, Okendo, Reviews.io, Judge.me, Feefo …).
- It feeds the **Opportunities** engine ("Katie Loxton's homepage rating trails the
  pack", or "N competitors show a rating and Katie Loxton's isn't detected") and the
  **change timeline** (rating moved, a review widget appeared).

**Honesty note:** these are **self-reported, on-page** numbers — a brand chooses
what to show — not an independent audit. Read it as "what trust signal does each
competitor put in front of a shopper", and as a directional trend over time
(like price bands and AI share-of-voice). Brands that don't surface a rating in
their server-rendered HTML simply show as "none surfaced" — never guessed. The
parsing is pure and covered by `tests/test_extractors.py`. The tab populates as
daily captures run.

**Ratings we'll stand behind:** a star rating is only believed when it's
*evidenced*. A bare "5 stars" in marketing copy with no review tally is not a
brand-wide aggregate, so the text reader **requires a review count** before it
trusts a rating (this killed the false 5.0★ that Katie Loxton/Abbott Lyon showed off a
stray pull-quote). And a rating only counts as **verified** — and toward the
market average — when it's backed by at least **25 reviews**; thinner scores are
shown and tagged "low volume" but excluded, so one 10-review rating can't set the
market bar. Same spirit as the Overview: surface what we genuinely know, not a
flattering artefact.

## 🛍️ Marketplace presence — retired

An Amazon/TikTok Shop "marketplace presence" pillar (classifying channels from
homepage-linked evidence only) was tried here and **fully removed**: reading only
what a brand links on its own site produced too many false negatives on channels
known to be real (most DTC brands never link their Amazon storefront), and a
stockists-page scan didn't rescue it enough to justify keeping it even hidden.
Reliably detecting an *unlinked* channel — the actual grey-market/outlet
question — needs a live Amazon/TikTok probe behind a paid proxy, which breaks
the £0 constraint. If that budget ever appears, build the probe; don't resurrect
the homepage-link heuristic.

## 📦 Assortment — range size & new-product velocity

A merchandising read the rest of the radar can't give you: **how big is each
competitor's range, who's expanding it, and who's dropping new products** — built
from each brand's **product sitemap** (`scraper/catalogue.py`, part of the daily
run).

Why sitemaps: every Shopify store (and most modern shops) exposes
`/sitemap.xml` → product sitemaps in plain XML that are **served to bots by
design**. So this is **reliable where shop-page scraping isn't**, adds **no new
blocking surface**, and is light (XML, no rendering). Each run we read the set of
product handles per brand, count them (catalogue size), and diff against the
previous run to detect **new** (and removed) products — which becomes the
"New (7d)" column on the **Assortment** tab, plus "added N new products" entries
on the change timeline and an Opportunities flag when Katie Loxton's range sits well
below the pack.

How the diff stays honest:

- A brand's **first** observation records its size but reports **zero** velocity
  (no prior snapshot to compare — we don't invent a "+400 products" spike); that
  day is flagged `first_seen`/`baseline`.
- The snapshot keeps both the latest handles and the **previous day's**, so a
  manual same-day re-run diffs against *yesterday* and never double-counts.
- A brand whose sitemap 404s, blocks us, or isn't in a recognised product format
  simply shows **"no sitemap"** that day — never hidden, never guessed. It's most
  reliable for Shopify-style stores; some brands won't expose a readable product
  sitemap, and that's shown plainly.
- The sitemap is fetched through the **full rendered browser** (`page.goto` +
  the raw response body), the same path the homepage capture already clears — so
  Shopify/Cloudflare stores that 403 a header-light HTTP request (Katie Loxton,
  Charles & Keith, Oliver Bonas…) are read correctly. We only accept a body that actually
  looks like a sitemap (`<urlset>`/`<sitemapindex>`), so a returned challenge
  page is rejected rather than mis-parsed; a plain HTTP request is the fallback
  for permissive hosts. (Genuinely Cloudflare-walled days can still miss — same
  limitation as the homepage capture — and are logged honestly.)

**Range mix by category.** The same product handles are classified into the
jewellery taxonomy (`product_categories` in `config/competitors.json`), giving a
**share-of-range per category** for each brand — *who's deep in charms vs
personalised vs necklaces* — shown as a matrix on the Assortment tab and fed to
an Opportunities rule ("competitors stock charms far more deeply than Katie Loxton").
This is the *actual published assortment*, distinct from the homepage
**product-mix** tab which counts category *mentions* in marketing copy. It reuses
the exact `\bkeyword` matching as the homepage mix, so "ring" catches "rings" but
never "ea*rring*"; a product can sit in several categories, so a brand's shares
needn't sum to 100%.

**Range-mix trend over time.** The Assortment tab also charts how a chosen
brand's range *shape* shifts month to month — each category's share aggregated by
month, with the ▲/▼ percentage-point move on the previous month. It answers
"is this competitor pivoting into charms / personalised this season?" and builds
up as catalogue history accumulates (a single month shows the snapshot; the
month-on-month moves appear once a second month lands).

**Honesty note:** sitemaps list what's *published*, which is an excellent proxy
for range and newness but not a stock or bestseller signal — read it as
assortment breadth, drop cadence and range *shape* over time. Parsing, diff and
category classification are pure and covered by `tests/test_catalogue.py`. The
tab populates as daily captures run (velocity needs a second run to compare
against).

## 🗺️ Market Map — positioning at a glance

The **Market Map** tab plots every brand on **price** (median — from real
listing-page distributions where available, else the homepage band) against
**range size** (catalogue products from sitemaps), and splits the market by the
pack medians into four quadrants: *broad & value*, *broad & premium*, *niche &
value*, *niche & premium*. It's a one-glance read of who sits where and where the
white space is. Pure client-side join of data already collected — no new
requests, drawn as inline SVG (no chart library, works offline like the rest).

**Honesty built in:** both price samplers are directional and can occasionally
pick up noise (a "spend over £X" line, a bundle, a stray "was" price). So when a
brand's listing-page and homepage medians **disagree by more than 4×**, the price
is detectably unreliable — that brand is **listed as "not placed", with both
figures shown**, rather than dropped onto the map at a misleading position. Read
it as positioning over time, not a precise valuation. Brands only appear once we
have both a trustworthy price and a catalogue size, so coverage grows as the
daily capture and catalogue steps fill in.

## 🎯 Opportunities & the change timeline

The point of accumulating history is to *act* on it. The **Opportunities** tab
turns the trove into two things (`scraper/events.py`, rebuilt every day):

- **A change timeline.** Every day the capture history is diffed into dated
  events — sales starting/ending, discounts moving, heroes rewritten, new codes,
  BNPL appearing, price-band shifts. The weekly digest already computed these and
  threw them away; now they're a **permanent record** ("when did everyone go on
  sale last summer?" becomes answerable).
- **Actionable opportunities.** Deterministic rules over the latest snapshot,
  framed Katie Loxton-vs-pack: *"3 competitors show Klarna, Katie Loxton doesn't"*, *"the pack's
  average discount is 28% and Katie Loxton is flat"*, *"competitors are named in AI
  answers for 'friendship jewellery' and Katie Loxton isn't"* (this last one ties in the
  AI Visibility data when it's enabled). Each is ranked high/medium/low.

No new scraping — it's a pure derivation of data you already collect, recomputed
from the full history each run (so it's idempotent), and the rules are covered by
`tests/test_events.py`.

## 💡 Ideas to enrich the treasure trove later
- **Live marketplace probe** — a paid-proxy Amazon/TikTok search that catches
  **third-party resellers / outlets a brand never links** (the true grey-market
  detector) and reads **marketplace price vs RRP** to flag outlet positioning.
  Only reliable behind a proxy from GitHub's IPs — and the cheap homepage-link
  version of this pillar was tried and removed (see the retired Marketplace
  note above), so this is the only version worth building.
- **Paid-acquisition intensity** via the (free, public) **Meta Ad Library** — how
  many active ads each competitor runs and when they spin up volume (sale
  launches). Another off-site pillar; it needs either a Meta API token or a paid
  scraping proxy to be reliable from GitHub's IPs, so it's a roadmap item rather
  than a £0 drop-in.
- Instagram follower counts · email open-rate proxies · a paid scraping proxy
  for 100% capture reliability · widening the AIO query set per category ·
  per-category *price* trends (median price within each jewellery category over
  time) · alerting when a competitor's range shape moves sharply.
