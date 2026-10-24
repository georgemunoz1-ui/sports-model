# Margin integration review — October 21, 2026

This is a settlement/API integration, not a predictive model selection. Keep the
existing selected defaults. Retain the NFL predictive HOLD, frozen forecasts,
research-only restrictions and action authority OFF. Neither original PR is
merged, closed or promoted by this work.

## Reviewed source identities

| Source | Pinned revision |
|---|---|
| Current main, including disclosure PR #72 | `90daf8e0036c67a5304aa0747bf50b2266e0b364` |
| PR #69, draft | `79b92e2fd7e0e16ca2bcb2ee8c6c137f20a0fb27` |
| PR #70, open | `37cfcf048a8f1ff6860ad49b8098160b07646364` |
| Shared prior base | `7cf2aea0581b4048802c920c9670823fab21679e` |

Fetched metadata and source were checked on October 21. Source files restored
locally were verified against Git blob identities. `tests/fixtures/margin_integration/sources.json`
pins the precise inputs used in the repeatable comparison; it is not an independent
attestation of historical sports-data availability.

## Component decisions

| Component | Decision | Reason |
|---|---|---|
| Main `discrete_research` artifact, five-state settlement and hashing | Retain as canonical settlement engine | Already present on main; #69 delegates to it, as do the disclosure contracts. |
| #69 summaries, predictive intervals, retained simulations, dense PMF representations | Retain in #69; consume existing PMFs through the bridge | Useful capabilities; importing the entire fitter/runner is unnecessary for contract interoperability. |
| #69 fitted residual/Student-t, fitted lattice and selected-QB child | Keep separate under existing identities and HOLD | Fitting, chronology, predictive evidence and runtime configuration must remain bound together. No refit or code-hash resealing here. |
| #70 CDF/push/sample protocol | Consolidate as a read interface over an existing source-bound PMF | Makes the same law consumable by both APIs without changing any mass or fitted mean. |
| #70 normal, empirical and simulated constructors | Keep as separate research construction methods | Continuous normal lacks integer push mass; empirical support and floating/integer handling have distinct contracts. No silent conversion or replacement of a fitted law. |
| #70 football key-number boosts | Exclude from integration | Unfitted defaults shift the mean; no source-fitted evidence justifies adopting them. |
| #70 sigma estimator and per-sport adapters | Keep separate pending stronger lineage/settlement binding | OOF flags/windows alone do not verify per-row source chronology; selected-arm token matching is weaker than an exact source/parent binding. |
| #70 validation harness | Retain independently for development; do not combine its scores with #69 | Requires explicit probability basis on push-excluded scoring and contract-matched records before comparisons are meaningful. |
| MLS 1X2-only adapter | Preserve its refusal | Availability of an explicit regulation margin PMF is a different capability from 1X2-only inputs. |
| #72 disclosures and current NFL/shared runners | Retain unchanged | Avoids dropping disclosure arguments, sidecars or partial-failure reporting. |

## Implemented scope

`models/common/margin_contract.py` is one opt-in compatibility module. It requires
an existing hash-validated discrete margin artifact plus matching event, cutoff
and source hash. It snapshots rather than mutates the input and preserves its
distribution identity. It exposes the #70-style CDF, point mass and explicit-seed
sampling interface. Sampling does not replace the original saved simulation.

Pricing delegates to main's existing settlement engine. The new record names
the selected side, home handicap, selected-side handicap, exact settlement,
distribution/source identities and all five unconditional settlement states.
Non-split quotes additionally expose a clearly labeled conditional non-push
probability; all-push and split-handicap quotes leave that value unavailable.
Semantic validation recomputes the quote from the bound law, so rehashing an
altered side, contract, probability basis or authority flag does not validate it.

No import from this module is added to a daily runner. No defaults, runtime
configurations, model coefficients, fitted artifacts, ledgers or forecast files
change. It does not accept winner-only probabilities, guessed sigma values, raw
unfitted key-number tables, or an arbitrary unscoped CDF as a pricing input.
Its source binding is a consistency check, not independent source authentication.
Historical timing limits in source provenance remain visible in every quote.

```python
from models.common.margin_contract import bind_margin, cover_quote

view = bind_margin(distribution, event_id=event_id, cutoff=cutoff,
                   source_field="parent_forecast_sha256",
                   source_sha256=parent_forecast_sha256)
home = cover_quote(view, -3.0)
away = cover_quote(view, -3.0, orientation="away")  # away +3
```

This is a new record schema, not a silent rewrite of #70's quote records or #69's
frozen reports. Downstream evaluation must explicitly select the matching basis.

## Settlement and evaluation incompatibilities

1. **Orientation:** both branches intend `M = home - away`, home covers when
   `M + home_handicap > 0`. However #70's `CoverQuote` and emitted record do not
   retain the selected side. At a symmetric zero line, home and away quotes emit
   identical records, including hashes. The bridge includes the side in its identity.
2. **Pushes:** #70 normal distributions are continuous; integer-normal, football
   and integer-draw distributions have mass at whole-number lines. Those are
   different predictions, not interchangeable encodings. A half line has no push
   only for integer-supported score margins. The bridge requires that support.
3. **MLS:** #69/main use regulation 90 minutes plus stoppage and five outcomes.
   Home -0.25 splits home 0 and -0.5: a draw is a half loss. #70's MLS adapter
   correctly refuses its own spread product, but its generic `cover_quote` accepts
   -0.25 and returns a binary full loss on the same draw. Never bypass the adapter
   refusal by handing quarter lines to that generic API. The bridge needs an
   explicit MLS margin PMF and retains half outcomes.
4. **Push-excluded evaluation:** #70's harness drops realized pushes and scores
   `p_cover` directly; it neither requires nor converts an ex-push basis. With
   win/push/loss probabilities .4/.2/.4 and one win, one loss and one push, it
   reports .26 Brier on the two non-push games. Conditional .5/.5 scoring gives
   .25. Either score full settlement states on all games or use conditional
   probabilities with explicit denominators. Do not compare these outputs until
   the basis is fixed and versioned. The existing harness is not changed here.
5. **Football key numbers:** #70 default boosts at sigma 13.5 change input mean
   -7 to -6.6215435164 and -14 to -13.4247284556, with mirrored positive shifts.
   They are placeholders, not fitted adjustments or mean-preserving transforms.
   #69 fits lattice/tail parameters under its own chronology and identity; these
   cannot be substituted without changing the model and invalidating evidence.
6. **Final-score scope:** regulation, NFL regular-season/postseason OT, NHL
   OT/shootout plus-one, and MLB extra-innings rules must remain explicit.
   #70's generic protocol carries no settlement scope; basketball/NHL integer
   normals may assign final tie mass unless a separate contract prevents it.
   Main rejects illegal tied final outcomes; this bridge never silently conditions
   those outcomes away. Existing no-tie conditioning in #69 stays disclosed and
   is not a mechanistic OT/shootout model.

## NFL disclosure integration risk

A three-way merge of main/#69 against their shared prior base reproduces a
conflict in `scripts/run_nfl_integrated.py`, at argparse/configuration setup.
Taking #69's entire file would remove `--disclosures`, its pregame/event guard,
sidecar creation and disclosure error propagation. Taking main's entire file
would remove #69's margin option and child handling. #70 changes neither runner.

The minimal integration changes neither file nor runtime configuration. The
current disclosure tests exercise the actual shared all-seven runner and separate
NFL runner. They check source/parent hashes, immutable outputs and probability
preservation. This establishes compatibility for **this opt-in bridge**, not a
claim that the full #69 branch is merge-ready. A later #69 runner integration must
resolve both options, ordering and failure paths together, then test margin-child
success/failure with disclosures enabled, with original config/code hashes valid.

## Executed evidence and limits

- 162 identical-draw contract/side cases across all seven sports and nine exact
  settlement scopes: #69, #70 and the bridge agree within absolute `1e-12` on
  compatible integer/half lines. Source hashes, events and cutoffs are identical.
- 26 same-law comparisons from the retained `2026_06_WAS_SF` reconstruction:
  #69 reporting, #70's original CDF quote API and the bridge agree at `1e-12`.
  The frozen law, key-number masses and its identity remain unchanged. Its source
  explicitly says the fit/config did not exist at the original parent cutoff.
  This is retrospective software evidence, not a newly registered forecast.
- 215 focused tests and 56 subtests passed locally, covering orientation, pushes,
  MLS quarter states, invalid final ties, source mismatches, tampering, actual
  runner disclosure integration and selected-default regressions.
- The copied NFL source decision remains HOLD: 816 later-period games; CRPS
  challenger minus baseline -0.0079080906, 95% interval
  [-0.0226643311, +0.0113019390]. These are preserved #69 results, not a fresh
  evaluation or a comparison against #70. The separately refitted all-history
  artifact remains distinct and not directly held-out evaluated.
- Local restoration is partial: health is RED with missing unrelated modules/data.
  Its failure count cannot be compared to a complete-checkout health result.
  Existing global release, storage and predictive gates are not cleared by these
  tests. Full clean-checkout CI and artifact delivery remain separate checks.

Reproduce with pinned source checkouts:

```sh
python -m pytest tests/test_margin_contract.py tests/test_card_disclosures.py tests/test_cross_sport_distributions.py tests/test_model_defaults.py -q
python scripts/audit_margin_integration.py --pr69-source /path/to/pinned69 --pr70-source /path/to/pinned70 --output NEW.json
```

The audit checks source hashes before importing either implementation, writes a
new file exclusively and cannot overwrite previous evidence. The dedicated
workflow runs on the exact candidate head, checks both pinned PR sources and
records the comparison digest. Existing repository CI remains enabled.

**Disposition:** engineering contract tests passed locally; no new predictive
validation; selected-QB predictive HOLD preserved; publication INELIGIBLE;
wagering OFF. This review does not authorize merging or promoting any branch.
