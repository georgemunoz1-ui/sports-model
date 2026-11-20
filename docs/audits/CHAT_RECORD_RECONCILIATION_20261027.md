# October 24–26 chat-record reconciliation

Reviewed October 27, 2026. Repository reference: `8003043ac97783b03e8e21c345d61dab1996ac50`.

This append-only record corrects contradictory chat claims. It does not overwrite original forecasts, establish predictive qualification, or deploy a model. The user's request was to correct unreliable prior work; the model tier that served a prior response was not independently established.

## Date and artifact identity

| Event slate | Evidence recovered | Correct interpretation |
|---|---|---|
| October 24 | 64 games: 44 CFB, 8 NBA, 12 NHL; 296 contract sides | The CFB card is present in the chat. A review delivered October 25 does not change its October 24 event date. |
| October 25 | 25 games: 12 NFL, 7 NBA, 5 NHL, 1 MLS; 151 priced contract sides | The original card was generated. The initial NFL failure was followed by successful source-reviewed run `40185798574`. |
| October 26 | 9 NBA and 3 NHL winner forecasts; NFL blocked | Retrospective backfill from run `40428832980`, generated after the slate began. Nine of the 12 events had started; no prospective re-registration. |

The October 25 CFB schedule receipt returned zero matching events while `authoritative_complete_census_verified=false` and `no_games_verified=false`. It was a scope-only acquisition, not CFB inference. Do not assert an authoritative empty slate from that receipt, erase the earlier CFB card, or relabel October 24 games as October 25 forecasts.

## October 25: the previously omitted spread/total breakdown

The original `October-25-2026-Now-Card.json` contains 151 priced sides. It is incorrect to say prices/spreads were unavailable for all historical grading. All 25 final outcomes were rejoined to retained provider snapshots using original provider event IDs, teams and kickoff; NFL's LA/LAR alias required its original schedule crosswalk.

The following is the original displayed higher-probability side at each captured market, with ONE HYPOTHETICAL unit risked per contract, before unverified fees. It is not a wager recommendation, an authenticated account return, or 75 independent games.

| League | ML | Spread / puck line | Totals | Combined | Hypothetical net |
|---|---:|---:|---:|---:|---:|
| NFL | 7–5 | 6–6 | 7–5 | 20–16 | -0.134699u |
| NBA | 4–3 | 5–2 | 6–1 | 15–6 | +6.096566u |
| NHL | 4–1 | 5–0 | 1–4 | 10–5 | +2.729272u |
| MLS | 0–1 | 1–0 | 0–1 | 1–2 | -1.459459u |
| Total | 15–10 | 17–8 | 14–11 | 46–29 | +7.231679u |

Zero pushes. Hypothetical yield is 9.6422% on 75 units risked. The winner-only 15–10 count was correct but incomplete. Both sides of a market were not counted as a betting portfolio. NFL probabilities retain conditional-no-tie scope; none of these actual outcomes tied. The quarantined combined-model NFL totals are included only because this is a reconstruction of what was displayed, not an endorsement.

Binary winner Brier versus the original proportional no-vig market benchmark: NFL 0.268624 vs 0.247682; NBA 0.225219 vs 0.206535; NHL 0.207092 vs 0.219648. These small descriptive samples establish neither superiority nor profitable selection.

## October 24: preserve the corrected control

All 296 contract grades and unit returns reproduce. CFB displayed spreads remain 16–28, zero pushes, -13.556288u. This review rejoined raw final-event evidence for 45 of 64 events, including 25 of 44 CFB games; 19 CFB games retain the earlier stored result records and references, not new source authentication.

17–25 plus two losses is 17–27, not 16–28. A purported 42-to-44 bridge needs a further event-level correction or population difference. Do not infer which event changed from aggregate arithmetic.

## October 26: hidden product incompleteness

| League | Winner forecasts | Margin/total products completed | Unavailable |
|---|---:|---:|---:|
| NBA | 9 | 4 of 18 | 14 |
| NHL | 3 | 2 of 6 | 4 |
| NFL | 0 | 0 | Historical starter/dropback binding |

The 18 unavailable distribution products explicitly report `PARENT_CUTOFF_NOT_PREGAME`. The summary's empty top-level `blockers` failed to expose these product-level failures. A successful Actions job is not proof all forecast products completed.

No target-game IDs appeared in the saved consumed-training/state list, and target scores were absent from the forecast event objects. Nevertheless, provider revisions and original-time availability are unproven. The actual UTC execution date controlled the embargo boundary. This is not proof of the same information set a morning pregame run would have used. All backfill rows remain retrospective research.

`projected_margin` is winner-oriented in the retained runtime; `diagnostics.home_margin` is home-minus-away. Mixing those conventions is a reporting/grading mistake, not by itself evidence that the underlying forecast changed sign incorrectly.

## Mathematical and interpretive claims that remain withdrawn

- Ole Miss/LSU and Golden State/Denver cross-event comparisons were invalid. Correct pairings are Ole Miss–Texas and Golden State–Phoenix.
- A negative standard deviation is not legitimate; taking `abs(sigma)` is not a coherence test. Non-tie ML and no-push spread probabilities condition on different events.
- Two margin thresholds do not identify totals, joint scores or halftime paths. A margin-only artifact cannot generate every betting market.
- A 25% outright winner can have a 64% cover probability by losing narrowly. Validate nesting and support instead of declaring such gaps impossible.
- Houston–Atlanta's mixed 52.39597% ML and 53.18427% -1.5 cover violate nesting when represented as one law. Preserve separate raw heads and block only the combined-law claim.
- The CFB control is translated empirical residual research, not the alleged Gaussian model. Key-number concentration, overall scale and tail thickness are different diagnostics.
- One night's disagreement split and line movement do not prove a profitable small-gap band or that excluding recent results creates information advantage.
- A retained pregame quote versus final score is settlement, not CLV. CLV needs a comparable authenticated closing quote.
- KC +3 raw EV belongs to its price: +25.19% at -115; +22.90% at -120 under unchanged W/P/L and refund-on-push arithmetic.
- Fees affect returns, not cover probabilities. The fixed 2.8% haircut is not a general fee schedule. Historical accepted cost/payout and fee version control; do not double-charge all-in parlay quotes.
- Calibration changes probabilities and therefore creates a separately identified forecast child. It is not merely a payout calculation.
- Synthetic profitability, repeated simulation draws, and task creation do not establish real-market edge, independent game evidence, or independently dispatched agents.
- Zero model allocation does not establish zero personal exposure. Personal P&L requires accepted tickets and settlement receipts.

## Implementation evidence: retain what actually reproduces

The available contract_risk/contract_lab suite was rerun: **91 tests and three subtests passed**. That is local engineering evidence, not full repository acceptance or profitability.

Exact `separation.py`, `tests_separation.py`, `night_audit_20261024.py`, `acceptance.py`, `sports_models.py`, `audit_gate.py`, `joint.py`, and `edge_lab.py` were not found in the available top-level ZIP member listings. This is not proof that no remote/unprovided version exists. Their reported tests cannot inherit the library results. The visible claim of 6/6 implementation tests was later disclaimed and is not accepted evidence.

The retained CFB recovery pairs were independently rescored: **758 paired event rows, 2,274 distributions, 9,102 numerical comparisons, zero mismatches**. On 714 historical evaluation events: F0 CRPS 9.105728; B1 9.105752; B2 9.104913. B2 slightly worsens winner Brier and all three retain ten observed outcomes with zero probability. No new fit was performed; B1 stays on hold and B2 remains research-only. The October 24 rows remain inspected regression data.

## Operations are not certified by this audit

PR #95 was checked and remains open/unmerged. Its own description says preflight-only, not the completed autonomous card pipeline. It neither generates the full model slate nor verifies end-to-end delivery. GitHub scheduled workflows execute from the default branch; a cron file on an unmerged feature branch is not deployment evidence.

Current `docs/CURRENT_STATUS.md` still carries an older review checkpoint. Historical 9F/6W or 55F/4W health counts cannot be treated as a current health run. No global health run, independent-agent execution, main/default change, canonical-ledger write or wagering authorization occurred in this review.

## Reproducibility and preserved failures

The conversation delivery includes executable reconciliation scripts, original artifact hashes, all 151 October 25 grades, the 42-entry claim register, recovery re-scoring, test logs and a formula-driven workbook. The first local reconciliation attempt failed on the Rams–Raiders row lacking `market_raw`; the failure source is preserved. The retry uses the original schedule's exact game ID/provider ID crosswalk and checks teams/kickoff. No prediction or outcome was changed.

1,862 reconciliation/preservation assertions passed. All 92 inventoried original artifact files remained hash-identical. All 447 October 24/25 contract grades were regenerated, but the raw outcome-source authentication limits above remain explicit.

### Input fingerprints

- `October-24-2026-Model-Card.json`: `9f8840e5de82cb8f5312ad63c2cb0e66a9fcc8e9c651938a75b617471c868c7b`
- `October-25-2026-Now-Card.json`: `f675de1403ea0636963e268a5ab94524b72461e8d214dbfa2300f730f38afad0`
- `october26-nba-final-audit.zip`: `fb9414aa90b9fba960868db79a29a60925f6950334a86df6d9ffaf6225e00fef`
- `october26-nhl-final-audit.zip`: `44e60862df2376e6eee3c0e5e1c037a8cf90c1a6282e093f5188b8b160e01b96`
- `CFB-Recovery-Execution-2026-10-25.zip`: `ef57cc3dae56aa79d74883c8c4daa84478bf173385b808b88de5ec9335938206`

This record is not an assertion that every unseen prior message or unavailable source has been verified. Unsupported claims remain unverified, not silently converted into completed work.
