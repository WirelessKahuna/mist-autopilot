#!/usr/bin/env python3
"""
track_time.py — Mist Autopilot Project Time Tracker
====================================================
Parses one or more conversation transcript files, extracts message timestamps,
filters out idle gaps longer than MAX_GAP_MINUTES, and reports total working time.

Usage:
    python3 track_time.py <transcript_file> [transcript_file2 ...]

Example:
    python3 track_time.py transcripts/2026-03-21-*.txt

The script reads transcript files in the format produced by Claude.ai, where
each message block contains start_timestamp and stop_timestamp fields in ISO
format. It considers the human's message start as the "clock in" point and
filters any gap between messages that exceeds MAX_GAP_MINUTES (default 20).
"""

import sys
import re
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
MAX_GAP_MINUTES = 20   # gaps longer than this are considered idle / not working


def parse_timestamps(filepath: str) -> list[datetime]:
    """
    Extract all start_timestamps from a transcript file.
    Returns sorted list of aware datetime objects (UTC).
    """
    text = Path(filepath).read_text(encoding="utf-8")

    # Match all start_timestamp values in the file
    pattern = r'"start_timestamp"\s*:\s*"([^"]+)"'
    matches = re.findall(pattern, text)

    timestamps = []
    for ts_str in matches:
        try:
            # Handle both Z suffix and +00:00 offset
            ts_str = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamps.append(dt)
        except ValueError:
            continue

    return sorted(set(timestamps))


def calculate_working_time(
    timestamps: list[datetime],
    max_gap: timedelta,
) -> tuple[timedelta, list[tuple[datetime, datetime, timedelta]]]:
    """
    Calculate total working time by summing gaps between consecutive timestamps,
    excluding any gap longer than max_gap.

    Returns:
        (total_time, gaps_list)
        gaps_list: list of (start, end, duration) for each counted interval
    """
    if len(timestamps) < 2:
        return timedelta(0), []

    total = timedelta(0)
    counted_gaps = []
    skipped_gaps = []

    for i in range(len(timestamps) - 1):
        gap = timestamps[i + 1] - timestamps[i]
        if gap <= max_gap:
            total += gap
            counted_gaps.append((timestamps[i], timestamps[i + 1], gap))
        else:
            skipped_gaps.append((timestamps[i], timestamps[i + 1], gap))

    return total, counted_gaps, skipped_gaps


def fmt_duration(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours   = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


def fmt_ts(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage: python3 track_time.py <transcript_file> [...]")
        sys.exit(1)

    files = sys.argv[1:]
    max_gap = timedelta(minutes=MAX_GAP_MINUTES)

    all_timestamps: list[datetime] = []
    file_stats: list[dict] = []

    for filepath in files:
        path = Path(filepath)
        if not path.exists():
            print(f"⚠️  File not found: {filepath}")
            continue

        timestamps = parse_timestamps(filepath)
        if not timestamps:
            print(f"⚠️  No timestamps found in: {filepath}")
            continue

        total, counted, skipped = calculate_working_time(timestamps, max_gap)
        all_timestamps.extend(timestamps)

        file_stats.append({
            "file":      path.name,
            "first":     timestamps[0],
            "last":      timestamps[-1],
            "messages":  len(timestamps),
            "total":     total,
            "counted":   counted,
            "skipped":   skipped,
        })

    if not file_stats:
        print("No valid transcripts found.")
        sys.exit(1)

    # ── Per-file report ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  MIST AUTOPILOT — PROJECT TIME TRACKER")
    print("=" * 70)

    for stat in file_stats:
        print(f"\n📄 {stat['file']}")
        print(f"   Session start : {fmt_ts(stat['first'])}")
        print(f"   Session end   : {fmt_ts(stat['last'])}")
        print(f"   Messages      : {stat['messages']}")
        print(f"   Working time  : {fmt_duration(stat['total'])}")
        if stat['skipped']:
            print(f"   Idle gaps     : {len(stat['skipped'])} gap(s) > {MAX_GAP_MINUTES}min skipped")
            for s, e, d in stat['skipped'][:5]:
                print(f"     • {fmt_ts(s)} → {fmt_ts(e)}  ({fmt_duration(d)} idle)")
            if len(stat['skipped']) > 5:
                print(f"     • ... and {len(stat['skipped']) - 5} more")

    # ── Grand total ────────────────────────────────────────────────────────
    if len(file_stats) > 1:
        all_timestamps_sorted = sorted(set(all_timestamps))
        grand_total, _, _ = calculate_working_time(all_timestamps_sorted, max_gap)
        print("\n" + "-" * 70)
        print(f"  TOTAL WORKING TIME (all sessions): {fmt_duration(grand_total)}")
        print("-" * 70)
    else:
        print("\n" + "-" * 70)
        print(f"  TOTAL WORKING TIME: {fmt_duration(file_stats[0]['total'])}")
        print("-" * 70)

    print(f"\n  (Gaps > {MAX_GAP_MINUTES} minutes treated as idle and excluded)\n")


if __name__ == "__main__":
    main()
