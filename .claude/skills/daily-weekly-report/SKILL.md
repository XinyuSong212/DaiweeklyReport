---
name: daily-weekly-report
description: Write daily and weekly status reports (in English) that show the author's reasoning, not just their activity. Mines Claude Code conversation transcripts for decisions, rejected alternatives and open questions, joins them with git history, and keeps a durable decision journal. Use when the user asks to write, draft, or prepare a daily report, weekly report, status update, standup note, 日报, or 周报 — or asks to capture what they decided today.
---

# Daily & Weekly Report

## The thesis

Git records what you did. **Conversations are the only place that records what
you did not do, and why.** A commit is the result of a decision; the transcript
is the decision itself — the framing you started with, the option you killed,
the constraint that forced your hand.

That material is what makes a report read as thinking rather than activity, and
it evaporates within days. This skill's real job is to capture it. The report is
the output format; the decision journal is the asset.

## Two modes, different jobs

| | Daily | Weekly |
|---|---|---|
| Job | **Ingest.** Capture decisions before they are lost | **Consume.** Aggregate into outcomes |
| Reads | Raw transcripts + git + notes | The journal (**not** raw transcripts) |
| Unit | An event | A result |
| Must run | Every working day | Once a week |

A week of raw transcripts does not fit in context and cannot be reconstructed
from memory. **Weekly is only accurate if daily has been running.** If the
journal is empty for the week, say so and fall back to a wider transcript scan,
warning the user that the older days will be thin.

## What the transcript source actually guarantees

Verified against the Claude Code docs, because the whole design rests on it.

**What holds.** `~/.claude/projects/<project>/<session>.jsonl` is the "full
conversation transcript: every message, tool call, and tool result", stored
locally in plaintext. Nothing is truncated or summarized on the way to disk.

**The four limits.** Each one is a reason the daily run matters:

1. **30-day default retention.** Claude Code deletes transcripts older than
   `cleanupPeriodDays` (default 30, minimum 1). Anything not mined within that
   window is gone. Sessions last continued in Claude Desktop or Cowork are
   exempt by default (`desktopSessionCleanupPeriodDays`).
2. **Local CLI sessions only.** Claude Code on the web and other remote
   sessions run in Anthropic-managed VMs; their transcripts live in an
   ephemeral container, not on the user's machine, and vanish when it is
   reclaimed. Work done in web sessions is invisible to this skill — if the
   user's journal looks thin, check this before assuming a mining failure.
3. **Set-aside copies double-count.** Earlier copies of a session are kept as
   `<session>.orphaned-<ts>-<suffix>.jsonl`, which also ends in `.jsonl`. The
   collector skips them; `--include-orphaned` overrides, and will duplicate
   prompts.
4. **Not encrypted, and it captures everything.** If a tool read a `.env` or a
   command printed a credential, that value is in the transcript. It can
   therefore reach a journal entry. Never copy a raw excerpt into `evidence`
   without reading it — quote the user's reasoning, not whatever the
   surrounding tool output happened to contain.

`~/.claude/history.jsonl` holds every prompt typed, across all projects, with
timestamps. It is a thinner fallback — prompts only, with no assistant turn to
pair an endorsement against — and is swept on the same schedule. Worth checking
only when a project's transcripts are missing.

---

## Daily workflow

**1. Set the window.** Default: today. `--since/--until` if the user names days.

**2. Collect.** From the repo root:

```bash
python3 .claude/skills/daily-weekly-report/scripts/collect_conversations.py --days 1 --format md
python3 .claude/skills/daily-weekly-report/scripts/collect_git.py --days 1 --format md --repo . [--repo OTHER]
```

Read `config.json` for the repo list and author emails if it exists. Also read
`notes.md` — it is the fallback for work that leaves no trace in git or chat
(meetings, reviews, decisions made verbally).

Use `--format md` for reading. Use `--format json --out <scratchpad>` only when
the window is large enough that the digest is unwieldy.

**3. Mine decisions.** This is the actual work — see
`references/journal-schema.md` for the schema and the mining rules. Attack the
collector output in this order, because that is the order of signal quality:

1. `choices` — an AskUserQuestion answer is a recorded tradeoff with the
   rejected options still attached. Nearly always a journal entry.
2. `pushbacks` — you rejecting or redirecting a proposal. `responding_to`
   holds what you killed. **This is the highest-value and most perishable
   signal; never skip it.**
3. `endorsements` — you approving a proposal. Tells you which path was taken.
4. `prompts` — everything else. Your framing, your constraints, the questions
   you asked. Most of it is not a decision; read for the few that are.

The classifiers over-trigger on purpose. Discard the false positives yourself —
a "ok" that just means "continue" is not an endorsement of anything.

**4. Append to the journal.** `journal/YYYY-MM.jsonl`, one JSON object per line.
Before appending, read the existing entries for that month: if a decision
continues or reverses an earlier one, set `supersedes` to the earlier `id`
rather than writing a near-duplicate. A reversal is valuable — it shows learning
— so record it, do not quietly overwrite.

**5. Render** `reports/daily/YYYY-MM-DD.md` from `references/report-anatomy.md`.

**6. Report back** what was captured and, briefly, what looked thin. If a day
produced commits but no discernible reasoning, say so — that is a real signal
about the day, not a failure of the tool.

---

## Weekly workflow

**1. Set the window.** Default: the most recent Monday through today (or through
Sunday if the week is complete).

**2. Read the journal** for the window: `journal/*.jsonl`, filtered by date. Do
not re-mine raw transcripts — the daily runs already did that with more context
than you now have.

**3. Collect outcomes** for the whole week, which the daily runs saw only in
fragments:

```bash
python3 .claude/skills/daily-weekly-report/scripts/collect_git.py --days 7 --format md --repo .
```

Use this for shipped/not-shipped status and for magnitude. Fetch PR state via
the available GitHub tooling when a journal entry references a PR.

**4. Cluster by project or theme, never by day.** Five journal entries about one
migration are one weekly item with an arc, not five bullets. The arc — what you
believed on Monday, what changed it, where it landed — *is* the thinking.

**5. Reconcile with last week.** Read the `Next` section of the previous
`reports/weekly/*.md`. Every commitment must be accounted for: done, moved,
dropped, or superseded. **A dropped commitment gets one line saying why.**
Silently omitting it is the single most common failure of real weekly reports
and the fastest way to lose a reader's trust.

**6. Render** `reports/weekly/YYYY-Www.md` per `references/report-anatomy.md`,
ending with a `Next` section that next week will reconcile against.

---

## Writing rules

Reports are **English**, regardless of the conversation language.

- Past tense, active voice, first person plural or singular — whichever the
  user's existing reports use. Match their register; check `reports/` first.
- Lead with the result, then the reasoning. Never build up to a conclusion.
- Translate engineering into consequence: not "refactored the retry handler"
  but "cut checkout failures from 4% to 0.6%". If you cannot name a
  consequence, say what is now possible that was not before.
- Quantify where the data supports it. Do not invent numbers to fill a slot —
  `insertions`/`deletions` are not achievements and do not belong in a report.
- Evidence quotes stay **verbatim in the language they were written in**. They
  are records. Only the surrounding prose is translated.

Do not write: "continued working on", "made progress on", "various fixes",
"as planned", "some issues were encountered". Each of these is a placeholder
where a fact should be.

## The attribution rule

Material mined from a conversation is used to record **what was decided and
why** — "chose per-request keys over a global lock, since the lock would have
serialized checkouts". That is true and it is the user's judgment, whoever
phrased the options.

Do not lift the assistant's analysis into the report as the user's own
exposition. Two practical consequences:

- Every journal entry carries `evidence`. An entry whose only support is
  assistant text the user never engaged with is not a decision — drop it.
- Prefer the user's own framing and vocabulary. Where their words and the
  assistant's differ, theirs win.

The test: the user's manager asks a follow-up question about any line in the
report. Everything in it must be something the user can defend, because they
actually decided it.

## Never

- Never invent a rationale, a metric, an alternative, or an outcome. Unknown
  fields are `null`. A thin entry is honest; a fabricated one gets caught on the
  first follow-up question.
- Never let a daily report's raw material leak into a weekly report unaggregated.
- Never drop an unmet commitment from last week's `Next`.
