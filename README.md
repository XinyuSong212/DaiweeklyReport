# DaiweeklyReport

Daily and weekly status reports that show reasoning rather than activity.

**Git records what you did. Conversations are the only place that records what
you did not do, and why.** That second thing is what makes a report worth
reading, and it evaporates within days. This repo captures it.

## How it works

```
~/.claude/projects/**/*.jsonl ─┐
git log / PRs ─────────────────┼──► daily run ──► journal/YYYY-MM.jsonl ──► weekly run ──► reports/weekly/
notes.md ──────────────────────┘        │                (decisions)              │
                                        ▼                                         ▼
                                 reports/daily/                      reconciled against last week's plan
```

The **daily** run is an ingest: it mines that day's conversations for decisions
— rejected alternatives, forced constraints, open questions — and appends them
to a durable journal. The daily report is a byproduct.

The **weekly** run consumes the journal, clusters by project, joins outcomes
from git, and reconciles against what last week promised. It never re-reads raw
transcripts: a week of them does not fit in context, which is why the daily run
has to happen.

## Usage

Ask Claude Code in this repo:

- "write today's daily report" / "写今天的日报"
- "write this week's weekly report" / "写本周周报"
- "capture what I decided today"

The `daily-weekly-report` skill triggers on those.

## Layout

```
.claude/skills/daily-weekly-report/
  SKILL.md                      workflow and writing rules
  references/
    journal-schema.md           entry schema + mining rules
    report-anatomy.md           the five elements, templates, before/after
  scripts/
    collect_conversations.py    transcripts -> prompts, pushbacks, endorsements, choices
    collect_git.py              git history -> commits, PRs, magnitude
config.json                     repos and author emails to scan
notes.md                        free-form capture for work that leaves no trace
journal/YYYY-MM.jsonl           the decision journal (the actual asset)
reports/daily/YYYY-MM-DD.md
reports/weekly/YYYY-Www.md
```

## Scripts standalone

Both run on their own, no model required:

```bash
python3 .claude/skills/daily-weekly-report/scripts/collect_conversations.py --days 1 --format md
python3 .claude/skills/daily-weekly-report/scripts/collect_git.py --days 7 --format md --repo .
```

The conversation collector optimizes for **recall** — its classifiers
over-trigger by design, and a model filters afterwards. Tightening them to
reduce noise loses signal.

## Reports are English

Conversations can be in any language. Reports are written in English; evidence
quotes stay verbatim in whatever language they were written in, because they are
records.

## A note on attribution

The journal records **what you decided and why** — a judgment you made, whoever
phrased the options. It does not lift assistant analysis into your report as
your own exposition. Every entry carries `evidence` traceable to your own words,
your own choices, or your own commits, so that any line survives a follow-up
question from whoever reads it.

## What the transcript source guarantees, and its four limits

The design rests on transcripts being complete and local, so this is worth
stating precisely (verified against the Claude Code docs):

`~/.claude/projects/<project>/<session>.jsonl` is the **full conversation
transcript — every message, tool call and tool result** — written locally in
plaintext, untruncated.

But:

1. **30-day default retention.** Transcripts older than `cleanupPeriodDays`
   (default 30, minimum 1) are deleted. This is the hard ceiling on how late
   you can mine a day, and the reason the daily run is not optional. Sessions
   last continued in Claude Desktop or Cowork are exempt by default.
2. **Local CLI sessions only.** Claude Code on the web and other remote
   sessions run in ephemeral Anthropic-managed VMs. Those transcripts never
   reach your machine. Work done in web sessions cannot be mined.
3. **Set-aside copies double-count.** Superseded session copies are kept as
   `<session>.orphaned-<ts>-<suffix>.jsonl` — also a `.jsonl` file. The
   collector skips them by default; `--include-orphaned` will duplicate prompts.
4. **Not encrypted, and it captures everything.** If a tool read a `.env` or a
   command printed a credential, that value is in the transcript in plaintext,
   and could reach a journal entry. Review `journal/` and `reports/` before
   pushing to a shared remote.
