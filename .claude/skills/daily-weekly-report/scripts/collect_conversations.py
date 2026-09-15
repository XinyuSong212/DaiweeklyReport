#!/usr/bin/env python3
"""Extract thinking signals from Claude Code transcripts.

Git records what you did. Conversations are the only place that records what
you *didn't* do and why. This script mines the second.

It pulls four kinds of signal out of ~/.claude/projects/**/*.jsonl:

  prompts      every message you actually typed (problem framing, constraints)
  pushback     messages where you rejected or redirected a proposal, paired
               with the proposal you were rejecting   <- highest value
  endorsements messages where you approved a proposal, paired with what you
               approved
  choices      AskUserQuestion answers: the option you picked AND the options
               you passed over, which is an explicit, recorded tradeoff

Design note: this script optimizes for RECALL, not precision. The regex
classifiers over-trigger on purpose. A model reads the output and decides what
was really a decision. Do not tighten these patterns to reduce noise -- that
loses signal the model could have used.

Usage:
    collect_conversations.py --days 1                  # today's signals
    collect_conversations.py --since 2026-09-08 --until 2026-09-14
    collect_conversations.py --days 7 --format md      # human-readable digest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Excerpt of the assistant turn kept alongside an endorsement/pushback.
# Taken from the END of the turn -- the closing prose is what you reacted to.
EXCERPT_CHARS = 900
# A short reaction is far more likely to be a pure verdict ("no, too slow")
# than a long one that happens to open with "but".
SHORT_MESSAGE_CHARS = 60

ENDORSE_PATTERNS = [
    # zh
    r"^(对|对的|没错|是的|嗯+|好|好的|行|可以|不错|赞|棒|漂亮|完美)\b",
    r"(同意|赞同|认可|有道理|说得对|就这样|就这么|就按|采纳|保留这个|这个思路好|正是)",
    # en
    r"^(yes|yep|yeah|right|correct|exactly|agreed|agree|perfect|nice|great|ok|okay|lgtm|sgtm|sounds good)\b",
    r"(good call|makes sense|that's right|let's do|go with|i like|love it|spot on)",
]

PUSHBACK_PATTERNS = [
    # zh -- rejection, correction, redirection
    r"(不行|不对|不好|不要|不用|别这样|别用|错了|有问题|不合适|不同意|不妥)",
    r"(太慢|太复杂|太重|开销|成本太|风险太)",
    r"(换个|换成|改成|重来|重新|再想想|回退|撤销|其实|反而)",
    r"^(但是|不过|然而|可是)",
    # en
    r"^(no|nope|not quite|wrong|actually|but|however)\b",
    r"(doesn't work|does not work|won't work|will not work|bad idea|disagree|too slow|too complex|instead of|rather than|revert|roll back|scrap that)",
]

# Turn-level noise that is not something a human typed as thinking.
STRIP_BLOCKS = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.S),
    re.compile(r"<command-message>.*?</command-message>", re.S),
    re.compile(r"<command-args>.*?</command-args>", re.S),
]

ENDORSE_RE = [re.compile(p, re.I) for p in ENDORSE_PATTERNS]
PUSHBACK_RE = [re.compile(p, re.I) for p in PUSHBACK_PATTERNS]


def text_of(content) -> str:
    """Flatten a message.content value to plain text.

    Skips `thinking` blocks deliberately: they are the model's internal
    reasoning, never shown to you, so they can't be something you endorsed.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def clean(text: str) -> str:
    for pattern in STRIP_BLOCKS:
        text = pattern.sub("", text)
    return text.strip()


def is_human_prompt(entry: dict) -> bool:
    """True only for messages the person actually typed.

    `type: "user"` covers three different things in a transcript: real human
    prompts, tool results fed back to the model, and subagent prompts written
    by a parent agent. Only the first is thinking.
    """
    if entry.get("type") != "user":
        return False
    if entry.get("isSidechain"):          # subagent turn, authored by an agent
        return False
    if "toolUseResult" in entry:          # tool output wearing a user costume
        return False
    origin = entry.get("origin")
    # Older transcripts omit `origin`; absence is not evidence of non-human.
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    return True


def classify(text: str) -> tuple[list[str], str]:
    """Return (labels, confidence) for a human message."""
    head = text[:200]
    labels = []
    if any(r.search(head) for r in ENDORSE_RE):
        labels.append("endorsement")
    if any(r.search(head) for r in PUSHBACK_RE):
        labels.append("pushback")
    confidence = "high" if len(text) <= SHORT_MESSAGE_CHARS else "medium"
    return labels, confidence


def parse_ts(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def tail(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def read_session(path: Path, start, end, local_tz) -> dict | None:
    """Mine one transcript file. Returns None if nothing falls in the window."""
    meta = {
        "session_id": path.stem,
        "project": path.parent.name,
        "cwd": None,
        "git_branch": None,
        "first_ts": None,
        "last_ts": None,
    }
    prompts, endorsements, pushbacks, choices = [], [], [], []
    assistant_buffer: list[str] = []

    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = entry.get("type")

            if kind == "assistant":
                assistant_buffer.append(text_of(entry.get("message", {}).get("content")))
                continue

            # AskUserQuestion: the only place a tradeoff is recorded with the
            # roads-not-taken still attached.
            if kind == "user" and isinstance(entry.get("toolUseResult"), dict):
                result = entry["toolUseResult"]
                answers = result.get("answers")
                if isinstance(answers, dict) and answers:
                    ts = parse_ts(entry.get("timestamp"))
                    if not in_window(ts, start, end):
                        continue
                    options_by_q = {}
                    for question in result.get("questions") or []:
                        if isinstance(question, dict):
                            options_by_q[question.get("question")] = [
                                {"label": o.get("label"), "description": o.get("description")}
                                for o in (question.get("options") or [])
                                if isinstance(o, dict)
                            ]
                    for question, answer in answers.items():
                        options = options_by_q.get(question, [])
                        chosen = {a.strip() for a in str(answer).split(",")}
                        choices.append({
                            "ts": iso(ts, local_tz),
                            "question": question,
                            "answer": answer,
                            "passed_over": [
                                o for o in options if o["label"] not in chosen
                            ],
                        })
                continue

            if not is_human_prompt(entry):
                continue

            text = clean(text_of(entry.get("message", {}).get("content")))
            ts = parse_ts(entry.get("timestamp"))
            meta["cwd"] = entry.get("cwd") or meta["cwd"]
            meta["git_branch"] = entry.get("gitBranch") or meta["git_branch"]

            preceding = "\n".join(t for t in assistant_buffer if t.strip())
            assistant_buffer = []

            if not text or not in_window(ts, start, end):
                continue

            stamp = iso(ts, local_tz)
            if meta["first_ts"] is None:
                meta["first_ts"] = stamp
            meta["last_ts"] = stamp

            labels, confidence = classify(text)
            prompts.append({"ts": stamp, "text": text, "labels": labels})

            if not preceding:
                continue
            record = {
                "ts": stamp,
                "your_words": text,
                "confidence": confidence,
                "responding_to": tail(preceding),
            }
            if "endorsement" in labels:
                endorsements.append(record)
            if "pushback" in labels:
                pushbacks.append(dict(record))

    if not (prompts or choices):
        return None
    meta.update({
        "prompts": prompts,
        "pushbacks": pushbacks,
        "endorsements": endorsements,
        "choices": choices,
    })
    return meta


def in_window(ts, start, end) -> bool:
    if ts is None:
        return False
    return start <= ts < end


def iso(ts, local_tz) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(local_tz).isoformat(timespec="seconds")


def resolve_window(args, local_tz) -> tuple[datetime, datetime]:
    """Day boundaries follow LOCAL time; transcripts store UTC."""
    if args.since:
        start = datetime.fromisoformat(args.since).replace(tzinfo=local_tz)
    else:
        today = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=args.days - 1)
    if args.until:
        end = datetime.fromisoformat(args.until).replace(tzinfo=local_tz) + timedelta(days=1)
    else:
        end = datetime.now(local_tz) + timedelta(seconds=1)
    return start, end


def render_markdown(payload: dict) -> str:
    out = [
        f"# Conversation signals — {payload['window']['since']} to {payload['window']['until']}",
        "",
        f"{payload['totals']['sessions']} sessions · {payload['totals']['prompts']} prompts · "
        f"{payload['totals']['pushbacks']} pushbacks · {payload['totals']['endorsements']} endorsements · "
        f"{payload['totals']['choices']} explicit choices",
        "",
    ]
    for session in payload["sessions"]:
        out.append(f"## {session['project']}  ({session['session_id'][:8]})")
        if session.get("git_branch"):
            out.append(f"branch: `{session['git_branch']}`")
        out.append("")

        if session["choices"]:
            out.append("### Explicit tradeoffs")
            for choice in session["choices"]:
                out.append(f"- **Q:** {choice['question']}")
                out.append(f"  **Chose:** {choice['answer']}")
                for option in choice["passed_over"]:
                    out.append(f"  **Passed over:** {option['label']} — {option['description']}")
            out.append("")

        if session["pushbacks"]:
            out.append("### Pushback (rejected / redirected)")
            for item in session["pushbacks"]:
                out.append(f"- [{item['ts']}] ({item['confidence']}) you: {item['your_words'][:400]}")
                out.append(f"  ↳ rejecting: {item['responding_to'][:400]}")
            out.append("")

        if session["endorsements"]:
            out.append("### Endorsed")
            for item in session["endorsements"]:
                out.append(f"- [{item['ts']}] ({item['confidence']}) you: {item['your_words'][:400]}")
                out.append(f"  ↳ approving: {item['responding_to'][:400]}")
            out.append("")

        out.append("### All your messages")
        for prompt in session["prompts"]:
            flags = f" `{'/'.join(prompt['labels'])}`" if prompt["labels"] else ""
            out.append(f"- [{prompt['ts']}]{flags} {prompt['text'][:600]}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=1, help="window size ending today (default: 1)")
    parser.add_argument("--since", help="YYYY-MM-DD, inclusive")
    parser.add_argument("--until", help="YYYY-MM-DD, inclusive")
    parser.add_argument("--projects-dir", default="~/.claude/projects")
    parser.add_argument("--project", help="substring filter on the project directory name")
    parser.add_argument("--include-orphaned", action="store_true",
                        help="also scan set-aside .orphaned- transcripts (duplicates prompts)")
    parser.add_argument("--format", choices=["json", "md"], default="json")
    parser.add_argument("--out", help="write here instead of stdout")
    args = parser.parse_args()

    local_tz = datetime.now().astimezone().tzinfo
    start, end = resolve_window(args, local_tz)

    root = Path(os.path.expanduser(args.projects_dir))
    if not root.is_dir():
        print(f"no transcripts at {root}", file=sys.stderr)
        return 1

    sessions = []
    for path in sorted(root.glob("*/*.jsonl")):
        if args.project and args.project not in path.parent.name:
            continue
        # Claude Code sets aside earlier copies of a session as
        # `<session>.orphaned-<ts>-<suffix>.jsonl` rather than deleting them.
        # Those still end in .jsonl, so scanning them double-counts the same
        # prompts. (`.jsonl.superseded-<ts>` doesn't match the glob at all.)
        if ".orphaned-" in path.name and not args.include_orphaned:
            continue
        session = read_session(path, start, end, local_tz)
        if session:
            sessions.append(session)

    sessions.sort(key=lambda s: s["first_ts"] or "")
    payload = {
        "window": {"since": start.date().isoformat(), "until": (end - timedelta(seconds=1)).date().isoformat()},
        "totals": {
            "sessions": len(sessions),
            "prompts": sum(len(s["prompts"]) for s in sessions),
            "pushbacks": sum(len(s["pushbacks"]) for s in sessions),
            "endorsements": sum(len(s["endorsements"]) for s in sessions),
            "choices": sum(len(s["choices"]) for s in sessions),
        },
        "sessions": sessions,
    }

    text = render_markdown(payload) if args.format == "md" else json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({payload['totals']['sessions']} sessions)", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
