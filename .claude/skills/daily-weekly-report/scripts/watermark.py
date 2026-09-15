#!/usr/bin/env python3
"""Track how far each source has been mined.

A daily run windowed on "today" loses two things silently:

  - a day nobody ran it (the transcripts expire ~30 days later, and nothing
    says they were never read)
  - the earlier turns of a session that spans days — a session started on the
    3rd and continued on the 15th has its opening turns, and any
    AskUserQuestion tradeoffs recorded there, outside every "today" window
    from the 4th onward

A watermark fixes both with one mechanism: mine everything since the last
successful run, not everything since midnight.

**The collectors never advance the watermark.** Mining is only successful once
the journal has been written, and only the caller knows whether that happened.
A collector that advanced it would mark unmined material as mined the moment a
run failed halfway. So the sequence is: collect → mine → write journal →
`watermark.py set`.

Usage:
    watermark.py show
    watermark.py set --source conversations --through 2026-09-15T01:27:10+00:00
    watermark.py reset --source git
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SOURCES = ("conversations", "git")
DEFAULT_PATH = Path("state/watermark.json")
# A gap wider than this is worth saying out loud: a working day was probably
# missed, and its transcripts are on a ~30-day clock.
GAP_ALERT_DAYS = 1.5


def find_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    for directory in [Path.cwd(), *Path.cwd().parents][:6]:
        if (directory / "state").is_dir() or (directory / "config.json").is_file():
            return directory / DEFAULT_PATH
    return DEFAULT_PATH


def load(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "sources": {}}
    data.setdefault("sources", {})
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_ts(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def mined_through(path: Path, source: str):
    """The last timestamp this source was successfully mined through, or None."""
    entry = load(path).get("sources", {}).get(source)
    return parse_ts(entry.get("mined_through")) if isinstance(entry, dict) else None


def gap_days(since, now) -> float | None:
    if since is None:
        return None
    return round((now - since).total_seconds() / 86400, 2)


def set_through(path: Path, source: str, through: str) -> dict:
    stamp = parse_ts(through)
    if stamp is None:
        raise SystemExit(f"not an ISO timestamp: {through}")
    data = load(path)
    previous = data["sources"].get(source, {}).get("mined_through")
    # Never move backwards: a narrow re-run of an old window must not un-mine
    # everything after it.
    if previous and parse_ts(previous) and parse_ts(previous) > stamp:
        return {"source": source, "unchanged": True, "mined_through": previous,
                "reason": "existing watermark is newer"}
    data["sources"][source] = {
        "mined_through": stamp.isoformat(timespec="seconds"),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    save(path, data)
    return {"source": source, "unchanged": False, "mined_through": data["sources"][source]["mined_through"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["show", "set", "reset"])
    parser.add_argument("--source", choices=SOURCES)
    parser.add_argument("--through", help="ISO timestamp of the latest event mined")
    parser.add_argument("--path", help=f"default: {DEFAULT_PATH} next to config.json")
    args = parser.parse_args()

    path = find_path(args.path)

    if args.command == "show":
        data = load(path)
        now = datetime.now().astimezone()
        print(f"watermark: {path}")
        for source in SOURCES:
            entry = data["sources"].get(source)
            if not entry:
                print(f"  {source:<14} never mined")
                continue
            since = parse_ts(entry.get("mined_through"))
            gap = gap_days(since, now)
            flag = "  <-- gap" if gap is not None and gap > GAP_ALERT_DAYS else ""
            print(f"  {source:<14} through {entry.get('mined_through')}  ({gap}d ago){flag}")
        return 0

    if not args.source:
        raise SystemExit("--source is required for set/reset")

    if args.command == "reset":
        data = load(path)
        data["sources"].pop(args.source, None)
        save(path, data)
        print(f"reset {args.source}; next run will bootstrap")
        return 0

    if not args.through:
        raise SystemExit("--through is required for set")
    result = set_through(path, args.source, args.through)
    if result["unchanged"]:
        print(f"{args.source}: unchanged ({result['reason']}), still {result['mined_through']}")
    else:
        print(f"{args.source}: mined through {result['mined_through']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
