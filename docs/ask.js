/* Ask Me — a deterministic, client-side Q&A engine over the captured data.

   No LLM, no network request, no API key: the dashboard is a static,
   offline-capable PWA with nowhere to safely hold a key, and quoting the
   recorded fields (rather than a model narrating them) keeps the project's
   "no self-grading, show the evidence" principle — every answer cites the
   capture date, the extracted field and the dated screenshot.

   UMD: runs as window.AskEngine in the browser and as a Node module for
   tests (tests/test_ask.mjs). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.AskEngine = factory();
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---------- text utils ----------
  const norm = s => (s || "").toLowerCase().replace(/[’]/g, "'").replace(/\s+/g, " ").trim();

  const STOPWORDS = new Set(("the a an of on at in and or was is are were did do does done " +
    "who what when where how why which their they its it's it his her our your this that " +
    "last first ever still yet any all with for from to by about tell me show us please " +
    "sale sales offer offers discount discounts price prices pricing cost hero banner " +
    "headline brand brands competitor competitors change changed changes deep deepest").split(" "));

  function levenshtein(a, b) {
    if (a === b) return 0;
    const m = a.length, n = b.length;
    if (!m) return n;
    if (!n) return m;
    let prev = Array.from({ length: n + 1 }, (_, j) => j);
    for (let i = 1; i <= m; i++) {
      const cur = [i];
      for (let j = 1; j <= n; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1,
                          prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      prev = cur;
    }
    return prev[n];
  }

  // ---------- brand matching ----------
  function brandRoster(captures) {
    const map = new Map();
    for (const r of captures || []) {
      if (!r.slug || map.has(r.slug)) continue;
      const name = r.brand || r.slug;
      const low = norm(name);
      const aliases = new Set([low]);
      if (low.includes("&")) aliases.add(low.replace(/\s*&\s*/g, " and "));
      if (/\band\b/.test(low)) aliases.add(low.replace(/\band\b/g, "&").replace(/\s+/g, " "));
      if (low.startsWith("the ")) aliases.add(low.slice(4));   // "The X" → "X"
      aliases.add(low.replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim());
      map.set(r.slug, { slug: r.slug, name, is_self: !!r.is_self, aliases: [...aliases] });
    }
    return [...map.values()];
  }

  // Exact/substring first (longest alias wins so "charles & keith" beats "keith"),
  // then Levenshtein fuzzy that must cover EVERY significant token of a brand's
  // name — so a generic word like "prices" can't spuriously match a brand, and
  // an unrelated brand name is rejected rather than mapped to something close.
  function matchBrand(question, roster) {
    const q = norm(question);
    let best = null;
    for (const b of roster) {
      for (const alias of b.aliases) {
        if (alias && q.includes(alias) && (!best || alias.length > best.len)) {
          best = { brand: b, len: alias.length };
        }
      }
    }
    if (best) return { brand: best.brand, fuzzy: false };

    const qTokens = q.replace(/[^a-z0-9&' ]/g, " ").split(/\s+/)
      .filter(t => t.length >= 3 && !STOPWORDS.has(t));
    let fuzzyBest = null;
    for (const b of roster) {
      const tokens = norm(b.name).replace(/[^a-z0-9 ]/g, " ").split(/\s+/)
        .filter(t => t.length >= 3 && !STOPWORDS.has(t));
      if (!tokens.length) continue;
      let total = 0, coverAll = true;
      for (const t of tokens) {
        let bestD = Infinity;
        for (const qt of qTokens) bestD = Math.min(bestD, levenshtein(t, qt));
        const allow = t.length <= 4 ? 1 : t.length <= 7 ? 2 : 3;
        if (bestD > allow) { coverAll = false; break; }
        total += bestD;
      }
      if (coverAll && (fuzzyBest === null || total < fuzzyBest.total)) {
        fuzzyBest = { brand: b, total };
      }
    }
    if (fuzzyBest) return { brand: fuzzyBest.brand, fuzzy: fuzzyBest.total > 0 };
    return null;
  }

  // The closest brand to an untracked name, for "did you mean".
  function closestBrand(name, roster) {
    let best = null;
    for (const b of roster) {
      const d = levenshtein(norm(name), norm(b.name));
      if (best === null || d < best.d) best = { b, d };
    }
    return best && best.d <= Math.max(3, norm(name).length / 2) ? best.b : null;
  }

  // ---------- date parsing ----------
  const MONTHS = ["january", "february", "march", "april", "may", "june", "july",
                  "august", "september", "october", "november", "december"];

  const pad = n => String(n).padStart(2, "0");
  const iso = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  const daysInMonth = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
  const shiftDays = (isoDate, n) => {
    const d = new Date(isoDate + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  };

  // Parse a date or date range out of the question. `latest` (the newest
  // capture date) anchors relative phrases and bare month names.
  function parseDateRange(question, latest) {
    const q = norm(question);
    const anchor = latest || new Date().toISOString().slice(0, 10);
    const anchorY = +anchor.slice(0, 4);

    const isoDates = q.match(/\d{4}-\d{2}-\d{2}/g);
    if (isoDates && isoDates.length >= 2) {
      const sorted = isoDates.slice(0, 2).sort();
      return { from: sorted[0], to: sorted[1], label: `${sorted[0]} to ${sorted[1]}` };
    }
    if (isoDates) return { from: isoDates[0], to: isoDates[0], label: isoDates[0] };

    if (/\btoday\b/.test(q)) return { from: anchor, to: anchor, label: `today (${anchor})` };
    if (/\byesterday\b/.test(q)) {
      const y = shiftDays(anchor, -1);
      return { from: y, to: y, label: `yesterday (${y})` };
    }
    if (/\bthis week\b/.test(q)) {
      const d = new Date(anchor + "T00:00:00Z");
      const day = (d.getUTCDay() + 6) % 7;                 // Mon=0
      const from = shiftDays(anchor, -day);
      return { from, to: anchor, label: `this week (${from} → ${anchor})` };
    }
    if (/\blast week\b/.test(q)) {
      const d = new Date(anchor + "T00:00:00Z");
      const day = (d.getUTCDay() + 6) % 7;
      const to = shiftDays(anchor, -day - 1);
      const from = shiftDays(to, -6);
      return { from, to, label: `last week (${from} → ${to})` };
    }

    // "end of June", "mid July", "early June", bare "in June" (+ optional year).
    const m = q.match(new RegExp(
      "\\b(?:(end|late|mid|middle|early|start|beginning)(?:\\s+of)?\\s+)?(" +
      MONTHS.join("|") + ")(?:\\s+(\\d{4}))?\\b"));
    if (m) {
      const part = m[1] || null;
      const mon = MONTHS.indexOf(m[2]) + 1;
      let year = m[3] ? +m[3] : anchorY;
      // A bare month later in the calendar than the anchor means last year.
      if (!m[3] && iso(year, mon, 1) > anchor) year -= 1;
      const dim = daysInMonth(year, mon);
      let from = 1, to = dim;
      if (part === "early" || part === "start" || part === "beginning") to = 10;
      else if (part === "mid" || part === "middle") { from = 11; to = 20; }
      else if (part === "end" || part === "late") from = dim - 9;
      return { from: iso(year, mon, from), to: iso(year, mon, to),
               label: `${part ? part + " " : ""}${m[2]} ${year}` };
    }
    return null;
  }

  // ---------- capture helpers ----------
  const ok = r => r && r.status === "success";
  const byDate = (a, b) => (a.date || "").localeCompare(b.date || "");

  function capturesFor(captures, slug) {
    return (captures || []).filter(r => r.slug === slug && ok(r)).sort(byDate);
  }
  function inRange(recs, range) {
    if (!range) return recs;
    return recs.filter(r => r.date >= range.from && r.date <= range.to);
  }
  function latestDate(captures) {
    let latest = null;
    for (const r of captures || []) if (ok(r) && (!latest || r.date > latest)) latest = r.date;
    return latest;
  }
  function medianPrice(r) {
    const lp = r.listing && r.listing.prices;
    if (lp && lp.median != null) return { value: lp.median, source: "listing page" };
    if (r.prices && r.prices.median != null) return { value: r.prices.median, source: "homepage band" };
    return null;
  }
  const ev = (r, field, value) => ({
    brand: r.brand, slug: r.slug, date: r.date, field, value,
    screenshot: r.screenshot || null,
  });

  // ---------- answer helpers ----------
  const answer = (text, evidence, note) =>
    ({ ok: true, text, evidence: evidence || [], note: note || null });
  const failure = text => ({ ok: false, text, evidence: [], note: null });

  function rosterText(roster) {
    return roster.map(b => b.name).sort().join(", ");
  }

  // ---------- intent handlers ----------

  // Sale/offer status for one brand over a day or a span.
  function handleOfferStatus(brand, range, captures) {
    const recs = capturesFor(captures, brand.slug);
    if (!recs.length) return failure(`No successful captures for ${brand.name} yet.`);
    const span = inRange(recs, range);
    if (range && !span.length) {
      return failure(`No captures for ${brand.name} in ${range.label} — ` +
        `the record runs ${recs[0].date} to ${recs[recs.length - 1].date}.`);
    }
    if (!range) {
      const last = recs[recs.length - 1];
      const text = last.headline_offer
        ? `Yes — on ${last.date} (the latest capture) ${brand.name} was running “${last.headline_offer}”` +
          (last.max_discount_pct ? ` (up to ${last.max_discount_pct}% off)` : "") + "."
        : `No — the latest capture (${last.date}) shows no homepage offer for ${brand.name}.`;
      return answer(text, [ev(last, "headline_offer", last.headline_offer || "no offer")]);
    }
    const on = span.filter(r => r.headline_offer);
    if (!on.length) {
      return answer(
        `No — across ${span.length} capture${span.length > 1 ? "s" : ""} in ${range.label}, ` +
        `${brand.name} showed no homepage offer.`,
        span.slice(-2).map(r => ev(r, "headline_offer", "no offer")));
    }
    const offers = [...new Set(on.map(r => r.headline_offer))];
    const allDays = on.length === span.length;
    return answer(
      `Yes — ${brand.name} was on sale ${allDays ? "throughout" : `on ${on.length} of ${span.length} captured days in`} ` +
      `${range.label}: “${offers.join("”, “")}”.`,
      [ev(on[0], "headline_offer", on[0].headline_offer),
       ...(on.length > 1 ? [ev(on[on.length - 1], "headline_offer", on[on.length - 1].headline_offer)] : [])]);
  }

  // Timeline of sale/hero changes: derived by diffing consecutive captures
  // directly (not the pre-built events file, which can drift).
  function saleTransitions(recs) {
    const out = [];
    for (let i = 1; i < recs.length; i++) {
      const prev = recs[i - 1], cur = recs[i];
      const had = !!prev.headline_offer, has = !!cur.headline_offer;
      if (has && !had) out.push({ type: "started", rec: cur });
      else if (had && !has) out.push({ type: "ended", rec: cur, prevOffer: prev.headline_offer });
      else if (has && cur.headline_offer !== prev.headline_offer) {
        out.push({ type: "changed", rec: cur, prevOffer: prev.headline_offer });
      }
    }
    return out;
  }

  function handleSaleTimeline(brand, captures) {
    const recs = capturesFor(captures, brand.slug);
    if (recs.length < 2) return failure(`Not enough capture history for ${brand.name} to build a timeline.`);
    const moves = saleTransitions(recs);
    if (!moves.length) {
      const state = recs[recs.length - 1].headline_offer
        ? `on sale (“${recs[recs.length - 1].headline_offer}”) the whole time`
        : "not on sale at any point";
      return answer(
        `No sale changes recorded for ${brand.name} between ${recs[0].date} and ` +
        `${recs[recs.length - 1].date} — it was ${state}.`,
        [ev(recs[recs.length - 1], "headline_offer", recs[recs.length - 1].headline_offer || "no offer")]);
    }
    const lines = moves.slice(-6).map(m =>
      m.type === "started" ? `${m.rec.date}: sale started — “${m.rec.headline_offer}”`
      : m.type === "ended" ? `${m.rec.date}: sale ended (was “${m.prevOffer}”)`
      : `${m.rec.date}: offer changed “${m.prevOffer}” → “${m.rec.headline_offer}”`);
    return answer(
      `${brand.name}'s sale timeline (from diffing consecutive captures): ` + lines.join("; ") + ".",
      moves.slice(-3).map(m => ev(m.rec, "headline_offer", m.rec.headline_offer || "no offer")));
  }

  function handleHeroTimeline(brand, captures) {
    const recs = capturesFor(captures, brand.slug);
    if (!recs.length) return failure(`No successful captures for ${brand.name} yet.`);
    let lastChange = null;
    for (let i = 1; i < recs.length; i++) {
      const p = recs[i - 1].hero_message || "", c = recs[i].hero_message || "";
      if (c && c !== p) lastChange = { rec: recs[i], prev: p };
    }
    const latest = recs[recs.length - 1];
    if (!lastChange) {
      return answer(
        `${brand.name}'s hero hasn't changed across the recorded history ` +
        `(${recs[0].date} → ${latest.date}); it reads “${latest.hero_message || "—"}”.`,
        [ev(latest, "hero_message", latest.hero_message || "—")]);
    }
    return answer(
      `${brand.name} last changed its hero on ${lastChange.rec.date}` +
      (lastChange.prev ? ` (from “${lastChange.prev}”)` : "") +
      ` to “${lastChange.rec.hero_message}”.`,
      [ev(lastChange.rec, "hero_message", lastChange.rec.hero_message)]);
  }

  function handleHero(brand, range, captures) {
    const recs = inRange(capturesFor(captures, brand.slug), range);
    if (!recs.length) {
      return failure(`No captures for ${brand.name}${range ? ` in ${range.label}` : ""}.`);
    }
    const r = recs[recs.length - 1];
    return answer(
      `${brand.name}'s hero on ${r.date}${range ? ` (latest capture in ${range.label})` : " (latest capture)"}: ` +
      `“${r.hero_message || "—"}”.`,
      [ev(r, "hero_message", r.hero_message || "—")]);
  }

  function handlePrice(brand, range, captures) {
    const recs = inRange(capturesFor(captures, brand.slug), range);
    if (!recs.length) {
      return failure(`No captures for ${brand.name}${range ? ` in ${range.label}` : ""}.`);
    }
    const r = [...recs].reverse().find(x => medianPrice(x)) || recs[recs.length - 1];
    const mp = medianPrice(r);
    if (!mp) return failure(`No price data captured for ${brand.name} yet.`);
    const band = r.listing && r.listing.prices && r.listing.prices.count
      ? r.listing.prices : r.prices;
    return answer(
      `${brand.name}'s median price on ${r.date} was £${mp.value} (from the ${mp.source}` +
      (band && band.min != null ? `; range £${band.min}–£${band.max}` : "") + `).`,
      [ev(r, "median price", `£${mp.value} (${mp.source})`)]);
  }

  function handleWhoOnSale(range, captures, roster) {
    const date = range ? range.to : latestDate(captures);
    if (!date) return failure("No captures on file yet.");
    const rows = [];
    for (const b of roster) {
      const recs = capturesFor(captures, b.slug).filter(r => r.date <= date);
      if (!recs.length) continue;
      const r = recs[recs.length - 1];
      if (range && r.date < range.from) continue;
      if (r.headline_offer) rows.push(r);
    }
    if (!rows.length) {
      return answer(`Nobody — no tracked brand showed a homepage offer` +
        (range ? ` in ${range.label}` : ` as of ${date}`) + ".", []);
    }
    rows.sort((a, b) => (b.max_discount_pct || 0) - (a.max_discount_pct || 0));
    return answer(
      `${rows.length} brand${rows.length > 1 ? "s" : ""} on sale` +
      (range ? ` in ${range.label}` : ` as of ${date}`) + ": " +
      rows.map(r => `${r.brand} (“${r.headline_offer}”)`).join(", ") + ".",
      rows.slice(0, 4).map(r => ev(r, "headline_offer", r.headline_offer)));
  }

  function handleDeepestDiscount(range, captures, roster) {
    const date = range ? range.to : latestDate(captures);
    if (!date) return failure("No captures on file yet.");
    let best = null;
    for (const b of roster) {
      const recs = capturesFor(captures, b.slug).filter(r => r.date <= date);
      if (!recs.length) continue;
      const r = recs[recs.length - 1];
      if (range && r.date < range.from) continue;
      if (r.max_discount_pct != null &&
          (!best || r.max_discount_pct > best.max_discount_pct)) best = r;
    }
    if (!best) return failure("No discount percentages captured" + (range ? ` in ${range.label}` : "") + ".");
    return answer(
      `${best.brand} has the deepest discount` + (range ? ` in ${range.label}` : "") +
      `: up to ${best.max_discount_pct}% off (“${best.headline_offer || "—"}”, captured ${best.date}).`,
      [ev(best, "max_discount_pct", best.max_discount_pct + "%")]);
  }

  function handleSnapshot(brand, captures) {
    const recs = capturesFor(captures, brand.slug);
    if (!recs.length) return failure(`No successful captures for ${brand.name} yet.`);
    const r = recs[recs.length - 1];
    const bits = [];
    bits.push(r.headline_offer ? `offer “${r.headline_offer}”` : "no homepage offer");
    if (r.hero_message) bits.push(`hero “${r.hero_message}”`);
    const mp = medianPrice(r);
    if (mp) bits.push(`median price £${mp.value}`);
    if (r.delivery && r.delivery.length) bits.push(`delivery: ${r.delivery[0]}`);
    const rep = r.reputation || {};
    if (rep.rating != null) bits.push(`rating ${rep.rating}★${rep.review_count ? ` (${rep.review_count} reviews)` : ""}`);
    if (r.menu && r.menu.length) bits.push(`nav leads with ${r.menu.join(" / ")}`);
    return answer(
      `${brand.name} as of ${r.date}: ` + bits.join("; ") + ".",
      [ev(r, "snapshot", r.headline_offer || r.hero_message || "capture")]);
  }

  // AI-visibility (share-of-voice) data from the weekly AIO capture, if run.
  function handleAio(brand, aio, roster) {
    const runs = (aio && aio.runs) || [];
    if (!runs.length) {
      return failure("No AI-visibility data yet — the weekly share-of-voice capture " +
        "hasn't run (it needs an API key; see the README).");
    }
    const run = runs[runs.length - 1];
    const sov = run.share_of_voice || {};
    const rows = Object.entries(sov).sort((a, b) => (b[1].sov || 0) - (a[1].sov || 0));
    if (brand) {
      const entry = sov[brand.slug];
      if (!entry) return failure(`${brand.name} doesn't appear in the ${run.date} AI-visibility run.`);
      const rank = rows.findIndex(([slug]) => slug === brand.slug) + 1;
      return answer(
        `In the ${run.date} AI-visibility run, ${brand.name} had ${Math.round((entry.sov || 0) * 100)}% ` +
        `share of voice (rank ${rank} of ${rows.length}), named in ` +
        `${Math.round((entry.visibility || 0) * 100)}% of the ${run.queries_total} buyer-intent queries.`,
        []);
    }
    return answer(
      `AI-visibility (week of ${run.date}, ${run.queries_total} queries) — top share of voice: ` +
      rows.slice(0, 5).map(([, v], i) => `${i + 1}. ${v.brand} ${Math.round((v.sov || 0) * 100)}%`).join(", ") + ".",
      []);
  }

  // ---------- intent detection + dispatch ----------
  const RE = {
    aio: /\bai (?:visibility|answers?|assistants?)|share of voice\b/,
    deepest: /\b(?:deepest|biggest|largest|highest|best)\b.*\b(?:discount|reduction|sale)\b|\bdiscounting (?:the )?most\b/,
    who: /\bwho(?:'s| is| are| was| were| has| had)?\b|\bwhich brands?\b/,
    onSale: /\bon sale\b|\brunning (?:a |an )?(?:sale|offer|promotion)\b|\bdiscounting\b|\boffer\b/,
    timeline: /\bwhen did\b|\bwhen was\b|\btimeline\b|\bhow long\b|\bsince when\b/,
    hero: /\bhero\b|\bheadline\b|\bbanner\b|\bhomepage message\b/,
    price: /\bprices?\b|\bpricing\b|\bcost\b|\bhow much\b|\bmedian\b|\bexpensive\b|\bcheap/,
    snapshot: /\bsnapshot\b|\btell me about\b|\bsummary\b|\bsummarise\b|\bsummarize\b|\bhow (?:is|are)\b/,
    changeVerb: /\bchange(?:d)?\b|\brewrote\b|\bupdate(?:d)?\b/,
    saleVerb: /\bsale\b|\boffer\b|\bdiscount\b/,
  };

  // A phrase that looks like it names a brand we don't track, for the
  // "brand not found" path: the subject of "was <X> on sale", etc.
  function namedUnknown(question) {
    const m = norm(question).match(
      /(?:was|is|are|were|did|does|has|about)\s+([a-z][a-z&' .-]{2,30}?)(?:'s)?\s+(?:on sale|running|discount|sale|offer|hero|price|prices|doing)/);
    return m ? m[1].trim() : null;
  }

  function ask(question, data) {
    const captures = (data && data.captures) || [];
    const aio = (data && data.aio) || { runs: [] };
    const roster = brandRoster(captures);
    const q = norm(question);
    if (!q) return failure("Ask a question like “was Mint Velvet on sale at the end of June?”");
    if (!captures.length) return failure("No capture data loaded yet.");

    const latest = latestDate(captures);
    const range = parseDateRange(question, latest);
    const match = matchBrand(question, roster);
    const brand = match && match.brand;
    const note = match && match.fuzzy
      ? `Read that as ${brand.name} — the closest tracked brand to the name you typed.` : null;
    const withNote = res => (res && res.ok && note ? { ...res, note } : res);

    // AI visibility first (its vocabulary doesn't collide with the others).
    if (RE.aio.test(q)) return withNote(handleAio(brand, aio, roster));

    // Market-wide questions don't need a brand.
    if (RE.deepest.test(q)) return handleDeepestDiscount(range, captures, roster);
    if (RE.who.test(q) && RE.onSale.test(q) && !brand) return handleWhoOnSale(range, captures, roster);

    // Brand-specific intents.
    if (brand) {
      if (RE.timeline.test(q) && RE.hero.test(q)) return withNote(handleHeroTimeline(brand, captures));
      if (RE.timeline.test(q) && (RE.saleVerb.test(q) || RE.changeVerb.test(q))) {
        return withNote(handleSaleTimeline(brand, captures));
      }
      if (RE.hero.test(q)) return withNote(handleHero(brand, range, captures));
      if (RE.price.test(q)) return withNote(handlePrice(brand, range, captures));
      if (RE.onSale.test(q)) return withNote(handleOfferStatus(brand, range, captures));
      return withNote(handleSnapshot(brand, captures));
    }

    // No tracked brand matched. If the question clearly names one, be honest
    // about not tracking it (with a did-you-mean) instead of misfiring.
    const unknown = namedUnknown(question);
    if (unknown) {
      const suggestion = closestBrand(unknown, roster);
      return failure(
        `“${unknown}” isn't a tracked brand.` +
        (suggestion ? ` Did you mean ${suggestion.name}?` : "") +
        ` Tracked brands: ${rosterText(roster)}.`);
    }
    if (RE.onSale.test(q)) return handleWhoOnSale(range, captures, roster);
    return failure(
      "I couldn't work out what that's asking. Try an offer question " +
      "(“was Sezane on sale last week?”), a timeline (“when did Coach's sale start?”), " +
      "a hero or price question, or “who has the deepest discount?”. " +
      `Tracked brands: ${rosterText(roster)}.`);
  }

  return {
    ask,
    // exported for tests
    _internal: { levenshtein, matchBrand, brandRoster, parseDateRange, saleTransitions },
  };
}));
