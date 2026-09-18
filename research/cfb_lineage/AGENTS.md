# CFB point-in-time lineage contract

Keep CFB separate from NFL data, weights, calibration, and promotion decisions.
NFL PR39 remains an unmerged research challenger; do not change defaults here.

Use four linked definition/observation/model-path/evaluation tables and an
immutable artifact graph. A feature list is not evidence of observed or useful
features. Every active numerical feature must link its exact source bytes,
identity, source family, source-model generation, definition/transform version,
units, signs, denominators, actual availability, model and evaluation path.

Legacy cfbfastR and ESPN-derived PBP are different families. Never substitute one
under the other's feature ID. Pin upstream EPA/WPA model generation and rule-era
contracts as well as package and raw-data versions. Missing upstream model
lineage blocks pregame use even if the row has a finite EPA value.

Register a provider-bound full schedule before state updates. Reject truncated
requests, extra-week PBP, duplicates, revisions needing reconciliation, ambiguous
identities, bad units, future sources, and unexplained missingness. FBS/FCS remains
blocked. Research accumulators and synthetic tests are not predictive learning.

Each state transition is parent-bound and exactly once within its local lineage.
A later real forecast must demonstrate consumption; synthetic graph validation
does not meet that acceptance condition. Require atomic publication and real
process exit codes; a green workflow alone is not evidence.

Do not invent rating-week filters, confuse ordinal rank and rating scale, or
subtract defensive EPA allowed while calling the result universally home-favorable.
Higher opposing EPA allowed is easier for an offense. Keep market fields out of
football-only features; no market imputation.

Do not force nonzero coefficients or weights. Fit preprocessing, weights and
calibration only in appropriate historical folds; predeclare metric/promotion
rules and retain failed experiments. No model or feature is promoted from these
infrastructure tests. Explanations consume frozen outputs and cannot alter them.

DVC and MLflow are provenance tools, not source-authorship, historical-publication,
remote-backup, or model-accuracy attestations. Report their actual execution scope.
ACTION OFF; dose 0.0. No merges, default changes, or historical artifact rewrites.
