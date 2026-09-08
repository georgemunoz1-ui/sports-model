# Canonical multi-sport entity registry

This directory defines the **registry contract**, not a hand-maintained roster truth source.

Populate `sports_entity_registry.v1` only from frozen official-provider snapshots. Every team, player,
alias, team assignment and event mapping is time-bounded. The resolver is exact-match and fail-closed:
it does not fuzzy-link a mention to a player, team or event.

Required invariants:

- Canonical IDs are stable within this repository.
- `official_provider_id` records the upstream identity used to create the snapshot.
- Player/team aliases may carry `valid_from_utc` / `valid_to_utc`.
- Player team assignments are time-bounded so trades, loans, call-ups and transfers do not rewrite history.
- Event mappings bind canonical event IDs to the official provider event ID plus home/away teams.
- Ambiguous or stale aliases remain unresolved.
- Registry snapshots are content-addressed via `registry_sha256` when finalized.
- Market identifiers are not authoritative entity inputs.

`registry_template.v1.json` is intentionally empty. Empty data is safer than invented official IDs.
