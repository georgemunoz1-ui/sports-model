"""Score the models out of sample, the only way that means anything.

    python examples/backtest_models.py

Every prediction below is made with ratings fit on earlier games only. A model
evaluated on games it was fit to will look far better than it is.
"""

from sportsim import generate_season
from sportsim.backtest import compare_models, walk_forward
from sportsim.core.metrics import ats_record

SPORT = "nba"

games = generate_season(SPORT, seed=17).games
print(f"backtesting {len(games):,} {SPORT.upper()} games\n")

# Elo vs ridge point ratings vs the full simulator, all scored on the same set
# of games so the numbers are comparable.
print(compare_models(games, SPORT, min_games=400, refit_every=150, sims=3_000))

result = walk_forward(games, SPORT, min_games=400, refit_every=150, sims=3_000)
print("\n" + result.report())

# What does betting one model against another look like? There are no real
# closing lines here, so the ridge model's margins stand in for the market and
# the simulator bets whenever it disagrees by more than a point. This measures
# one model against another -- a real book is a much harder opponent.
ridge = walk_forward(games, SPORT, method="ridge", min_games=400, refit_every=150)
market = [-m for m in ridge.predicted_margins]   # market spreads are the home line
record = result.ats(market, threshold=1.0)

print("\nsimulator vs the ridge model's line (not a real market)")
print(f"  {record['bets']} bets: {record['wins']}-{record['losses']}-{record['pushes']}"
      f"   {record['win_pct']:.1%}   {record['units_at_-110']:+.1f}u   ROI {record['roi']:+.1%}")
print("  break-even at -110 is 52.4%, so anything near 50% means the two models agree")
print("  about as often as they differ -- which is the expected result here.")
