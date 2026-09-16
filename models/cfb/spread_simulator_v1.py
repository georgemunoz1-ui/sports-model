#!/usr/bin/env python3
"""Seeded Monte Carlo pricing for frozen CFB home-margin distributions."""
from __future__ import annotations

MODEL_ID = "cfb.spread_simulator.v1"
MIN_SIMS = 50_000


def simulate_margins(mu_margin: float, sigma_margin: float, n_sims: int, seed: int):
    import numpy as np
    if n_sims < MIN_SIMS:
        raise ValueError(f"n_sims must be >= {MIN_SIMS}")
    if sigma_margin <= 0:
        raise ValueError("sigma_margin must be positive")
    rng = np.random.default_rng(int(seed))
    return rng.normal(float(mu_margin), float(sigma_margin), int(n_sims))


def summarize(margins):
    import numpy as np
    q = np.quantile(margins, [0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "home_win_p_sim": float(np.mean(margins > 0.0)),
        "margin_quantiles": dict(zip(("p10","p25","p50","p75","p90"), map(float,q)))
    }


def price_home_spread(margins, home_spread: float, *, integer_margin_mode: bool = False):
    """Canonical sign: home_spread=-6.5 means home covers when margin > +6.5.

    For V1 continuous margins, integer spreads have zero exact push mass. Set
    integer_margin_mode only when the supplied margins have been produced by an
    independently validated discrete-margin transform.
    """
    import numpy as np
    threshold = -float(home_spread)
    if integer_margin_mode:
        home = float(np.mean(margins > threshold))
        push = float(np.mean(margins == threshold))
        away = float(np.mean(margins < threshold))
    else:
        home = float(np.mean(margins > threshold))
        push = 0.0
        away = float(np.mean(margins < threshold))
    return {"home_cover_p_sim": home, "push_p_sim": push, "away_cover_p_sim": away}
