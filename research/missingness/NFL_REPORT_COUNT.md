# NFL report-count support experiment

The frozen design in `nfl_report_count_design.json` was committed at
`aa938cf` before evaluation. The registered availability and combined variants change
only `report_missing_count` to the nearest supported boundary in its original units.
Official injury reports, imputation of other variables and all fitted coefficients remain
the incumbent's. An input of two missing reports remains documented as two even when
the candidate's numeric value is one. This diagnostic does not imply either team
supplied a report, or that either team had zero injuries.

From this repository, with its NFL dependencies, run

```sh
OPENBLAS_NUM_THREADS=1 python -m research.missingness.nfl_report_count \
  --archive /path/to/nfl_20260914_integrated_context_report.zip --output NEW_DIR
```

The archive and CSV digests must match the original acquisition record. Optionally
add repeated `--forecast PATH SHA256` arguments for frozen development illustrations.
The tool refits both incumbent arms using only earlier seasons for each fold,
reproduces the stored per-game predictions and compares the same heads on the same
test games. Winner Brier and log loss exclude tied finals. Margin is home minus away
and signed error is actual minus predicted. This experiment produces point heads and
a decisive winner probability. It does not issue a replacement card or a priced
spread or total distribution.

The November 8 replay covered 1,871 distinct games over seven held-out seasons
(2019 through 2025), including 1,865 decisive games. No held-out observation fell
outside its own prior-season fit support. The 2015–2025 deployment fit had 2,877
observations with both reports, eight missing one and zero missing both. Historical
reports have incomplete pregame timestamp evidence. No numerical accuracy advantage
or safe production threshold was established. Retain the incumbent and continue with
untouched, source-bound forward monitoring before considering release.
