"""Price a single game and compare the model against a book's numbers.

    python examples/price_a_game.py

Swap the synthetic season for your own results CSV and the rest is unchanged:

    games = read_games_csv("nba_2025.csv")
"""

from sportsim import generate_season, get_simulator, scan_edges
from sportsim.core.ratings import EloModel, fit_for_sport

SPORT = "nba"

season = generate_season(SPORT, seed=4)
played = [g for g in season.games if g.played]

# 1. Fit ratings. fit_for_sport applies the shrinkage and recency weighting that
#    suit this league's season length.
fit = fit_for_sport(played, SPORT)
elo = EloModel(SPORT).fit(played)
ratings = fit.ratings()

home, away = fit.table()[0][0], fit.table()[8][0]
print(f"{away} @ {home}")
print(f"  {home}: attack {fit.attack[home]:.3f}  defense {fit.defense[home]:.3f}  elo {elo.get(home):.0f}")
print(f"  {away}: attack {fit.attack[away]:.3f}  defense {fit.defense[away]:.3f}  elo {elo.get(away):.0f}")
print()

# 2. Simulate the game.
forecast = get_simulator(SPORT).forecast(ratings[home], ratings[away], n=50_000, rng=1)
print(forecast.report())

# 3. Ask the questions a market asks.
spread, total = -4.5, 228.5
print()
print(f"  P({home} {spread:+g}) = {forecast.cover_prob(spread):.1%}")
print(f"  P(over {total:g})  = {forecast.over_prob(total):.1%}")
print(f"  P({home} scores 115+) = {forecast.team_total_over_prob(home, 114.5):.1%}")

# 4. Compare with posted prices. Passing both sides of each market lets the
#    comparison strip the vig first -- otherwise every bet looks bad.
lines = {
    "moneyline": {"home": -180, "away": +155},
    "spread": {"line": spread, "home": -110, "away": -110},
    "total": {"line": total, "over": -108, "under": -112},
}
print("\nmodel vs market (quarter Kelly)")
print("-" * 92)
for edge in scan_edges(forecast, lines, kelly_multiplier=0.25):
    flag = "  <-- bet" if edge.edge > 0.02 else ""
    print(f"  {edge}{flag}")

print("\nNote: these are synthetic ratings against invented prices. Against a real")
print("book, measure closing line value before you believe any of this.")
