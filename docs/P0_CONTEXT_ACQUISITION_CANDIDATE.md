# P0 source acquisition candidate

Research only; no model inputs changed, no historical admission, no action authority.

NWS hourly: use a reviewed NFL event/stadium/coordinate/roof binding JSON with league, event_id, stadium_id, latitude, longitude, roof=outdoor, start_utc. Set NWS_USER_AGENT to an application name and operator contact per NWS docs. Source: https://www.weather.gov/documentation/services-web-api and https://github.com/weather-gov/api/blob/master/gridpoints.md. Wind range and precipitation probability remain observations, not a point wind estimate or precipitation amount.

CBB: use an independently reviewed binding JSON with league=CBB, event_id, start_utc, provider_schedule_date, access_level=trial or production, sr_game_id, sr_team_ids, sr_venue_id. Set SPORTRADAR_API_KEY in the operator environment; never commit it. Source: https://developer.sportradar.com/basketball/reference/ncaamb-daily-schedule and https://developer.sportradar.com/basketball/v3/reference/ncaamb-faq. Separate vendor does not alone prove upstream independence. Require explicit review of vendor lineage and mapping to the original NCAA/ESPN records before mapper use. No score matching or name guessing. No existing gate modified.

Run from repository root: python -m scripts.capture_context_observations --binding <reviewed.json> --binding-sha256 <independent-pin> --output <new-dir>. Receipt retention and tests are not provider signatures or PIT certification. The source-only report must never be used as a forecast or automatically clear a hold. No live source smoke test or archived pregame recovery is claimed. Historical observations may not be relabeled as pregame forecasts.
