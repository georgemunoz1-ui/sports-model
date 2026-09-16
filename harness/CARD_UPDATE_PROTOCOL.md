# Card Update Protocol (standing rule — adopted 2026-08-29, owner directive)

**Trigger "update card" / "refresh" ALWAYS means ALL sports.** Never a single-sport sweep.

## Mandatory sweep order on every update
1. **Results pass (all four sports):** check every game on the card — CFB, WNBA, MLB, NFL —
   for finals/in-progress status. Grade every play: WON / LOST / PUSH / LIVE / PENDING.
   Unbindable ids (DK_RELAY etc.) are graded *descriptively* and never touch the ledger.
2. **Lines pass:** current prices for anything not yet played.
3. **Audit-clause pass:** injury/availability/lineup news for every unplayed game with an
   active play (per MARKET_INDEPENDENCE_RULE: large-edge audit). This pass is MANDATORY for
   WNBA (ff7 has no availability inputs) and for any play where the model disagrees with the
   market by >1σ.
4. **Scoring pass:** any new final gets the residual table treatment (per signal, in σ units,
   at the measured sport σ — not a retired constant).
5. **Hypothesis watch:** totals-bias tracker, convergence-magnitude rule, any open items.

## Anti-omission rules
- An update that covers fewer sports than the card contains is a FAILED update — say so and
  complete it.
- "No new information" is a valid entry per sport, stated explicitly — silence is not.
- Timestamp every update in ET **and** PDT (owner is Pacific).
- Sources: live web pull (scores/odds/news), graded IDENTIFIED_UNCONFIRMED per the freshness
  contract; never injected into frozen forecasts — valuation and audit layers only.
- The ledger only moves on bindable ids (real ESPN/gamePk joins).

## First application
2026-08-29 late-night refresh — see cards/2026-08-29_final_results.md.
