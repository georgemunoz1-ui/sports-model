# Real Week 3 research state

This extends the independent PR42 repair. It imports no PR38 implementation and
does not change fitted coefficients, default selection or ensemble promotion.

Fresh capture succeeded on September 22 for all seven leagues. NFL now has all
32 Week 1–2 finals and PBP. The original bytes still fail safely: schedule
`2026_02_CAR_ATL` names `00-0036212` (Tagovailoa), whereas PBP identifies Rush
and Strand. HEAD and existing objects remain unchanged after refusal.

The retained ESPN box score and AP recap identify Rush as the fill-in starter
and Tagovailoa as inactive. A separately reviewed correction binds that exact
event, team, final score, source hash, player crosswalk and first QB play. The
review is in `data/nfl/starter_adjudications_20260922/review.json`. The correction
must be included when constructing a **new seed**, whose ID is retained outside
forecast packets. Existing chains and original source bytes are not edited.
Changes to the upstream starter assignment require another reviewed rebuild.
This is research source adjudication, not official gamebook clearance.

The revised chain advances through Week 2, replays both transitions and verifies
identical retries. The next-week package derives team features from that chain,
retains source schedule QB assignments as unconfirmed, and leaves weather and
injury reports missing. It never turns missing information into healthy status.
The canonical command uses the existing selected QB arm. Its 100,000-draw winner
diagnostic does not become a score simulator; the failed combined arm stays
diagnostic. No wagering or official release is enabled.

## Reproduce

Download historical seed artifact `10525312986` and current source artifact
`10682535981` from this repository. Verify the archive hashes shown in
`.github/workflows/all-model-operations.yml`, then extract them as `frozen/` and
`sources/`. Run from the repository with the consolidated requirements installed:

```bash
python scripts/verify_nfl_current_acceptance.py \
  --frozen frozen --capture sources --output current-acceptance
```

This checks the original refusal, creates a distinct corrected chain, prepares
all 16 Week 3 events, runs the actual CLI for each slate date, and checks selected
model, weekly-state consumption, 32 consumed games and simulation count. Source
freshness and pregame gates remain enforced: this is a time-bounded acceptance,
not an evergreen retrospective forecast. Refresh sources and review corrections
when freshness expires. Artifacts retain state objects, source bytes, forecasts,
draws and manifests. The historical repair replay remains a separate test.

## Seven-league operational boundary

397 unit/research tests pass. This does not establish all-seven current operation.

| League | Verified state of this repair | Remaining current-path work |
| --- | --- | --- |
| NFL | Real Week 2 state and Week 3 consumption acceptance | Confirm current QBs and acquire weather/injury/inactive reports for richer context |
| MLB | Tested incumbent and current producer exist; fresh source acquisition succeeds | Bind fresh starter logs and complete team form into the current adapter package |
| WNBA | Frozen validated baseline; 22 additional regular-season box scores parse | Reconcile extension provenance, preserve replacement identity, wire a selected-model adapter with genuine simulation semantics |
| CFB | Frozen validated baseline; fresh schedules/results captured | Replace the shared candidate adapter with the selected incumbent and validate current chronological feature state |
| NBA | Schedule source captured with zero events in this window | No verified fitted default recovered |
| NHL | Fresh schedule captured, mostly preseason | No verified fitted default recovered |
| MLS | Fresh schedule captured | No verified fitted default recovered |

Repository health still has four historical failures: missing production archive,
overdue recovery jobs, immutable September 3 release rejection and overdue
standing-health evidence. None is cleared by relabeling. No claim that every
model is operational is justified by this repair.


## Subsequent all-league completion

The boundary table above records PR43's scope at publication. PR44 subsequently
implements and validates the missing current MLB/WNBA/CFB runtimes and explicit
initial NBA/NHL/MLS research models. See
[ALL_MODELS_CURRENT_RUNTIME](ALL_MODELS_CURRENT_RUNTIME.md) and the all-seven
acceptance artifact for current operational evidence. The NFL runtime config also
now names the selected QB arm directly, removing the stale combined-arm fallback.
Historical health incidents and model verdicts in the earlier section are preserved.
