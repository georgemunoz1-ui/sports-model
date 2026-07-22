# RUNBOOK — daily procedures (URL patterns below are TESTED-WORKING; don't improvise new ones)

## pregame  (run ~15:00 UTC / before first pitch)
1. healthcheck.py; read state.json.
2. Slate: WebFetch `https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher`
   -> gamePk|away|home|time|aSP name+id|hSP name+id. Save data/mlb/schedule/YYYY-MM-DD_slate.json.
3. K lines — SOURCE OF TRUTH: Taco's RotoWire CSV export (he clicks Export Table Data->CSV on
   rotowire.com/betting/mlb/player-props.php and drops the file in chat; check /root/.claude/uploads/
   for today's newest .csv/.xls). Parse flexibly: header row names the books; row = player, team,
   opp, line, under price, over price per book — use DraftKings column primarily, best-price across
   books for the EV line if unambiguous. Screenshots/pasted text are the fallback. If neither:
   projection-only card, do NOT guess prices (R1). RotoWire pages themselves are JS shells —
   direct fetch does NOT work (tested 2026-07-22); don't burn fetches retrying.
4. Projections: LOCAL — engine k-prop method, START-ONLY accumulation from pitcher_logs
   (bug history: relief outings inflate TBF/start). <5 prior GS -> skip. |proj-line|>=1.5 -> R5 audit.
5. Card = FULL-TRACKING (Taco standing order 7/22): run `python3 harness/daily_card.py DATE slate.psv`
   -> ALL games x {lines, V13 H%/projT/RLcov/blow%, K projs, gap-vs-market} displayed as TRACKING.
   Plays remain kprop-only: EV>0 AND edge>=4pp AND |dev|>=0.8 -> paper play (weight 0.5 if GS<10). Write
   cards/YYYY-MM-DD_kprops.json + html; append plays to state.json ledgers.kprops_paper.plays_pending;
   SendUserFile card to Taco. NO sides plays (R3) — log V13 directional silently if V13 inputs handy.
6. LINE SNAPSHOT (free, feeds E3): WebFetch ESPN core odds for today's event ids (runbook pattern in
   session history / sports/registry.py espn_odds_url) -> save data/mlb/odds/YYYY-MM-DD_pregame.json.
   ML+totals only; prop prices still come from Taco's boards.
7. Append docs/progress.md (3-6 lines). git commit; bash harness/push.sh.

## postgame  (run ~05:30 UTC after last final)
1. healthcheck.py.
2. Finals: WebFetch `...schedule?sportId=1&startDate=D&endDate=D&hydrate=linescore,venue`
   -> date|gamePk|away|home|ascore|hscore|status|venue. UPSERT into results.csv (sports/ingest_mlb.py
   pattern; overwrite same game_id — verify AFTER flush, in a separate process, not mid-write).
3. Actual K for carded pitchers: WebFetch `.../people/{id}/stats?stats=gameLog&group=pitching&season=2026&fields=stats,splits,date,stat,inningsPitched,earnedRuns,strikeOuts,baseOnBalls,battersFaced,gamesStarted`
   -> last row = tonight. ALSO append that row to pitcher_logs/{id}.txt (keeps projections current).
4. Grade pending plays: OVER wins if K>line. P/L at price (weight-adjusted). Move pending->graded in
   state.json; update record/units; append docs/kprop_ledger.md row per play.
5. Update v13_forward_directional if slate was logged. Update state.json.updated_utc + next_actions.
6. Append docs/progress.md; git commit; run `bash harness/push.sh` (durability push to origin —
   if push fails, WARN in the summary but continue; local commit still made).
7. Message Taco: record, running units, notable grades, tomorrow.

## edge cases (postgame)
- LATE FINALS: 05:30Z fire can catch West-coast extras still live. Grade what is FINAL; leave the
  rest in plays_pending with a note — next postgame sweeps them. NEVER grade a non-final.
- POSTPONED game on a carded play -> play is VOID (remove from pending, 0u, note in ledger).
- DOUBLEHEADERS: match pitcher's gameLog row by date AND opponent; two same-date rows possible.

## weekly review (Sundays, after postgame)
- Recompute K-prop calibration on ALL graded forward plays vs backtest curve (drift check).
- Check gates in state.json (kprops_go_live progress n/100). Report to Taco.
- Pick ONE experiment from experiment_queue if capacity; pre-register method BEFORE running (R7).
- BACKUP: `git bundle create /tmp/sportsmodel_backup_$(date +%F).bundle --all` -> SendUserFile to Taco.
- LEDGER DASHBOARD: regenerate docs/dashboard.html (running record, units curve, calibration table)
  -> SendUserFile so Taco tracks visually without asking.

## fetch discipline (hard-won)
- WebFetch only; big JSON truncates -> always use `fields=` and <=7-day windows.
- ESPN odds vanish at final -> pregame capture only. statsapi standings = stale; never use.
- 429: wait 60-90s, retry ONCE, log gap. Same-URL retry <15min hits cache — vary a param.
- FanGraphs per-team (`team={id}&pageitems=60`) works; full-board truncates.
