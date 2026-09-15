#!/usr/bin/env python3
"""Check journal entries against the transcripts they claim to quote.

The journal's whole value is that its evidence is real: months later, nobody
remembers enough to catch a quote that drifted or a timestamp filled in from
memory. Two of the first nine entries written here carried invented
timestamps — the quotes were verbatim, the times were rounded or guessed, and
nothing noticed. That class of error is mechanical, so a machine should catch
it rather than a reader.

Checks, in order of severity:

  FABRICATED   an evidence ts with no event at that time, or a quote that does
               not appear in the event it cites
  UNSOURCED    an entry claiming `attribution: "author"` with no `your_words`
               or `choice` evidence at all — nothing ties it to a decision the
               author demonstrably made. An entry recording a call someone else
               made declares `attribution: "assistant"` and is exempt; it must
               never be written up as the author's own reasoning.
  MALFORMED    missing required field, duplicate id, supersedes pointing at an
               id that does not exist

Usage:
    validate_journal.py                          # every journal file
    validate_journal.py --journal journal/2026-09.jsonl
    validate_journal.py --strict                 # UNSOURCED also fails
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REQUIRED = ("id", "date", "project", "title", "status", "decision", "evidence")
STATUSES = {"shipped", "in_progress", "parked", "abandoned", "reversed"}
ATTRIBUTIONS = {"author", "assistant", "shared"}
USER_KINDS = ("your_words", "choice")
# How much of a quote must match. Quotes are often elided with "…" in the
# journal, so compare a prefix rather than the whole string.
QUOTE_STEM = 20


def load_signals(script_dir: Path, since: str) -> dict[str, list[str]]:
    """Every human event the collector can see, indexed by timestamp."""
    result = subprocess.run(
        [sys.executable, str(script_dir / "collect_conversations.py"),
         "--since", since, "--format", "json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit("could not run collect_conversations.py")
    signals: dict[str, list[str]] = {}
    for session in json.loads(result.stdout)["sessions"]:
        for prompt in session["prompts"]:
            signals.setdefault(prompt["ts"], []).append(prompt["text"])
        for choice in session["choices"]:
            signals.setdefault(choice["ts"], []).append(str(choice["answer"]))
    return signals


def check_entry(entry: dict, signals: dict, known_ids: set) -> list[tuple[str, str]]:
    problems = []
    entry_id = entry.get("id", "<no id>")

    for field in REQUIRED:
        if entry.get(field) in (None, "", []):
            problems.append(("MALFORMED", f"missing `{field}`"))
    if entry.get("status") not in STATUSES:
        problems.append(("MALFORMED", f"status {entry.get('status')!r} not one of {sorted(STATUSES)}"))
    supersedes = entry.get("supersedes")
    if supersedes and supersedes not in known_ids:
        problems.append(("MALFORMED", f"supersedes unknown id {supersedes!r}"))

    evidence = entry.get("evidence") or []
    attribution = entry.get("attribution", "author")
    if attribution not in ATTRIBUTIONS:
        problems.append(("MALFORMED", f"attribution {attribution!r} not one of {sorted(ATTRIBUTIONS)}"))
    if attribution == "author" and not any(
            e.get("kind") in USER_KINDS for e in evidence if isinstance(e, dict)):
        problems.append(("UNSOURCED",
                         "claims attribution 'author' but carries no your_words or choice "
                         "evidence — either cite the author, or declare attribution "
                         "'assistant' and keep it out of the report's Decided section"))

    for item in evidence:
        if not isinstance(item, dict) or item.get("kind") not in USER_KINDS:
            continue
        ts, quote = item.get("ts"), item.get("quote", "")
        if not ts:
            problems.append(("FABRICATED", f"{item['kind']} evidence has no ts"))
            continue
        events = signals.get(ts)
        if events is None:
            same_minute = [t for t in signals if t[:16] == ts[:16]]
            hint = f"; same minute has {same_minute}" if same_minute else ""
            problems.append(("FABRICATED", f"no event at {ts}{hint}"))
            continue
        stem = quote.rstrip("….").strip()[:QUOTE_STEM]
        if stem and not any(stem in text for text in events):
            problems.append(("FABRICATED", f"quote at {ts} not found in that event: {quote[:40]!r}"))

    return [(level, f"{entry_id}: {message}") for level, message in problems]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--journal", action="append", default=[],
                        help="repeatable; defaults to every journal/*.jsonl")
    parser.add_argument("--since", default="2026-01-01",
                        help="how far back to load transcript signals")
    parser.add_argument("--strict", action="store_true", help="UNSOURCED also fails")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    paths = [Path(p) for p in args.journal] or sorted(Path("journal").glob("*.jsonl"))
    if not paths:
        print("no journal files found", file=sys.stderr)
        return 1

    entries = []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"FAIL  {path}:{number} is not valid JSON — {exc}")
                return 1

    known_ids = {e.get("id") for e in entries}
    duplicates = {i for i in known_ids if [e.get("id") for e in entries].count(i) > 1}

    signals = load_signals(script_dir, args.since)
    problems = []
    for entry in entries:
        problems.extend(check_entry(entry, signals, known_ids))
    problems.extend(("MALFORMED", f"{i}: duplicate id") for i in sorted(duplicates) if i)

    counts = {"FABRICATED": 0, "UNSOURCED": 0, "MALFORMED": 0}
    for level, message in problems:
        counts[level] += 1
        print(f"{level:<11} {message}")

    checked = sum(1 for e in entries
                  for i in (e.get("evidence") or [])
                  if isinstance(i, dict) and i.get("kind") in USER_KINDS)
    print(f"\n{len(entries)} entries · {checked} user-sourced evidence items checked "
          f"against {len(signals)} transcript events")
    print(f"FABRICATED {counts['FABRICATED']} · UNSOURCED {counts['UNSOURCED']} "
          f"· MALFORMED {counts['MALFORMED']}")

    failing = counts["FABRICATED"] + counts["MALFORMED"] + (counts["UNSOURCED"] if args.strict else 0)
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
