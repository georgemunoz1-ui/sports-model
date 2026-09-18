"""Versioned CFB candidate definitions. No NFL weights and no implied activation."""
from .registry import seal_definition

# id suffix, block, source family, source columns, unit, orientation
SPECS = [
 ('rating.internal_prior','prior','cfb_internal_state',['team_rating'],'INTERNAL_RATING','HOME_FAVORABLE'),
 ('rating.cfbd_srs','ratings','cfbd_srs',['rating'],'POINTS_RELATIVE_TO_FBS','HIGHER_STRONGER'),
 ('rating.cfbd_elo','ratings','cfbd_elo',['elo'],'ELO_POINTS_NOT_MARGIN','HIGHER_STRONGER'),
 ('rating.sp_overall','ratings','cfbd_sp',['rating'],'PROVIDER_RATING','HIGHER_STRONGER'),
 ('rating.sp_offense','ratings','cfbd_sp',['offense.rating'],'PROVIDER_COMPONENT','PROVIDER_DIRECTION_MUST_BE_VERIFIED'),
 ('rating.sp_defense','ratings','cfbd_sp',['defense.rating'],'PROVIDER_COMPONENT','PROVIDER_DIRECTION_MUST_BE_VERIFIED'),
 ('rating.sp_special_teams','ratings','cfbd_sp',['specialTeams.rating'],'PROVIDER_COMPONENT','PROVIDER_DIRECTION_MUST_BE_VERIFIED'),
 ('rating.fpi','ratings','cfbd_fpi',['fpi'],'FPI_POINTS_NOT_RANK','HIGHER_STRONGER'),
 ('rating.massey','ratings','cfb_massey',['rating'],'UNVERIFIED_PROVIDER_SCALE','UNVERIFIED'),
 ('rating.versus','ratings','cfb_versus',['rating'],'UNVERIFIED_PROVIDER_SCALE','UNVERIFIED'),
 ('team.off_epa_l8','efficiency','cfbfastR_legacy_pbp',['EPA','pos_team'],'EPA_PER_PLAY','OFFENSE_POSITIVE'),
 ('team.def_epa_allowed_l8','efficiency','cfbfastR_legacy_pbp',['EPA','def_pos_team'],'EPA_PER_PLAY','LOWER_DEFENSIVELY_BETTER'),
 ('team.off_success_l8','efficiency','cfbfastR_legacy_pbp',['EPA','pos_team'],'FRACTION','OFFENSE_POSITIVE'),
 ('team.def_success_allowed_l8','efficiency','cfbfastR_legacy_pbp',['EPA','def_pos_team'],'FRACTION','LOWER_DEFENSIVELY_BETTER'),
 ('team.off_pass_epa_l8','efficiency','cfbfastR_legacy_pbp',['EPA','pass','pos_team'],'EPA_PER_PLAY','OFFENSE_POSITIVE'),
 ('team.def_pass_epa_allowed_l8','efficiency','cfbfastR_legacy_pbp',['EPA','pass','def_pos_team'],'EPA_PER_PLAY','LOWER_DEFENSIVELY_BETTER'),
 ('team.off_rush_epa_l8','efficiency','cfbfastR_legacy_pbp',['EPA','rush','pos_team'],'EPA_PER_PLAY','OFFENSE_POSITIVE'),
 ('team.def_rush_epa_allowed_l8','efficiency','cfbfastR_legacy_pbp',['EPA','rush','def_pos_team'],'EPA_PER_PLAY','LOWER_DEFENSIVELY_BETTER'),
 ('team.off_explosiveness_l8','efficiency','cfbfastR_legacy_pbp',['EPA','pos_team'],'EPA_PER_SUCCESSFUL_PLAY','OFFENSE_POSITIVE'),
 ('team.def_explosiveness_allowed_l8','efficiency','cfbfastR_legacy_pbp',['EPA','def_pos_team'],'EPA_PER_SUCCESSFUL_PLAY','LOWER_DEFENSIVELY_BETTER'),
 ('team.off_standard_down_epa_l8','efficiency','cfbfastR_legacy_pbp',['EPA','down','distance'],'EPA_PER_PLAY','OFFENSE_POSITIVE'),
 ('team.def_standard_down_epa_l8','efficiency','cfbfastR_legacy_pbp',['EPA','down','distance'],'EPA_PER_PLAY','LOWER_DEFENSIVELY_BETTER'),
 ('tempo.plays_per_game','tempo','cfbfastR_legacy_pbp',['game_id','game_play_number'],'PLAYS_PER_GAME','HIGHER_MORE_PLAYS_NOT_WIN'),
 ('tempo.clock_seconds','tempo','cfbfastR_legacy_pbp',['clock_minutes','clock_seconds','period','id_drive'],'SECONDS_PER_ELIGIBLE_INTERVAL','LOWER_FASTER_NOT_WIN'),
 ('tempo.drives_per_game','tempo','cfbfastR_legacy_pbp',['game_id','id_drive'],'DRIVES_PER_GAME','HIGHER_MORE_DRIVES_NOT_WIN'),
 ('prior.talent','continuity','cfbd_talent',['talent'],'PROVIDER_TALENT_SCALE','HIGHER_STRONGER'),
 ('prior.returning_production','continuity','cfbd_returning_production',['percentPPA'],'FRACTION','HIGHER_MORE_RETURNED_NOT_CAUSAL'),
 ('prior.returning_qb','continuity','cfbd_roster',['id','team','position'],'BINARY','HIGHER_CONTINUITY_NOT_CONFIRMED_STARTER'),
 ('prior.head_coach_continuity','continuity','cfbd_coaches',['firstName','lastName','seasons'],'BINARY','HIGHER_CONTINUITY_NOT_WIN'),
 ('prior.offensive_coordinator_continuity','continuity','official_cfb_coaches',['coordinator','effective_date'],'BINARY','HIGHER_CONTINUITY_NOT_WIN'),
 ('schedule.home_field','schedule','cfbd_games',['homeId','neutralSite'],'BINARY','HOME_FAVORABLE'),
 ('schedule.neutral_site','schedule','cfbd_games',['neutralSite'],'BINARY','NO_AUTOMATIC_HOME_ADVANTAGE'),
 ('schedule.rest_difference','schedule','cfbd_games',['startDate','homeId','awayId'],'CALENDAR_DAYS_HOME_MINUS_AWAY','EXPLICIT_NO_EMPIRICAL_SIGN_CLAIM'),
 ('schedule.travel_difference','schedule','cfbd_venues',['latitude','longitude'],'KM_HOME_MINUS_AWAY','EXPLICIT_NO_EMPIRICAL_SIGN_CLAIM'),
 ('weather.wind','weather','weather_forecast',['wind_speed','wind_unit'],'MPH','SUSTAINED_NOT_GUST'),
 ('weather.temperature','weather','weather_forecast',['temperature','unit'],'FAHRENHEIT','NO_FIXED_WIN_DIRECTION'),
 ('matchup.home_off_plus_away_allowed','matchup','cfbfastR_legacy_pbp',['EPA','pos_team','def_pos_team'],'EPA_PER_PLAY','HOME_OFFENSE_FAVORABLE'),
 ('matchup.symmetric_epa_difference','matchup','cfbfastR_legacy_pbp',['EPA','pos_team','def_pos_team'],'EPA_PER_PLAY','HOME_FAVORABLE'),
]

SOURCE_POLICIES = {
 'cfbfastR_legacy_pbp':{'loader':'load_cfb_pbp','release_tag':'cfbfastR_cfb_pbp','documented_start_season':2014,'source_version_key':['loader_commit','raw_hash','upstream_model_hash','rule_era_contract_hash'],'primary_historical_family':True},
 'espn_cfb_pbp':{'loader':'load_espn_cfb_pbp','release_tag':'espn_cfb_pbp','documented_start_season':2004,'source_version_key':['loader_commit','raw_hash','upstream_model_hash','rule_era_contract_hash'],'primary_historical_family':False,'never_substitute_for':'cfbfastR_legacy_pbp'},
 'cfbd_ratings':{'srs_endpoint':'/ratings/srs','srs_expanded_endpoint':'/ratings/srs/expanded','elo_endpoint':'/ratings/elo','sp_endpoint':'/ratings/sp','fpi_endpoint':'/ratings/fpi','week_query_supported':['elo'],'historical_snapshot_required':True},
 'ratings_roles':{'SP+':'EXTERNAL_BENCHMARK_CANDIDATE','FPI':'EXTERNAL_BENCHMARK_CANDIDATE','SRS':'POINT_SCALE_CANDIDATE','Elo':'SEQUENTIAL_SCALE_CANDIDATE','Massey':'DIAGNOSTIC_CANDIDATE','Versus':'UNVERIFIED_CANDIDATE'},
 'market':{'feature_in_football_only':False,'separate_model_required':True},
 'division_bridge':{'status':'BLOCKED','expanded_srs_does_not_establish_calibrated_bridge':True},
}


def definitions():
    result=[]
    for suffix,block,family,columns,unit,orientation in SPECS:
        is_pbp=family=='cfbfastR_legacy_pbp'
        d={'feature_id':'cfb.'+suffix+'.v1','display_name':suffix.replace('.',' ').replace('_',' '),'sport':'CFB','prediction_mode':'PREGAME',
           'entity_grain':'team_game' if suffix.startswith('team.') else 'event','target_compatibility':['home_win_probability','home_margin','game_total'],
           'source_family':family,'source_dataset':'load_cfb_pbp' if is_pbp else family,'source_columns':columns,
           'source_endpoint_version':'cfb-pit-source-contract.v1','identity_keys':['season','event_id','team_id'],
           'availability_rule':'FINALIZED_PRIOR_GAMES_AND_CAPTURE_BEFORE_CUTOFF' if is_pbp else 'CAPTURE_BEFORE_CUTOFF',
           'lookback_rule':'PRIOR_8_COMPLETED_GAMES' if is_pbp else 'LATEST_ELIGIBLE_SOURCE_SNAPSHOT',
           'transform_version':'cfb.'+suffix+'.transform.v1','unit':unit,'orientation':orientation,
           'missingness_policy':'REJECT_REQUIRED; OPTIONAL_NULL_AND_REASON; FITTED_IMPUTER_REQUIRED_BEFORE_USE',
           'eligible_competition':'FBS_VS_FBS','status':'REGISTERED','owner':'sports-model-cfb-research',
           'block':block,'requires_denominator':suffix.startswith('team.'),'upstream_model_required':is_pbp and 'EPA' in columns,
           'transform_implemented':suffix=='matchup.symmetric_epa_difference','empirical_value_status':'NOT_EVALUATED','live_status':'BLOCKED_NOT_FITTED'}
        result.append(seal_definition(d))
    return result
