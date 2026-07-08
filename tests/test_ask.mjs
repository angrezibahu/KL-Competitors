/* Offline tests for the Ask Me query engine. No browser, no network.
   Run:  node tests/test_ask.mjs */
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const AskEngine = require("../docs/ask.js");
const { ask } = AskEngine;
const { levenshtein, matchBrand, brandRoster, parseDateRange, saleTransitions } =
  AskEngine._internal;

// ---------- fixture ----------
const cap = (slug, brand, date, extra = {}) => ({
  slug, brand, date, status: "success",
  screenshot: `screenshots/${slug}/${date}.jpg`,
  ...extra,
});

const CAPTURES = [
  cap("katie-loxton", "Katie Loxton", "2026-06-20", { is_self: true, hero_message: "New In: Summer Edit" }),
  cap("katie-loxton", "Katie Loxton", "2026-06-25", {
    is_self: true, headline_offer: "up to 50% off", max_discount_pct: 50,
    hero_message: "Summer Sale Now On",
    prices: { median: 40, min: 8, max: 110, count: 20 },
    delivery: ["free uk delivery over £50"],
    reputation: { rating: 4.8, review_count: 3200 },
    menu: ["New In", "Bags", "Sale"],
  }),
  cap("katie-loxton", "Katie Loxton", "2026-06-30", {
    is_self: true, headline_offer: "up to 50% off", max_discount_pct: 50,
    hero_message: "Summer Sale Now On",
  }),
  cap("katie-loxton", "Katie Loxton", "2026-07-05", { is_self: true, hero_message: "The Holiday Shop" }),
  cap("mint-velvet", "Mint Velvet", "2026-06-25", {}),
  cap("mint-velvet", "Mint Velvet", "2026-06-30", { headline_offer: "up to 40% off", max_discount_pct: 40 }),
  cap("mint-velvet", "Mint Velvet", "2026-07-05", { headline_offer: "up to 60% off", max_discount_pct: 60 }),
  cap("charles-keith", "Charles & Keith", "2026-07-05", {
    listing: { prices: { median: 75, min: 30, max: 150, count: 30 } },
    prices: { median: 80, min: 30, max: 150, count: 10 },
  }),
  cap("white-company", "The White Company", "2026-07-05", { hero_message: "Whites for Summer" }),
];
const DATA = { captures: CAPTURES, aio: { runs: [] } };

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---------- unit: levenshtein / brand matching ----------
test("levenshtein basics", () => {
  assert.equal(levenshtein("kitten", "sitting"), 3);
  assert.equal(levenshtein("same", "same"), 0);
  assert.equal(levenshtein("", "abc"), 3);
});

test("brand match: exact and & variants and The-prefix", () => {
  const roster = brandRoster(CAPTURES);
  assert.equal(matchBrand("was charles and keith on sale?", roster).brand.slug, "charles-keith");
  assert.equal(matchBrand("charles & keith prices", roster).brand.slug, "charles-keith");
  const wc = matchBrand("what is white company's hero?", roster);
  assert.equal(wc.brand.slug, "white-company");
  assert.equal(wc.fuzzy, false);
});

test("brand match: typo-tolerant, flagged as fuzzy", () => {
  const roster = brandRoster(CAPTURES);
  const m = matchBrand("was katie loxten on sale?", roster);
  assert.equal(m.brand.slug, "katie-loxton");
  assert.equal(m.fuzzy, true);
});

test("brand match: generic words and unrelated brands are rejected", () => {
  const roster = brandRoster(CAPTURES);
  assert.equal(matchBrand("who has the deepest discount on prices?", roster), null);
  assert.equal(matchBrand("was pandora on sale?", roster), null);
});

// ---------- unit: date parsing ----------
test("date parse: ISO, today, yesterday", () => {
  const r = parseDateRange("what happened on 2026-06-28?", "2026-07-05");
  assert.deepEqual([r.from, r.to], ["2026-06-28", "2026-06-28"]);
  const t = parseDateRange("is anyone on sale today?", "2026-07-05");
  assert.deepEqual([t.from, t.to], ["2026-07-05", "2026-07-05"]);
  const y = parseDateRange("yesterday?", "2026-07-05");
  assert.deepEqual([y.from, y.to], ["2026-07-04", "2026-07-04"]);
});

test("date parse: end/mid/early of month + bare month rolls back a year", () => {
  const e = parseDateRange("at the end of june", "2026-07-05");
  assert.deepEqual([e.from, e.to], ["2026-06-21", "2026-06-30"]);
  const m = parseDateRange("mid june", "2026-07-05");
  assert.deepEqual([m.from, m.to], ["2026-06-11", "2026-06-20"]);
  const early = parseDateRange("early june", "2026-07-05");
  assert.deepEqual([early.from, early.to], ["2026-06-01", "2026-06-10"]);
  // December is after the July anchor, so it means LAST December.
  const dec = parseDateRange("in december", "2026-07-05");
  assert.equal(dec.from.slice(0, 4), "2025");
});

test("date parse: last week relative to the newest capture", () => {
  // 2026-07-05 is a Sunday; last week = Mon 2026-06-22 → Sun 2026-06-28.
  const r = parseDateRange("last week", "2026-07-05");
  assert.deepEqual([r.from, r.to], ["2026-06-22", "2026-06-28"]);
});

// ---------- unit: timeline diffing ----------
test("sale transitions from consecutive captures", () => {
  const recs = CAPTURES.filter(r => r.slug === "katie-loxton");
  const moves = saleTransitions(recs);
  assert.deepEqual(moves.map(m => [m.type, m.rec.date]),
    [["started", "2026-06-25"], ["ended", "2026-07-05"]]);
});

// ---------- end-to-end: intents ----------
test("offer status over a span cites evidence with screenshots", () => {
  const res = ask("was katie loxton on sale at the end of june?", DATA);
  assert.equal(res.ok, true);
  assert.match(res.text, /Yes/);
  assert.match(res.text, /50% off/);
  assert.ok(res.evidence.length >= 1);
  assert.match(res.evidence[0].screenshot, /screenshots\/katie-loxton/);
});

test("offer status without a date uses the latest capture", () => {
  const res = ask("is mint velvet on sale?", DATA);
  assert.match(res.text, /Yes.*2026-07-05.*60% off/s);
});

test("negative offer status reads honestly", () => {
  const res = ask("was mint velvet on sale on 2026-06-25?", DATA);
  assert.match(res.text, /No/);
});

test("sale timeline diffs captures directly", () => {
  const res = ask("when did katie loxton's sale start?", DATA);
  assert.match(res.text, /2026-06-25: sale started/);
  assert.match(res.text, /2026-07-05: sale ended/);
});

test("hero change timeline", () => {
  const res = ask("when did katie loxton last change their hero?", DATA);
  assert.match(res.text, /2026-07-05/);
  assert.match(res.text, /The Holiday Shop/);
});

test("price prefers the listing median", () => {
  const res = ask("what are charles & keith's prices?", DATA);
  assert.match(res.text, /£75/);
  assert.match(res.text, /listing page/);
});

test("who is on sale", () => {
  const res = ask("who's on sale today?", DATA);
  assert.match(res.text, /Mint Velvet/);
  assert.doesNotMatch(res.text, /Katie Loxton \(/);   // KL's sale ended by 07-05
});

test("deepest discount", () => {
  const res = ask("who has the deepest discount?", DATA);
  assert.match(res.text, /Mint Velvet/);
  assert.match(res.text, /60%/);
});

test("brand snapshot", () => {
  const res = ask("tell me about katie loxton", DATA);
  assert.match(res.text, /2026-07-05/);
});

test("fuzzy match is disclosed in the note", () => {
  const res = ask("was mint velvit on sale?", DATA);
  assert.equal(res.ok, true);
  assert.match(res.note, /Read that as Mint Velvet/);
});

test("untracked brand returns roster + did-you-mean", () => {
  const res = ask("was mint velvot marlot on sale?", DATA);
  if (res.ok) {
    // acceptable only if fuzzily matched to Mint Velvet with a note
    assert.match(res.note || "", /Mint Velvet/);
  } else {
    assert.match(res.text, /Tracked brands/);
  }
  const res2 = ask("was pandora on sale?", DATA);
  assert.equal(res2.ok, false);
  assert.match(res2.text, /isn't a tracked brand/);
  assert.match(res2.text, /Tracked brands/);
});

test("aio handler degrades honestly with no runs", () => {
  const res = ask("what's our ai visibility?", DATA);
  assert.equal(res.ok, false);
  assert.match(res.text, /hasn't run/);
});

test("aio handler surfaces share of voice when present", () => {
  const withAio = {
    captures: CAPTURES,
    aio: { runs: [{ date: "2026-07-01", queries_total: 12, share_of_voice: {
      "katie-loxton": { brand: "Katie Loxton", sov: 0.31, visibility: 0.5 },
      "mint-velvet": { brand: "Mint Velvet", sov: 0.12, visibility: 0.25 },
    } }] },
  };
  const res = ask("what is katie loxton's share of voice in AI answers?", withAio);
  assert.equal(res.ok, true);
  assert.match(res.text, /31%/);
  assert.match(res.text, /rank 1/);
});

test("nonsense question fails gracefully with guidance", () => {
  const res = ask("purple monkey dishwasher", DATA);
  assert.equal(res.ok, false);
  assert.match(res.text, /Tracked brands/);
});

// ---------- runner ----------
let failures = 0;
for (const [name, fn] of tests) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name}: ${e.message}`);
  }
}
console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
process.exit(failures ? 1 : 0);
