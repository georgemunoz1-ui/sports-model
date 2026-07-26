"""Mid-season projection: keep the games already played, simulate the rest.

    python examples/project_a_season.py

This is the "rest of season" workflow. Results so far are treated as fixed
facts, ratings are fit from them, and only the remaining fixtures are simulated
-- so a team that started 0-6 has to dig out of a real hole, not a modelled one.
"""

from sportsim import SeasonSimulator, compute_standings, generate_season, standings_table
from sportsim.core.ratings import fit_for_sport

SPORT = "nhl"
FRACTION_PLAYED = 0.55

# A season that is 55% complete: some games have results, the rest do not.
season = generate_season(SPORT, seed=12, played_fraction=FRACTION_PLAYED)
played = [g for g in season.games if g.played]
remaining = [g for g in season.games if not g.played]
print(f"{len(played):,} games played, {len(remaining):,} to go\n")

print(standings_table(compute_standings(played, season.league.teams, ot_points=True), season.league, ot_points=True))

# Ratings come only from what has actually happened.
fit = fit_for_sport(played, SPORT)

# Feeding the full season (results + fixtures) makes the simulator carry the
# completed games through as facts and simulate only what is left. If results
# arrive in a separate file, sportsim.season.merge_results overlays them onto a
# bare schedule first.
sim = SeasonSimulator(SPORT, fit.ratings(), league=season.league)
result = sim.run(season.games, n_sims=4_000, rng=7)

print(result.report(top=12))

print("\nA closer look at three teams:")
for row in result.summary()[:3]:
    print("  " + result.team_report(row["team"]))

# The distribution matters more than the average: a 55%-playoff team is a
# genuine coin flip, not a team that will finish exactly on the bubble.
bubble = [r for r in result.summary() if 0.35 < r["playoffs"] < 0.65]
print(f"\n{len(bubble)} teams are still a real coin flip for a playoff spot:")
for r in bubble:
    print(f"  {r['team']:<5} {r['playoffs']:.0%} playoffs, projected {r['mean_wins']:.1f} wins")
