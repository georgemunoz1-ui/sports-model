# 28. Binding one join does not bind the others

2026-08-23. I shipped `franchise_identity` in the morning to stop the WAS@POR / WAS@PDX class of
failure, wrote a lesson about it, and gated it in the healthcheck. That evening I ingested fifteen
tier-1 finals and the completeness gate reported **all fifteen games of a fully ingested slate as
missing**.

The frozen slate `.psv` writes full team names — `Athletics|Houston Astros` — and `results.csv`
writes abbreviations. `slate_completeness` compared the raw strings, found no overlap, and concluded
the slate had no results at all. Same defect as the 62 keys, same day, one layer over. The module
that fixes it already existed and was already running; it simply was not applied at *this* join.

That is the actual shape of the bug. An identity map is not a fix you install once — it is a fix you
have to apply at every place two records are matched, and the places are not all obvious, because a
join on unbound identities never raises. It returns an empty intersection and lets the caller
interpret that as a fact about the world. Here the interpretation was "the slate is missing", which
is the loudest possible failure and therefore the lucky case. The quiet one is a partial overlap,
where some games pair and some silently do not, and the arm with fewer paired games looks like it
covered fewer games rather than like it was spelled differently.

Two properties made the fix safe to apply inside a gate: binding can only MERGE two spellings of one
franchise, so it can never hide a genuinely absent game; and an unresolvable token falls through as
its own raw string rather than being dropped, so an identity the table does not know still gets
compared rather than silently vanishing.

Standing rule: when a canonical-identity module is introduced, grep for every comparison of a team,
game or franchise string and bind both sides. The healthcheck's own gates are not exempt — see
lesson 23.
