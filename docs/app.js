/* Katie Loxton Competitor Radar — vanilla JS, no build step, no CDN (works offline). */

// Side-nav sections: logical groups rather than one flat row of 16 tabs.
const NAV_GROUPS = [
  ["Overview", [
    ["overview",      "Overview"],
    ["opportunities", "Opportunities"],
  ]],
  ["Daily trading", [
    ["offers",  "Offer trends"],
    ["trading", "Trading"],
    ["pricing", "Pricing"],
  ]],
  ["Market & range", [
    ["market",     "Market map"],
    ["assortment", "Assortment"],
    ["periods",    "W/M/Q overview"],
  ]],
  ["Brand & creative", [
    ["competitors", "By competitor"],
    ["colours",     "Colour trends"],
    ["reputation",  "Reputation"],
  ]],
  ["Search & visibility", [
    ["keywords", "Keyword trends"],
    ["seo",      "SEO"],
    ["ask",      "Ask Me"],
    ["a11y",     "Accessibility"],
  ]],
  ["Screenshots", [
    ["screens", "Screenshots"],
  ]],
];
const TABS = NAV_GROUPS.flatMap(([, items]) => items);

const state = { captures: [], byBrand: {}, dates: [], latest: {}, aio: { runs: [] }, events: { events: [], opportunities: [] }, catalogue: { runs: [] }, active: "overview" };

// ---------- data loading ----------
async function loadData() {
  // Network-first so an open app always pulls the freshest committed data.
  const res = await fetch("data/captures.json?v=" + Date.now(), { cache: "no-store" });
  const data = await res.json();
  state.captures = Array.isArray(data) ? data : [];
  index();
  // AIO visibility is optional (weekly, key-gated) — load best-effort, never block.
  try {
    const ar = await fetch("data/aio.json?v=" + Date.now(), { cache: "no-store" });
    if (ar.ok) {
      const ad = await ar.json();
      state.aio = ad && Array.isArray(ad.runs) ? ad : { runs: [] };
    }
  } catch (e) { state.aio = { runs: [] }; }
  // Events timeline + opportunities (derived; rebuilt daily) — also best-effort.
  try {
    const er = await fetch("data/events.json?v=" + Date.now(), { cache: "no-store" });
    if (er.ok) {
      const ed = await er.json();
      state.events = { events: ed.events || [], opportunities: ed.opportunities || [] };
    }
  } catch (e) { state.events = { events: [], opportunities: [] }; }
  // Catalogue / assortment (from product sitemaps; best-effort) — also non-blocking.
  try {
    const cr = await fetch("data/catalogue.json?v=" + Date.now(), { cache: "no-store" });
    if (cr.ok) {
      const cd = await cr.json();
      state.catalogue = cd && Array.isArray(cd.runs) ? cd : { runs: [] };
    }
  } catch (e) { state.catalogue = { runs: [] }; }
}

function index() {
  state.byBrand = {};
  const dateSet = new Set();
  for (const r of state.captures) {
    (state.byBrand[r.slug] ||= { brand: r.brand, slug: r.slug, is_self: r.is_self, recs: [] }).recs.push(r);
    dateSet.add(r.date);
  }
  state.dates = [...dateSet].sort();
  for (const slug in state.byBrand) {
    const recs = state.byBrand[slug].recs.sort((a, b) => a.date.localeCompare(b.date));
    state.latest[slug] = [...recs].reverse().find(r => r.status === "success") || recs[recs.length - 1];
  }
}

// ---------- helpers ----------
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => (s ?? "").toString().replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const brandsSorted = () => Object.values(state.byBrand).sort((a, b) => (b.is_self - a.is_self) || a.brand.localeCompare(b.brand));
const latestDate = () => state.dates[state.dates.length - 1] || "—";
const nameCell = b => `<b class="${b.is_self ? "self" : ""}">${esc(b.brand)}${b.is_self ? " ★" : ""}</b>`;

function statusPill(rec) {
  if (!rec) return `<span class="pill bad">no data</span>`;
  if (rec.status !== "success") return `<span class="pill bad">failed</span>`;
  const age = state.dates.length ? (latestDate() === rec.date ? "fresh" : "stale") : "";
  return `<span class="pill ${age === "fresh" ? "good" : "warn"}">${rec.date}</span>`;
}

// ---------- scoring / period helpers ----------
const a11yClass = s => s == null ? "" : s >= 90 ? "good" : s >= 70 ? "warn" : "bad";
const avgOf = arr => { const v = arr.filter(x => x != null); return v.length ? v.reduce((a, c) => a + c, 0) / v.length : null; };
// Median — the honest middle when a single outlier would skew the mean.
const medianOf = arr => { const v = arr.filter(x => x != null).sort((a, b) => a - b); if (!v.length) return null; const m = Math.floor(v.length / 2); return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };

// A cheap SEO health score (0-100) from the stored SEO fields.
function seoHealth(r) {
  const s = (r && r.seo) || {};
  const tl = s.title_length || 0, dl = s.meta_description_length || 0;
  let v = 0;
  v += (tl >= 50 && tl <= 62) ? 30 : (tl ? 15 : 0);
  v += (dl >= 120 && dl <= 160) ? 30 : (dl ? 15 : 0);
  v += (s.h1_count >= 1) ? 20 : 0;
  v += (s.structured_data_types && s.structured_data_types.length) ? 20 : 0;
  return v;
}

// ISO-8601 week number for a UTC date.
function isoWeekParts(d) {
  const date = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = (date.getUTCDay() + 6) % 7;          // Mon=0 … Sun=6
  date.setUTCDate(date.getUTCDate() - day + 3);     // Thursday of this week
  const firstThu = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const firstDay = (firstThu.getUTCDay() + 6) % 7;
  firstThu.setUTCDate(firstThu.getUTCDate() - firstDay + 3);
  const week = 1 + Math.round((date - firstThu) / (7 * 24 * 3600 * 1000));
  return [date.getUTCFullYear(), week];
}

// Bucket a YYYY-MM-DD date into a weekly / monthly / quarterly key.
function periodKey(dateStr, gran) {
  const d = new Date(dateStr + "T00:00:00Z");
  if (gran === "weekly") { const [y, w] = isoWeekParts(d); return `${y}-W${String(w).padStart(2, "0")}`; }
  if (gran === "quarterly") return `${d.getUTCFullYear()}-Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

// ---------- views ----------
function viewOverview() {
  const wrap = el("div");
  const brands = brandsSorted();
  const today = latestDate();

  // Lead with the storefronts themselves — the latest (mobile-first) capture
  // per brand; tapping one jumps into that brand's screenshot history.
  const shots = brands.map(b => {
    const recs = (state.byBrand[b.slug] || {}).recs || [];
    const latest = [...recs].reverse().find(r => r.screenshot);
    return latest ? { b, latest } : null;
  }).filter(Boolean);
  if (shots.length) {
    const heroCard = el("div", "card");
    heroCard.innerHTML = `<h3>Today's storefronts</h3>
      <p class="hint">The latest homepage capture per brand (phone view where captured). Tap a storefront to open its screenshot history.</p>`;
    const grid = el("div", "storefronts");
    for (const { b, latest } of shots) {
      const mobile = !!latest.screenshot_mobile;
      const src = latest.screenshot_mobile || latest.screenshot;
      const btn = el("button", "storefront");
      btn.setAttribute("aria-label", `${b.brand} storefront, captured ${latest.date} — open screenshot history`);
      btn.innerHTML = `<span class="shot"><img src="${esc(src)}" alt="" loading="lazy"></span>
        <span class="lbl">${esc(b.brand)}${b.is_self ? " ★" : ""}<span class="date">${esc(latest.date)}</span></span>`;
      btn.onclick = () => {
        shotState = { slug: b.slug, device: mobile ? "mobile" : "desktop", bucket: "all", lightbox: null };
        selectTab("screens");
      };
      grid.append(btn);
    }
    heroCard.append(grid);
    wrap.append(heroCard);
  }
  // Sale/discount/shipping figures read from brands actually captured TODAY, so
  // the denominator is honest — a brand that fell to a block today isn't counted
  // as "on sale" off a stale capture. Coverage is shown explicitly below.
  const fresh = brands.map(b => state.latest[b.slug]).filter(r => r && r.date === today && r.status === "success");
  const onSale = fresh.filter(r => r.headline_offer);
  const discounts = fresh.map(r => r.max_discount_pct).filter(v => v != null);
  const medDisc = medianOf(discounts);
  const maxDisc = discounts.length ? Math.max(...discounts) : null;
  // Brands discounting deeper than the median — the outliers we should name
  // rather than let them drag a mean upward.
  const deepest = fresh.filter(r => r.max_discount_pct != null && medDisc != null && r.max_discount_pct > medDisc);
  const isFast = s => /next[\s-]?day|express/i.test(s || "");
  const fastShippers = fresh.filter(r => (r.delivery || []).some(isFast));
  const me = brands.find(b => b.is_self);
  const meRec = me && state.latest[me.slug];

  // KPIs — only figures that read true at a glance (median, not a skewed mean).
  const kpis = el("div", "grid cols-3");
  const kpi = (big, lbl) => { const c = el("div", "card kpi"); c.innerHTML = `<div class="big">${big}</div><div class="lbl">${lbl}</div>`; return c; };
  kpis.append(
    kpi(`${onSale.length}/${fresh.length}`, "brands running a sale"),
    kpi(medDisc == null ? "—" : medDisc + "%", "median headline discount"),
    kpi(`${fastShippers.length}/${fresh.length}`, "offer next-day or express delivery"),
  );
  wrap.append(kpis);

  // What the market is doing — plain, honest observations from today's captures.
  const obs = [];
  if (fresh.length && onSale.length >= fresh.length - 1) {
    obs.push(`Nearly the whole market is on a summer sale — <b>${onSale.length} of ${fresh.length}</b> brands captured today are running an offer.`);
  } else if (onSale.length) {
    obs.push(`<b>${onSale.length} of ${fresh.length}</b> brands captured today are running an offer.`);
  }
  if (medDisc != null) {
    let line = `<b>${medDisc}% off</b> is the going rate — the median headline discount.`;
    if (deepest.length && maxDisc > medDisc) {
      const names = deepest.map(r => `${esc(r.brand)} (up to ${r.max_discount_pct}%)`).join(", ");
      line += ` Only ${names} go deeper, so the median is the honest read — a mean would be dragged up by the outlier.`;
    }
    obs.push(line);
  }
  const thresholds = fresh.map(r => r.trading && r.trading.free_delivery_threshold).filter(v => v != null && v > 0).sort((a, b) => a - b);
  const freeNoMin = fresh.filter(r => r.trading && r.trading.free_delivery_threshold === 0).length;
  if (thresholds.length || freeNoMin) {
    let line = "Free delivery is near-universal";
    if (thresholds.length) line += `, usually above a spend threshold (£${thresholds[0]}–£${thresholds[thresholds.length - 1]})`;
    obs.push(line + ".");
  }
  if (fastShippers.length) {
    obs.push(`Fast shipping is the differentiator: <b>${fastShippers.map(r => esc(r.brand)).join(", ")}</b> surface next-day or express delivery; most others show standard only.`);
  }
  // Coverage line — make the denominator visible. Brands that fell to a block
  // today aren't in the figures above; they show their last good capture below.
  const blocked = brands.length - fresh.length;
  const coverage = `<b>${fresh.length} of ${brands.length}</b> brands captured today`
    + (blocked > 0 ? ` — ${blocked} fell to a block and show their last good capture in the snapshot below.` : ".");
  const read = el("div", "card");
  read.innerHTML = `<h3>What the market is doing — ${today}</h3><p class="hint">${coverage}</p>`
    + (obs.length ? `<ul class="obs">${obs.map(o => `<li>${o}</li>`).join("")}</ul>` : `<p class="muted">Not enough data captured today yet.</p>`);
  wrap.append(read);

  // Katie Loxton vs the pack — concrete levers, not a skewed average.
  const callout = el("div", "card");
  if (meRec) {
    const t = meRec.trading || {};
    const bits = [];
    if (meRec.headline_offer) {
      const jd = meRec.max_discount_pct;
      const stance = (jd != null && medDisc != null)
        ? (jd > medDisc ? "deeper than" : jd < medDisc ? "shallower than" : "in line with")
        : "in line with";
      bits.push(`In the sale at <b>${esc(meRec.headline_offer)}</b> — ${stance} the pack median${medDisc != null ? ` (${medDisc}%)` : ""}.`);
    } else if (onSale.length) {
      bits.push(`Not running a homepage offer while <b>${onSale.length}</b> competitors are.`);
    }
    if (t.free_delivery_threshold != null) bits.push(t.free_delivery_threshold === 0 ? "Free delivery, no minimum." : `Free delivery over £${t.free_delivery_threshold}.`);
    if (t.email_capture_offer) bits.push(`${esc(t.email_capture_offer)} for new sign-ups.`);
    if (t.has_bnpl) bits.push("Buy-now-pay-later available at checkout.");
    callout.innerHTML = `<h3>Katie Loxton vs the pack</h3><p class="hint">Hero: “${esc(meRec.hero_message || "—")}”</p>`
      + (bits.length ? `<ul class="obs">${bits.map(b => `<li>${b}</li>`).join("")}</ul>` : "");
  } else {
    callout.innerHTML = `<h3>Katie Loxton vs the pack</h3><p class="muted">No Katie Loxton capture yet.</p>`;
  }
  wrap.append(callout);

  // master table
  const card = el("div", "card");
  card.innerHTML = `<h3>Market snapshot — ${latestDate()}</h3><p class="hint">Latest successful capture per brand. ★ = Katie Loxton.</p>`;
  const tw = el("div", "tablewrap");
  let rows = "";
  for (const b of brands) {
    const r = state.latest[b.slug];
    rows += `<tr>
      <td>${nameCell(b)}</td>
      <td>${esc((r && r.hero_message) || "—")}</td>
      <td>${r && r.headline_offer ? `<span class="pill warn">${esc(r.headline_offer)}</span>` : '<span class="muted">—</span>'}</td>
      <td>${r && r.delivery && r.delivery.length ? esc(r.delivery[0]) : '<span class="muted">—</span>'}</td>
      <td>${r && r.discount_codes && r.discount_codes.length ? r.discount_codes.map(c => `<span class="tag"><b>${esc(c)}</b></span>`).join("") : '<span class="muted">—</span>'}</td>
      <td>${statusPill(r)}</td>
    </tr>`;
  }
  tw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">Hero message</th><th scope="col">Offer</th><th scope="col">Delivery</th><th scope="col">Codes</th><th scope="col">Captured</th></tr></thead><tbody>${rows}</tbody></table>`;
  card.append(tw);
  wrap.append(card);
  return wrap;
}

function viewCompetitors() {
  const wrap = el("div", "grid cols-2");
  for (const b of brandsSorted()) {
    const r = state.latest[b.slug];
    const card = el("div", "card");
    if (!r) { card.innerHTML = `<h3>${nameCell(b)}</h3><p class="muted">No data.</p>`; wrap.append(card); continue; }
    const mix = Object.entries(r.product_mix || {}).slice(0, 6);
    const maxShare = Math.max(0.0001, ...mix.map(([, v]) => v.share));
    card.innerHTML = `
      <h3>${nameCell(b)}</h3>
      <p class="hint">${esc(r.date)} · <a href="${esc(r.url)}" target="_blank" rel="noopener">open site ↗</a></p>
      <p><b>Hero:</b> ${esc(r.hero_message || "—")}</p>
      <p><b>Top menu:</b> ${r.menu && r.menu.length ? r.menu.map(m => `<span class="pill">${esc(m)}</span>`).join(" ") : '<span class="muted">—</span>'}</p>
      <p><b>Offer:</b> ${r.headline_offer ? `<span class="pill warn">${esc(r.headline_offer)}</span>` : '<span class="muted">none</span>'}
         &nbsp; <b>Delivery:</b> ${r.delivery && r.delivery[0] ? esc(r.delivery[0]) : "—"}</p>
      <p>${r.prices && r.prices.median != null ? `<b>Prices:</b> £${r.prices.min}–£${r.prices.max} <span class="pill">med £${r.prices.median}</span>` : ""}</p>
      <p class="hint" style="margin-top:10px">Product mix (share of mentions)</p>
      ${mix.map(([c, v]) => `<div class="row"><span class="name"><b>${esc(c)}</b></span>
        <span class="bar"><span style="width:${Math.round(v.share / maxShare * 100)}%"></span></span>
        <span class="pill">${Math.round(v.share * 100)}%</span></div>`).join("") || '<span class="muted">—</span>'}
      <p class="hint" style="margin-top:10px">Top palette</p>
      <div class="swrow">${(r.colours || []).map(c => `<i style="width:${Math.round((c.share || 0) * 100)}%;background:${esc(c.hex)}"></i>`).join("")}</div>`;
    wrap.append(card);
  }
  return wrap;
}

function viewOffers() {
  const wrap = el("div");
  const brands = brandsSorted();

  // time series: how many brands on offer per date
  const series = state.dates.map(d => {
    const recs = state.captures.filter(r => r.date === d && r.status === "success");
    return { date: d, on: recs.filter(r => r.headline_offer).length, total: recs.length };
  });
  const tsCard = el("div", "card");
  tsCard.innerHTML = `<h3>Promotional pressure over time</h3><p class="hint">Brands running a homepage offer, by day.</p>`;
  const maxOn = Math.max(1, ...series.map(s => s.total));
  tsCard.append(el("div", "", series.map(s =>
    `<div class="row"><span class="name"><b>${s.date}</b></span>
      <span class="bar"><span style="width:${Math.round(s.on / maxOn * 100)}%"></span></span>
      <span class="pill ${s.on ? "warn" : ""}">${s.on}/${s.total}</span></div>`).join("")));
  wrap.append(tsCard);

  // current offers leaderboard
  const card = el("div", "card");
  card.innerHTML = `<h3>Who's discounting now — ${latestDate()}</h3>`;
  const rows = brands.map(b => state.latest[b.slug]).filter(Boolean)
    .sort((a, b) => (b.max_discount_pct || 0) - (a.max_discount_pct || 0));
  const maxPct = Math.max(1, ...rows.map(r => r.max_discount_pct || 0));
  card.append(el("div", "", rows.map(r =>
    `<div class="row"><span class="name">${nameCell(state.byBrand[r.slug])}</span>
      <span class="bar"><span style="width:${Math.round((r.max_discount_pct || 0) / maxPct * 100)}%"></span></span>
      <span class="pill ${r.headline_offer ? "warn" : ""}">${r.headline_offer ? esc(r.headline_offer) : "no offer"}</span></div>`).join("")));
  wrap.append(card);
  return wrap;
}

function viewColours() {
  const wrap = el("div");
  // aggregate market palette (sum shares by colour name)
  const agg = {};
  for (const b of brandsSorted()) {
    const r = state.latest[b.slug];
    for (const c of (r && r.colours) || []) {
      if (!c.name) continue;
      (agg[c.name] ||= { share: 0, hex: c.hex });
      agg[c.name].share += c.share || 0;
    }
  }
  const top = Object.entries(agg).sort((a, b) => b[1].share - a[1].share).slice(0, 12);
  const totalShare = top.reduce((s, [, v]) => s + v.share, 0) || 1;
  const mkt = el("div", "card");
  mkt.innerHTML = `<h3>Market colour palette — ${latestDate()}</h3><p class="hint">Dominant homepage colours across all brands.</p>`;
  mkt.append(el("div", "swatches", top.map(([n, v]) =>
    `<span class="sw"><i style="background:${esc(v.hex)}"></i>${esc(n)} ${Math.round(v.share / totalShare * 100)}%</span>`).join("")));
  wrap.append(mkt);

  const grid = el("div", "grid cols-3");
  for (const b of brandsSorted()) {
    const r = state.latest[b.slug];
    const c = el("div", "card");
    c.innerHTML = `<h3>${nameCell(b)}</h3>
      <div class="swrow" style="margin:8px 0">${((r && r.colours) || []).map(x => `<i style="width:${Math.round((x.share || 0) * 100)}%;background:${esc(x.hex)}"></i>`).join("") || '<span class="muted">—</span>'}</div>
      <div class="swatches">${((r && r.colours) || []).map(x => `<span class="sw"><i style="background:${esc(x.hex)}"></i>${esc(x.name || x.hex)}</span>`).join("")}</div>`;
    grid.append(c);
  }
  wrap.append(grid);
  return wrap;
}

function viewKeywords() {
  const wrap = el("div");
  const agg = {};
  for (const b of brandsSorted()) {
    const r = state.latest[b.slug];
    for (const [w, c] of (r && r.keywords) || []) agg[w] = (agg[w] || 0) + c;
  }
  const top = Object.entries(agg).sort((a, b) => b[1] - a[1]).slice(0, 40);
  const max = Math.max(1, ...top.map(([, c]) => c));
  const card = el("div", "card");
  card.innerHTML = `<h3>Market keyword cloud — ${latestDate()}</h3><p class="hint">Most frequent words across competitor homepages.</p>`;
  card.append(el("div", "", top.map(([w, c]) =>
    `<span class="tag" style="font-size:${(12 + c / max * 16).toFixed(0)}px">${esc(w)} <b>${c}</b></span>`).join("")));
  wrap.append(card);

  const grid = el("div", "grid cols-2");
  for (const b of brandsSorted()) {
    const r = state.latest[b.slug];
    const c = el("div", "card");
    c.innerHTML = `<h3>${nameCell(b)}</h3><div>${((r && r.keywords) || []).slice(0, 12)
      .map(([w, n]) => `<span class="tag">${esc(w)} <b>${n}</b></span>`).join("") || '<span class="muted">—</span>'}</div>`;
    grid.append(c);
  }
  wrap.append(grid);
  return wrap;
}

function viewSeo() {
  const wrap = el("div", "card");
  wrap.innerHTML = `<h3>SEO snapshot — ${latestDate()}</h3>
    <p class="hint">Title &amp; meta lengths (≈50–60 / ≈140–160 chars are healthy), headings, content depth & structured data.</p>`;
  const tw = el("div", "tablewrap");
  let rows = "";
  for (const b of brandsSorted()) {
    const r = state.latest[b.slug]; const s = (r && r.seo) || {};
    const a = r && r.accessibility;
    const tl = s.title_length || 0, dl = s.meta_description_length || 0;
    const tlPill = tl >= 50 && tl <= 62 ? "good" : tl ? "warn" : "bad";
    const dlPill = dl >= 120 && dl <= 160 ? "good" : dl ? "warn" : "bad";
    rows += `<tr>
      <td>${nameCell(b)}</td>
      <td>${esc(s.title || "—")}<br><span class="pill ${tlPill}">title ${tl}</span></td>
      <td>${esc(s.meta_description || "—")}<br><span class="pill ${dlPill}">desc ${dl}</span></td>
      <td class="num">${s.h1_count ?? "—"}/${s.h2_count ?? "—"}</td>
      <td class="num">${s.word_count ?? "—"}</td>
      <td>${(s.structured_data_types || []).map(t => `<span class="tag">${esc(t)}</span>`).join("") || "—"}</td>
      <td class="num">${a ? `<span class="pill ${a11yClass(a.score)}">${a.score} · ${esc(a.grade)}</span>` : '<span class="muted">—</span>'}</td>
    </tr>`;
  }
  tw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">Title</th><th scope="col">Meta description</th><th scope="col">H1/H2</th><th scope="col">Words</th><th scope="col">Structured data</th><th scope="col">A11y</th></tr></thead><tbody>${rows}</tbody></table>`;
  wrap.append(tw);
  return wrap;
}

// ---------- screenshots: filterable gallery + accessible lightbox ----------
let shotState = { slug: "all", device: "desktop", bucket: "week", lightbox: null };

// Which date bucket does a capture fall in, relative to the newest capture?
function inBucket(dateStr, bucket) {
  if (bucket === "all") return true;
  const latest = latestDate();
  if (latest === "—") return true;
  if (bucket.startsWith("month:")) return dateStr.slice(0, 7) === bucket.slice(6);
  const [ly, lw] = isoWeekParts(new Date(latest + "T00:00:00Z"));
  const [y, w] = isoWeekParts(new Date(dateStr + "T00:00:00Z"));
  if (bucket === "week") return y === ly && w === lw;
  if (bucket === "lastweek") {
    // Previous ISO week, handling the year boundary.
    const prev = new Date(latest + "T00:00:00Z");
    prev.setUTCDate(prev.getUTCDate() - 7);
    const [py, pw] = isoWeekParts(prev);
    return y === py && w === pw;
  }
  return true;
}

function galleryItems() {
  const brands = shotState.slug === "all"
    ? brandsSorted()
    : brandsSorted().filter(b => b.slug === shotState.slug);
  const items = [];
  for (const b of brands) {
    for (const r of (state.byBrand[b.slug] || {}).recs || []) {
      const src = shotState.device === "mobile" ? r.screenshot_mobile : r.screenshot;
      if (!src || !inBucket(r.date, shotState.bucket)) continue;
      items.push({ b, r, src });
    }
  }
  // Newest first, then brand order for same-day shots.
  items.sort((a, c) => c.r.date.localeCompare(a.r.date));
  return items;
}

function viewScreens() {
  const wrap = el("div");
  const brands = brandsSorted();

  // --- filters: brand, device, date bucket ---
  const ctrl = el("div", "card");
  ctrl.innerHTML = `<h3>Screenshot gallery</h3>
    <p class="hint">Every capture, filterable by brand, device and date. Newest first; select a shot to view it full-size.</p>`;

  const brandRow = el("div", "brandpick");
  brandRow.setAttribute("role", "group");
  brandRow.setAttribute("aria-label", "Filter by brand");
  const brandBtn = (slug, label) => {
    const on = shotState.slug === slug;
    const btn = el("button", on ? "active" : "", label);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.onclick = () => { shotState.slug = slug; shotState.lightbox = null; render(); };
    return btn;
  };
  brandRow.append(brandBtn("all", "All brands"));
  for (const b of brands) brandRow.append(brandBtn(b.slug, esc(b.brand) + (b.is_self ? " ★" : "")));

  const deviceRow = el("div", "brandpick");
  deviceRow.setAttribute("role", "group");
  deviceRow.setAttribute("aria-label", "Device");
  for (const [dev, label] of [["desktop", "🖥 Desktop"], ["mobile", "📱 Mobile"]]) {
    const on = shotState.device === dev;
    const btn = el("button", on ? "active" : "", label);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.onclick = () => { shotState.device = dev; shotState.lightbox = null; render(); };
    deviceRow.append(btn);
  }

  const bucketRow = el("div", "brandpick");
  bucketRow.setAttribute("role", "group");
  bucketRow.setAttribute("aria-label", "Date range");
  const months = [...new Set(state.dates.map(d => d.slice(0, 7)))].sort().reverse();
  const buckets = [["week", "This week"], ["lastweek", "Last week"],
    ...months.map(m => ["month:" + m, m]), ["all", "All"]];
  for (const [bk, label] of buckets) {
    const on = shotState.bucket === bk;
    const btn = el("button", on ? "active" : "", esc(label));
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.onclick = () => { shotState.bucket = bk; shotState.lightbox = null; render(); };
    bucketRow.append(btn);
  }
  ctrl.append(el("p", "hint", "Brand"), brandRow,
              el("p", "hint", "Device"), deviceRow,
              el("p", "hint", "Date"), bucketRow);
  wrap.append(ctrl);

  // --- the gallery grid ---
  const items = galleryItems();
  // An evidence link (Ask Me) can ask for a specific date's shot: open the
  // lightbox straight onto it, once.
  if (shotState.focusDate) {
    const i = items.findIndex(it => it.r.date === shotState.focusDate);
    if (i >= 0) shotState.lightbox = i;
    shotState.focusDate = null;
  }
  const card = el("div", "card");
  if (!items.length) {
    card.innerHTML = `<p class="muted">No ${esc(shotState.device)} screenshots in this date range yet`
      + (shotState.device === "mobile" ? " — mobile capture starts with the next daily run." : ".") + `</p>`;
    wrap.append(card);
    return wrap;
  }
  const grid = el("div", "gallery");
  items.forEach((it, i) => {
    const cell = el("button", "galleryitem");
    cell.setAttribute("aria-label",
      `${it.b.brand} ${shotState.device} screenshot, ${it.r.date} — open full size`);
    cell.innerHTML = `<span class="shot"><img src="${esc(it.src)}" alt="" loading="lazy"></span>
      <span class="lbl">${esc(it.b.brand)}${it.b.is_self ? " ★" : ""}<span class="date">${esc(it.r.date)}</span>
      ${it.r.headline_offer ? `<span class="pill warn">${esc(it.r.headline_offer)}</span>` : ""}</span>`;
    cell.onclick = () => { shotState.lightbox = i; render(); };
    grid.append(cell);
  });
  card.append(grid);
  wrap.append(card);

  // --- lightbox (modal dialog: focus trap, Escape, ‹ Newer / Older ›) ---
  if (shotState.lightbox != null && items[shotState.lightbox]) {
    wrap.append(buildLightbox(items, shotState.lightbox));
  }
  return wrap;
}

function buildLightbox(items, idx) {
  const it = items[idx];
  const box = el("div", "lightbox");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label",
    `${it.b.brand} screenshot, ${it.r.date} (${idx + 1} of ${items.length})`);
  box.innerHTML = `
    <div class="lightbox-bar">
      <span><b>${esc(it.b.brand)}</b> — ${esc(it.r.date)} (${idx + 1}/${items.length})
        ${it.r.headline_offer ? `<span class="pill warn">${esc(it.r.headline_offer)}</span>` : ""}</span>
      <span class="lightbox-ctl">
        <button class="btn" id="lbPrev" ${idx === 0 ? "disabled" : ""} aria-label="Newer screenshot">‹ Newer</button>
        <button class="btn" id="lbNext" ${idx === items.length - 1 ? "disabled" : ""} aria-label="Older screenshot">Older ›</button>
        <button class="btn" id="lbClose" aria-label="Close">✕ Close</button>
      </span>
    </div>
    <div class="lightbox-body"><img src="${esc(it.src)}"
      alt="${esc(it.b.brand)} homepage captured ${esc(it.r.date)}"></div>`;
  const close = () => { shotState.lightbox = null; render(); };
  const go = i => { shotState.lightbox = Math.max(0, Math.min(items.length - 1, i)); render(); };
  setTimeout(() => {
    const prev = document.getElementById("lbPrev"), next = document.getElementById("lbNext");
    document.getElementById("lbClose").onclick = close;
    prev.onclick = () => go(idx - 1);
    next.onclick = () => go(idx + 1);
    (idx > 0 ? prev : next).focus();
    box.onkeydown = e => {
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "ArrowLeft" && idx > 0) go(idx - 1);
      else if (e.key === "ArrowRight" && idx < items.length - 1) go(idx + 1);
      else if (e.key === "Tab") {
        // Focus trap inside the dialog.
        const f = [...box.querySelectorAll("button:not([disabled])")];
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
  }, 0);
  return box;
}

function viewPricing() {
  const wrap = el("div");
  const brands = brandsSorted();
  const rows = brands.map(b => ({ b, r: state.latest[b.slug] }))
    .filter(x => x.r && x.r.prices && x.r.prices.median != null)
    .sort((a, b) => a.r.prices.median - b.r.prices.median);
  const globalMax = Math.max(1, ...rows.map(x => x.r.prices.max || 0));

  const card = el("div", "card");
  card.innerHTML = `<h3>Price bands — ${latestDate()}</h3>
    <p class="hint">Approximate, sampled from homepages (cheapest first). Bar spans min→max; dot is the median.</p>`;
  card.append(el("div", "", rows.map(({ b, r }) => {
    const p = r.prices, L = (p.min / globalMax) * 100, W = ((p.max - p.min) / globalMax) * 100, M = (p.median / globalMax) * 100;
    return `<div class="row"><span class="name" style="flex:0 0 150px">${nameCell(b)}</span>
      <span class="bar" style="position:relative;background:#f0eaee">
        <span style="position:absolute;left:${L}%;width:${Math.max(2, W)}%;background:#d9c4cf"></span>
        <span style="position:absolute;left:${M}%;width:8px;height:9px;border-radius:50%;background:var(--accent);transform:translateX(-4px)"></span>
      </span>
      <span class="pill">£${p.min}–£${p.max}</span>
      <span class="pill warn">med £${p.median}</span></div>`;
  }).join("") || '<span class="muted">No pricing captured yet.</span>'));
  wrap.append(card);
  return wrap;
}

// ---------- trading view ----------
// Real listing-page trading data + homepage conversion levers. Listing fields
// only appear once a brand has a working listing_url that returned prices.
function viewTrading() {
  const wrap = el("div");
  const brands = brandsSorted();
  const rows = brands.map(b => ({ b, r: state.latest[b.slug] })).filter(x => x.r);

  const intro = el("div", "card");
  intro.innerHTML = `<h3>Trading signals — ${latestDate()}</h3>
    <p class="hint">Real prices &amp; promo intensity sampled from each brand's listing page, plus
    homepage conversion levers (BNPL, first-order offers, free-delivery thresholds, scarcity).
    Listing figures are a sample of one page — read <b>% on sale</b> as "how promotional is this range",
    not an exact count. Brands without a working listing page show homepage data only.</p>`;
  wrap.append(intro);

  // --- real listing price + discount intensity ---
  const withListing = rows.filter(x => x.r.listing && x.r.listing.prices && x.r.listing.prices.count);
  const lc = el("div", "card");
  lc.innerHTML = `<h3>Real price &amp; discount depth (listing pages)</h3>`;
  if (withListing.length) {
    const gMax = Math.max(1, ...withListing.map(x => x.r.listing.prices.max || 0));
    lc.append(el("div", "", withListing
      .sort((a, b) => a.r.listing.prices.median - b.r.listing.prices.median)
      .map(({ b, r }) => {
        const p = r.listing.prices, share = Math.round((r.listing.discounted_share || 0) * 100);
        const L = (p.min / gMax) * 100, W = ((p.max - p.min) / gMax) * 100, M = (p.median / gMax) * 100;
        return `<div class="row"><span class="name" style="flex:0 0 150px">${nameCell(b)}</span>
          <span class="bar" style="position:relative;background:#f0eaee">
            <span style="position:absolute;left:${L}%;width:${Math.max(2, W)}%;background:#d9c4cf"></span>
            <span style="position:absolute;left:${M}%;width:8px;height:9px;border-radius:50%;background:var(--accent);transform:translateX(-4px)"></span>
          </span>
          <span class="pill">£${p.min}–£${p.max}</span>
          <span class="pill warn">med £${p.median}</span>
          <span class="pill ${share >= 40 ? "warn" : ""}">${share}% on sale</span></div>`;
      }).join("")));
  } else {
    lc.append(el("p", "muted", "No listing-page data yet. Add a working listing_url per brand in config/competitors.json; it fills in as the daily job runs."));
  }
  wrap.append(lc);

  // --- finance / BNPL adoption ---
  const fc = el("div", "card");
  fc.innerHTML = `<h3>Finance &amp; payment options</h3><p class="hint">Buy-now-pay-later is the conversion lever; ✓ marks BNPL.</p>`;
  const tw = el("div", "tablewrap");
  let frows = "";
  for (const { b, r } of rows) {
    const t = r.trading || {};
    const fin = (t.finance || []);
    frows += `<tr>
      <td>${nameCell(b)}</td>
      <td>${t.has_bnpl ? '<span class="pill good">✓ BNPL</span>' : '<span class="muted">—</span>'}</td>
      <td>${fin.length ? fin.map(f => `<span class="tag">${esc(f)}</span>`).join("") : '<span class="muted">—</span>'}</td>
      <td>${t.email_capture_offer ? `<span class="pill warn">${esc(t.email_capture_offer)}</span>` : '<span class="muted">—</span>'}</td>
      <td>${t.free_delivery_threshold == null ? '<span class="muted">—</span>' : (t.free_delivery_threshold === 0 ? '<span class="pill good">free</span>' : `<span class="pill">over £${t.free_delivery_threshold}</span>`)}</td>
      <td>${(t.scarcity && t.scarcity.length) ? t.scarcity.slice(0, 2).map(s => `<span class="tag">${esc(s)}</span>`).join("") : '<span class="muted">—</span>'}</td>
    </tr>`;
  }
  tw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">BNPL</th><th scope="col">Finance / wallets</th><th scope="col">Sign-up offer</th><th scope="col">Free delivery</th><th scope="col">Scarcity</th></tr></thead><tbody>${frows}</tbody></table>`;
  fc.append(tw);
  wrap.append(fc);

  // --- urgency & conversion levers (homepage) ---
  const uc = el("div", "card");
  uc.innerHTML = `<h3>Urgency &amp; conversion levers</h3>
    <p class="hint">Countdown/urgency copy, bundle offers, gift-with-purchase, loyalty prompts, personalisation upsells,
    SMS capture and live chat — read from each homepage. Empty cells mean the signal wasn't detected, not proven absent.</p>`;
  const utw = el("div", "tablewrap");
  const tag = s => `<span class="tag">${esc(s)}</span>`;
  const dash = '<span class="muted">—</span>';
  let urows = "";
  for (const { b, r } of rows) {
    const t = r.trading || {};
    urows += `<tr>
      <td>${nameCell(b)}</td>
      <td>${(t.urgency || []).length ? t.urgency.slice(0, 2).map(tag).join("") : dash}</td>
      <td>${(t.multibuy || []).length ? t.multibuy.slice(0, 2).map(tag).join("") : dash}</td>
      <td>${t.gift_with_purchase ? tag(t.gift_with_purchase) : dash}</td>
      <td>${t.loyalty ? tag(t.loyalty) : dash}</td>
      <td>${t.personalisation_upsell ? tag(t.personalisation_upsell) : dash}</td>
      <td>${t.sms_capture ? '<span class="pill good">✓</span>' : dash}</td>
      <td>${t.live_chat ? `<span class="pill good">✓${t.live_chat !== "copy" ? " " + esc(t.live_chat) : ""}</span>` : dash}</td>
    </tr>`;
  }
  utw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">Urgency</th><th scope="col">Multi-buy</th><th scope="col">Gift w/ purchase</th><th scope="col">Loyalty</th><th scope="col">Personalisation</th><th scope="col">SMS</th><th scope="col">Live chat</th></tr></thead><tbody>${urows}</tbody></table>`;
  uc.append(utw);
  wrap.append(uc);

  // --- delivery & returns (dedicated policy-page captures) ---
  const withPolicy = rows.filter(x => x.r.delivery_info || x.r.returns_info);
  const dc = el("div", "card");
  dc.innerHTML = `<h3>Delivery &amp; returns</h3>
    <p class="hint">The service proposition from each brand's own delivery and returns pages: priced options,
    free-delivery threshold, express + order cutoff, returns window and whether returns cost the shopper money.</p>`;
  if (withPolicy.length) {
    const dtw = el("div", "tablewrap");
    let drows = "";
    for (const { b, r } of withPolicy) {
      const d = r.delivery_info || {};
      const ret = r.returns_info || {};
      const opts = (d.options || []).slice(0, 3)
        .map(o => tag(`${o.name} ${o.price}`)).join("") || dash;
      const express = d.express
        ? `<span class="pill good">✓${d.express_cutoff ? " by " + esc(d.express_cutoff) : ""}</span>`
          + (d.express_source === "config" ? ' <span class="tag" title="Confirmed express service; the page wording didn\'t match the detection patterns today">confirmed</span>' : "")
        : dash;
      const freeRet = ret.free_returns === true ? '<span class="pill good">free</span>'
        : ret.free_returns === false ? '<span class="pill warn">paid</span>'
        : dash;
      drows += `<tr>
        <td>${nameCell(b)}</td>
        <td>${opts}</td>
        <td class="num">${d.free_threshold == null ? dash : (d.free_threshold === 0 ? '<span class="pill good">free</span>' : `<span class="pill">over £${d.free_threshold}</span>`)}</td>
        <td>${express}</td>
        <td class="num">${ret.window_days != null ? `<span class="pill">${ret.window_days} days</span>` : dash}</td>
        <td>${freeRet}</td>
        <td>${ret.exchanges ? '<span class="pill good">✓</span>' : dash}</td>
      </tr>`;
    }
    dtw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">Delivery options</th><th scope="col">Free over</th><th scope="col">Express</th><th scope="col">Returns window</th><th scope="col">Return cost</th><th scope="col">Exchanges</th></tr></thead><tbody>${drows}</tbody></table>`;
    dc.append(dtw);
  } else {
    dc.append(el("p", "muted", "No delivery/returns pages captured yet — this fills in as the daily job runs (URLs are auto-discovered from each homepage, or set delivery_url / returns_url per brand in config)."));
  }
  wrap.append(dc);
  return wrap;
}

// ---------- accessibility view ----------
// ---------- market map (positioning: price × range size) ----------
// A robust median price for positioning. Both the listing-page and homepage
// price samplers are directional and occasionally pick up noise (a "spend over
// £X" line, a bundle, a stray "was" price). When BOTH exist and disagree wildly
// (>4x), we can DETECT the price is unreliable, so we decline to place the brand
// rather than mislabel it — and say so. Otherwise we prefer the real listing
// median, else the homepage band.
function brandPriceSignal(r) {
  const lm = r && r.listing && r.listing.prices && r.listing.prices.median != null ? r.listing.prices.median : null;
  const hm = r && r.prices && r.prices.median != null ? r.prices.median : null;
  if (lm != null && hm != null) {
    const hi = Math.max(lm, hm), lo = Math.min(lm, hm);
    if (lo > 0 && hi / lo > 4) return { price: null, noisy: true, lm, hm };
    return { price: lm, noisy: false };
  }
  if (lm != null) return { price: lm, noisy: false };
  if (hm != null) return { price: hm, noisy: false };
  return { price: null, noisy: false };
}

function viewMarketMap() {
  const wrap = el("div");
  const runs = (state.catalogue && state.catalogue.runs) || [];
  const latestCat = runs.length ? runs[runs.length - 1].brands || {} : {};
  const brands = brandsSorted();

  // Join price signal + catalogue range size for EVERY tracked brand. Where a
  // coordinate is missing or detectably unreliable we estimate it at the pack
  // median and render the point visibly differently (hollow, dashed) with a
  // caveat below — a brand with a noisy signal still exists in the market, so
  // dropping it from the map would misdescribe the field.
  const joined = brands.map(b => {
    const r = state.latest[b.slug];
    const ce = latestCat[b.slug];
    const size = ce && ce.ok && ce.product_count != null ? ce.product_count : null;
    return { b, size, sig: brandPriceSignal(r) };
  });
  const knownPrices = joined.filter(j => !j.sig.noisy && j.sig.price != null).map(j => j.sig.price).sort((a, b) => a - b);
  const knownSizes = joined.filter(j => j.size != null).map(j => j.size).sort((a, b) => a - b);

  const intro = el("div", "card");
  intro.innerHTML = `<h3>Market map — positioning</h3>
    <p class="hint">Where each brand sits on <b>price</b> (median, from real listing pages where available, else the homepage band)
    against <b>range size</b> (catalogue products from sitemaps), splitting the market into value/premium × niche/broad.
    Every tracked brand is plotted; estimated positions are hollow dashed dots (see the caveats below the map).</p>`;
  wrap.append(intro);

  if (knownPrices.length < 3 || knownSizes.length < 3) {
    const c = el("div", "card");
    c.innerHTML = `<p class="muted">Not enough measured price + catalogue data yet to map positions
      (need at least 3 brands measured on each axis). This fills in as the daily capture and the catalogue step run.</p>`;
    wrap.append(c);
    return wrap;
  }

  // Pack medians of MEASURED brands = the quadrant dividers and the fallback
  // position for brands whose own signal is missing/noisy.
  const medP = knownPrices[Math.floor(knownPrices.length / 2)];
  const medS = knownSizes[Math.floor(knownSizes.length / 2)];

  const pts = [];
  const caveats = [];
  for (const { b, size, sig } of joined) {
    let price = sig.price, estimated = false;
    const why = [];
    if (sig.noisy) {
      price = medP; estimated = true;
      why.push(`listing £${Math.round(sig.lm)} vs homepage £${Math.round(sig.hm)} disagree by more than 4× (usually a stray "spend over £X", bundle or "was" price) — plotted at the pack-median price`);
    } else if (price == null) {
      price = medP; estimated = true;
      why.push("no price captured — plotted at the pack-median price");
    }
    let s = size;
    if (s == null) {
      s = medS; estimated = true;
      why.push("no readable product sitemap — plotted at the pack-median range size");
    }
    if (why.length) caveats.push({ b, why: why.join("; ") });
    pts.push({ b, price, size: s, estimated });
  }

  // SVG scale with padding so points don't sit on the frame.
  const W = 760, H = 470, mL = 58, mR = 128, mT = 28, mB = 46;
  const pW = W - mL - mR, pH = H - mT - mB;
  const xs = pts.map(p => p.price), ys = pts.map(p => p.size);
  let xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
  const xpad = (xmax - xmin || xmax || 1) * 0.12, ypad = (ymax - ymin || ymax || 1) * 0.12;
  xmin -= xpad; xmax += xpad; ymin = Math.max(0, ymin - ypad); ymax += ypad;
  const X = v => mL + (v - xmin) / (xmax - xmin || 1) * pW;
  const Y = v => mT + pH - (v - ymin) / (ymax - ymin || 1) * pH;

  const ticksX = 4, ticksY = 4;
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img" aria-label="Market positioning map">`;
  // Quadrant background tint (very light) split by the median lines.
  svg += `<rect x="${mL}" y="${mT}" width="${pW}" height="${pH}" fill="#fcfafb" stroke="var(--line)"/>`;
  // Axis ticks + labels.
  for (let i = 0; i <= ticksX; i++) {
    const v = xmin + (xmax - xmin) * i / ticksX, x = X(v);
    svg += `<line x1="${x}" y1="${mT}" x2="${x}" y2="${mT + pH}" stroke="#f1ecef"/>`;
    svg += `<text x="${x}" y="${mT + pH + 16}" font-size="11" text-anchor="middle" fill="var(--muted)">£${Math.round(v)}</text>`;
  }
  for (let i = 0; i <= ticksY; i++) {
    const v = ymin + (ymax - ymin) * i / ticksY, y = Y(v);
    svg += `<line x1="${mL}" y1="${y}" x2="${mL + pW}" y2="${y}" stroke="#f1ecef"/>`;
    svg += `<text x="${mL - 8}" y="${y + 4}" font-size="11" text-anchor="end" fill="var(--muted)">${Math.round(v)}</text>`;
  }
  // Axis titles.
  svg += `<text x="${mL + pW / 2}" y="${H - 6}" font-size="12" text-anchor="middle" fill="var(--muted)">Median price (£) →</text>`;
  svg += `<text x="14" y="${mT + pH / 2}" font-size="12" text-anchor="middle" fill="var(--muted)" transform="rotate(-90 14 ${mT + pH / 2})">Range size (products) →</text>`;
  // Median dividers.
  const mx = X(medP), my = Y(medS);
  svg += `<line x1="${mx}" y1="${mT}" x2="${mx}" y2="${mT + pH}" stroke="var(--accent2)" stroke-dasharray="5 4" opacity="0.7"/>`;
  svg += `<line x1="${mL}" y1="${my}" x2="${mL + pW}" y2="${my}" stroke="var(--accent2)" stroke-dasharray="5 4" opacity="0.7"/>`;
  // Quadrant labels (corners).
  const ql = (x, y, anchor, t) => `<text x="${x}" y="${y}" font-size="11.5" font-weight="600" text-anchor="${anchor}" fill="#b9b2bb">${t}</text>`;
  svg += ql(mL + 8, mT + 16, "start", "Broad & value");
  svg += ql(mL + pW - 8, mT + 16, "end", "Broad & premium");
  svg += ql(mL + 8, mT + pH - 8, "start", "Niche & value");
  svg += ql(mL + pW - 8, mT + pH - 8, "end", "Niche & premium");
  // Points. Estimated positions render hollow with a dashed ring so they can
  // never be mistaken for a measurement.
  for (const p of pts) {
    const cx = X(p.price), cy = Y(p.size), self = p.b.is_self;
    const rad = self ? 8 : 6;
    const fill = p.estimated ? "none" : (self ? "var(--accent)" : "#fff");
    const stroke = p.estimated ? (self ? "var(--accent)" : "var(--muted)")
      : (self ? "var(--accent)" : "var(--accent2)");
    const dash = p.estimated ? ' stroke-dasharray="3 3"' : "";
    const labelRight = cx < mL + pW * 0.72;
    const lx = labelRight ? cx + rad + 5 : cx - rad - 5;
    const anchor = labelRight ? "start" : "end";
    svg += `<circle cx="${cx}" cy="${cy}" r="${rad}" fill="${fill}" stroke="${stroke}" stroke-width="2"${dash}>`
         + `<title>${esc(p.b.brand)} — £${Math.round(p.price)} median, ${p.size} products${p.estimated ? " (position estimated)" : ""}</title></circle>`;
    svg += `<text x="${lx}" y="${cy + 4}" font-size="11.5" text-anchor="${anchor}" `
         + `fill="${self ? "var(--accent)" : "var(--ink)"}" font-weight="${self ? 700 : 500}">${esc(p.b.brand)}${self ? " ★" : ""}</text>`;
  }
  svg += `</svg>`;

  const mapCard = el("div", "card");
  mapCard.innerHTML = `<h3>Positioning — ${esc((runs[runs.length - 1] || {}).date || latestDate())}</h3>
    <p class="hint">Dashed lines are the pack medians (£${Math.round(medP)} · ${Math.round(medS)} products). ★ = Katie Loxton. Hover a dot for detail.</p>${svg}`;
  wrap.append(mapCard);

  // Where does Katie Loxton sit?
  const jp = pts.find(p => p.b.is_self);
  if (jp && !jp.estimated) {
    const quad = (jp.size >= medS ? "broad" : "niche") + " & " + (jp.price >= medP ? "premium" : "value");
    const vc = el("div", "card");
    vc.innerHTML = `<h3>Where Katie Loxton sits</h3><p class="hint" style="margin:0">Katie Loxton maps to the <b>${esc(quad)}</b> quadrant
      (≈£${Math.round(jp.price)} median across ${jp.size} products). The empty quadrants are the strategic white space —
      compare against the range-size and pricing tabs before reading too much into one snapshot.</p>`;
    wrap.append(vc);
  }

  if (caveats.length) {
    const nc = el("div", "card");
    nc.innerHTML = `<h3>Plotted with a caveat</h3>
      <p class="hint">Every tracked brand is on the map, but these positions are <b>estimated</b> (hollow dashed dots), not measured:</p>
      <div>${caveats.map(n => `<span class="tag">${esc(n.b.brand)} — ${esc(n.why)}</span>`).join("")}</div>`;
    wrap.append(nc);
  }

  const note = el("div", "card");
  note.innerHTML = `<p class="hint" style="margin:0">Price is a directional median (a homepage/listing sample, not a full price list)
    and range size counts published products from sitemaps (not stock or sales) — a positioning read over time, not a precise valuation.</p>`;
  wrap.append(note);
  return wrap;
}

// ---------- assortment / new-product velocity ----------
let assortMixState = { slug: null };   // selected brand for the range-mix trend

function viewAssortment() {
  const wrap = el("div");
  const runs = (state.catalogue && state.catalogue.runs) || [];
  const brands = brandsSorted();

  if (!runs.length) {
    const c = el("div", "card");
    c.innerHTML = `<h3>Assortment &amp; new-product velocity</h3>
      <p class="hint">Built from each brand's <b>product sitemap</b> — tracking how big each competitor's range is,
      who's expanding, and who's adding new products.</p>
      <p class="muted">No catalogue data yet — this populates on the next daily capture. New-vs-removed needs a second run to
      compare against (the first run just records each range's size).</p>`;
    wrap.append(c);
    return wrap;
  }

  const latest = runs[runs.length - 1];
  const lb = latest.brands || {};
  // Recent newness window: sum new_count over up to the last 7 runs.
  const recent = runs.slice(-7);
  const recentNew = {};
  for (const b of brands) {
    recentNew[b.slug] = recent.reduce((s, r) => {
      const e = (r.brands || {})[b.slug];
      return s + (e && e.ok && !e.first_seen ? (e.new_count || 0) : 0);
    }, 0);
  }
  const counts = brands.map(b => lb[b.slug]).filter(e => e && e.ok && e.product_count != null).map(e => e.product_count);
  const total = counts.reduce((a, c) => a + c, 0);
  const med = counts.length ? counts.slice().sort((a, b) => a - b)[Math.floor(counts.length / 2)] : null;
  const me = brands.find(b => b.is_self);
  const je = me && lb[me.slug];

  const kpis = el("div", "grid cols-3");
  const kpi = (big, lbl) => { const c = el("div", "card kpi"); c.innerHTML = `<div class="big">${big}</div><div class="lbl">${lbl}</div>`; return c; };
  kpis.append(
    kpi(total ? fmtCount(total) : "—", "products tracked across the market"),
    kpi(je && je.ok && je.product_count != null ? fmtCount(je.product_count) : "—", "Katie Loxton's range size"),
    kpi(med == null ? "—" : fmtCount(med), "pack median range size"),
  );
  wrap.append(kpis);

  const note = el("div", "card");
  note.innerHTML = `<h3>What this is</h3><p class="hint" style="margin:0">Catalogue size and <b>new-product velocity</b> read from each brand's product sitemap.
    <b>New</b> counts product handles that appeared since the previous run; a brand's <i>first</i> day shows its size but zero velocity (no prior snapshot to diff).
    A brand whose sitemap can't be read shows as <b>"no sitemap"</b> for that day. Works best for Shopify-style stores; some brands don't expose a readable product sitemap.</p>`;
  wrap.append(note);

  const card = el("div", "card");
  card.innerHTML = `<h3>Range size &amp; newness — ${esc(latest.date || latestDate())}</h3>
    <p class="hint">Ranked by catalogue size. <b>New (7d)</b> = product handles added across the last up-to-7 runs. ★ = Katie Loxton.</p>`;
  const tw = el("div", "tablewrap");
  const ordered = brands.slice().sort((a, a2) => {
    const ea = lb[a.slug], eb = lb[a2.slug];
    return ((eb && eb.product_count) || -1) - ((ea && ea.product_count) || -1);
  });
  const maxCount = Math.max(1, ...counts);
  let rows = "";
  for (const b of ordered) {
    const e = lb[b.slug];
    if (!e || !e.ok || e.product_count == null) {
      rows += `<tr><td>${nameCell(b)}</td><td colspan="3"><span class="muted">no sitemap</span></td></tr>`;
      continue;
    }
    const newN = recentNew[b.slug] || 0;
    const newCell = e.first_seen
      ? '<span class="tag" title="First observation — no prior snapshot to compare">baseline</span>'
      : (newN > 0 ? `<span class="pill warn">+${newN}</span>` : '<span class="muted">0</span>');
    rows += `<tr>
      <td>${nameCell(b)}</td>
      <td class="num">${fmtCount(e.product_count)}</td>
      <td><span class="bar"><span style="width:${Math.round(e.product_count / maxCount * 100)}%"></span></span></td>
      <td class="num">${newCell}</td>
    </tr>`;
  }
  tw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">Products</th><th scope="col"></th><th scope="col">New (7d)</th></tr></thead><tbody>${rows}</tbody></table>`;
  card.append(tw);
  wrap.append(card);

  // --- Range mix by category (matrix of share-of-each-brand's-range) ---
  const withCats = brands.filter(b => { const e = lb[b.slug]; return e && e.ok && e.categories && e.product_count; });
  if (withCats.length) {
    // Column set: categories ranked by total prevalence across brands, top 8.
    const totals = {};
    for (const b of withCats) for (const [c, n] of Object.entries(lb[b.slug].categories)) totals[c] = (totals[c] || 0) + n;
    const cols = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([c]) => c);
    const mc = el("div", "card");
    mc.innerHTML = `<h3>Range mix by category — ${esc(latest.date || latestDate())}</h3>
      <p class="hint">Share of each brand's own published range that falls in each category (a product can sit in more than one, so rows needn't sum to 100%).
      The actual assortment, not homepage mentions. ★ = Katie Loxton.</p>`;
    const mtw = el("div", "tablewrap");
    const shareCell = (e, c) => {
      const n = (e.categories || {})[c] || 0;
      if (!n) return '<td class="num"><span class="muted">·</span></td>';
      const pct = Math.round(n / e.product_count * 100);
      return `<td class="num"><span class="pill ${pct >= 25 ? "good" : pct >= 10 ? "warn" : ""}">${pct}%</span></td>`;
    };
    let mrows = "";
    for (const b of withCats) {
      const e = lb[b.slug];
      mrows += `<tr><td>${nameCell(b)}</td>${cols.map(c => shareCell(e, c)).join("")}</tr>`;
    }
    mtw.innerHTML = `<table><thead><tr><th scope="col">Brand</th>${cols.map(c => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead><tbody>${mrows}</tbody></table>`;
    mc.append(mtw);
    wrap.append(mc);
  }

  // --- Range-mix trend over time (monthly, per selected brand) ---
  const trendBrands = brands.filter(b => runs.some(r => {
    const e = (r.brands || {})[b.slug]; return e && e.ok && e.categories && e.product_count;
  }));
  if (trendBrands.length) {
    const sel = (assortMixState.slug && trendBrands.some(b => b.slug === assortMixState.slug))
      ? assortMixState.slug
      : (trendBrands.find(b => b.is_self) || trendBrands[0]).slug;
    const selName = (state.byBrand[sel] || {}).brand || sel;

    const tc = el("div", "card");
    tc.innerHTML = `<h3>Range-mix trend over time</h3>
      <p class="hint">How <b>${esc(selName)}</b>'s range <i>shape</i> shifts month to month — each cell is that category's share of the
      published range, with the move vs the previous month (▲/▼ percentage points). Builds up as catalogue history accumulates.</p>`;
    const pick = el("div", "brandpick");
    for (const b of trendBrands) {
      const btn = el("button", b.slug === sel ? "active" : "", esc(b.brand) + (b.is_self ? " ★" : ""));
      btn.onclick = () => { assortMixState.slug = b.slug; render(); };
      pick.append(btn);
    }
    tc.append(pick);

    // Aggregate the selected brand's catalogue runs into monthly buckets.
    const byMonth = {};
    for (const r of runs) {
      const e = (r.brands || {})[sel];
      if (!e || !e.ok || !e.categories || !e.product_count) continue;
      (byMonth[periodKey(r.date, "monthly")] ||= []).push(e);
    }
    const months = Object.keys(byMonth).sort().slice(-6);
    const share = (m, cat) => avgOf(byMonth[m].map(e => (e.categories[cat] || 0) / e.product_count));
    if (months.length) {
      const lastM = months[months.length - 1];
      const catSet = new Set();
      for (const m of months) for (const e of byMonth[m]) for (const c of Object.keys(e.categories)) catSet.add(c);
      const cats = [...catSet].sort((a, b) => (share(lastM, b) || 0) - (share(lastM, a) || 0)).slice(0, 8);
      const tw = el("div", "tablewrap");
      let rows = "";
      for (const cat of cats) {
        let cells = "", prev = null;
        for (const m of months) {
          const s = share(m, cat);
          if (s == null) { cells += `<td class="num"><span class="muted">·</span></td>`; continue; }
          const pct = Math.round(s * 100);
          let arrow = "";
          if (prev != null) {
            const d = pct - prev;
            arrow = d > 0 ? ` <span style="color:var(--good)">▲${d}</span>`
              : d < 0 ? ` <span style="color:var(--bad)">▼${-d}</span>` : ` <span class="muted">–</span>`;
          }
          cells += `<td class="num">${pct}%${arrow}</td>`;
          prev = pct;
        }
        rows += `<tr><td>${esc(cat)}</td>${cells}</tr>`;
      }
      tw.innerHTML = `<table><thead><tr><th>Category</th>${months.map(m => `<th>${esc(m)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`;
      tc.append(tw);
      if (months.length < 2) tc.append(el("p", "hint", "Only one month of catalogue history so far — the month-on-month moves appear once a second month lands."));
    } else {
      tc.append(el("p", "muted", "No category history for this brand yet."));
    }
    wrap.append(tc);
  }

  if (je && je.ok && je.product_count != null && med != null) {
    const verdict = je.product_count >= med ? "at or above" : "below";
    const vc = el("div", "card");
    vc.innerHTML = `<h3>Katie Loxton vs the pack</h3><p class="hint" style="margin:0">Katie Loxton's range (<b>${fmtCount(je.product_count)}</b> products) sits <b>${verdict}</b>
      the pack median (<b>${fmtCount(med)}</b>). Range breadth and how fast rivals add new lines are merchandising signals — gaps surface on the Opportunities tab.</p>`;
    wrap.append(vc);
  }
  return wrap;
}

// ---------- reputation / social proof ----------
// A homepage rating only counts as "verified" when it's backed by a real review
// volume — otherwise one thin score (e.g. 10 reviews) can set the whole market
// average. Ratings below the bar are shown, tagged, and left OUT of the average.
const MIN_VERIFIED_REVIEWS = 25;
const isVerifiedRating = rep => !!(rep && rep.rating != null && rep.review_count != null && rep.review_count >= MIN_VERIFIED_REVIEWS);
function ratingClass(v) { return v == null ? "" : v >= 4.7 ? "good" : v >= 4.3 ? "warn" : "bad"; }
function fmtCount(n) {
  if (n == null) return "—";
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k";
  return String(n);
}

function viewReputation() {
  const wrap = el("div");
  const brands = brandsSorted();
  const verified = brands.map(b => state.latest[b.slug]).filter(r => isVerifiedRating(r && r.reputation));
  const avg = avgOf(verified.map(r => r.reputation.rating));
  const me = brands.find(b => b.is_self);
  const jr = me && state.latest[me.slug];
  const jrep = jr && jr.reputation;
  const meVerified = isVerifiedRating(jrep);

  const kpis = el("div", "grid cols-3");
  const kpi = (big, lbl) => { const c = el("div", "card kpi"); c.innerHTML = `<div class="big">${big}</div><div class="lbl">${lbl}</div>`; return c; };
  kpis.append(
    kpi(avg == null ? "—" : avg.toFixed(2) + "★", "market avg verified rating"),
    kpi(meVerified ? jrep.rating + "★" : "—", "Katie Loxton's verified rating"),
    kpi(verified.length + "/" + brands.length, "brands with a verified rating"),
  );
  wrap.append(kpis);

  const note = el("div", "card");
  note.innerHTML = `<h3>What this is</h3><p class="hint" style="margin:0">The <b>trust pillar</b>: the star rating, review volume and review platforms each brand
    surfaces on its homepage (JSON-LD <code>AggregateRating</code> plus Trustpilot/Yotpo/Okendo/Reviews.io/Feefo-style widgets).
    A rating only counts as <b>verified</b> — and toward the market average — when it's backed by at least <b>${MIN_VERIFIED_REVIEWS} reviews</b>; thinner scores are shown but tagged, so one low-volume rating can't set the bar.
    Most brands surface a review <i>widget</i> without an aggregate number we can read, which honestly shows as a platform with no rating.</p>`;
  wrap.append(note);

  const card = el("div", "card");
  card.innerHTML = `<h3>Social-proof leaderboard — ${latestDate()}</h3><p class="hint">Latest successful capture per brand. Verified ratings first, then thin-volume, then widget-only. ★ = Katie Loxton.</p>`;
  const tw = el("div", "tablewrap");
  // Rank: verified ratings first (by score), then any rating, then review-widget
  // presence, then nothing surfaced.
  const repScore = b => {
    const rep = state.latest[b.slug] && state.latest[b.slug].reputation || {};
    return (isVerifiedRating(rep) ? 1e6 : 0) + (rep.rating != null ? rep.rating * 1000 : 0)
      + (rep.review_count || 0) / 1e6 + ((rep.platforms || []).length ? 0.1 : 0);
  };
  const ordered = brands.slice().sort((a, b) => repScore(b) - repScore(a));
  let rows = "";
  for (const b of ordered) {
    const r = state.latest[b.slug]; const rep = r && r.reputation;
    if (!rep || !rep.has_reviews) { rows += `<tr><td>${nameCell(b)}</td><td colspan="3"><span class="muted">none surfaced</span></td></tr>`; continue; }
    const plats = (rep.platforms || []).map(p => `<span class="tag">${esc(p)}</span>`).join("") || '<span class="muted">—</span>';
    let ratingCell = '<span class="muted">—</span>';
    if (rep.rating != null) {
      ratingCell = isVerifiedRating(rep)
        ? `<span class="pill ${ratingClass(rep.rating)}">${rep.rating}★</span>`
        : `<span class="pill" title="Only ${fmtCount(rep.review_count)} reviews — below the ${MIN_VERIFIED_REVIEWS}-review bar, so it's not counted in the market average">${rep.rating}★ <span class="muted">· low volume</span></span>`;
    }
    rows += `<tr>
      <td>${nameCell(b)}</td>
      <td class="num">${ratingCell}</td>
      <td class="num">${fmtCount(rep.review_count)}</td>
      <td>${plats}</td>
    </tr>`;
  }
  tw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">Rating</th><th scope="col">Reviews</th><th scope="col">Platforms</th></tr></thead><tbody>${rows}</tbody></table>`;
  card.append(tw);
  wrap.append(card);

  // Katie Loxton-vs-pack one-liner — only meaningful when there's verified volume to compare.
  const vc = el("div", "card");
  if (meVerified && verified.filter(r => !r.is_self).length) {
    const pack = verified.filter(r => !r.is_self).map(r => r.reputation.rating).sort((a, b) => a - b);
    const med = pack[Math.floor(pack.length / 2)];
    const verdict = jrep.rating >= med ? "at or above" : "below";
    vc.innerHTML = `<h3>Katie Loxton vs the pack</h3><p class="hint" style="margin:0">Katie Loxton's verified rating (<b>${jrep.rating}★</b>) sits <b>${verdict}</b>
      the verified pack median (<b>${med.toFixed(2)}★</b>). A visible rating is one of the cheapest top-of-funnel trust levers — gaps surface on the Opportunities tab.</p>`;
  } else {
    vc.innerHTML = `<h3>Katie Loxton vs the pack</h3><p class="hint" style="margin:0">No brand currently surfaces a rating with enough verified volume to compare
      (most show a review widget without a readable aggregate). Surfacing a real, well-evidenced rating on the homepage is an easy, honest trust win.</p>`;
  }
  wrap.append(vc);
  return wrap;
}

function viewA11y() {
  const wrap = el("div");
  const brands = brandsSorted();
  const scored = brands.map(b => state.latest[b.slug]).filter(r => r && r.accessibility);
  const avg = avgOf(scored.map(r => r.accessibility.score));
  const me = brands.find(b => b.is_self);
  const jr = me && state.latest[me.slug];

  const kpis = el("div", "grid cols-3");
  const kpi = (big, lbl) => { const c = el("div", "card kpi"); c.innerHTML = `<div class="big">${big}</div><div class="lbl">${lbl}</div>`; return c; };
  kpis.append(
    kpi(avg == null ? "—" : Math.round(avg), "market avg accessibility score"),
    kpi(jr && jr.accessibility ? `${jr.accessibility.score} · ${esc(jr.accessibility.grade)}` : "—", "Katie Loxton's score"),
    kpi(scored.length, "brands with a score"),
  );
  wrap.append(kpis);

  const note = el("div", "card");
  note.innerHTML = `<h3>What this is</h3><p class="hint" style="margin:0">A rules-based, "Lighthouse-lite" homepage audit (0–100, higher is better) — alt text,
    page language, form labels, landmarks, heading structure and similar checks that can be read straight from the HTML.
    <b>It is not a full WCAG audit:</b> it can't judge colour contrast, keyboard order or anything needing a live render.
    Treat it as a cheap directional signal. Scores populate as daily captures run.</p>`;
  wrap.append(note);

  const card = el("div", "card");
  card.innerHTML = `<h3>Accessibility scores — ${latestDate()}</h3><p class="hint">Latest successful capture per brand. ★ = Katie Loxton.</p>`;
  const tw = el("div", "tablewrap");
  let rows = "";
  for (const b of brands) {
    const r = state.latest[b.slug]; const a = r && r.accessibility;
    if (!a) { rows += `<tr><td>${nameCell(b)}</td><td colspan="3"><span class="muted">no data</span></td></tr>`; continue; }
    const fails = (a.checks || []).filter(c => c.applicable !== false && c.ratio < 0.9)
      .sort((x, y) => y.weight - x.weight).slice(0, 5);
    rows += `<tr>
      <td>${nameCell(b)}</td>
      <td class="num"><span class="pill ${a11yClass(a.score)}">${a.score} · ${esc(a.grade)}</span></td>
      <td><span class="bar"><span style="width:${Math.max(0, Math.min(100, a.score))}%"></span></span></td>
      <td>${fails.length ? fails.map(c => `<span class="tag" title="${esc(c.detail || "")}">${esc(c.label)}</span>`).join("") : '<span class="pill good">all checks pass</span>'}</td>
    </tr>`;
  }
  tw.innerHTML = `<table><thead><tr><th scope="col">Brand</th><th scope="col">Score</th><th scope="col"></th><th scope="col">Top issues to fix</th></tr></thead><tbody>${rows}</tbody></table>`;
  card.append(tw);
  wrap.append(card);
  return wrap;
}

// ---------- weekly / monthly / quarterly overview ----------
let periodState = { gran: "monthly", metric: "a11y" };
const PERIOD_GRAN = [["weekly", "Weekly", 8], ["monthly", "Monthly", 6], ["quarterly", "Quarterly", 4]];
const PERIOD_METRICS = [
  ["a11y",     "Accessibility", r => (r.accessibility ? r.accessibility.score : null), v => (v == null ? "—" : Math.round(v)),       s => a11yClass(s)],
  ["seo",      "SEO health",    r => seoHealth(r),                                     v => (v == null ? "—" : Math.round(v)),       s => (s == null ? "" : s >= 80 ? "good" : s >= 60 ? "warn" : "bad")],
  ["promo",    "Promo intensity", r => (r.headline_offer ? 100 : 0),                   v => (v == null ? "—" : Math.round(v) + "%"), s => (s == null ? "" : s >= 50 ? "warn" : "")],
  ["discount", "Avg discount",  r => (r.max_discount_pct || 0),                        v => (v == null ? "—" : Math.round(v) + "%"), s => (s == null ? "" : s >= 30 ? "warn" : "")],
];

function viewPeriods() {
  const wrap = el("div");
  const succ = state.captures.filter(r => r.status === "success");

  const ctrl = el("div", "card");
  ctrl.innerHTML = `<h3>Weekly / monthly / quarterly overview</h3>
    <p class="hint">Aggregated trends over time — by brand and by jewellery category. These views fill in as daily captures
    accumulate: weekly within ~a week, monthly within ~a month, quarterly within ~3 months.</p>`;
  const granRow = el("div", "brandpick");
  granRow.setAttribute("role", "group");
  granRow.setAttribute("aria-label", "Granularity");
  for (const [g, label] of PERIOD_GRAN) {
    const btn = el("button", g === periodState.gran ? "active" : "", label);
    btn.setAttribute("aria-pressed", g === periodState.gran ? "true" : "false");
    btn.onclick = () => { periodState.gran = g; render(); };
    granRow.append(btn);
  }
  const metRow = el("div", "brandpick");
  metRow.setAttribute("role", "group");
  metRow.setAttribute("aria-label", "Metric for by-brand table");
  for (const m of PERIOD_METRICS) {
    const btn = el("button", m[0] === periodState.metric ? "active" : "", m[1]);
    btn.setAttribute("aria-pressed", m[0] === periodState.metric ? "true" : "false");
    btn.onclick = () => { periodState.metric = m[0]; render(); };
    metRow.append(btn);
  }
  ctrl.append(el("p", "hint", "Granularity"), granRow, el("p", "hint", "Metric (by-brand table)"), metRow);
  wrap.append(ctrl);

  if (!succ.length) {
    const c = el("div", "card");
    c.innerHTML = `<p class="muted">Not enough capture data yet. As the daily job runs, periods appear here automatically.</p>`;
    wrap.append(c);
    return wrap;
  }

  const gran = periodState.gran;
  const periodWord = gran.replace("ly", "");                    // weekly→week …
  const nLimit = (PERIOD_GRAN.find(p => p[0] === gran) || [])[2] || 6;
  const keys = [...new Set(succ.map(r => periodKey(r.date, gran)))].sort().slice(-nLimit);

  // --- by brand ---
  const metric = PERIOD_METRICS.find(m => m[0] === periodState.metric);
  const brands = brandsSorted();
  const brandCard = el("div", "card");
  brandCard.innerHTML = `<h3>By brand · ${metric[1]}</h3><p class="hint">Average per ${periodWord} period. ★ = Katie Loxton.</p>`;
  const tw = el("div", "tablewrap");
  let head = `<tr><th scope="col">Brand</th>${keys.map(k => `<th scope="col">${esc(k)}</th>`).join("")}</tr>`;
  let body = "";
  for (const b of brands) {
    let cells = "";
    for (const k of keys) {
      const recs = succ.filter(r => r.slug === b.slug && periodKey(r.date, gran) === k);
      const v = recs.length ? avgOf(recs.map(metric[2])) : null;
      cells += `<td class="num">${recs.length && v != null ? `<span class="pill ${metric[4](v)}">${metric[3](v)}</span>` : '<span class="muted">—</span>'}</td>`;
    }
    body += `<tr><td>${nameCell(b)}</td>${cells}</tr>`;
  }
  tw.innerHTML = `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
  brandCard.append(tw);
  wrap.append(brandCard);

  // --- by jewellery category (market-wide avg share of product mentions) ---
  const catTotal = {};
  for (const r of succ) for (const [c, v] of Object.entries(r.product_mix || {})) catTotal[c] = (catTotal[c] || 0) + (v.share || 0);
  const topCats = Object.keys(catTotal).sort((a, b) => catTotal[b] - catTotal[a]).slice(0, 10);

  const catCard = el("div", "card");
  catCard.innerHTML = `<h3>By jewellery category · share of product mentions</h3>
    <p class="hint">Market-wide average share per ${periodWord} period — what the field is pushing.</p>`;
  const tw2 = el("div", "tablewrap");
  let head2 = `<tr><th scope="col">Category</th>${keys.map(k => `<th scope="col">${esc(k)}</th>`).join("")}</tr>`;
  let body2 = "";
  for (const c of topCats) {
    let cells = "";
    for (const k of keys) {
      const recs = succ.filter(r => periodKey(r.date, gran) === k);
      const v = recs.length ? avgOf(recs.map(r => (r.product_mix && r.product_mix[c] ? r.product_mix[c].share : 0) * 100)) : null;
      cells += `<td class="num">${v == null ? '<span class="muted">—</span>' : `<span class="pill">${Math.round(v)}%</span>`}</td>`;
    }
    body2 += `<tr><td><b>${esc(c)}</b></td>${cells}</tr>`;
  }
  tw2.innerHTML = `<table><thead>${head2}</thead><tbody>${body2}</tbody></table>`;
  catCard.append(tw2);
  if (!topCats.length) catCard.append(el("p", "muted", "No product-mix data captured yet."));
  wrap.append(catCard);
  return wrap;
}

// ---------- opportunity infographics (inline SVG, theme-aware) ----------
// Each opportunity kind renders as the diagram matching its actual mechanism —
// a self-reinforcing flywheel, a funnel with the leak stage highlighted, or a
// cause→effect chain. Kinds without an obvious diagram shape fall back to
// plain text — no forced metaphors. All SVGs carry <title>/<desc> for screen
// readers and use theme CSS custom properties.

let _svgId = 0;
function _svgOpen(w, h, title, desc) {
  const id = "oppsvg" + (++_svgId);
  return [`<svg viewBox="0 0 ${w} ${h}" class="oppsvg" role="img" aria-labelledby="${id}t ${id}d">`
    + `<title id="${id}t">${esc(title)}</title><desc id="${id}d">${esc(desc)}</desc>`, id];
}

// Wrap a short label into <tspan> lines that fit a box.
function _tspans(label, x, y, maxChars) {
  const words = label.split(" ");
  const lines = [""];
  for (const w of words) {
    const cur = lines[lines.length - 1];
    if (cur && (cur + " " + w).length > maxChars) lines.push(w);
    else lines[lines.length - 1] = cur ? cur + " " + w : w;
  }
  const y0 = y - (lines.length - 1) * 6.5;
  return lines.map((l, i) =>
    `<tspan x="${x}" y="${y0 + i * 13}">${esc(l)}</tspan>`).join("");
}

function svgChain(steps, title) {
  const n = steps.length, W = 640, H = 84, gap = 26;
  const bw = (W - gap * (n - 1) - 8) / n, bh = 64;
  const [open] = _svgOpen(W, H, title, "Cause and effect chain: " + steps.join(", then "));
  let s = open;
  steps.forEach((step, i) => {
    const x = 4 + i * (bw + gap);
    const last = i === n - 1;
    s += `<rect x="${x}" y="10" width="${bw}" height="${bh}" rx="10" fill="${last ? "var(--bad-bg,#f7e4e4)" : "var(--card,#fff)"}" stroke="${last ? "var(--bad)" : "var(--line)"}"/>`;
    s += `<text x="${x + bw / 2}" y="${10 + bh / 2 + 4}" font-size="11.5" text-anchor="middle" fill="${last ? "var(--bad)" : "var(--ink)"}">${_tspans(step, x + bw / 2, 10 + bh / 2 + 4, Math.round(bw / 6.2))}</text>`;
    if (!last) {
      const ax = x + bw;
      s += `<path d="M${ax + 4} ${10 + bh / 2} h${gap - 14} m-6 -5 l6 5 l-6 5" fill="none" stroke="var(--muted)" stroke-width="1.8"/>`;
    }
  });
  return s + "</svg>";
}

function svgFunnel(stages, leak, note, title) {
  const n = stages.length, W = 640, H = 46 * n + 30;
  const [open] = _svgOpen(W, H, title,
    `Funnel: ${stages.join(" → ")}. Leak at the ${stages[leak]} stage: ${note}`);
  let s = open;
  const cx = 210, top = 10, rh = 38, vgap = 8;
  stages.forEach((st, i) => {
    const wTop = 340 - i * 64, wBot = 340 - (i + 1) * 64;
    const y = top + i * (rh + vgap);
    const isLeak = i === leak;
    s += `<path d="M${cx - wTop / 2} ${y} h${wTop} l${(wBot - wTop) / 2} ${rh} h${-wBot} z"
      fill="${isLeak ? "var(--bad-bg,#f7e4e4)" : "var(--accent-bg,#f0e5ea)"}"
      stroke="${isLeak ? "var(--bad)" : "var(--line)"}"${isLeak ? ' stroke-width="2"' : ""}/>`;
    s += `<text x="${cx}" y="${y + rh / 2 + 4}" font-size="12" text-anchor="middle" fill="${isLeak ? "var(--bad)" : "var(--ink)"}">${esc(st)}</text>`;
    if (isLeak) {
      s += `<path d="M${cx + wTop / 2 + 6} ${y + rh / 2} h30 m-6 -5 l6 5 l-6 5" fill="none" stroke="var(--bad)" stroke-width="1.8"/>`;
      s += `<text x="${cx + wTop / 2 + 44}" y="${y + rh / 2 + 4}" font-size="11.5" fill="var(--bad)">${_tspans(note, cx + wTop / 2 + 44, y + rh / 2 + 4, 34)}</text>`;
    }
  });
  return s + "</svg>";
}

function svgFlywheel(steps, title) {
  const W = 640, H = 240, cx = 180, cy = 120, r = 78;
  const [open] = _svgOpen(W, H, title,
    "Self-reinforcing loop: " + steps.join(" leads to ") + ", which feeds back to the start.");
  let s = open;
  // Four arc arrows around the circle.
  const arc = (a1, a2) => {
    const p = a => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
    const [x1, y1] = p(a1), [x2, y2] = p(a2);
    return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} A${r} ${r} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}" fill="none" stroke="var(--accent)" stroke-width="2.2" marker-end="url(#flyarrow)"/>`;
  };
  s += `<defs><marker id="flyarrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="var(--accent)"/></marker></defs>`;
  const seg = Math.PI / 2, pad = 0.34;
  for (let i = 0; i < 4; i++) s += arc(-Math.PI / 2 + i * seg + pad, -Math.PI / 2 + (i + 1) * seg - pad);
  // Labels at N / E / S / W.
  const pos = [[cx, cy - r - 18], [cx + r + 16, cy], [cx, cy + r + 22], [cx - r - 16, cy]];
  const anchors = ["middle", "start", "middle", "end"];
  steps.slice(0, 4).forEach((st, i) => {
    s += `<text x="${pos[i][0]}" y="${pos[i][1] + 4}" font-size="12" text-anchor="${anchors[i]}" fill="var(--ink)" font-weight="600">${_tspans(st, pos[i][0], pos[i][1] + 4, 20)}</text>`;
  });
  s += `<text x="${cx}" y="${cy + 4}" font-size="11.5" text-anchor="middle" fill="var(--muted)">reinforces</text>`;
  return s + "</svg>";
}

// kind → mechanism diagram. Anything not listed falls back to plain text.
const OPP_DIAGRAMS = {
  promo: o => svgChain(["Pack discounts deepen", "Shoppers price-compare", "Full-price offer loses"], o.title),
  finance: o => svgFunnel(["Browse", "Basket", "Checkout", "Order"], 2, "no BNPL at the payment step", o.title),
  delivery: o => svgFunnel(["Browse", "Basket", "Delivery", "Order"], 2, "threshold friction", o.title),
  acquisition: o => svgFlywheel(["Sign-up offer", "List grows", "Owned traffic", "Repeat sales"], o.title),
  reputation: o => svgFlywheel(["Visible rating", "Shopper trust", "More conversions", "More reviews"], o.title),
  ai_visibility: o => svgFunnel(["AI answer", "Shortlist", "Site visit", "Sale"], 0, "absent from the answer", o.title),
  assortment: o => svgChain(["Narrower range", "Fewer entry points", "Less discovery"], o.title),
  assortment_mix: o => svgChain(["Category gap", "Buyers shop it elsewhere", "Basket lost"], o.title),
};

// ---------- opportunities + change timeline ----------
const EVENT_LABEL = {
  sale_started: "Sale started", sale_ended: "Sale ended", discount_changed: "Discount moved",
  hero_changed: "Hero rewrite", code_added: "New code", bnpl_added: "BNPL added",
  bnpl_removed: "BNPL dropped", price_shift: "Price shift",
  rating_changed: "Rating moved", reviews_added: "Reviews added",
  products_added: "New products",
};
function viewOpportunities() {
  const wrap = el("div");
  const opps = (state.events && state.events.opportunities) || [];
  const evs = (state.events && state.events.events) || [];

  const intro = el("div", "card");
  intro.innerHTML = `<h3>Opportunities &amp; what changed</h3>
    <p class="hint">Gaps between Katie Loxton and the pack from the latest snapshot, plus a timeline of what's
    changed over time. Updated daily.</p>`;
  wrap.append(intro);

  // Opportunities
  const oc = el("div", "card");
  oc.innerHTML = `<h3>Actionable opportunities</h3>`;
  if (opps.length) {
    const rank = { high: 0, medium: 1, low: 2 };
    const pillCls = { high: "bad", medium: "warn", low: "" };
    oc.append(el("div", "", opps.slice().sort((a, b) => (rank[a.priority] ?? 3) - (rank[b.priority] ?? 3))
      .map(o => {
        const diagram = OPP_DIAGRAMS[o.kind];
        return `<div class="opp">
        <div><span class="pill ${pillCls[o.priority] || ""}">${esc(o.priority)}</span>
          <b style="margin-left:6px">${esc(o.title)}</b></div>
        <div class="hint" style="margin-top:4px">${esc(o.detail)}</div>
        ${diagram ? `<div class="oppdiagram">${diagram(o)}</div>` : ""}</div>`;
      }).join("")));
  } else {
    oc.append(el("p", "muted", "No standout gaps in the latest snapshot — or not enough data yet. "
      + "This fills in as the daily capture runs (and the AI Visibility job, if enabled)."));
  }
  wrap.append(oc);

  // Change timeline
  const tc = el("div", "card");
  tc.innerHTML = `<h3>Recent changes</h3><p class="hint">Newest first. The permanent record of competitor moves.</p>`;
  if (evs.length) {
    let curDate = null, html = "";
    for (const e of evs.slice(0, 80)) {
      if (e.date !== curDate) { curDate = e.date; html += `<p class="hint" style="margin:10px 0 2px"><b>${esc(e.date)}</b></p>`; }
      const self = state.byBrand[e.slug] && state.byBrand[e.slug].is_self;
      html += `<div class="row"><span class="tag">${esc(EVENT_LABEL[e.type] || e.type)}</span>
        <span style="margin-left:6px${self ? ";font-weight:600" : ""}">${esc(e.text)}</span></div>`;
    }
    tc.append(el("div", "", html));
  } else {
    tc.append(el("p", "muted", "No changes recorded yet — the timeline builds as history accumulates."));
  }
  wrap.append(tc);
  return wrap;
}

// ---------- Ask Me: deterministic Q&A over the captured record ----------
// The engine (docs/ask.js, window.AskEngine) is pure and offline — it quotes
// recorded fields with dated-screenshot evidence rather than narrating. It
// also surfaces the weekly AI-visibility share-of-voice data when present,
// replacing the old AI Visibility placeholder tab.
let askState = { q: "", result: null };

const ASK_EXAMPLES = [
  "Who has the deepest discount?",
  "Was Mint Velvet on sale at the end of June?",
  "When did Katie Loxton's sale start?",
  "Who's on sale today?",
  "What are Strathberry's prices?",
  "When did Sezane last change their hero?",
];

function runAsk(q) {
  askState.q = q;
  askState.result = (typeof AskEngine !== "undefined")
    ? AskEngine.ask(q, { captures: state.captures, aio: state.aio })
    : { ok: false, text: "Ask engine failed to load — refresh the page.", evidence: [], note: null };
  render();
}

function viewAsk() {
  const wrap = el("div");

  const intro = el("div", "card");
  intro.innerHTML = `<h3>Ask Me</h3>
    <p class="hint">Ask a buyer-intent question about the tracked brands. Answers quote the recorded captures —
    no AI narration — and every answer cites the capture date and links the dated screenshot.</p>
    <form class="askform" id="askForm">
      <label class="sr-only" for="askInput">Your question</label>
      <input id="askInput" type="text" autocomplete="off" placeholder="e.g. was Mint Velvet on sale at the end of June?"
        value="${esc(askState.q)}">
      <button class="btn" type="submit">Ask</button>
    </form>`;
  const chips = el("div", "brandpick");
  chips.setAttribute("aria-label", "Example questions");
  for (const ex of ASK_EXAMPLES) {
    const b = el("button", "", esc(ex));
    b.type = "button";
    b.onclick = () => runAsk(ex);
    chips.append(b);
  }
  intro.append(el("p", "hint", "Try one of these:"), chips);
  wrap.append(intro);

  if (askState.result) {
    const res = askState.result;
    const card = el("div", "card");
    card.innerHTML = `<h3>${res.ok ? "Answer" : "No answer"}</h3>
      <p class="hint">“${esc(askState.q)}”</p>
      <p class="asktext">${esc(res.text)}</p>
      ${res.note ? `<p class="hint">${esc(res.note)}</p>` : ""}`;
    if (res.evidence && res.evidence.length) {
      const evWrap = el("div");
      evWrap.innerHTML = `<p class="hint" style="margin-top:10px">Evidence — recorded fields, one click from the screenshot:</p>`;
      for (const e of res.evidence) {
        const row = el("div", "row");
        const open = e.screenshot
          ? `<button class="btn askev" data-slug="${esc(e.slug)}" data-date="${esc(e.date)}">View screenshot ↗</button>`
          : '<span class="muted">no screenshot</span>';
        row.innerHTML = `<span class="name"><b>${esc(e.brand)}</b></span>
          <span class="tag">${esc(e.date)}</span>
          <span class="tag">${esc(e.field)}: <b>${esc(String(e.value))}</b></span>
          ${open}`;
        evWrap.append(row);
      }
      card.append(evWrap);
    }
    wrap.append(card);
  }

  setTimeout(() => {
    const form = document.getElementById("askForm");
    if (form) form.onsubmit = e => { e.preventDefault(); runAsk(document.getElementById("askInput").value); };
    for (const b of document.querySelectorAll(".askev")) {
      b.onclick = () => {
        shotState = { slug: b.dataset.slug, device: "desktop", bucket: "all",
                      lightbox: null, focusDate: b.dataset.date };
        selectTab("screens");
      };
    }
  }, 0);
  return wrap;
}

const VIEWS = { overview: viewOverview, opportunities: viewOpportunities, periods: viewPeriods, competitors: viewCompetitors, offers: viewOffers, market: viewMarketMap, trading: viewTrading, reputation: viewReputation, assortment: viewAssortment, pricing: viewPricing, colours: viewColours, keywords: viewKeywords, seo: viewSeo, ask: viewAsk, a11y: viewA11y, screens: viewScreens };

// ---------- shell ----------
function render() {
  const view = document.getElementById("view");
  view.innerHTML = "";
  // Tie the panel to its tab so assistive tech announces the section name.
  view.setAttribute("aria-labelledby", "tab-" + state.active);
  view.append((VIEWS[state.active] || viewOverview)());

  const allSample = state.captures.length && state.captures.every(r => r.sample);
  document.getElementById("sampleBanner").classList.toggle("hidden", !allSample);

  const succ = state.captures.filter(r => r.status === "success").length;
  document.getElementById("freshness").innerHTML =
    `Latest: <b>${latestDate()}</b><br>${succ} captures on file`;
  document.getElementById("footStatus").textContent =
    `${Object.keys(state.byBrand).length} brands · ${state.dates.length} days of history`;
}

// Build the grouped side nav: collapsible sections, each holding a vertical
// WAI-ARIA tablist entry (role=tab, roving tabindex, Up/Down/Home/End keys).
function buildNav() {
  const nav = document.getElementById("sidenav");
  nav.innerHTML = "";
  nav.setAttribute("role", "tablist");
  nav.setAttribute("aria-orientation", "vertical");
  let flat = 0;
  for (const [group, items] of NAV_GROUPS) {
    const sec = el("div", "navgroup");
    const head = el("button", "navhead", `<span>${esc(group)}</span><span class="chev" aria-hidden="true">▾</span>`);
    head.setAttribute("aria-expanded", "true");
    head.onclick = () => {
      const open = head.getAttribute("aria-expanded") === "true";
      head.setAttribute("aria-expanded", open ? "false" : "true");
      sec.classList.toggle("collapsed", open);
    };
    sec.append(head);
    const list = el("div", "navitems");
    for (const [id, label] of items) {
      const i = flat++;
      const b = el("button", "navitem" + (id === state.active ? " active" : ""), label);
      b.id = "tab-" + id;
      b.dataset.tab = id;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-controls", "view");
      b.setAttribute("aria-selected", id === state.active ? "true" : "false");
      b.tabIndex = id === state.active ? 0 : -1;   // roving tabindex
      b.onclick = () => selectTab(id);
      b.onkeydown = e => onTabKey(e, i);
      list.append(b);
    }
    sec.append(list);
    nav.append(sec);
  }
}

// Switch tab, keeping ARIA state and roving tabindex in sync; on mobile the
// off-canvas drawer closes so the chosen view is immediately visible.
function selectTab(id, focusTab) {
  state.active = id;
  for (const b of document.querySelectorAll("#sidenav [role=tab]")) {
    const on = b.dataset.tab === id;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1;
    if (on && focusTab) b.focus();
  }
  closeNav();
  render();
}

// Up/Down (vertical list) + Home/End keyboard navigation (WAI-ARIA pattern).
function onTabKey(e, i) {
  const dir = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
  const n = TABS.length;
  let j = null;
  if (e.key in dir) j = (i + dir[e.key] + n) % n;
  else if (e.key === "Home") j = 0;
  else if (e.key === "End") j = n - 1;
  if (j === null) return;
  e.preventDefault();
  selectTab(TABS[j][0], true);
}

// ---------- mobile off-canvas drawer ----------
const isDrawerMode = () => window.matchMedia("(max-width: 900px)").matches;

function openNav() {
  document.body.classList.add("nav-open");
  document.getElementById("backdrop").hidden = false;
  document.getElementById("navToggle").setAttribute("aria-expanded", "true");
  const active = document.querySelector("#sidenav [role=tab][tabindex='0']");
  if (active) active.focus();
}

function closeNav() {
  if (!document.body.classList.contains("nav-open")) return;
  document.body.classList.remove("nav-open");
  document.getElementById("backdrop").hidden = true;
  const toggle = document.getElementById("navToggle");
  toggle.setAttribute("aria-expanded", "false");
  if (isDrawerMode()) toggle.focus();
}

// Keep keyboard focus inside the open drawer (focus trap), Escape to close.
function navKeydown(e) {
  if (!document.body.classList.contains("nav-open") || !isDrawerMode()) return;
  if (e.key === "Escape") { e.preventDefault(); closeNav(); return; }
  if (e.key !== "Tab") return;
  const focusables = [document.getElementById("navToggle"),
    ...document.querySelectorAll("#sidenav button")].filter(b => b.offsetParent !== null || b.id === "navToggle");
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

function wireDrawer() {
  const toggle = document.getElementById("navToggle");
  toggle.onclick = () => document.body.classList.contains("nav-open") ? closeNav() : openNav();
  document.getElementById("backdrop").onclick = closeNav;
  document.addEventListener("keydown", navKeydown);
  window.matchMedia("(max-width: 900px)").addEventListener("change", m => { if (!m.matches) closeNav(); });
}

// The side nav sticks directly under the header; the header height isn't fixed
// (it wraps on small screens), so measure it into a CSS variable.
function syncStickyOffsets() {
  const topbar = document.querySelector(".topbar");
  if (topbar) document.documentElement.style.setProperty("--topbar-h", topbar.offsetHeight + "px");
}

async function boot() {
  buildNav();
  wireDrawer();
  syncStickyOffsets();
  window.addEventListener("resize", syncStickyOffsets);
  try { await loadData(); }
  catch (e) {
    document.getElementById("view").innerHTML =
      `<div class="card"><h3>No data yet</h3><p class="muted">Couldn't load <code>data/captures.json</code> (${esc(e.message)}). Run the capture or seed step first.</p></div>`;
    return;
  }
  render();
  // Header height can change once data lands (banner, wrapped meta); re-measure.
  syncStickyOffsets();
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
boot();
