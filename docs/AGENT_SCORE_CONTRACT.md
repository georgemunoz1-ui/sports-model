# Agent Score Contract

Short by design. The README is long and an agent skims it; this file is the whole policy.

## Policy

```
Score-ingestion policy:

1. Do not search the web for scores.
2. Do not use search snippets, headlines, cached summaries, or article text as score evidence.
3. Use only the supplied verified_scores artifact.
4. Match games by event_id, not by team names alone.
5. A score is FINAL only when terminal_verified=true and status is terminal.
6. IN_PROGRESS, NOT_STARTED, POSTPONED, UNKNOWN, CONFLICT, and UNBOUND
   must never be treated as final.
7. DISPLAY_ONLY records may be described as visible results but may not settle,
   grade, update a ledger, or alter a model record.
8. If the artifact does not contain a verified final, state:
   "No canonical final admitted."
9. Never fill a missing result from another source.
10. Never infer a final from elapsed time.
```

## Required output fields

Every score claim must reproduce these. A claim that cannot is **unauditable** and is refused:

```
event_id:
status:
terminal_verified:
evidence_state:
source:
source_fetched_at_utc:
repository_commit:
```

## Authority

```
Operational source:   sportsmodel/main at the audited head
Non-authoritative:    GitHub default main
                      web-search results
                      rendered score pages
                      uncommitted working-tree files
```

Every handoff carries a runtime header:

```
AUTHORITATIVE_CONTEXT: data/agent_context/verified_scores_<date>.json
SOURCE_COMMIT: <sha>
WEB_SCORE_LOOKUP: PROHIBITED
```

## Rule 4 is not optional here

`(away, home)` is a **non-unique key across a repeated series**. On 2026-08-30 a search returned
three finals that were all *genuine* — they were the 2026-08-28 results for the same three
matchups, because the 8/30 MLB slate was set-identical to the 8/28 board's fifteen. A true score
for the wrong date is worse than an invented one: it is checkable, and it is convincing.

`result_binding_gate` names this `PRIOR_DATE_SERIES_JOIN` and has since before that incident.

## What "no data" looks like, and why it is the right answer

Both egress paths to `statsapi.mlb.com` are denied in this deployment — the approved fetch tool
returns `EGRESS_BLOCKED` and the governed adapter returns `403 Forbidden` through the proxy. So a
correct MLB export today contains **zero records and a lane-down header**.

That is the contract working. Pinning the agent to the artifact does not make MLB *correct*; it
makes MLB *dark*, honestly, instead of backfilled, plausibly. The wrong instinct — the one that
produced this whole incident — is to treat an empty governed path as permission to go find
something.

## The one design decision

**The analysis layer may explain and audit `UNVERIFIED`. It may not promote `UNVERIFIED` to
`FINAL`.**

See `docs/SCORE_ADMISSION_CONTRACT.md` for the architecture, the eight admission rules, the split
clock rule, and the board invariants.
