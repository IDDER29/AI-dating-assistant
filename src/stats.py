"""
Minimal event-based stats recorder.
Appends events to data/stats.json, capped at 2000 entries.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

STATS_PATH = Path(__file__).resolve().parent.parent / "data" / "stats.json"
MAX_STATS_ENTRIES = 2000


def record_event(event_type: str, metadata: dict = None):
    """
    Append a timestamped event to stats.json.
    Non-blocking — failures are logged but do not affect the caller.
    """
    entry = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(metadata or {}),
    }
    try:
        STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if STATS_PATH.exists() and STATS_PATH.stat().st_size > 0:
            with STATS_PATH.open("r", encoding="utf-8") as f:
                existing = json.load(f)

        existing.append(entry)
        if len(existing) > MAX_STATS_ENTRIES:
            existing = existing[-MAX_STATS_ENTRIES:]

        tmp = STATS_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        tmp.replace(STATS_PATH)

    except Exception as e:
        logging.error(f"[STATS] Failed to record event '{event_type}': {e}")


def get_api_stats_summary(hours: int = 6) -> dict:
    """
    Summarise API usage from the last N hours.
    Returns: {"calls": int, "total_tokens": int, "failures": int}
    Safe to call at any time — returns zeroed dict on any error.
    """
    summary = {"calls": 0, "total_tokens": 0, "failures": 0}
    try:
        if not STATS_PATH.exists():
            return summary
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with STATS_PATH.open("r", encoding="utf-8") as f:
            events = json.load(f)
        for event in events:
            if event.get("event") != "api_call":
                continue
            ts = event.get("timestamp", "")
            try:
                event_time = datetime.fromisoformat(ts)
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
                if event_time < cutoff:
                    continue
            except ValueError:
                continue
            summary["calls"] += 1
            if event.get("status") == "failed":
                summary["failures"] += 1
            summary["total_tokens"] += event.get("total_tokens", 0)
    except Exception as e:
        logging.error(f"[STATS] Failed to compute API summary: {e}")
    return summary
