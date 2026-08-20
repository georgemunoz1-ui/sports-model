# Operating Charter — governed sports-forecasting pipeline

Status: clauses through "1. DECISION" are OWNER VERBATIM (received 2026-08-20T00:0xZ).
The remainder of OUTPUT was truncated in transmission; the completion below is drafted
faithfully to the system as built and is PENDING OWNER RATIFICATION.

## GOAL
Produce accurate, prospective, gradeable forecasts and a separate, readable
betting-decision card.

## EVIDENCE
- Forecast probabilities must exist before market prices are consulted.
- Market prices are downstream screening inputs only.
- Never invent, reconstruct from memory, or silently repair a number.
- Every reported number must be read from a tool-produced artifact in the
  current turn and retain its source or artifact binding.
- Source pixels/bytes govern conflicting prose transcriptions.
- Missing information remains null and receives a reason code.

## IMMUTABILITY
- Never alter a registered forecast.
- Material input changes create a new cohort.
- Grade each registered estimand exactly once.
- Keep winner, spread, total, and prop records separate.

## DECISION POLICY
- A theoretical edge is not automatically a bet.
- Apply validation, uncertainty, compression, personnel, and data-quality gates.
- If any required gate fails, final action must be PASS or BLOCKED.
- Never portray WATCH, diagnostic output, or positive EV as an approved wager.
- Do not use market disagreement alone as evidence that the model is sharp.

## OUTPUT
Return two distinct sections:

1. DECISION
   - Written for a bettor, plain English only.
   - One row per game: game and start time; predicted winner named with both
     teams' win probabilities; team-labeled projected score; best screened
     price explicitly marked as a screen; best total read bound to its exact
     line; plain-English trust label; explicit final action
     (BET / WATCH / PASS / BLOCKED); one-sentence reason.
   - Sections in order: qualified bets, watchlist, passes, blocked.
   - While wager authority is NO, lead with:
     "Official betting output: NO QUALIFIED BETS" — and BET is unrenderable.
   - No internal identifiers, no bare "home/away" probabilities, no
     probabilities detached from their lines, no screens dressed as picks.

2. AUDIT
   - The technical appendix: probabilities as registered, per-side EV
     calculations, artifact hashes and vintages, gate results (compression,
     totals certification, render gate), internal statuses, cohort identities,
     correction and incident references, and standing authority state
     (gate progress, ledger, wager authority, execution).
   - Every number carries its artifact binding. Nothing in AUDIT is ever
     presented as actionable; nothing in DECISION is ever unsupported by AUDIT.

## ENFORCEMENT MAP (informative)
- EVIDENCE: forecast-before-price = registration practice + input_vintage bindings;
  no invented numbers = R1 + lesson 02 (report-layer binding, totals incident);
  pixels govern = lesson 01 (SD sign correction); null+reason = R1 intake convention.
- IMMUTABILITY: O_EXCL card writes + artifact_immutability gate; starter forks =
  lesson 05; graded-once = grade_slate guard; estimand separation =
  settlement_contract gate (cutoff 2026-08-19T05:00Z).
- DECISION POLICY: unified_card.classify + compression gate (frozen >= 5pp) +
  LCB screen + personnel/data-quality blocks; QUALIFIED unreachable without a
  forward-validated edge class; market-disagreement humility = lesson 07.
- OUTPUT: harness/decision_card.py render gate (six refusal conditions + BET
  impossible while authority NO), selftested and healthcheck-wired.
