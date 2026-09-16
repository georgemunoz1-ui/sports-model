# ML-P3 CANDIDATE FREEZE — written BEFORE the holdout is opened

**Candidate: `d_logistic_2f`** — the pre-registered 2-feature logistic, the only model satisfying
the frozen P2 decision rule (pooled dev: Brier 0.2460 < b 0.2500 and c 0.2496; not worse than a
0.2486; calibration intercept −0.004, slope 1.069).

**Ablation route produced no candidate:** A1 (HFA 1.03) ΔBrier −0.000546 ± SE 0.000355 — noise-
compatible, CLOSED, HFA remains UNRESOLVED and unchanged. A2 (per-pitcher IP prior) ΔBrier
+0.000297 ± 0.00027 — worse, CLOSED.

**Disclosed wording tension in the prereg:** the candidate-freeze paragraph described candidates as
"(a) plus improving ablations," while the P2 decision rule independently defines qualifying models
as "P3 candidate input." The (a)-family route is empty; (d) qualifies under the decision rule. This
freeze proceeds under the decision rule and flags the ambiguity instead of resolving it silently.
If the owner rejects this reading, the holdout result for (d) is void and the seal was spent.

**Frozen configuration (no refit on holdout):**
- beta = [0.097249, 0.049057, 0.210657]  (b0, b1, b2), trained on n=1111 rows < 2026-06-29
- config sha256 = 132523ac86695b851fd8e4c88815da0416a79421e76ba0cce1c9bce24dfe096b
- references scored alongside, for context only: (a) v13 p2eval HFA 1.005 (holdout RNG stream
  9_000_000+idx, disclosed), (b) 0.500, (c) train base rate = 0.523
- The holdout (2026-06-29..2026-07-19) opens ONCE, now. Its verdict is FINAL for this candidate.
  No promotion regardless: ML stays NO_PROMOTE; Phase 4 forward validation would be a separate
  authorization.
