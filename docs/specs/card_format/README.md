# Card Format Specs — Decision-State Card Formatter

Owner-supplied formatter specifications, adopted 2026-08-30. Stored verbatim (CRLF→LF normalization per repo convention; content otherwise byte-identical, disclosed).

## Documents
- `decision_state_card_formatter.md` — strict 3-market schema: exactly three independent market records per game (ML / SPREAD_RL / TOTALS), NO_LINE explicit for missing markets, JSON canonical with the table generated from it, decision precedence NO_FORECAST/BLOCKED > CLV_ONLY > WAIT > PASS > LEAN > PLAY, formatter never recalculates probabilities.
- `market_specific_probabilities.md` — market-specific probability fields: ML=model_win_pct, SPREAD_RL=model_cover_pct, TOTALS=model_over_pct/model_under_pct, push_pct semantics (0.0 on half-point lines), no-vig market probabilities only, edges in percentage points.
- `v5_review_notes.md` — owner review of the V5 implementation: signal_decision vs execution_status separation (LEAN + NO_PRICE), clock semantics (entry_snapshot_cutoff vs decision_time), movement.market qualification, source-status flags (line/price/probability/source_available, actionable/clv_eligible/roi_eligible), extended validation battery.

## Implementations (lineage, append-only)
- V4 (`cards/2026-08-30_pregame_board_v4.md` + `_v4_canonical.json`) — first 3-market implementation; lineage-complete.
- V5 (`_v5.md` + `_v5_canonical.json`) — market-specific probability fields.
- V6 (`_v6.md` + `_v6_canonical.json`) — **current**: signal/execution separation, movement.market, source-status flags; extended validation clean.

## Integrity note
Interactive card version ids (e.g. 5506e0b) are presentation references only — never a substitute for immutable git commit/blob SHAs. The SHA is the artifact-integrity check.
