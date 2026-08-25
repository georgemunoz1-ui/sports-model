# Pregame Decision Readiness Standard v1.0

**Effective:** next registered slate.
**Applies to:** primary models, challengers, replacement forecasts, acquisition pipelines, action
overlays and final reports, for every supported sport.

Registered 2026-08-25. This file is the binding text. Implementation lives in
`harness/acquisition_ladder.py`, `harness/checkpoint_schedule.py`,
`harness/replacement_workflow.py`, `harness/fallback_registry.py`, `harness/readiness_gate.py`,
`harness/decision_view.py`, `harness/price_overlay.py`, and is proven by
`harness/standard_acceptance.py`.

## 1. Binding objective

Produce a complete, current and understandable decision for every scheduled game.

Normal final decision vocabulary: **BET** or **PASS**.

A game must not end as `BLOCKED_INFORMATION_UNAVAILABLE`, `PERSONNEL_UNVERIFIED`, `PRICE_MISSING`,
`STARTER_UNCONFIRMED` or `UNCERTAINTY_PIPELINE_DEFECT` merely because the system failed to search,
refresh or prepare its infrastructure. Those are **internal work queues**, to be resolved
autonomously before the decision deadline.

A properly supported PASS is a valid decision. Forcing a wager where uncertainty-adjusted EV is
non-positive is prohibited.

## 2. Autonomous research authority

The primary model has full authority to search and retrieve everything it needs, without waiting for
owner instructions. It must not ask the owner for a schedule, lineup, injury report, starter, score
or price obtainable through an authorized route.

A blocked direct-fetch rail is **not** a finding that information is unavailable. The ladder:

    OFFICIAL_API -> OFFICIAL_LEAGUE_PAGE -> OFFICIAL_TEAM_PAGE_OR_STATUS -> DIRECT_SPORTSBOOK
      -> NAMED_AGGREGATOR -> WEB_SEARCH_OPEN -> OWNER_RELAY

The attempt may not terminate while an authorized route remains untried.

Search snippets may identify an artifact or report a provisional status. Authoritative fields
require the underlying page, payload, team post, or a corroborated fallback source whenever
obtainable.

## 3. Mandatory acquisition schedule

| Checkpoint | Work |
|---|---|
| T−24h | schedule, official game IDs, start times, venues, cohort population |
| T−6h  | starters, roster status, injuries, expected lineups, weather, initial market board |
| T−90m | refresh all material inputs; identify unresolved statuses; **alternate-source search begins** |
| T−45m | official/team injury reports, active rosters, lineup announcements; **recheck team feeds** |
| T−20m | generate replacement forecasts from newly confirmed information; **activate fallback** |
| T−10m | refresh same-book moneyline, spread, total; validate market phase; **open incident on any unresolved field** |
| T−5m  | freeze the final board; remotely anchor model, input and cohort hashes; **must emit BET, PASS or SYSTEM_FAILURE** |
| pre-execution | fresh quote from the selected book; verify max/min playable price |

Sport-specific checkpoints may shift when a league publishes on a different schedule. The final
post-lineup refresh remains mandatory.

## 4. Required information by game

Official league game ID; canonical teams; scheduled and actual start status; venue; starting pitcher
or lineup as appropriate; full active/inactive and injury status; material roster changes; rest,
travel and schedule context; weather and park where relevant; current moneyline, spread and total;
both sides of each market; exact sportsbook identity; quote timestamp; market phase
(`PRE_GAME` / `LIVE` / `HALFTIME` / `FINAL` / `UNVERIFIED`); source URLs or identifiers; retrieval
timestamp; raw retained artifact; content hash; acquisition rung; freshness status.

Public betting percentages, app predictions, trends and sportsbook prices may be shown as context.
They may not enter the underlying forecast model.

## 5. Material-change replacement workflow

A material change after lock must not automatically end the game as blocked.

Material changes: confirmed starter replacing an official TBD; pitcher scratch; starting-lineup
change; player ruled in or out; minutes restriction; venue change; significant weather change;
game-time change; other preregistered high-impact inputs.

On occurrence: (1) preserve the original forecast unchanged; (2) record the exact changed input and
its source; (3) generate a replacement under a **preregistered replacement identity**; (4) assign a
new input hash, forecast hash and generation timestamp; (5) remotely anchor before actual start;
(6) use the newest valid pregame identity in the overlay; (7) grade original and replacement
separately by their registered roles.

**No forecast may be silently overwritten.**

## 6. Validated fallback models

Preregistered, independently testable fallback modes for common missing-input states — e.g. MLB
full-starter, MLB one-starter-partial, MLB official-TBD, MLB confirmed-lineup replacement; WNBA
full-availability, WNBA player-out adjustment, WNBA uncertain-availability conservative.

Fallbacks must be defined **before** the slate and carry distinct identities. An improvised manual
adjustment after seeing the market or the outcome is prohibited. If a fallback is used the report
must identify it. A valid fallback is preferable to blocking a game over one missing normal input.

## 7. Uncertainty must be production infrastructure

`UNCERTAINTY_PIPELINE_DEFECT` is a **board-readiness failure**, not an acceptable recurring
game-level explanation.

Before the primary model may be called decision-ready it must have a frozen uncertainty estimator on
eligible out-of-fold evidence grouped by slate date, specifying: exact estimand; training and
calibration population; cluster definition; minimum admissible cluster count; subgroup pooling
rules; coverage validation; versioned model identity; input and evidence hashes; method for
converting probability uncertainty into conservative EV; refusal behaviour outside validated
support.

Cross-game probability dispersion, Bernoulli outcome variance, Monte Carlo simulation error and
prior-parameter SD may not substitute for model forecast uncertainty.

Provenance restoration and OOF rebuilding run as an **autonomous maintenance task before** the next
production board. The model must not wait until decision time to discover its estimator is missing.

If the pipeline is not ready the entire product is **`SYSTEM_NOT_DECISION_READY`**, and it must not
publish a page that appears decision-ready while containing a slate full of blocked rows.

## 8. Price and market requirements

Prices belong only in the action overlay. Per potential wager: the exact price at the identified
book; the quote verified pregame; both sides from the same book for hold and no-vig; cross-book best
prices for line shopping only, never same-book hold; opening and current recorded separately; a
fresh pre-wager quote check; a quote captured after actual start rejected from the pregame overlay;
**never** a live price combined with a frozen pregame probability.

## 9. Final decision contract

The report begins with one row per game: actual decision (BET or PASS); recommended side and market;
current price; max/min playable price; model probability; break-even probability; no-vig
probability; raw EV per $100; conservative uncertainty-adjusted EV; projected winner; projected
margin and total; model-arm agreement; personnel and lineup verification; quote timestamp and age;
recommended units and dollars; primary reason.

Unit size **$100**; a wager shows both units and dollars. Blocked model preferences appear only in a
technical watchlist and may never be labelled selections.

## 10. Failure escalation

T−90 alternate-source search begins automatically. T−45 official team pages, status posts and league
feeds rechecked. T−20 registered fallback or replacement mode activated. T−10 any unresolved field
opens an acquisition incident. T−5 the system must produce BET, PASS or an exceptional
`SYSTEM_FAILURE`.

`SYSTEM_FAILURE` is not an acceptable normal result. It records: missing field; every attempted
route; exact errors; last successful artifact; responsible subsystem; remediation required before
the next slate.

**The system must never disguise acquisition failure as model conservatism.**

## 11. Exceptional non-actionable states

`GAME_ALREADY_LIVE`, `GAME_POSTPONED_OR_CANCELLED`, `MARKET_SUSPENDED`,
`CONFLICTING_AUTHORITATIVE_IDENTITIES`, `MATERIAL_CHANGE_TOO_LATE_TO_ANCHOR`,
`INTEGRITY_OR_CHRONOLOGY_FAILURE`, `NO_VALIDATED_MODEL_OR_FALLBACK_FOR_STATE`.

These are exceptional **incident** states — not ordinary PASS decisions, and not evidence that
searching was optional.

## 12. Acceptance tests

Implemented only when automated tests prove: every scheduled game receives a final decision row;
every required acquisition route is attempted in order; a blocked direct rail automatically advances;
material changes generate replacement identities; original forecasts remain immutable; live prices
cannot enter pregame overlays; cross-book prices cannot pass same-book hold validation; stale quotes
cannot authorize execution; missing uncertainty prevents the board from claiming decision readiness;
no blocked opportunity is labelled a selection; every authorized wager carries a fresh quote, risk,
stake and playable-price boundary.

## Binding conclusion

Information unavailability is an acquisition and infrastructure failure to be resolved autonomously.
It is not an acceptable routine explanation for an unusable decision board.

The primary model owns the complete path:

    ACQUIRE -> VERIFY -> REFRESH -> REFORECAST -> PRICE -> QUANTIFY UNCERTAINTY -> DECIDE
      -> RENDER -> ANCHOR

Every game receives a decision. Every wager must be supported. No wager is forced merely to avoid
reporting a pass.
