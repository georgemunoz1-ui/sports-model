# Independent validation audit — 2026-07-28 (two rounds, read-only)

Audit of the KSIM-0727-U02 work and its follow-ons, conducted read-only against primary artifacts,
historical git blobs, and reproducible computation. The audited narrative was treated as untrusted
claims throughout. This file records the final (round-2) state; round-1 statuses that round 2
revised are shown struck through in prose, not deleted.

## Verdict: PASS_WITH_CORRECTIONS — one procedural deficiency

Every deterministic quantity reproduced from primary artifacts. Frozen artifacts intact and matching
their historical blobs. Zero numeric errors found. **One procedural deficiency:** a capture that
failed a mandatory pre-registered evidence requirement (C5 item 5, visible slate date) was labelled
"first qualifying Phase-2A capture" (commit subject of `7efb9b9`) and its four decisions labelled
executable pending owner adjudication — when the frozen text leaves nothing to adjudicate.
Containment held: the decisions never touched a ledger or the gate, were hashed pre-outcome, and the
deficiency was self-reported rather than argued away.

## Disposition of the four U02 decisions (Alvarez, Peterson, Imai, Perkins)

**NONQUALIFYING as Class-B executable captures. Retained as `EVIDENCE_DEFICIENT_SHADOW` only.**
Permanently barred from the prospective ledger and gate for this slate. Frozen-rule basis:

1. **C5** (protocol §C5): "All six, visible in the image itself, not supplied alongside it" — item 5,
   game or slate date. The K-board image fails item 5 (date control cropped; confirmed on re-read).
   Slate-match corroboration and companion images are what "not supplied alongside it" excludes.
2. **C4**: Class B's requirement is "a complete same-book quote in one image"; completeness of
   screenshot evidence is defined by C5, so C8's "may support a prospective executable decision" is
   never reached.
3. **D2** (expressio unius): the protocol built exactly one degraded path for a failed C5 item —
   item 6, `MAIN_LINE_UNRESOLVED` — and none for item 5. The omission is a decision, not a gap.
4. **D3/E2**: the amendment window closed at `af12e52` (2026-07-27T04:28:30Z), **twelve hours before
   U02 arrived** (16:38:58Z). E2 defers post-closure discoveries to the next untouched slate. An
   owner cannot retroactively waive a pre-registered evidence requirement after the slate begins.
5. **D1-R**: timing alone holds — `received_at_utc` precedes every first pitch — hence the split:
   TIMING_ELIGIBLE **23/23** · EVIDENCE_COMPLETE **NO** · CLASS_B_QUALIFIED **FALSE**.

Alternative reading (C4's requirement column alone defines Class B) considered and rejected: C5's
title is "What a screenshot **must** visibly establish"; U01 was killed on exactly the date guard;
E2 itself applies the same standard in stating no qualifying capture existed.

## Findings, final severities

- **HIGH — capture qualification.** As above. Commit-subject label "first qualifying Phase-2A
  capture" is CONTRADICTED; superseded by the classification sidecar (immutable commit message, so a
  superseding record, not a rewrite).
- **MEDIUM — T1 overstatement.** "A misread digit would almost certainly have broken one" is
  demonstrated false: +124 misread as +134 passes T1 at 4.1% hold, and T1 does not constrain line
  values at all (the line never enters the hold formula). T1 validates only broad two-sided price
  coherence; it detects some gross price errors and cannot establish digit-perfect transcription.
- **MEDIUM — no independent reader.** Transcription status is `REPRODUCED_BY_CORRELATED_READER`:
  the image is primary evidence, but original extraction, T4, and the audit re-read were all
  performed by the same model family. A human or genuinely independent extraction can strengthen
  confidence; it cannot repair the missing-date requirement.
- **MEDIUM — timing is internally evidenced only.** A signed commit binds its claimed committer
  timestamp; it does not attest it against a trusted clock, and an SSH signature is not a
  timestamping service. Upload mtime, `frozen_utc` and committer time all derive from the same
  container clock. No remote received any commit before first pitch (the only push occurred
  2026-07-28, post-slate). Pre-first-pitch existence is therefore `INTERNALLY_CONSISTENT_ONLY`.
  Independent timing would require a pregame remote receipt, trusted server log, or transparency
  timestamp.
- **LOW — "essentially unbiased" withdrawn.** Bias is an expectation over repeated samples relative
  to truth. The supportable statement: on this single slate, the mean difference between model E[K]
  and the constructed market-implied λ was near zero (+0.013 proportional de-vig; +0.023 power
  de-vig; mean|diff| 0.416 K; n=23; construction-dependent; exploratory).

## What was independently reproduced

Selector rerun (4/23, identical prices/EV/edges) · T1 recompute (110 pairs, 0 out of tolerance) ·
market-λ statistics under two de-vig methods · dispersion identity and moments · DQ-freeze timing
(11 of 12 games underway at 01:40:27Z; only MIL@SF, −4.5 min, not started) · close_* scope (30 rows,
7/24–7/25 only) · log widths on disk {7,10} · Verifier A (frozen lineage, from git blobs at
`6d4a7c0`) · Verifier B (unrounded E[K] bit-identical 23/23; fixtures; malformed widths raise) ·
full HFA 2×2 factorial + noise floor + pre-fix order-dependence from the historical blob (two
identical calls: 0.2402 vs 0.2408) · E6 derivations · signature validity on all commits with a
pinned signer and a wrong-key negative control · falsifiability by in-memory injection of the gate,
placeholder, T1, and selector checks.

## Unverifiable from this environment

GitHub's verification verdict · screenshot capture times · book attribution beyond
`AGGREGATOR_DISPLAYED` · SO/TBF accuracy on the 8 placeholder rows · signing-key identity (TOFU
pin) · 2026-07-27 game outcomes (none in repo; none asserted).

## Corrections authorized 2026-07-28 and implemented in the same commit as this file

1. Sidecar `KSIM-0727-U02_transcription_audit_addendum.json` (T1 limits, correlated-reader caveat).
2. Sidecar `KSIM-0727-U02_capture_CLASSIFICATION.json` (EVIDENCE_DEFICIENT_SHADOW reclassification).
3. Findings-doc banner + the two authorized sentence replacements.
4. `state.json` known-issues append (label defect + reclassification).

No frozen artifact was edited. The frozen transcription JSON, DQ tags, decision set and Phase-1
artifact retain their published hashes.
