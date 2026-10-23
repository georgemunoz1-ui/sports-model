# Efficiency experiment evidence contracts

`integrity.py` is shared by the independent CFB and NBA research experiments.
It changes no existing model, canonical forecast, registry, ledger or authority.

## Component receipts

`build_component_receipt` binds the exact model/stage/event, event start and
forecast cutoff, retained input/state/config/forecast JSON, code file hashes,
source digests and the numerical inference components. Numeric components are
marked `USED` only in this runner-reported inference trace; this is not external
execution attestation. Optional component `input_paths` must exist in the retained
input snapshot, source references must belong to the source set, and declared
maximum feature/label availability cannot be after the cutoff. Unsupported score
heads remain null and are disclosed in `unsupported_forecast_fields`.

All timestamps must include a timezone. A source with a `path` is verified against
its bytes; a pathless source explicitly reports `bytes_verified=false`. A runner
may separately verify a large source manifest once and bind that run-level proof.
Checksums do not authenticate source truth. Historical later retrieval is allowed
only with retrospective labeling and an explicit unverified availability status;
it is never backdated. Claiming an earlier historical availability time requires
an accompanying evidence digest and remains an unauthenticated claim here.

Simulation metadata requires the actual integer count/seed, RNG, distribution
identity, encoding and array digest. If `draws_path` and `draws_file_sha256` are
provided, the stored NumPy array is loaded without pickle and its finite values,
draw count and array/file digests are checked. Otherwise the receipt explicitly
reports metadata-only verification; it does not certify actual draw execution.

## Local prospective SHADOW

`write_shadow_receipt` accepts only a SHADOW receipt. The writer owns its actual
registration clock and revalidates serialized semantics, byte bindings and
source chronology before writing. Retrieval and provider observation must precede
the cutoff; cutoff <= creation <= registration < start. A late replay cannot
enter this cohort. First-write event/model/stage identity is exclusive, and an
existing forecast cannot be replaced or silently refreshed. Components are saved
through the existing content-addressed ArtifactStore; registration uses the
existing lock primitive and an exclusive write. Descendant symlink paths reject.

Status is `LOCAL_PROSPECTIVE_SHADOW_LOGGED`. External timestamp verification,
canonical prospective eligibility, publication and action authority are false.
An independent durable GitHub or other timestamp receipt may anchor the log
separately; this module does not mint signing keys or trusted external witnesses.

## Source reconciliation

- Stable IDs and verified aliases resolve only within the event's two teams.
  Duplicate IDs, ambiguous aliases and ID/name contradictions quarantine.
- Conflicting source values remain explicit; record order or provider priority
  never selects a winner automatically.
- NBA totals reconcile made/attempted shooting and points. A provided player table
  must reconcile points, minutes and available player rebound sums. DNP production,
  missing rows, duplicate players, nonfinite values and invalid counts quarantine.
- Player ORB/DRB exclude uncredited team rebounds; separate `team_orb/team_drb`
  fields prevent double counting. Unknown rebound conventions quarantine.
- Minutes precision is explicit: one decimal by default, or zero for integer-
  rounded ESPN values. Sum tolerance is half the displayed unit per player.
  Regulation is 240 player-minutes; each declared overtime adds 25.
- A zero/missing denominator is unavailable, not an observed zero rate. EPA can
  use signed numerators through the explicit `bounded=false` rate contract.

Synthetic tests establish software behavior only. Actual retained-provider
reconciliation is reported separately by the acquisition/run artifacts.
