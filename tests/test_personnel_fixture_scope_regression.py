"""Regression coverage for source-established NFL personnel fixture scope."""

from research.personnel_events import _fixture_scope


EVENT = {
    "event_id": "2026_10_MIN_GB",
    "away_team": "MIN",
    "home_team": "GB",
    "start_time_utc": "2026-11-15T18:00:00Z",
}


def notice(**overrides):
    row = {
        "league": "NFL",
        "event_id": EVENT["event_id"],
        "team_id": "MIN",
        "status": "STARTING",
        "source_url": "https://www.vikings.com/news/kirk-cousins-starting-packers-week-10-game-2026",
        "published_at_utc": "2026-11-13T21:11:08Z",
        "retrieved_at_utc": "2026-11-15T12:57:21Z",
        "published_time_verified": True,
        "excerpt": "Kirk Cousins will start.",
        "context_excerpt": "Week 10 at Packers",
        "pdf_matchup": None,
        "pdf_team": None,
    }
    row.update(overrides)
    return row


def test_prior_season_week_label_does_not_scope_to_2026_fixture():
    old_notice = notice(
        published_at_utc="2025-11-09T18:00:00Z",
        retrieved_at_utc="2026-11-15T12:57:21Z",
        source_season=2025,
        source_fixture_date_utc="2025-11-09",
    )

    assert _fixture_scope(old_notice, EVENT) is False


def test_missing_source_date_or_event_identity_is_not_scoped():
    without_source_date = notice()
    without_source_date.pop("source_fixture_date_utc", None)
    without_source_date.pop("source_event_id", None)

    without_source_event_id = notice(source_fixture_date_utc="2026-11-15")

    assert _fixture_scope(without_source_date, EVENT) is False
    assert _fixture_scope(without_source_event_id, EVENT) is False


def test_source_backed_season_and_date_can_scope_club_notice():
    dated = notice(source_season=2026, source_fixture_date_utc="2026-11-15")

    assert _fixture_scope(dated, EVENT) is True


def test_source_established_event_id_can_scope_club_notice():
    identified = notice(
        source_event_id=EVENT["event_id"],
        context_excerpt="Kirk Cousins named the starter.",
    )

    assert _fixture_scope(identified, EVENT) is True


def test_manifest_event_id_alone_cannot_scope_club_notice():
    manifest_only = notice(context_excerpt="Week 10 at Packers")
    manifest_only.pop("source_event_id", None)
    manifest_only.pop("source_fixture_date_utc", None)
    assert manifest_only["event_id"] == EVENT["event_id"]

    assert _fixture_scope(manifest_only, EVENT) is False
