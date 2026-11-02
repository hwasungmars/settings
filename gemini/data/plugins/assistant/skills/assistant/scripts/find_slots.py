#!/usr/bin/env python3
"""
find_slots.py - Deterministic availability and candidate slot finder for Antigravity.

Combines `gcalendar readonly freebusy` and `gcalendar readonly events` to calculate
exact open meeting slots respecting working hours, travel buffers, all-day blockers,
and multi-timezone displays (Pacific & UK London).
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo
from typing import Any


def run_gcalendar(*args: str) -> dict[str, Any] | list[Any]:
    cmd = ["gcalendar", *args]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gcalendar command failed ({' '.join(cmd)}): {res.stderr.strip()}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as err:
        raise ValueError(f"Failed to parse gcalendar JSON output: {err}\nOutput: {res.stdout}")


def parse_rfc3339(ts: str) -> datetime.datetime:
    # Python 3.11+ fromisoformat handles standard RFC3339 including 'Z'
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def calculate_slots_from_busy(
    busy_data: dict[str, Any],
    date_str: str,
    tz_name: str = "America/Los_Angeles",
    duration_min: int = 30,
    buffer_min: int = 15,
    start_hour_str: str = "09:00",
    end_hour_str: str = "17:30",
) -> list[dict[str, Any]]:
    tz = ZoneInfo(tz_name)
    uk_tz = ZoneInfo("Europe/London")
    target_date = datetime.date.fromisoformat(date_str)

    calendars = busy_data.get("calendars", {})
    busy_intervals: list[tuple[datetime.datetime, datetime.datetime]] = []
    for cal_id, cal_info in calendars.items():
        for b in cal_info.get("busy", []):
            b_start = parse_rfc3339(b["start"]).astimezone(tz)
            b_end = parse_rfc3339(b["end"]).astimezone(tz)
            # Add buffers around existing meetings
            adj_start = b_start - datetime.timedelta(minutes=buffer_min)
            adj_end = b_end + datetime.timedelta(minutes=buffer_min)
            busy_intervals.append((adj_start, adj_end))

    # Sort and merge overlapping busy intervals
    busy_intervals.sort(key=lambda x: x[0])
    merged_busy: list[tuple[datetime.datetime, datetime.datetime]] = []
    for start, end in busy_intervals:
        if not merged_busy:
            merged_busy.append((start, end))
        else:
            prev_start, prev_end = merged_busy[-1]
            if start <= prev_end:
                merged_busy[-1] = (prev_start, max(prev_end, end))
            else:
                merged_busy.append((start, end))

    # Working hours window
    sh_h, sh_m = map(int, start_hour_str.split(":"))
    eh_h, eh_m = map(int, end_hour_str.split(":"))
    work_start = datetime.datetime.combine(target_date, datetime.time(sh_h, sh_m), tzinfo=tz)
    work_end = datetime.datetime.combine(target_date, datetime.time(eh_h, eh_m), tzinfo=tz)

    # Calculate free windows by subtracting merged_busy from [work_start, work_end]
    free_windows: list[tuple[datetime.datetime, datetime.datetime]] = []
    curr = work_start

    for b_start, b_end in merged_busy:
        if b_end <= curr:
            continue
        if b_start >= work_end:
            break
        if b_start > curr:
            window_end = min(b_start, work_end)
            if window_end - curr >= datetime.timedelta(minutes=duration_min):
                free_windows.append((curr, window_end))
        curr = max(curr, b_end)

    if curr < work_end:
        if work_end - curr >= datetime.timedelta(minutes=duration_min):
            free_windows.append((curr, work_end))

    # Extract discrete slots (stepping by 30 min intervals)
    slots = []
    for w_start, w_end in free_windows:
        slot_start = w_start
        while slot_start + datetime.timedelta(minutes=duration_min) <= w_end:
            slot_end = slot_start + datetime.timedelta(minutes=duration_min)
            uk_start = slot_start.astimezone(uk_tz)
            uk_end = slot_end.astimezone(uk_tz)

            disp_us = f"{slot_start.strftime('%a, %d %b')}: {slot_start.strftime('%H:%M')}–{slot_end.strftime('%H:%M')} PT"
            disp_uk = f"{uk_start.strftime('%H:%M')}–{uk_end.strftime('%H:%M')} UK"

            slots.append({
                "date": date_str,
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "display_pt": disp_us,
                "display_uk": disp_uk,
                "display_combined": f"{disp_us} ({disp_uk})",
            })
            slot_start += datetime.timedelta(minutes=30)

    return slots


def main() -> None:
    parser = argparse.ArgumentParser(description="Find open calendar slots deterministically from freebusy data.")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--duration", type=int, default=30, help="Meeting duration in minutes (default: 30)")
    parser.add_argument("--buffer", type=int, default=15, help="Buffer around existing meetings in minutes (default: 15)")
    parser.add_argument("--start-hour", default="09:00", help="Working hours start (default: 09:00)")
    parser.add_argument("--end-hour", default="17:30", help="Working hours end (default: 17:30)")
    parser.add_argument("--tz", default="America/Los_Angeles", help="Timezone (default: America/Los_Angeles)")
    parser.add_argument("--quote-uk", action="store_true", help="Always include UK time in output")
    parser.add_argument("--file", help="Path to freebusy JSON file (defaults to stdin)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of formatted text")

    args = parser.parse_args()

    raw_input = ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw_input = f.read()
    elif not sys.stdin.isatty():
        raw_input = sys.stdin.read()

    if not raw_input.strip():
        sys.stderr.write("error: please provide freebusy JSON via stdin or --file.\n")
        sys.exit(1)

    try:
        busy_data = json.loads(raw_input)
    except json.JSONDecodeError as err:
        sys.stderr.write(f"error: failed to parse input JSON: {err}\n")
        sys.exit(1)

    all_slots = calculate_slots_from_busy(
        busy_data=busy_data,
        date_str=args.date,
        tz_name=args.tz,
        duration_min=args.duration,
        buffer_min=args.buffer,
        start_hour_str=args.start_hour,
        end_hour_str=args.end_hour,
    )

    if args.json:
        print(json.dumps(all_slots, indent=2))
        return

    if not all_slots:
        print(f"No open {args.duration}-min slots found on {args.date} within working hours.")
        return

    print(f"Open {args.duration}-min slots on {args.date} (buffer: {args.buffer} min):")
    for s in all_slots:
        if args.quote_uk:
            print(f"  • {s['display_combined']}")
        else:
            print(f"  • {s['display_pt']}")


if __name__ == "__main__":
    main()
