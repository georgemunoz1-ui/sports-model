from scripts.scan_divergence_and_context import scan_event_row

def test_scanner_flags_nfl_divergence_and_imputed_weather():
    # Synthetic regression inputs; not an assertion about the historical event.
    row = {"event_id": "NFL:synthetic", "league": "NFL", "product": "margin", "p": 0.7062, "market": 0.5152}
    ctx = {"roof": "outdoor", "temperature_status": "WEATHER_IMPUTED",
           "wind_status": "WEATHER_IMPUTED", "precipitation_status": "WEATHER_OBSERVED_CONSUMED"}
    codes = {a.alert_code for a in scan_event_row(row, ctx)}
    assert "MARKET_PROB_DIVERGENCE" in codes
    assert "NFL_TEMPERATURE_WEATHER_IMPUTED" in codes
    assert "NFL_WIND_WEATHER_IMPUTED" in codes

def test_scanner_flags_cbb_total_gap_and_unverified_neutral_hold():
    row = {"event_id": "CBB:synthetic", "league": "CBB", "product": "total", "point_total": 148.88, "line": 140.5}
    ctx = {"orientation_reversed": True, "neutral_venue_verified": False}
    alerts = scan_event_row(row, ctx)
    assert any(a.alert_code == "TOTAL_LINE_DIVERGENCE" for a in alerts)
    assert any(a.alert_code == "CBB_UNVERIFIED_NEUTRAL_REVERSAL" and a.severity == "BLOCK" for a in alerts)
