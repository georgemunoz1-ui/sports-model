"""Shared margin->cover library (research-only, no action authority)."""
from .distribution import (
    MarginDistribution,
    normal_margin,
    empirical_margin,
    simulated_margin,
    discrete_football_margin,
    distribution_id_for,
)
from .cover import CoverQuote, cover_quote
from .sigma import estimate_sigma
from .emit import margin_quote_record, validate_record, SCHEMA

__all__ = [
    "MarginDistribution",
    "normal_margin",
    "empirical_margin",
    "simulated_margin",
    "discrete_football_margin",
    "distribution_id_for",
    "CoverQuote",
    "cover_quote",
    "estimate_sigma",
    "margin_quote_record",
    "validate_record",
    "SCHEMA",
]
