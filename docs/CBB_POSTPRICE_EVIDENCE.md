# CBB post-price incident evidence

The append-only sidecar assesses the baseline away spread on each CBB fixture.
An evaluable row can be flagged or unflagged. An unevaluable row carries an
evidence reason and a null incident label. Every row retains NO_PICK and zero units.

```sh
python -m pipelines.cards.cbb_incident priced-card.json new-review.json \
  --evidence-root /path/to/unpacked-replay \
  --manifest-sha256 "$trusted_manifest_sha256"
```

Obtain the manifest pin from an independently retained digest or a previously
pinned archive. Computing a fresh pin over supplied, untrusted files does not
authenticate them. The card bytes must match a delivered entry in SHA256SUMS.txt.
The freeze binds the policy, census and CBB schedule identity. The original
verification.json binds the priced-card hash and verification instant. The
market/raw directory must contain the retained ESPN payload and HTTP receipt for
each offered event. The verifier currently supports the ESPN DraftKings Game Odds
full-game CBB spread including overtime.

Declare a timezone-aware `quote_cutoff_utc` in evaluation-protocol.json before
the forecast seal. The cutoff is inclusive. Both sides must have the same
retrieval instant, strictly before the agreed schedule tip and no later than
original verification. For this freeze-first protocol the interval from request
to retrieval must begin at or after the seal. An absent vendor observation time
yields retrieval-only evidence. A verified stored receipt establishes what was
retrieved at that instant. The book's posting time requires separate evidence.

A card-only invocation retains coverage with unevaluable rows. The November 6
historical protocol did not declare the additional cutoff. The last observed
retrieval is ineligible as a substitute. Preserve the original card and label
any historical reproduction of its counts with the rule used.
