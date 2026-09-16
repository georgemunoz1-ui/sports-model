from research.adapters.mlb import MLBAdapter
from research.adapters.cfb import CFBAdapter
from research.adapters.mls import MLSAdapter

ADAPTERS = {"MLB": MLBAdapter(), "CFB": CFBAdapter(), "MLS": MLSAdapter()}
