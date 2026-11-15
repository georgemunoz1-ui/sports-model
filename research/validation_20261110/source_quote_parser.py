"""Exact retained-source quote parser reused from the established card audit."""
import math
from decimal import Decimal, localcontext

def require(condition, reason):
    if not condition:
        raise ValueError(reason)

def source_price(value):
    if value is None or value == "OFF":
        return None
    require(type(value) in (str, int, float), "INVALID_SOURCE_PRICE")
    parsed = Decimal(str(value))
    require(parsed.is_finite() and parsed == int(parsed) and abs(parsed) >= 100, "INVALID_SOURCE_PRICE")
    return int(parsed)

def decimal_price(american):
    with localcontext() as context:
        context.prec = 60
        odds = Decimal(american)
        return Decimal(1) + (Decimal(100) / -odds if odds < 0 else odds / Decimal(100))

def source_contracts(raw):
    books = [item for item in raw.get("pickcenter", []) if item.get("provider", {}).get("name") == "DraftKings"]
    require(len(books) <= 1, "AMBIGUOUS_SOURCE_BOOK")
    if not books:
        return []
    book = books[0]
    require(str(book["provider"]["id"]) == "100", "SOURCE_BOOK_ID")
    contracts = []
    for market, property_name, sides in [
        ("moneyline", "moneyline", ("home", "away")),
        ("spread", "pointSpread", ("home", "away")),
        ("total", "total", ("over", "under")),
    ]:
        if property_name not in book:
            continue
        ticks = [book[property_name][side]["close"] for side in sides]
        prices = [source_price(tick["odds"]) for tick in ticks]
        if None in prices:
            continue
        lines = [None, None]
        if market != "moneyline":
            strings = [str(tick["line"]) for tick in ticks]
            if market == "total":
                require(strings[0].lower().startswith("o") and strings[1].lower().startswith("u"), "SOURCE_TOTAL_SIDES")
                strings = [value[1:] for value in strings]
            lines = [float(value) for value in strings]
            require(all(math.isfinite(value) for value in lines), "SOURCE_LINE_NOT_FINITE")
            require(lines[0] == (-lines[1] if market == "spread" else lines[1]), "SOURCE_PAIRED_LINE_SCOPE")
        decimals = [decimal_price(price) for price in prices]
        implied = [Decimal(1) / decimal for decimal in decimals]
        denominator = sum(implied)
        contracts.extend({
            "book": "DraftKings", "market": market, "side": side, "line": line,
            "american_odds": price, "decimal_odds": float(decimal),
            "no_vig_probability": float(implied[index] / denominator),
            "book_overround": float(denominator - 1),
            "source_pointer": f"/pickcenter/{raw['pickcenter'].index(book)}/{property_name}/{side}/close",
        } for index, (side, line, price, decimal) in enumerate(zip(sides, lines, prices, decimals)))
    return contracts
