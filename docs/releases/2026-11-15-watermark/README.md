# Consumed-state shadow freeze

The shared seven-league generator now writes an append-only consumed-state review alongside the raw diagnostic. Request a governed artifact with `--freeze-shadow --channel-inventory manifest.json --freeze-journal journal --max-census-age-seconds N`. Use a common persistent journal for all invocations. Supply the capture lag approved for the experiment. Missing evidence produces a refusal receipt and no governed card.

For an existing CBB parent, a native NFL trace, or another supported card format, use the same gate directly.

```sh
python -m research.consumed_state recheck parent.json erratum.json --personnel-events personnel-review-inputs.json --journal journal
python -m research.consumed_state freeze parent.json shadow.json --inventory manifest.json --personnel-events personnel-review-inputs.json --max-census-age-seconds N --journal journal
```

A recheck records new evidence and can invalidate the parent for further card use. A successor requires a newly issued inference with a later cutoff, current census, and an open fixture. The journal serializes concurrent writers and links previous freezes by file digest. Treat the newest applicable review as authoritative for research reuse. This module performs no fit or numerical inference. A scheduler or source producer must invoke the recheck when news or results arrive. No push subscription is deployed.

## Producer contract

The implementation and a complete executable example are in `research/consumed_state.py` and `tests/test_consumed_state.py`. A supported numerical parent has a fixture-bound input snapshot whose digest matches the stored forecast input identity. Each channel contains its read time and the exact normalized records consumed. An empty channel requires an independently captured complete census. Missing coverage yields a null count. Sources must encode revisions under stable IDs. Result records are completed results only. A pending game is a schedule record. Team IDs on a trade include both parties.

The manifest pins separate normalized census files by byte digest for results, rosters, schedule, and quotes for each fixture. Each declares its league, scope, complete-through and retrieval clocks, and coverage. Results cover the league season, and personnel reports include current confirmed starter IDs by team. The reader trusts these producer contracts. Verifying completeness against source-specific APIs and instrumenting every league's numerical reader are outstanding dependencies. A matching self-contained test fixture exercises the contract but does not qualify a live source feed.

Missing results currently block the shadow freeze in every sport; no positive missed-event budget has been approved. No executable market comparison or price is emitted. Pricing windows, preregistered adjustments and decision-facing authorization remain separate.

The archived NFL audit uses native state, schedule, and independently reconstructed QB features. Last-consumed game times in that audit are **kickoff times**. The dated errata preserve source and forecast identities for all 12 NFL fixtures and the ULM game.
