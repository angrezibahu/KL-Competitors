"""Append-only storage. We NEVER overwrite history -- that was the whole point."""

import json
import os
from datetime import datetime, timezone

# Everything the PWA reads lives under docs/ so GitHub Pages can serve it.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DATA_DIR = os.path.join(DOCS, "data")
CAPTURES_PATH = os.path.join(DATA_DIR, "captures.json")
RUNLOG_PATH = os.path.join(DATA_DIR, "run_log.json")
SHOTS_DIR = os.path.join(DOCS, "screenshots")


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(SHOTS_DIR, exist_ok=True)


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)


def load_captures():
    return _load_json(CAPTURES_PATH, [])


def append_captures(new_records):
    """Append today's records. If a record for the same brand+date already
    exists (e.g. a manual re-run), replace it rather than duplicate."""
    records = load_captures()
    index = {(r.get("slug"), r.get("date")): i for i, r in enumerate(records)}
    for rec in new_records:
        key = (rec.get("slug"), rec.get("date"))
        if key in index:
            records[index[key]] = rec
        else:
            records.append(rec)
    with open(CAPTURES_PATH, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=1, ensure_ascii=False)
    return len(records)


def write_run_log(run_summary):
    """Keep a rolling log of runs so gaps/failures are VISIBLE, never hidden."""
    log = _load_json(RUNLOG_PATH, [])
    log.append(run_summary)
    log = log[-120:]  # keep last ~4 months of runs
    with open(RUNLOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=1, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
