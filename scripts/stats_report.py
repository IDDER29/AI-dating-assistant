#!/usr/bin/env python3
"""
Stats report for the AI Dating Assistant.

Usage:
    python scripts/stats_report.py              # last 24 hours
    python scripts/stats_report.py --days 7     # last 7 days
    python scripts/stats_report.py --all        # all time
    python scripts/stats_report.py --event meeting_signal

Reads data/stats.json. No dependencies beyond the standard library.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

STATS_PATH = Path(__file__).parent.parent / "data" / "stats.json"
SEP = "=" * 52


def load_events(since: datetime | None = None) -> list:
    if not STATS_PATH.exists():
        print(f"No stats file found at {STATS_PATH}", file=sys.stderr)
        return []
    try:
        with STATS_PATH.open("r", encoding="utf-8") as f:
            events = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error reading stats file: {e}", file=sys.stderr)
        return []

    if since is None:
        return events

    filtered = []
    for e in events:
        ts = e.get("timestamp", "")
        try:
            t = datetime.fromisoformat(ts)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t >= since:
                filtered.append(e)
        except ValueError:
            pass
    return filtered


def _pct(a: int, b: int) -> str:
    return f"{a / b * 100:.0f}%" if b else "—"


def print_summary(events: list, label: str):
    total = len(events)
    print(f"\n{SEP}")
    print(f"  Stats Report — {label}")
    print(SEP)
    print(f"  Total events: {total}")

    if total == 0:
        print("  No events in this period.\n")
        return

    counts = Counter(e.get("event") for e in events)
    print()

    # ── Profile decisions ────────────────────────────────────────────────────
    liked    = counts.get("profile_liked", 0)
    disliked = counts.get("profile_disliked", 0)
    total_profiles = liked + disliked
    print(f"  Profiles seen:       {total_profiles}")
    if total_profiles:
        print(f"    Liked:             {liked} ({_pct(liked, total_profiles)})")
        print(f"    Disliked:          {disliked} ({_pct(disliked, total_profiles)})")

    # ── Funnel ───────────────────────────────────────────────────────────────
    openers   = counts.get("opener_sent", 0)
    convos    = counts.get("conversation_started", 0)
    replies   = counts.get("reply_sent", 0)
    meetings  = counts.get("meeting_signal", 0)
    print()
    print(f"  Openers sent:        {openers}")
    print(f"  Conversations:       {convos}")
    print(f"  Replies sent:        {replies}")
    print(f"  Meeting signals:     {meetings}")

    if total_profiles or openers or convos or meetings:
        print()
        print("  Conversion funnel:")
        if total_profiles:
            print(f"    Profiles → liked:   {_pct(liked, total_profiles)}")
        if liked:
            print(f"    Liked → opener:     {_pct(openers, liked)}")
        if openers:
            print(f"    Opener → convo:     {_pct(convos, openers)}")
        if convos:
            print(f"    Convo → meeting:    {_pct(meetings, convos)}")

    # ── API calls ────────────────────────────────────────────────────────────
    api_calls = [e for e in events if e.get("event") == "api_call"]
    if api_calls:
        print()
        failed       = sum(1 for e in api_calls if e.get("status") == "failed")
        total_tokens = sum(e.get("total_tokens", 0) for e in api_calls)
        by_type      = Counter(e.get("type") for e in api_calls)
        print(f"  API calls:           {len(api_calls)}")
        if failed:
            print(f"    Failed:            {failed} ({_pct(failed, len(api_calls))})")
        print(f"    Total tokens:      ~{total_tokens:,}")
        for call_type, n in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"    {call_type:<22} {n}")

    # ── API errors ───────────────────────────────────────────────────────────
    api_errors = [e for e in events if e.get("event") == "api_error"]
    if api_errors:
        print()
        print(f"  API errors:          {len(api_errors)}")
        for e in api_errors[-5:]:
            ts  = e.get("timestamp", "")[:19]
            why = e.get("reason", "unknown")
            print(f"    {ts}  {why}")

    # ── Meeting signals detail ───────────────────────────────────────────────
    meeting_events = [e for e in events if e.get("event") == "meeting_signal"]
    if meeting_events:
        print()
        print(f"  Meeting signals ({len(meeting_events)}):")
        for e in meeting_events:
            ts   = e.get("timestamp", "")[:19]
            name = e.get("user_name", "unknown")
            uid  = e.get("chat_id", "?")
            print(f"    {ts}  {name} (ID: {uid})")

    print(f"\n{SEP}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Stats report for the AI Dating Assistant."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--days", type=int, default=1,
        help="Summarise the last N days (default: 1)",
    )
    group.add_argument(
        "--all", action="store_true",
        help="Summarise all recorded events",
    )
    parser.add_argument(
        "--event", metavar="TYPE",
        help="Filter to a specific event type (e.g. meeting_signal, api_call)",
    )
    args = parser.parse_args()

    if args.all:
        events = load_events(since=None)
        label  = "All time"
    else:
        since  = datetime.now(timezone.utc) - timedelta(days=args.days)
        events = load_events(since=since)
        label  = f"Last {args.days} day(s)"

    if args.event:
        events = [e for e in events if e.get("event") == args.event]
        label += f" — event: {args.event}"

    print_summary(events, label)


if __name__ == "__main__":
    main()
