# Score Admission Contract

**Adopted 2026-08-30, owner directive.** Standing rule, same force as R1/R3/R6.

## Why this exists

Twice in four days a language model turned a natural-language summary into a final score.

- **2026-08-27** — five fabricated finals were **published**. Nothing in code stopped it.
- **2026-08-30 13:30 ET** — a search returned three confident finals: Nationals 9–2,
  Yankees 1–0, Braves 6–4. `BOS@NYY` and `COL@ATL` were both scheduled for 13:35 ET and
  **had not started**. `MIA@WSH` was 75 minutes into a game that needs ~170. All three
  were refused **by hand**. Nothing in code stopped that either.

Hand-refusal is not a control. The second time, the thing that caught it was arithmetic on
the clock — not source reputation, not model care. That arithmetic is now code.

A separate defect surfaced the same day inside a *frozen* board: `MIN @ ATL` carried
`model_win_pct 39.7` (ATL losing by 3.65) and `model_cover_pct 64.2` derived from
`Phi(5.1/13.97)` (ATL **winning** by 2.6), and took a LEAN off the second. Better sourcing
would not have touched it. Two problems, two independent gates.

## Architecture

```
        Approved source API          ← CANONICAL lane only
                 ↓
   Game binding + status validator   ← score_admission.admit()
                 ↓
     Immutable verified snapshot     ← verified_snapshot, content-addressed
                 ↓
   Analysis / card generation        ← reads records, never raw feeds
```

The analysis layer never sees a page, a headline, or a snippet. It sees normalized JSON that
already passed the gate, or it sees `NO_DATA`.

## Three lanes

| Lane | Source | Trust | May write to |
|---|---|---|---|
| **CANONICAL** | official league feeds (MLB StatsAPI) | high | the board, after validation |
| **SEARCH** | web search, secondary sites | low | **quarantine only — never the board** |
| **MARKET** | odds, CLV, injury status | medium | price rows only |

Lane permissions are **data the checker enforces**, not prose in a comment.

**When the canonical lane is down, the output is an explicit `NO_DATA_LANE_DOWN`** — never a
search backfill. An empty list reads like "no games today"; a lane-down verdict does not.
As of this writing `espn.com` and `covers.com` are `EGRESS_BLOCKED`, which is precisely the
condition under which the 8/30 fabrication entered.

## The eight admission rules

1. Bind by provider event ID, never by team names alone.
2. Require exact home team, away team, league, and scheduled date.
3. Require a source status field.
4. Accept a final score only when status is terminal.
5. Reject search snippets without an event ID and terminal status.
6. Reject scores that conflict with the canonical schedule.
7. Preserve the raw response and content hash.
8. Treat unknown, delayed, postponed, and in-progress games as non-final.

## The clock rule, split

The owner's two messages disagreed here, and the disagreement is real rather than a wording
slip. Message 1: provider status is primary, the clock is a secondary check, *because a
legitimately short game could be rejected for ending faster than the minimum*. Message 2:
time-gate everything as a hard reject.

Both are right about different halves, so the rule is split:

- **Pre-start is a HARD invariant.** `now < scheduled_start` → a final is *impossible*.
  No provider status overrides it. A feed asserting a final before first pitch is a provider
  bug or a mis-bound game, and either way it must not be admitted. **No legitimately short
  game is affected, because no game ends before it begins.** Disposition:
  `REJECT_PRESTART_OR_UNBOUND`.
- **Minimum duration is a SOFT check.** It *can* false-reject a rain-shortened or called
  game, so on its own it yields `UNVERIFIED_TOO_SOON` — clearable by a terminal status from
  the **canonical** lane, and never by a search snippet.

Minimums: MLB 150 min · NBA 120 · WNBA 120 · NFL 165 · CFB 180.

## Terminal is not validated

Some providers distinguish `complete` (over, statistics not yet validated) from `closed`
(validated). `TERMINAL_STATES` and `VALIDATED_STATES` are **separate sets**, and
`terminal_verified` is true only for the validated one. A game can be over and still not be
settled.

## Consensus does not launder search

Two independent search sources agreeing raises the grade to
`IDENTIFIED_UNCONFIRMED_CORROBORATED` — and no further. **Search never mints FINAL, with or
without consensus.** Two outlets carrying one wire feed are not two observations, and the
standing rule is older than this document: *snippets identify and never bind.*

## Tool surface

The analysis layer may call exactly these, and they return only normalized validated records:

```
get_verified_score(event_id)
get_verified_scores(date, league)
get_source_manifest(snapshot_id)
```

Quarantine is reachable only through `get_quarantine(date, league)` — a separate, deliberately
awkward name, so reading unadmitted data is always an explicit act.

The analysis layer has no permission to alter the raw feed, the result ledger, or the
settled-game table.

## Board invariants — the second gate

Independent of sourcing, before publication:

```
if market_price is null:
    prohibit edge calculation
    prohibit usable_edge calculation
    decision = PASS_DATA_QUALITY

if ML probability and spread probability claim one distribution:
    verify both derive from the same projected margin and sigma

if the two arms imply materially incompatible outcomes:
    decision = CONVERGENCE_FAIL
    suppress LEAN

if injury availability is stale or unresolved:
    availability_state = UNKNOWN
    suppress any play dependent on it
```

An edge computed against a **round assumed** no-vig (`50.0`, no captured price) is the same
defect wearing a plausible number, and discounting it by DQ × Unc launders a wrong base rather
than repairing it. That earns `ASSUMED_NO_VIG_PRICE`.

σ discipline: `13.97` is a **registered coherence tolerance**, not a distributional constant.
Measured WNBA values are margin `12.5523` and totals `18.0156`, n=1721 each, in
`data/audit/2026-08-30_sigma_provenance_register.json`. A sigma the register does not classify
as MEASURED earns `UNMEASURED_SIGMA` — a warning, because on the `MIN @ ATL` row it moved the
answer by two points and was the *smallest* thing wrong.

### Acceptance case

`MIN @ ATL` in `cards/2026-08-30_pregame_board_v6_canonical.json` must come out as:

```json
{ "decision": "PASS",
  "reason_codes": ["MISSING_MARKET_PRICE", "AVAILABILITY_UNKNOWN", "MODEL_CONVERGENCE_FAIL"] }
```

## Instruction to the analysis layer

```
You are not the score-ingestion system.

Never infer a final score from:
- a search snippet;
- a headline;
- an article title;
- a cached page;
- a result lacking a provider event ID;
- a result whose game status is not explicitly terminal.

Only use records from the verified snapshot.

A score may be marked FINAL only when:
1. event_id matches the canonical schedule;
2. league, date, home team, and away team match;
3. source status is terminal;
4. source_fetched_at_utc is present;
5. the score fields are numeric;
6. terminal_verified is true.

If any condition fails, output:
    status: UNVERIFIED
and do not write the score to any card, ledger, residual table, or grading table.

Never repair missing data with a likely score.
Never use a same-team matchup from another date.
Never convert IN_PROGRESS into FINAL based on elapsed time.
```

**The design decision, stated once:** the analysis layer may *explain and audit* `UNVERIFIED`.
It may not *promote* `UNVERIFIED` to `FINAL`.

## Standing hazards this contract does not close

- **Same-matchup, different date.** The 8/30 MLB slate was **set-identical** to the 8/28
  board's fifteen matchups — normal for a Friday–Sunday series, and exactly the
  `PRIOR_DATE_SERIES_JOIN` condition `result_binding_gate` already names. Binding by event ID
  closes it *for records that carry one*. Anything that still joins on `(away, home)` remains
  unsafe.
- **Mutable archives.** On 2026-08-30 the admitted pitch archive rewrote two historical daily
  files under unchanged filenames. Every read is commit-addressed and content-hashed; a sha
  recorded once is an observation at a moment, not a permanent fact.
- **Team-code collisions.** `ARI` vs `AZ` for one club. Normalize at capture or a row drops
  silently.
## Probed, not assumed: the MLB canonical lane is DOWN

The owner's directive said, correctly, that MLB StatsAPI is unauthenticated and *"if your
environment can reach MLB's Stats API, that becomes your canonical lane for baseball
specifically."* That was the right thing to check, so it was checked, with the approved fetch
tool:

```
GET https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-08-30
{"error_type":"EGRESS_BLOCKED","domain":"statsapi.mlb.com",
 "message":"Access to statsapi.mlb.com is blocked by the network egress proxy."}
```

**It is blocked.** Not routed around, before or after. So the MLB canonical lane cannot come
up in this deployment, and the contract's own answer applies: MLB score output is
`NO_DATA_LANE_DOWN` until an approved fetcher is provisioned. That is the same posture already
taken on NFL, extended to MLB exactly as the owner asked — and it is the whole point of the
lane-down rule that it produces a *stated* absence rather than a silent one.

### The asymmetry that actually defines this deployment

`github.com` **is** reachable — the session git proxy serves it. Every sports content domain
and now the league's own API are not. So the admissible-source frontier here is not *"what a
sports API publishes"* but ***"what is mirrored into a public GitHub repository."*** WNBA
works precisely because `wehoop-wnba-raw` mirrors ESPN into git; that is why the 8/29 cohort
bound 2/2 while MLB bound 0/62.

Searched so far, and what each does and does not carry:

| Archive | gamePks | Finals |
|---|---|---|
| `lancebroz/mlb-pitcher-data` | yes, all games | **no** — no runs column, RJ-001B standing |
| `sportsdataverse/baseballr-data` | yes, in `mlb_wpa_*` | **no** — model tables and WPA only |
| its `statcast/` folder | — | coverage ends 2022 |

## Standing hazards this contract does not close

- **Same-matchup, different date.** The 8/30 MLB slate was **set-identical** to the 8/28
  board's fifteen matchups — normal for a Friday–Sunday series, and exactly the
  `PRIOR_DATE_SERIES_JOIN` condition `result_binding_gate` already names. Binding by event ID
  closes it *for records that carry one*. Anything that still joins on `(away, home)` remains
  unsafe.
- **Mutable archives.** On 2026-08-30 the admitted pitch archive rewrote two historical daily
  files under unchanged filenames. Every read is commit-addressed and content-hashed; a sha
  recorded once is an observation at a moment, not a permanent fact.
- **Team-code collisions.** `ARI` vs `AZ` for one club. Normalize at capture or a row drops
  silently.
- **CFB** has no admissible source at all under the current id schema.
