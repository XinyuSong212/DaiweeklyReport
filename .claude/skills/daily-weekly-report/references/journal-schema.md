# Journal schema and mining rules

The journal is the asset this skill builds. Reports are rendered from it; it
outlives them. Stored as `journal/YYYY-MM.jsonl`, one JSON object per line,
append-only.

## Schema

```json
{
  "id": "2026-09-15-checkout-idempotency",
  "date": "2026-09-15",
  "project": "payments-api",
  "title": "Idempotency keys for checkout retries",
  "status": "shipped",

  "framing": "Checkout failures were being read as gateway timeouts; the retries themselves were the cause.",
  "alternatives": [
    {"option": "Global checkout lock", "rejected_because": "serializes all checkouts for ~3x p99 latency, to buy a property obtainable locally"}
  ],
  "constraint": "No schema migration available before the freeze on the 20th.",
  "decision": "Per-request idempotency keys, stored client-side and echoed on retry.",
  "outcome": "Failure rate 4% -> 0.6% over two days.",
  "open_question": "Whether to backfill keys for in-flight orders or let them drain.",

  "evidence": [
    {"kind": "your_words", "ts": "2026-09-15T10:22:00+08:00", "quote": "不行，加全局锁会把结账串行化"},
    {"kind": "choice", "ts": "2026-09-15T10:31:00+08:00", "quote": "Chose: per-request keys | Passed over: global lock"},
    {"kind": "commit", "ref": "a1b2c3d4e5f6", "quote": "fix(checkout): idempotency keys on retry (#123)"}
  ],
  "supersedes": null
}
```

### Fields

| Field | Required | Notes |
|---|---|---|
| `id` | yes | `YYYY-MM-DD-slug`, stable, used by `supersedes` |
| `date` | yes | local date of the decision |
| `project` | yes | repo, service or workstream. Be consistent — weekly clusters on it |
| `title` | yes | ≤ 60 chars, names the decision, not the task |
| `status` | yes | `shipped` · `in_progress` · `parked` · `abandoned` · `reversed` |
| `framing` | no | what was believed at the start, especially if it was wrong |
| `alternatives` | no | each needs a real `rejected_because` |
| `constraint` | no | the thing that actually forced the call |
| `decision` | yes | what was chosen |
| `outcome` | no | measured result. `null` until measured — not a prediction |
| `open_question` | no | what is still unresolved |
| `evidence` | yes | ≥ 1 item |
| `supersedes` | no | `id` of an entry this continues or reverses |

`evidence.kind` is one of `your_words`, `choice`, `commit`, `note`, `pr`.
Quotes are **verbatim, in the original language**. Never paraphrase into
evidence — the point of evidence is that it is unedited.

## What qualifies as an entry

A journal entry requires a **fork in the road**: a moment where more than one
path was available and one was taken. If there was no alternative, it was
execution, not a decision — it belongs in the report's activity line, not the
journal.

Qualifies:
- A rejection with a reason ("no, that serializes checkouts")
- A choice between named options, including AskUserQuestion answers
- A reframing ("the timeout isn't the cause, the retry is")
- A constraint discovered that closed off options
- A reversal of an earlier decision — **always record these**, with `supersedes`
- A question left deliberately open, with the reason it was deferred

Does not qualify:
- "ok", "continue", "go ahead" — these approve execution, not a direction
- Assistant analysis the user never responded to
- Tool failures, retries, typo fixes, environment problems
- Anything you would have to invent a rationale for

## Mining procedure

1. **Start from `choices`.** Each is a fork with the untaken paths recorded.
   The `passed_over` options become `alternatives`. Free-text answers matter
   more than the label picked — that is the user speaking.

2. **Then `pushbacks`.** For each, read `responding_to` to find *what* was
   rejected, and `your_words` for *why*. If the why is absent, look at the
   next few prompts — the reason usually follows the rejection. If it is
   genuinely absent, keep the alternative and leave `rejected_because` null;
   do not supply a plausible one.

3. **Then `endorsements`**, to identify which path was taken. An endorsement
   alone is usually not an entry; it completes an entry that a pushback or
   choice started.

4. **Then `prompts`**, for framing and constraints. Read the first prompt of
   each session — it often states the problem better than anything after it.

5. **Join to git.** Match by time proximity and by topic (files, paths, commit
   subject). A commit whose reasoning you found becomes `evidence` and fills
   `outcome`. A commit with no reasoning anywhere is still activity for the
   report — it just gets no journal entry.

6. **Check for supersedes.** Read the month's existing entries before
   appending.

## Confidence and honesty

Precision matters more than coverage. Three well-evidenced entries beat ten
speculative ones — the journal is read months later, when nobody remembers
enough to catch an error.

When the evidence is ambiguous, the options in order of preference are:
write a thinner entry with only the supported fields; or ask the user one
direct question; or drop it. Never fill a gap with something plausible.
