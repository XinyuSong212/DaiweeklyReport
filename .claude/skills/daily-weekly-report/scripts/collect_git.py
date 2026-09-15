#!/usr/bin/env python3
"""Collect git activity for a report window.

This is the outcome side of a report entry. Conversations say what you decided
and why; git says what actually landed and how big it was. The two are joined
by time and topic when the journal entry is written.

Usage:
    collect_git.py --days 1
    collect_git.py --since 2026-09-08 --until 2026-09-14 --repo ~/work/api --repo .
    collect_git.py --days 7 --format md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
# The separator LEADS the format. With --numstat, git prints the formatted
# header first and the stat block after it, so a trailing separator would slice
# each commit's numstat onto the front of the next record.
PRETTY = RECORD_SEP + FIELD_SEP.join(["%H", "%aI", "%an", "%ae", "%s", "%b"])


def load_config(start: Path) -> dict:
    """Find config.json in cwd or any ancestor up to the repo root."""
    for directory in [start, *start.parents][:6]:
        candidate = directory / "config.json"
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
    return {}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def default_emails(repo: Path) -> list[str]:
    email = git(repo, "config", "user.email").strip()
    return [email] if email else []


def parse_numstat(block: str) -> tuple[list[str], int, int]:
    files, added, removed = [], 0, 0
    for line in block.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        plus, minus, path = parts
        files.append(path)
        # Binary files report "-" instead of a count.
        added += int(plus) if plus.isdigit() else 0
        removed += int(minus) if minus.isdigit() else 0
    return files, added, removed


def collect_repo(repo: Path, since: str, until: str, emails: list[str], include_merges: bool) -> dict | None:
    if not (repo / ".git").exists() and not git(repo, "rev-parse", "--git-dir").strip():
        return None

    args = ["log", f"--since={since}", f"--until={until}", f"--pretty=format:{PRETTY}", "--numstat"]
    if not include_merges:
        args.append("--no-merges")
    for email in emails:
        args.append(f"--author={email}")
    # --all so work on feature branches that were never merged still shows up.
    args.append("--all")

    raw = git(repo, *args)
    commits = []
    for record in raw.split(RECORD_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue
        head, _, rest = record.partition("\n")
        fields = head.split(FIELD_SEP)
        if len(fields) < 6:
            continue
        sha, authored, name, email, subject, body_head = fields[:6]
        # %b spans newlines, so the tail holds the rest of the body followed by
        # the numstat block. A numstat line is exactly three tab-separated
        # fields; everything before the first of those is still body.
        body_lines, stat_lines = [body_head], []
        for line in rest.splitlines():
            if len(line.split("\t")) == 3:
                stat_lines.append(line)
            elif not stat_lines:
                body_lines.append(line)
        files, added, removed = parse_numstat("\n".join(stat_lines))
        body = "\n".join(body_lines).strip()
        commits.append({
            "sha": sha[:12],
            "ts": authored,
            "author": f"{name} <{email}>",
            "subject": subject,
            "body": body,
            "pr": extract_pr(subject, body),
            "files": files,
            "files_changed": len(files),
            "insertions": added,
            "deletions": removed,
        })

    if not commits:
        return None
    commits.sort(key=lambda c: c["ts"])
    return {
        "repo": str(repo),
        "name": repo.resolve().name,
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "commits": commits,
        "totals": {
            "commits": len(commits),
            "insertions": sum(c["insertions"] for c in commits),
            "deletions": sum(c["deletions"] for c in commits),
            "files_touched": len({f for c in commits for f in c["files"]}),
        },
    }


def extract_pr(subject: str, body: str) -> str | None:
    import re
    match = re.search(r"#(\d+)", subject) or re.search(r"#(\d+)", body)
    return f"#{match.group(1)}" if match else None


def render_markdown(payload: dict) -> str:
    out = [
        f"# Git activity — {payload['window']['since']} to {payload['window']['until']}",
        "",
    ]
    if not payload["repos"]:
        out.append("_No commits in window._")
        return "\n".join(out)
    for repo in payload["repos"]:
        totals = repo["totals"]
        out.append(f"## {repo['name']}  ({totals['commits']} commits, "
                   f"+{totals['insertions']}/-{totals['deletions']}, "
                   f"{totals['files_touched']} files)")
        for commit in repo["commits"]:
            pr = f" {commit['pr']}" if commit["pr"] else ""
            out.append(f"- `{commit['sha']}` {commit['ts'][:10]}{pr} — {commit['subject']} "
                       f"(+{commit['insertions']}/-{commit['deletions']})")
            for path in commit["files"][:8]:
                out.append(f"    - {path}")
            if len(commit["files"]) > 8:
                out.append(f"    - … {len(commit['files']) - 8} more")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--repo", action="append", default=[], help="repeatable; defaults to cwd")
    parser.add_argument("--author", action="append", default=[], help="repeatable email filter; defaults to git config user.email")
    parser.add_argument("--all-authors", action="store_true")
    parser.add_argument("--include-merges", action="store_true")
    parser.add_argument("--format", choices=["json", "md"], default="json")
    parser.add_argument("--out")
    args = parser.parse_args()

    config = load_config(Path.cwd())

    today = datetime.now().date()
    since_date = datetime.fromisoformat(args.since).date() if args.since \
        else today - timedelta(days=args.days - 1)
    until_date = datetime.fromisoformat(args.until).date() if args.until else today

    # Always pass an explicit time. `git log --since=2026-09-15` does NOT mean
    # midnight: git's approxidate fills a missing time-of-day with the CURRENT
    # time, so a bare date silently drops everything committed earlier today.
    since = f"{since_date.isoformat()}T00:00:00"
    until = f"{(until_date + timedelta(days=1)).isoformat()}T00:00:00"

    repo_args = args.repo or config.get("repos") or ["."]
    repos = [Path(os.path.expanduser(r)) for r in repo_args]
    payload = {"window": {"since": since_date.isoformat(), "until": until_date.isoformat()}, "repos": []}
    for repo in repos:
        emails = [] if args.all_authors else (
            args.author or config.get("author_emails") or default_emails(repo)
        )
        collected = collect_repo(repo, since, until, emails, args.include_merges)
        if collected:
            payload["repos"].append(collected)

    text = render_markdown(payload) if args.format == "md" else json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
