"""
AI-Overview / answer-engine visibility ("AIO").

The classic radar measures what competitors put on their *own* pages. This
measures something different and increasingly decisive: when a real shopper asks
an AI assistant a buyer-intent question ("best personalised birthday jewellery
UK"), *which* brands does the AI name, and in what order? That is share-of-voice
in AI answers -- the 2026 equivalent of a search ranking, and a direct source of
"who should we be, and aren't" opportunities.

Design mirrors the rest of the project:
  * The PARSING + SCORING is pure (string in, data out) and unit-tested offline
    -- no network, no key. That is the part that can silently rot, so it is the
    part we test.
  * The LIVE query is best-effort and gated on ANTHROPIC_API_KEY, exactly like
    the weekly digest email is gated on SMTP secrets. No key -> it prints a clear
    message and exits 0 without writing a run. Never fatal.
  * Output is append-only history in docs/data/aio.json, one record per weekly
    run, so the dashboard can show both the latest leaderboard and the trend.

Run:  python -m scraper.aio        (needs ANTHROPIC_API_KEY + internet)
"""

import json
import os
import re
import sys

from . import storage

CONFIG_PATH = os.path.join(storage.ROOT, "config", "competitors.json")
QUERIES_PATH = os.path.join(storage.ROOT, "config", "aio_queries.json")
AIO_PATH = os.path.join(storage.DATA_DIR, "aio.json")

MODEL = "claude-opus-4-8"
# Web search tool version with dynamic filtering (Opus 4.6+/Sonnet 4.6).
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


# ---------------------------------------------------------------------------
# Brand matching (pure)
# ---------------------------------------------------------------------------

def brand_matchers(brands):
    """Build per-brand regex matchers from name (+ a couple of safe variants).

    Returns a list of {slug, name, patterns:[compiled regex]}. We normalise
    '&' <-> 'and' so 'Astrid & Miyu' matches 'Astrid and Miyu', and match on
    word boundaries so a brand name inside a longer word doesn't false-positive.
    Aliases can be supplied per brand in config via an optional "aliases" list.
    """
    matchers = []
    for b in brands:
        names = {b["name"]}
        if "&" in b["name"]:
            names.add(b["name"].replace("&", "and"))
            names.add(b["name"].replace("&", "+"))
        for alias in b.get("aliases", []) or []:
            names.add(alias)
        patterns = []
        for nm in names:
            esc = re.escape(nm.strip())
            # Allow flexible whitespace and an optional 'and'/'&' interchange.
            esc = esc.replace(r"\ ", r"\s+")
            patterns.append(re.compile(r"(?<![\w])" + esc + r"(?![\w])", re.I))
        matchers.append({"slug": b["slug"], "name": b["name"], "patterns": patterns})
    return matchers


def extract_brand_mentions(answer_text, brands):
    """Which tracked brands appear in an AI answer, and in what order.

    Returns a list of {slug, brand, position, rank} sorted by first appearance,
    with rank assigned 1..N by that order (rank 1 = named first = most prominent).
    Pure: (answer string, brand list) -> list. Each brand counted once."""
    text = answer_text or ""
    hits = []
    for m in brand_matchers(brands):
        pos = None
        for pat in m["patterns"]:
            found = pat.search(text)
            if found and (pos is None or found.start() < pos):
                pos = found.start()
        if pos is not None:
            hits.append({"slug": m["slug"], "brand": m["name"], "position": pos})
    hits.sort(key=lambda h: h["position"])
    for rank, h in enumerate(hits, 1):
        h["rank"] = rank
    return hits


def score_share_of_voice(query_results, brands):
    """Aggregate per-query mentions into a per-brand share-of-voice table.

    For each brand:
      mentions   -- number of queries it appeared in
      queries    -- total queries scored
      visibility -- mentions / queries (0..1): how often it shows up at all
      avg_rank   -- mean position when mentioned (1 = always named first)
      points     -- sum of 1/rank across appearances (rewards being named first)
      sov        -- points / total points across all brands (shares ~sum to 1)

    Pure. `query_results` is a list of {mentions:[{slug,rank}, ...]}.
    """
    total_q = len(query_results)
    agg = {b["slug"]: {"brand": b["name"], "mentions": 0, "ranks": [], "points": 0.0}
           for b in brands}
    for qr in query_results:
        for men in qr.get("mentions", []):
            slug = men["slug"]
            if slug not in agg:
                continue
            agg[slug]["mentions"] += 1
            agg[slug]["ranks"].append(men["rank"])
            agg[slug]["points"] += 1.0 / men["rank"]

    total_points = sum(a["points"] for a in agg.values()) or 1.0
    out = {}
    for slug, a in agg.items():
        ranks = a["ranks"]
        out[slug] = {
            "brand": a["brand"],
            "mentions": a["mentions"],
            "queries": total_q,
            "visibility": round(a["mentions"] / total_q, 3) if total_q else 0.0,
            "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
            "sov": round(a["points"] / total_points, 3),
        }
    return out


# ---------------------------------------------------------------------------
# Live query (best-effort; needs ANTHROPIC_API_KEY + internet)
# ---------------------------------------------------------------------------

def _answer_prompt(query, market):
    return (
        f"A shopper asks: \"{query}\". Market: {market}. "
        "Search the web and answer as a helpful shopping assistant would, naming the "
        "specific brands you'd actually recommend (use each brand's real name). "
        "Keep it to a short, natural recommendation — no preamble."
    )


def query_answer_engine(client, query, market, max_continuations=4):
    """Ask Claude (with live web search) the buyer-intent question and return
    {answer_text, sources}. Best-effort: any failure returns ('', []).

    Handles the server-tool `pause_turn` loop (web search runs server-side and
    can pause when it hits its iteration cap; we resend to resume)."""
    prompt = _answer_prompt(query, market)
    messages = [{"role": "user", "content": prompt}]
    sources, text_parts = [], []
    try:
        for _ in range(max_continuations + 1):
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                tools=[WEB_SEARCH_TOOL],
                messages=messages,
            )
            for block in resp.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "web_search_tool_result":
                    content = getattr(block, "content", None)
                    # Success content is a list of results; an error is a single object.
                    if isinstance(content, list):
                        for r in content:
                            url = getattr(r, "url", None)
                            if url and url not in sources:
                                sources.append(url)
            if resp.stop_reason == "pause_turn":
                messages = [{"role": "user", "content": prompt},
                            {"role": "assistant", "content": resp.content}]
                continue
            break
    except Exception as exc:
        print(f"    [aio query failed] {query!r}: {type(exc).__name__}: {exc}")
        return "", []
    return " ".join(t for t in text_parts if t).strip(), sources[:8]


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_queries():
    with open(QUERIES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def append_run(run):
    """Append one weekly AIO run to the append-only history file."""
    existing = storage._load_json(AIO_PATH, {"runs": []})
    if not isinstance(existing, dict) or "runs" not in existing:
        existing = {"runs": []}
    existing["runs"].append(run)
    existing["runs"] = existing["runs"][-104:]  # keep ~2 years of weekly runs
    os.makedirs(os.path.dirname(AIO_PATH), exist_ok=True)
    with open(AIO_PATH, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=1, ensure_ascii=False)
    return len(existing["runs"])


def run():
    storage.ensure_dirs()
    brands = load_config()["brands"]
    qcfg = load_queries()
    queries = qcfg["queries"]
    market = qcfg.get("market", "UK jewellery")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("AIO: ANTHROPIC_API_KEY not set — skipping live run (nothing written). "
              "Set the secret to start tracking AI-answer visibility.")
        return 0

    import anthropic
    client = anthropic.Anthropic()

    print(f"== AIO visibility: {len(queries)} queries, {len(brands)} brands ==")
    query_results = []
    for item in queries:
        q = item["q"]
        answer, sources = query_answer_engine(client, q, market)
        mentions = extract_brand_mentions(answer, brands)
        query_results.append({
            "query": q,
            "category": item.get("category"),
            "answer_excerpt": (answer or "")[:600],
            "sources": sources,
            "mentions": mentions,
        })
        named = ", ".join(m["brand"] for m in mentions) or "(none of our brands)"
        print(f"  [{'OK' if answer else '--'}] {q[:48]!r}: {named}")

    sov = score_share_of_voice(query_results, brands)
    run_record = {
        "date": storage.today(),
        "ran_at": storage.now_iso(),
        "provider": f"anthropic:{MODEL}+web_search",
        "ok": any(qr["mentions"] for qr in query_results),
        "queries_total": len(queries),
        "market": market,
        "queries": query_results,
        "share_of_voice": sov,
    }
    total = append_run(run_record)

    leaders = sorted(sov.items(), key=lambda kv: -kv[1]["sov"])[:5]
    print("== Share of voice (top): " +
          ", ".join(f"{v['brand']} {round(v['sov'] * 100)}%" for _, v in leaders))
    print(f"== Done. {total} weekly AIO runs on file. ==")
    return 0


if __name__ == "__main__":
    sys.exit(run())
