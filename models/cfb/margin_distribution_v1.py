#!/usr/bin/env python3
"""CFB V1 market-independent home-margin distribution.

Fit only on point-in-time historical features. Current market spread/odds are
forbidden inputs. The model predicts expected HOME-AWAY final margin and a
positive residual scale for downstream simulation.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

MODEL_ID = "cfb.margin_distribution.v1"

@dataclass(frozen=True)
class MarginModel:
    intercept: float
    elo_diff_coef: float
    hfa_coef: float
    neutral_coef: float
    sigma_default: float
    sigma_early: float | None = None
    sigma_large_gap: float | None = None
    large_gap_threshold: float = 300.0

    def predict(self, *, home_elo_pre: float, away_elo_pre: float,
                home_field_indicator: float = 1.0, neutral_site: bool = False,
                early_season: bool = False) -> tuple[float, float]:
        elo_diff = float(home_elo_pre) - float(away_elo_pre)
        mu = (self.intercept + self.elo_diff_coef * elo_diff
              + self.hfa_coef * float(home_field_indicator)
              + self.neutral_coef * float(bool(neutral_site)))
        sigma = self.sigma_default
        if early_season and self.sigma_early is not None:
            sigma = self.sigma_early
        if abs(elo_diff) >= self.large_gap_threshold and self.sigma_large_gap is not None:
            sigma = max(sigma, self.sigma_large_gap)
        if not math.isfinite(mu) or not math.isfinite(sigma) or sigma <= 0:
            raise ValueError("invalid margin prediction")
        return float(mu), float(sigma)


def fit_ols(rows):
    """Fit baseline margin mapping with numpy OLS and empirical residual scales.

    Required keys: home_margin_final, home_elo_pre, away_elo_pre.
    Optional: home_field_indicator, neutral_site, early_season_flag.
    """
    import numpy as np
    if len(rows) < 100:
        raise ValueError("insufficient historical rows for margin fit")
    X, y = [], []
    for r in rows:
        X.append([1.0,
                  float(r["home_elo_pre"]) - float(r["away_elo_pre"]),
                  float(r.get("home_field_indicator", 1.0)),
                  float(bool(r.get("neutral_site", False)))])
        y.append(float(r["home_margin_final"]))
    X, y = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    sigma = float(np.sqrt(np.mean(resid ** 2)))
    early = [resid[i] for i,r in enumerate(rows) if bool(r.get("early_season_flag", False))]
    large = [resid[i] for i,r in enumerate(rows)
             if abs(float(r["home_elo_pre"])-float(r["away_elo_pre"])) >= 300]
    rms = lambda a: float(np.sqrt(np.mean(np.asarray(a, dtype=float)**2))) if a else None
    return MarginModel(float(beta[0]), float(beta[1]), float(beta[2]), float(beta[3]),
                       sigma, rms(early), rms(large))
