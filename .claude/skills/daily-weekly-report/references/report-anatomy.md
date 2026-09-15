# Report anatomy

## The five elements

An entry reads as thinking when it carries these. Four of the five exist only
in conversation; git supplies the last one.

| | Element | Where it comes from |
|---|---|---|
| 1 | What you believed at the start, and what corrected it | your early prompts |
| 2 | **The option you rejected, and why** | `pushbacks`, `choices.passed_over` |
| 3 | The constraint that forced the call | your context-setting messages |
| 4 | What is still open | your unanswered questions |
| 5 | The result, measured | git / PR / metrics |

Element 2 carries the most weight and is almost never present in an ordinary
status report. Its absence is why most reports read as activity logs: they
describe a path without showing it was chosen.

## Before / after

Activity:

```markdown
- Refactored the payment retry logic (#123)
- Fixed some flaky tests
- Reviewed Dana's PR
```

Thinking:

```markdown
**Checkout reliability — shipped**
Traced the 4% checkout failure rate to non-idempotent retries, not the gateway
timeouts we had assumed. Considered a global checkout lock and rejected it:
serializing every checkout would have cost ~3x p99 latency to buy a property we
could get locally. Shipped per-request idempotency keys instead (#123); failure
rate is 0.6% after two days.
Open: whether to backfill keys for in-flight orders or let them drain.
```

Same work, same length. The difference is that the second one can be
interrogated — and survives it.

## Daily report

`reports/daily/YYYY-MM-DD.md`. Short. Its job is to surface blockers fast and
prove the journal was written.

```markdown
# Daily — 2026-09-15

## Decided
- **Checkout retries use per-request idempotency keys.** Rejected a global
  lock — ~3x p99 latency for a property obtainable locally. (#123)

## Moved
- Rate limiter: cut over to the token bucket in staging, 0 errors in 6h.
- Reviewed Dana's schema migration; flagged the missing backfill path.

## Blocked
- Staging Redis still on 6.0 — the keyspace notifications we need land in 6.2.
  Needs infra. Asked Wed, no owner yet.

## Open
- Backfill keys for in-flight orders, or let them drain?
```

Rules:
- `Decided` comes first and holds journal entries from today. If it is empty,
  leave the heading with "nothing that qualified" rather than deleting it —
  a run of empty days is information.
- `Blocked` names who is needed and since when. A blocker without an owner and
  an age is not actionable.
- Omit `Open` if nothing is open. Never pad.

## Weekly report

`reports/weekly/YYYY-Www.md`. Clustered by project, never by day.

```markdown
# Week 38 — Sep 15–21, 2026

## Summary
Checkout failures down 4% → 0.6%; the rate limiter cutover is complete. The
Redis upgrade is still unowned and now blocks the quota work planned for next
week.

## Checkout reliability — shipped
Traced the 4% failure rate to non-idempotent retries rather than the gateway
timeouts we had assumed. Rejected a global checkout lock (~3x p99 latency for a
property obtainable locally) in favour of per-request idempotency keys (#123).
Failure rate 0.6% over the last two days.
Open: backfill for in-flight orders, or let them drain.

## Rate limiting — shipped
Cut over to the token bucket. Reversed Tuesday's decision to keep the leaky
bucket behind a flag: maintaining both paths cost more than the rollback safety
was worth once staging ran clean for 48h. (#131, #134)

## Redis 6.2 upgrade — blocked
Needs keyspace notifications, unavailable on staging's 6.0. Raised Wednesday,
still no owner. Blocks per-tenant quotas below.

## Last week's plan
- Ship checkout idempotency — **done** (#123)
- Migrate the rate limiter — **done** (#131, #134)
- Draft the quota RFC — **not started.** Blocked on the Redis upgrade; the
  design depends on which primitives 6.2 gives us.

## Next
- Per-tenant quotas — gated on the Redis upgrade landing
- Backfill decision for in-flight idempotency keys
- Post-mortem on the retry bug: it was live for six weeks before anyone looked
```

Rules:
- `Summary` is three sentences at most: the result, the trend, the thing that
  needs someone else.
- One section per project, headed `## Project — status`.
- Reversals are stated as reversals. "Reversed Tuesday's decision because X" is
  a stronger line than pretending the first decision never happened.
- `Last week's plan` accounts for **every** item from last week's `Next`. Done,
  moved, dropped, superseded — with a reason. This section is the first thing
  an experienced reader checks.
- `Next` is what next week reconciles against. Each item verifiable — "draft
  the quota RFC", not "work on quotas".

## Register

Match the user's existing reports in `reports/` if any exist. Absent those:
plain declarative English, no hedging, no throat-clearing, no exclamation
marks. Short sentences. A paragraph per project beats a bullet list when there
is an arc to tell; bullets are for items with no arc.
