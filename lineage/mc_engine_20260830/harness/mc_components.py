"""Market-independent model arms wired into mc_engine as ensemble components.

MODULE_ID: mc_components

WHAT THIS IS. Adapters that turn the registered market-independent arms — WNBA ff7
(wnba.rs.ff7_logit_ridge.v1_0.shadow), MLB CHAMPION_V13 (a 30k-trial keyed-seed Monte Carlo
that IS its own arm), and the CFB house Elo+context lean arm
(cfb.fbs.elo_context_logit.v1_0.week1_shadow) — into mc_engine ensemble components, per
MARKET_INDEPENDENCE_RULE.md: sportsbook data is firewalled from every predictive component;
market prices exist only in the post-freeze valuation layer (mc_engine's lines{} handling).

FIREWALL (signature-level). Component predict() functions accept NO odds/lines/spread/
total-price parameters — the forbidden-parameter set below is enforced at adapter
construction by inspect.signature, and every emitted component dict is validated to contain
no market-derived fields before it may leave this module. The forecast path in mc_engine
never calls de_vig (guarded there); market comparison is post-freeze valuation only.

R1 — never invent a number. Every emitted mov_home / p_home / total comes out of the
registered arm itself, or out of a registered FROZEN artifact the arm computed (the CFB
house fallback reads the frozen board, a computed artifact — never a hand-relayed number).
Where the real arm cannot run in this checkout (missing parquet pool / engine module /
feature archive), the adapter raises ArmUnavailableError naming the EXACT missing artifact,
and the slate runner records {status: "ARM_UNAVAILABLE", artifact_missing: <exact path>}.
No arm output is ever fabricated.

FROZEN CONSTANTS (R3 — argue with the reason, not the number):
- WNBAFF7Component.MARGIN_SD = 13.97: frozen, matches wnba_model_v1's frozen MARGIN_SD
  (empirical, measured from staged bytes 2026-08-11). Never refit inside this module.
- NFL_MARGIN_SD = 13.8 / NFL_TOTAL_SD = 15.5: frozen NFL priors (historical league
  margin/total dispersion scale), DECLARED HERE so the engine structure is NFL-ready.
  They are priors, not refits: no NFL arm has live authority (v0_2.shadow), so nothing
  may tune them — and NFLComponent refuses to emit anything until one does.
"""
from __future__ import annotations

MODULE_ID = "mc_components"

import datetime as dt
import inspect
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.dirname(os.path.abspath(__file__))
if HARNESS not in sys.path:
    sys.path.insert(0, HARNESS)

# ------------------------------------------------------------------ frozen constants

NFL_MARGIN_SD = 13.8   # frozen prior: historical NFL margin-of-victory dispersion; no live
                       # NFL authority exists to refit it (nfl v0_2.shadow) — declared so the
                       # engine structure is NFL-ready
NFL_TOTAL_SD = 15.5    # frozen prior: historical NFL total dispersion; same standing

WNBA_MARGIN_SD_FROZEN = 13.97  # frozen: wnba_model_v1 MARGIN_SD, never refit here

# ------------------------------------------------------------------ firewall

#: parameter names a component function may never take (sportsbook data is firewalled
#: from predictive components — MARKET_INDEPENDENCE_RULE.md).
FORBIDDEN_COMPONENT_PARAMS = frozenset({
    "odds", "lines", "line", "spread", "spreads", "market", "market_spread",
    "market_total", "market_ml", "moneyline", "ml", "price", "prices", "vig",
    "de_vig", "implied_prob", "book", "books", "consensus",
})

#: field names a component output dict may never carry. "total" is a projection target and
#: is allowed; "market_total"/"total_line"/"over_prob" are not.
FORBIDDEN_OUTPUT_FIELDS = FORBIDDEN_COMPONENT_PARAMS | frozenset({
    "total_line", "over_prob", "under_prob", "cover_prob", "ev", "ev_per_100",
    "edge", "break_even", "implied",
})


def _is_market_field(key):
    k = str(key).lower()
    if k in FORBIDDEN_OUTPUT_FIELDS:
        return True
    if k.startswith(("market_", "odds_", "price_", "ev_")) or k.endswith(
            ("_odds", "_price", "_ml", "_spread")):
        return True
    return False


def assert_firewall_signature(fn, arm):
    """Fail at wiring time if a component function's signature names any market parameter."""
    bad = set(inspect.signature(fn).parameters) & FORBIDDEN_COMPONENT_PARAMS
    if bad:
        raise TypeError(f"FIREWALL: {arm} component function takes forbidden market "
                        f"parameter(s) {sorted(bad)} — MARKET_INDEPENDENCE_RULE")


def assert_no_market_fields(out, arm):
    """Fail before any component output leaves this module if it carries a market field."""
    for k in out:
        if _is_market_field(k):
            raise ValueError(f"FIREWALL: {arm} component output carries market-derived "
                             f"field {k!r} — MARKET_INDEPENDENCE_RULE")
    return out


# ------------------------------------------------------------------ errors

class ArmUnavailableError(RuntimeError):
    """The registered arm cannot run in this checkout. Names the exact missing artifact.

    Raised, never defaulted — the slate runner turns this into
    {status: ARM_UNAVAILABLE, artifact_missing: <exact path>} and emits NO number (R1).
    """

    def __init__(self, arm, artifact_missing, detail=None):
        self.arm = arm
        self.artifact_missing = artifact_missing
        msg = f"ARM_UNAVAILABLE {arm}: missing artifact {artifact_missing}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class NFLComponentRefused(RuntimeError):
    """NFLComponent refuses: v0_2.shadow has no live authority. Fail loud, with reason."""


# ------------------------------------------------------------------ WNBA ff7

class WNBAFF7Component:
    """Wraps wnba_model_v1.predict_slate as an mc_engine component.

    Emits {source, grade, arm, mov_home, total, dose, provenance}. MARGIN_SD stays frozen
    at 13.97 (the model's own frozen value); the dose comes from the freshness-contract
    disposition for that game's board row (input_freshness.dose_multiplier), defaulting to
    1.0 only when no board row is supplied — declared in provenance.
    """

    SOURCE = "wnba_ff7"
    ARM_ID = "wnba.rs.ff7_logit_ridge.v1_0.shadow"
    MARGIN_SD = WNBA_MARGIN_SD_FROZEN
    GRADE = "MODEL"

    #: seasons the real arm's pool must cover (wnba_model_v1.build_games range)
    POOL_SEASONS = range(2017, 2027)

    #: governed ESPN extension artifact (wnba_refresh_espn EXT_PATH). GOING-FORWARD CHANGE
    #: 2026-08-29 (documented): when this artifact exists, predict() runs the SAME frozen
    #: wnba_model_v1 machinery over base pool + extension via wnba_refresh_espn.run_slate,
    #: under the preregistered replacement identity wnba.replacement.FEATURE_REFRESH —
    #: otherwise the official-plus-one pool ends at the 2026-07-22 cutoff and every current
    #: slate is months-stale. When the artifact is absent the component degrades to the base
    #: pool exactly as before (and the freshness dose shrinks honestly). No frozen constant
    #: changes; MARGIN_SD stays 13.97.
    EXTENSION_ARTIFACT = "data/wnba/source/staging/EXTENSION_ESPN/ext_2026.json"

    def __init__(self, model_module=None, required_artifacts=None):
        self._W = model_module
        self._injected = model_module is not None
        if required_artifacts is not None:
            self._required = list(required_artifacts)
        elif model_module is not None:
            self._required = []   # an injected module is the authority in tests
        else:
            self._required = None  # derived lazily from the real module's STAGE

    def _load_module(self):
        if self._W is None:
            try:
                import wnba_model_v1 as W
            except Exception as e:
                raise ArmUnavailableError(
                    self.ARM_ID, "harness/wnba_model_v1.py",
                    detail=f"import failed: {e}")
            self._W = W
        return self._W

    def _require_pool(self):
        W = self._load_module()
        if self._required is None:
            stage = getattr(W, "STAGE", None)
            if stage is None:
                raise ArmUnavailableError(
                    self.ARM_ID, "harness/wnba_model_v1.py",
                    detail="imported module exposes no STAGE pool path (stub shadow?)")
            self._stage = stage
            stage = self._stage
            self._required = [
                f"{stage}/WNBA_OFFICIAL/wnba_stats/schedules/parquet/"
                f"wnba_stats_schedule_{s}.parquet" for s in self.POOL_SEASONS
            ] + [f"{stage}/ESPN/wnba/team_box/parquet/team_box_{s}.parquet"
                 for s in self.POOL_SEASONS]
        for p in self._required:
            if not os.path.isfile(os.path.join(BASE, p)):
                raise ArmUnavailableError(self.ARM_ID, p)

    def predict(self, date, home, away, tip_utc, board_row=None):
        """One game -> component dict. NO market parameters — the firewall asserts it.

        tip_utc: the real tip instant (offset-qualified); the model's rest/b2b features are
        ET-date derived from it, so it must be real, never synthesized (R1). board_row: the
        freshness-contract board row for this game, supplying input_freshness; its
        dose_multiplier becomes the component dose.
        """
        assert_firewall_signature(self.predict, self.ARM_ID)
        self._require_pool()   # artifact honesty first: an absent pool degrades before
        W = self._load_module()  # any input validation, so the missing artifact is named
        if not tip_utc:
            raise ValueError("WNBAFF7Component requires the real tip instant (tip_utc) — "
                             "rest/b2b features derive from it; synthesizing one is R1 fraud")
        ext_path = os.path.join(BASE, self.EXTENSION_ARTIFACT)
        refresh = None
        if not self._injected and os.path.isfile(ext_path):
            # (an injected module is the authority in tests and never takes this path)
            # base pool + governed ESPN extension, frozen machinery, replacement identity
            import wnba_refresh_espn as R
            res = R.run_slate([(away, home, tip_utc)], ext_path=ext_path)
            pred = res["predictions"][0]
            feature_as_of = res["pool"]["extension_window"].split(".. ")[-1]
            refresh = {"identity": res["identity"], "input_grade": res["input_grade"],
                       "extension_commit": res["provenance"]["commit"],
                       "extension_sha256": res["pool"]["extension_sha256"],
                       "base_games": res["pool"]["base_games"],
                       "extension_games": res["pool"]["extension_games"]}
        else:
            games = W.build_games()
            rows, ts, lg = W.make_rows(games)
            model = W.fit_full(rows)
            pred = W.predict_slate(model, ts, lg, [(away, home, tip_utc)])[0]
            feature_as_of = max(g["date"] for g in games)
        if "p_home" not in pred:
            raise ArmUnavailableError(
                self.ARM_ID,
                f"feature state for {away}@{home} on {pred.get('et_date')}",
                detail=pred.get("status"))
        dose, dose_note = _dose_from_board_row(board_row, "input_freshness")
        out = {"source": self.SOURCE, "grade": self.GRADE, "arm": self.ARM_ID,
               "mov_home": float(pred["margin_home"]), "total": float(pred["total"]),
               "dose": dose,
               "provenance": {
                   "model": self.ARM_ID,
                   "margin_sd_frozen": self.MARGIN_SD,
                   "coherence_pass": pred.get("coherence_pass"),
                   "coherence_gap_pp": pred.get("coherence_gap_pp"),
                   "feature_state_as_of": feature_as_of,
                   "dose_note": dose_note}}
        if refresh is not None:
            out["provenance"]["feature_refresh"] = refresh
        return assert_no_market_fields(out, self.ARM_ID)


# ------------------------------------------------------------------ MLB CHAMPION_V13

class MLBV13Component:
    """Wraps the registered CHAMPION_V13 Monte Carlo (30k trials, keyed seed).

    v13 IS its own MC arm: the adapter passes through its p_home / proj_total and attaches
    the starter-cohort information_dose (board_freshness.game_dose over the starter
    dispositions — multiplicative, 0.20-floored by the frozen contract). v13's own
    convergence discipline (mc_se from its 30k keyed-seed trials) is echoed in provenance;
    the engine treats the component as p_home-supplying.

    The caller supplies the RESOLVED starter feature dicts and their freshness dispositions
    (from a board builder's starter path); the adapter never resolves starters itself and
    never sees a market number.

    WIRED TO THE REAL MODULE (2026-08-30, owner review): the registered engine module
    harness/run_v13_historical.py (owner-uploaded) is present in this checkout, with
    engine/hfa.py (CURRENT == 1.005) reconstructed from its own docstring/comment. The
    ARM_UNAVAILABLE path for v13 is deleted: predict() runs V13.v13_sim directly.
    """

    SOURCE = "mlb_v13"
    ARM_ID = "mlb.winner.CHAMPION_V13"
    TRIALS = 30000          # LEGACY_TRIAL_COUNT, frozen with the champion registration
    GRADE = "MODEL"

    #: data artifacts the component itself requires, relative to BASE. ONLY the slate psv:
    #: the frozen backfill store (pitchers.csv / pitcher logs / results.csv /
    #: park_factors.json) is NOT in this checkout, so the caller resolves starters and
    #: team form from the governed LiveStore (byte-verified fetched season stats; feature
    #: provenance recorded per game) and park factors are DECLARED ABSENT — v13 then runs
    #: WITHOUT park adjustment (pf=None -> 1.0 inside v13_sim; declared in provenance).
    #: R1: no park factor is ever invented.
    DATA_ARTIFACTS = ("data/mlb/slates/{date}_slate.psv",)

    #: park factor artifact, checked honestly: when absent the component declares
    #: "no park adjustment" rather than failing or inventing factors.
    PARK_FACTORS = "data/backfill/mlb/2026/park_factors.json"

    def __init__(self, v13_module=None, bf_module=None, require_data_artifacts=True):
        self._V13 = v13_module
        self._BF = bf_module
        self._require_data_flag = require_data_artifacts

    def _load_engine(self):
        if self._V13 is None:
            try:
                import run_v13_historical as V13
            except Exception:
                raise ArmUnavailableError(
                    self.ARM_ID,
                    "harness/run_v13_historical.py (registered CHAMPION_V13 engine module "
                    "— not in this checkout)")
            mod_file = str(getattr(V13, "__file__", "") or "")
            mod_id = str(getattr(V13, "MODULE_ID", "") or "")
            if "stub" in mod_id.lower() or "stubs" in mod_file.replace("\\", "/").split("/"):
                raise ArmUnavailableError(
                    self.ARM_ID,
                    "harness/run_v13_historical.py (only the tests/stubs shadow exists; "
                    "the registered engine module is not in this checkout)")
            self._V13 = V13
        return self._V13

    def _load_bf(self):
        if self._BF is None:
            import board_freshness as BF
            self._BF = BF
        return self._BF

    def _require_data(self, date):
        for tmpl in self.DATA_ARTIFACTS:
            p = tmpl.format(date=date)
            if not os.path.isfile(os.path.join(BASE, p)):
                raise ArmUnavailableError(self.ARM_ID, p)

    #: league-default starter dict — v13's own _sp({}) cap convention. A slot whose
    #: disposition is not fresh+confirmed runs on THIS, never on stale/unconfirmed
    #: measured rates (freshness-p0 H2).
    LEAGUE_DEFAULT_SP = {"era": None, "gs": 0, "k": None, "bb": None}

    @classmethod
    def _gate_starter(cls, sp, disposition, side):
        """(sp_dict_for_v13, routing_record). Measured rates enter v13 ONLY when the
        slot's freshness disposition is fresh/confirmed per the frozen contract
        (FRESH or ACQUIRING with grade CONFIRMED). Anything else — DEGRADED, ABSENT,
        or FRESH but identity-unconfirmed (IDENTIFIED_UNCONFIRMED) — is rerouted to
        the league-default dict and the reroute is recorded for provenance."""
        if hasattr(disposition, "disposition"):
            disp, grade = disposition.disposition, disposition.grade
            subj = getattr(disposition, "subject", None)
        else:
            disp, grade = disposition.get("disposition"), disposition.get("grade")
            subj = disposition.get("subject")
        confirmed = disp in ("FRESH", "ACQUIRING") and grade == "CONFIRMED"
        if confirmed:
            return sp, {"side": side, "subject": subj, "disposition": disp,
                        "grade": grade, "rates_used": "measured (fresh/confirmed)"}
        return (dict(cls.LEAGUE_DEFAULT_SP),
                {"side": side, "subject": subj, "disposition": disp, "grade": grade,
                 "rates_used": ("LEAGUE_DEFAULT_REROUTE: disposition "
                                f"{disp}/{grade} is not fresh+confirmed, so measured "
                                "rates were withheld from v13 and the slot ran on "
                                "v13's league-default _sp({}) cap convention "
                                "(freshness-p0 H2)")})

    @staticmethod
    def _seed(date, game_id):
        try:
            import keyed_seed as KS
            return KS.seed_for(f"mlb.winner.CHAMPION_V13.{MLBV13Component.TRIALS}",
                               date, game_id, "v13_1")
        except Exception:
            import mc_engine
            return mc_engine.seed_for(
                f"mlb.winner.CHAMPION_V13.{MLBV13Component.TRIALS}", date, game_id, "v13_1")

    def predict(self, date, game_id, sp_away, sp_home, rf_ra_away, rf_ra_home,
                park_factor, starter_dispositions, feature_provenance=None):
        """One game -> {source, grade, arm, p_home, total, dose, provenance}.

        starter_dispositions: [disp_away, disp_home] from the board row (freshness contract
        dicts or Disposition objects); the cohort information_dose is their contract
        product. An OFFICIAL_TBD_CAP slot arrives as a league-default sp dict ({era: None,
        gs: 0, k: None, bb: None} — v13's own _sp({}) cap convention) plus a reduced-dose
        disposition: v13 runs the game honestly on league defaults and the dose carries
        the penalty; nothing is fabricated and the game is NOT skipped.
        feature_provenance: optional caller-supplied dict describing how the sp/rf/ra
        features were resolved (echoed into provenance). NO market parameters — firewall
        asserted.
        """
        assert_firewall_signature(self.predict, self.ARM_ID)
        V13 = self._load_engine()
        if self._require_data_flag:
            self._require_data(date)
        BF = self._load_bf()
        dose = BF.game_dose(starter_dispositions)
        # GOING-FORWARD FIX (freshness-p0 H2, 2026-08-30): a starter slot whose
        # freshness disposition is NOT fresh+confirmed (stale beyond MAX_AGE, ABSENT,
        # or identity-unconfirmed — e.g. a historical game-log/season-stats stamp
        # that attests rates but never tonight's starter) must NOT inject its
        # measured rates into v13. Previously the only consequence was the
        # multiplicative dose shrink while the stale rates still drove the sim.
        # Such a slot is rerouted to the SAME league-default path as an absent
        # starter ({era: None, gs: 0, k: None, bb: None} — v13's own _sp({}) cap
        # convention) and the reroute is recorded in provenance. R3: this changes
        # nothing frozen; it governs the going-forward builder path only.
        sp_away, route_away = self._gate_starter(sp_away, starter_dispositions[0], "away")
        sp_home, route_home = self._gate_starter(sp_home, starter_dispositions[1], "home")
        seed = self._seed(date, game_id)
        sim = V13.v13_sim(sp_away, sp_home, rf_ra_away[0], rf_ra_away[1],
                          rf_ra_home[0], rf_ra_home[1], park_factor, seed, self.TRIALS)
        park_note = ("park factor applied from data/backfill/mlb/2026/park_factors.json"
                     if park_factor is not None else
                     "NO PARK ADJUSTMENT: data/backfill/mlb/2026/park_factors.json is absent "
                     "from this checkout, so v13 runs with pf=None (no park adjustment). "
                     "Declared, not hidden — R1: no park factor is invented.")
        prov = {"model": self.ARM_ID, "simulation_trials": self.TRIALS,
                "simulation_seed": seed, "simulation_version": "v13_1",
                "v13_mc_se": sim.get("mc_se"),
                "park_factor": park_note,
                "dose_note": ("starter-cohort information_dose "
                              "(board_freshness.game_dose: multiplicative, "
                              "0.20-floored by the frozen contract)"),
                "starter_routing": [route_away, route_home]}
        if feature_provenance is not None:
            prov["feature_provenance"] = feature_provenance
        out = {"source": self.SOURCE, "grade": self.GRADE, "arm": self.ARM_ID,
               "p_home": float(sim["p_home"]), "total": float(sim["proj_total"]),
               "dose": float(dose), "provenance": prov}
        return assert_no_market_fields(out, self.ARM_ID)


# ------------------------------------------------------------------ MLB interim runs arm

class MLBInterimComponent:
    """INTERIM, UNVALIDATED MLB runs-based arm — NOT v13, and never labeled as v13.

    SUPERSEDED (2026-08-30, owner review): the registered CHAMPION_V13 engine module
    (harness/run_v13_historical.py) is now in this checkout and MLBV13Component is the
    MLB component (label MODEL, arm mlb.winner.CHAMPION_V13). This interim arm remains
    available BEHIND A FLAG (build_slate_arm_restore.py --interim) with its UNVALIDATED
    label, untouched. Owner's reproducibility point: the interim path's 108 network
    fetches are NOT reproducible under AcquisitionDisabled environments — the v13 path
    uses static delivered artifacts + the governed store, which is why it is the
    registered path.

    WHY THIS EXISTS (historical). The registered CHAMPION_V13 engine
    (run_v13_historical.py) was absent from this checkout when this component was written;
    v13 was never reimplemented or impersonated. This component is a
    transparent, declared-formula runs model over real StatsAPI data so the MLB slate was
    not numberless while v13 was unavailable. Every row it touches carries
    GRADE="MODEL_INTERIM_UNVALIDATED" and card language "interim, unvalidated".

    FORMULA (declared; coefficients are JUDGMENT, not fitted — stated here, argued with
    the reason, not the number):
        L        = league runs per team-game (computed from fetched standings)
        off_T    = (RF_T / G_T) / L              offensive factor vs league
        def_T    = (RA_T / G_T) / L              run-prevention factor vs league
        sp_T     = ERA_SP_T / L                  starter factor vs league scoring
                   (ERA is earned runs per 9 innings = per game, the same scale as L)
        stuff_T  = 1 + STUFF_COEF * (refK9 - K9_SP_T)/refK9
                     + STUFF_COEF * (BB9_SP_T - refBB9)/refBB9     clamped to STUFF_CLAMP
        runs_H   = L * off_H * ((1-SP_WEIGHT)*def_A + SP_WEIGHT*sp_A) * stuff_A * HOME_MULT
        runs_A   = L * off_A * ((1-SP_WEIGHT)*def_H + SP_WEIGHT*sp_H) * stuff_H / HOME_MULT
        total    = runs_H + runs_A ; mov_home = runs_H - runs_A
    SP_WEIGHT = 0.5 (a starter faces roughly half the opponent's plate appearances — a
    declared judgment, not a measurement); STUFF_COEF = 0.05 judgment; HOME_MULT = 1.02
    judgment (historical home edge exists; its size here is judgment); refK9/refBB9 are
    the NAIVE-IP-weighted means over the FULL FETCHED probable-starter pool (declared
    reference — a starter-pool mean, not a league mean, because only the starter pool is
    fetched). NAIVE IP convention, stated explicitly: inningsPitched is used as the
    decimal number StatsAPI reports (e.g. "133.2" is 133.2, NOT 133 + 2/3 outs). The
    pool is the COMPLETE set of pitchers fetched during the build, frozen before any
    game is priced (reference_rates_from_pool iterates pitcher ids in sorted order so
    the float accumulation order is fixed and bit-reproducible).
    PARK FACTOR: OMITTED — no real park run-factor data is fetched (StatsAPI venues carry
    no run factors), so no park adjustment is applied and this says so. R1: no invented
    constants beyond the judgment coefficients declared above.

    DATA. Only via the approved acquisition chain (acquisition.MLBStatsAPIAdapter with an
    explicitly injected http_get; the default fetcher refuses). The caller supplies a
    `provider` exposing team_form() / reference_rates() / probables(date); every fetch is
    stamped and LiveStore-logged by the caller. Any missing real input raises
    ArmUnavailableError naming the exact gap — nothing is defaulted (R1).

    Firewall: no market parameters; output carries no market fields.
    """

    SOURCE = "mlb_interim_runs"
    ARM_ID = "mlb.interim.runs_sp_adjusted.v0_unvalidated"
    GRADE = "MODEL_INTERIM_UNVALIDATED"
    CARD_LANGUAGE = "interim, unvalidated"

    SP_WEIGHT = 0.5            # judgment, declared
    STUFF_COEF = 0.05          # judgment, declared
    STUFF_CLAMP = (0.90, 1.10) # judgment, declared
    HOME_MULT = 1.02           # judgment, declared
    PARK_FACTOR = None         # OMITTED — no real park data fetched; documented, not hidden

    @staticmethod
    def _clamp(x, lo, hi):
        return max(lo, min(hi, x))

    @classmethod
    def expected_runs(cls, off, def_opp, sp_opp, stuff_opp, lg, home):
        """One side's expected runs under the declared formula. Pure; deterministic."""
        adj = (1 - cls.SP_WEIGHT) * def_opp + cls.SP_WEIGHT * sp_opp
        x = lg * off * adj * stuff_opp
        return x * cls.HOME_MULT if home else x / cls.HOME_MULT

    @staticmethod
    def sp_stats_from_season_stat(stat):
        """One StatsAPI season pitching `stat` dict -> {"era","k9","bb9","ip"}.

        NAIVE IP: float(stat["inningsPitched"]) — the decimal number as reported
        ("133.2" = 133.2). K9/BB9 derived from raw strikeOuts/baseOnBalls over that IP.
        Raises KeyError/ValueError/ZeroDivisionError on an unusable split (R1: caller
        degrades honestly; nothing is defaulted)."""
        ip = float(stat["inningsPitched"])
        return {"era": float(stat["era"]),
                "k9": float(stat["strikeOuts"]) / ip * 9.0,
                "bb9": float(stat["baseOnBalls"]) / ip * 9.0, "ip": ip}

    @classmethod
    def sp_stats_from_body(cls, body):
        """Decoded StatsAPI body for people/{id}/stats?stats=season&group=pitching ->
        season stat dict via the same split selection as the acquisition adapter
        (first split across all stats groups), then sp_stats_from_season_stat."""
        splits = []
        for grp in body.get("stats") or []:
            splits.extend(grp.get("splits") or [])
        if not splits:
            raise ValueError("no pitching splits in payload")
        return cls.sp_stats_from_season_stat(splits[0].get("stat") or {})

    @staticmethod
    def reference_rates_from_pool(sp_by_pid):
        """(ref_k9, ref_bb9) = NAIVE-IP-weighted mean over the fetched probable-starter
        pool. sp_by_pid: {int pitcher_id: {"k9","bb9","ip",...}}. Iterates pitcher ids in
        sorted order so the float accumulation order is fixed and the result is
        bit-reproducible by an independent recomputation over the same pool."""
        num_k = num_b = num_ip = 0.0
        for pid in sorted(sp_by_pid):
            sp = sp_by_pid[pid]
            num_k += sp["k9"] * sp["ip"]
            num_b += sp["bb9"] * sp["ip"]
            num_ip += sp["ip"]
        if num_ip <= 0:
            raise ValueError("reference K9/BB9: empty pool — no fetched starter season "
                             "stats to weight")
        return num_k / num_ip, num_b / num_ip

    @classmethod
    def stuff_factor(cls, k9, bb9, ref_k9, ref_bb9):
        s = (1 + cls.STUFF_COEF * (ref_k9 - k9) / ref_k9
             + cls.STUFF_COEF * (bb9 - ref_bb9) / ref_bb9)
        return cls._clamp(s, *cls.STUFF_CLAMP)

    def predict(self, date, away, home, provider, starter_dispositions):
        """One game -> {source, grade, arm, mov_home, total, dose, provenance}.

        provider: injected data access object (real acquisition or a test double) with
          team_form()  -> {team_id: {"abbr", "rf_pg", "ra_pg", "games"}}
          reference_rates() -> {"lg_runs_pg", "ref_k9", "ref_bb9"}
          probables(date) -> {(away_abbr, home_abbr): {"away_sp": {...}|None,
                             "home_sp": {...}|None, "game_pk": int, "game_date": str}}
          sp stats dicts carry era/k9/bb9/ip (real fetched season numbers).
        starter_dispositions: [disp_away, disp_home] freshness-contract dicts; the dose is
          board_freshness.game_dose over them (multiplicative, 0.20-floored by contract).
        """
        assert_firewall_signature(self.predict, self.ARM_ID)
        form = provider.team_form()
        ref = provider.reference_rates()
        prob = provider.probables(date)
        entry = prob.get((away, home))
        if entry is None:
            raise ArmUnavailableError(
                self.ARM_ID, f"StatsAPI probable-pitcher slate entry for {away}@{home} on "
                f"{date}", detail="no real slate entry — no number may be substituted (R1)")
        by_abbr = {v["abbr"]: v for v in form.values()}
        missing = [t for t in (away, home) if t not in by_abbr]
        if missing:
            raise ArmUnavailableError(self.ARM_ID,
                                      f"standings team_form rows for {missing}")
        for side in ("away_sp", "home_sp"):
            if entry.get(side) is None:
                raise ArmUnavailableError(
                    self.ARM_ID,
                    f"{side} probable pitcher in StatsAPI slate entry "
                    f"{entry.get('game_pk')} for {away}@{home}",
                    detail="probable pitcher not named (TBD) — no invented fill (R1)")
        fa, fh = by_abbr[away], by_abbr[home]
        lg = float(ref["lg_runs_pg"])
        sa, sh = entry["away_sp"], entry["home_sp"]
        stuff_a = self.stuff_factor(sa["k9"], sa["bb9"], ref["ref_k9"], ref["ref_bb9"])
        stuff_h = self.stuff_factor(sh["k9"], sh["bb9"], ref["ref_k9"], ref["ref_bb9"])
        # home scoring is opposed by the AWAY starter (sp/stuff), and vice versa
        runs_h = self.expected_runs(fh["rf_pg"] / lg, fa["ra_pg"] / lg,
                                    sa["era"] / lg, stuff_a, lg, home=True)
        runs_a = self.expected_runs(fa["rf_pg"] / lg, fh["ra_pg"] / lg,
                                    sh["era"] / lg, stuff_h, lg, home=False)
        BF = _load_board_freshness()
        dose = BF.game_dose(starter_dispositions)
        out = {"source": self.SOURCE, "grade": self.GRADE, "arm": self.ARM_ID,
               "mov_home": float(runs_h - runs_a), "total": float(runs_h + runs_a),
               "dose": float(dose),
               "card_language": self.CARD_LANGUAGE,
               "provenance": {
                   "model": self.ARM_ID, "card_language": self.CARD_LANGUAGE,
                   "formula": ("declared multiplicative runs model (see mc_components "
                               "MLBInterimComponent docstring); coefficients are JUDGMENT, "
                               "not fitted: SP_WEIGHT=0.5, STUFF_COEF=0.05, HOME_MULT=1.02"),
                   "park_factor": ("OMITTED — no real park run-factor data fetched; no park "
                                   "adjustment applied"),
                   "reference_rates": dict(ref),
                   "sp_away": {"name": sa.get("name"), "era": sa["era"], "k9": sa["k9"],
                               "bb9": sa["bb9"], "ip": sa.get("ip")},
                   "sp_home": {"name": sh.get("name"), "era": sh["era"], "k9": sh["k9"],
                               "bb9": sh["bb9"], "ip": sh.get("ip")},
                   "team_form_games": {away: fa["games"], home: fh["games"]},
                   "expected_runs": {"home": round(runs_h, 4), "away": round(runs_a, 4)},
                   "dose_note": ("starter-cohort information_dose "
                                 "(board_freshness.game_dose: multiplicative, 0.20-floored "
                                 "by the frozen contract)")}}
        return assert_no_market_fields(out, self.ARM_ID)


def _load_board_freshness():
    import board_freshness as BF
    return BF


# ------------------------------------------------------------------ CFB house lean arm

class CFBHouseComponent:
    """The registered CFB Week-1 house arm as a component: Elo + context lean
    (cfb.fbs.elo_context_logit.v1_0.week1_shadow), so CFB MOVs are COMPUTED, never
    hand-relayed.

    Resolution order, honest at each rung:
      1. LIVE: run harness/cfb_forecast_0829.build() — only when its real dependencies
         exist in this checkout (the real cfb_v1_port archive module, the 2026 team-info
         parquet, the owner-relay fixture file). The MOV is projected_margin_home from the
         registered lean arm's own fit.
      2. FROZEN ARTIFACT: read the frozen registered board for the slate date
         (cards/<date>_cfb_board.json, or its byte-identical committed audit fixture
         data/audit/cfb_board_output_prev.json). Those margins were computed by the same
         registered arm at freeze time — a computed artifact, not a relay.
      3. Otherwise raise ArmUnavailableError naming the exact missing artifact.

    Team names are matched against board rows by the forecast module's diacritic-folding
    normalizer; an unmatched game raises rather than guessing an identity.
    """

    SOURCE = "cfb_house"
    ARM_ID = "cfb.fbs.elo_context_logit.v1_0.week1_shadow"
    GRADE = "MODEL"

    FROZEN_BOARD = "cards/{date}_cfb_board.json"
    AUDIT_FIXTURE = "data/audit/cfb_board_output_prev.json"

    def __init__(self, forecast_module=None, frozen_board_paths=None):
        self._F = forecast_module
        self._frozen_paths = frozen_board_paths  # test injection point

    def _live_prereqs(self, F):
        """None if the live arm can run, else the exact missing artifact path."""
        try:
            import cfb_v1_port as V1
        except Exception:
            return "harness/cfb_v1_port.py (registered V1 archive port — not in this checkout)"
        if "stub" in str(getattr(V1, "MODULE_ID", "")).lower():
            return ("harness/cfb_v1_port.py (only the tests/stubs shadow exists; the "
                    "registered V1 archive port is not in this checkout)")
        for p in (F.TEAM_INFO_2026, F.RELAY):
            if not os.path.isfile(p if os.path.isabs(p) else os.path.join(BASE, p)):
                return p
        return None

    def _load_forecast(self):
        """Import cfb_forecast_0829 if possible; its absence disables only the LIVE rung —
        the frozen-board rung needs nothing but the JSON artifact and the normalizer."""
        if self._F is None and not getattr(self, "_F_failed", None):
            try:
                import cfb_forecast_0829 as F
                self._F = F
            except Exception as e:
                self._F_failed = str(e)
        return self._F

    @staticmethod
    def _norm_local(name):
        """Same diacritic/punctuation fold as cfb_forecast_0829._norm (kept in lockstep so
        the frozen-board rung matches team names identically when the forecast module's own
        heavy imports are unavailable in this checkout)."""
        import re
        import unicodedata
        x = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]", "", x.lower())

    def _norm(self, name):
        F = self._load_forecast()
        return F._norm(name) if F is not None else self._norm_local(name)

    @staticmethod
    def _board_rows(board):
        # contract shape going forward: board["cfb"]["rows"]; the frozen 8/29 board keeps
        # board["rows"] forever (R3) — read either, never rewrite.
        if isinstance(board.get("cfb"), dict) and "rows" in board["cfb"]:
            return board["cfb"]["rows"]
        return board.get("rows") or []

    def _frozen_paths_for(self, date):
        if self._frozen_paths is not None:
            return list(self._frozen_paths)
        return [self.FROZEN_BOARD.format(date=date), self.AUDIT_FIXTURE]

    def _find_row(self, rows, away, home):
        na, nh = self._norm(away), self._norm(home)
        for r in rows:
            if self._norm(r.get("away", "")) == na and self._norm(r.get("home", "")) == nh:
                return r
        return None

    def predict(self, date, away, home):
        """One game -> {source, grade, arm, mov_home, dose, provenance}. No market params."""
        assert_firewall_signature(self.predict, self.ARM_ID)
        F = self._load_forecast()
        if self._frozen_paths is not None:
            missing = "(live path disabled by injected frozen_board_paths)"
        elif F is None:
            missing = f"harness/cfb_forecast_0829.py (import failed: {self._F_failed})"
        else:
            missing = self._live_prereqs(F)
        row, via = None, None
        if missing is None:
            board = F.build()
            row = self._find_row(self._board_rows(board), away, home)
            via = ("LIVE cfb_forecast_0829.build() — lean arm refit on the registered "
                   "archive at call time")
        else:
            for p in self._frozen_paths_for(date):
                fp = p if os.path.isabs(p) else os.path.join(BASE, p)
                if not os.path.isfile(fp):
                    continue
                board = json.load(open(fp))
                row = self._find_row(self._board_rows(board), away, home)
                via = (f"FROZEN registered board {p} (computed by {self.ARM_ID} at freeze "
                       f"time; live path unavailable: missing {missing})")
                if row is not None:
                    break
        if row is None:
            if via is None:
                tried = ", ".join(self._frozen_paths_for(date))
                raise ArmUnavailableError(
                    self.ARM_ID, tried,
                    detail=f"no frozen registered board exists and the live arm cannot "
                           f"run ({missing}) — no number may be substituted (R1)")
            raise ArmUnavailableError(
                self.ARM_ID, f"row for {away} @ {home} in {via.split('(')[0].strip()}",
                detail="the registered CFB arm produced no forecast for this game and no "
                       "number may be substituted (R1)")
        disp = row.get("input_freshness") or {}
        dose = disp.get("dose_multiplier")
        dose_note = ("input_freshness.dose_multiplier from the board row"
                     if dose is not None else
                     "frozen board row carries no information dose (CFB rows are "
                     "freshness-additive only) — dose 1.0 declared, not computed")
        out = {"source": self.SOURCE, "grade": self.GRADE, "arm": self.ARM_ID,
               "mov_home": float(row["projected_margin_home"]),
               "dose": float(dose) if dose is not None else 1.0,
               "provenance": {"model": self.ARM_ID, "via": via, "dose_note": dose_note,
                              # the arm's own win prob travels as provenance only: the
                              # engine maps mov_home through the frozen CFB_MARGIN_SD so
                              # one coherence convention applies to every mov component
                              "arm_p_home": float(row["p_home"])}}
        return assert_no_market_fields(out, self.ARM_ID)


# ------------------------------------------------------------------ NFL: structural only

class NFLComponent:
    """Declared so the engine structure is NFL-ready — and it REFUSES.

    nfl.v0_2.shadow has no live authority: no validated NFL arm exists, so no NFL
    component output may be emitted. The frozen priors NFL_MARGIN_SD / NFL_TOTAL_SD are
    declared at module level so the structure is ready the day an arm earns authority;
    until then predict() raises, loudly, with the reason.
    """

    SOURCE = "nfl"
    ARM_ID = "nfl.v0_2.shadow"
    REFUSAL_REASON = ("nfl.v0_2.shadow has NO LIVE AUTHORITY: the arm is a preregistered "
                      "shadow with no validated walk-forward and no wager authority; "
                      "emitting an NFL component would be fabricating an arm output (R1). "
                      "NFL_MARGIN_SD=13.8 / NFL_TOTAL_SD=15.5 are declared frozen priors "
                      "for engine structure only.")

    def predict(self, *args, **kwargs):
        raise NFLComponentRefused(f"NFL_REFUSAL: {self.REFUSAL_REASON}")


# ------------------------------------------------------------------ dose helper

def _dose_from_board_row(board_row, freshness_key):
    """(dose, note) from a board row's freshness-contract disposition.

    The disposition's dose_multiplier is the contract's number; this helper contains no
    arithmetic of its own. A missing board row means no freshness evidence was supplied —
    dose 1.0 is declared as such, never presented as computed.
    """
    if not board_row:
        return 1.0, ("no board row supplied — dose 1.0 declared (no freshness evidence "
                     "presented to the adapter)")
    disp = board_row.get(freshness_key) or {}
    dose = disp.get("dose_multiplier")
    if dose is None:
        return 1.0, (f"board row carries no {freshness_key}.dose_multiplier — dose 1.0 "
                     "declared")
    return float(dose), f"{freshness_key}.dose_multiplier from the board row"


__all__ = ["WNBAFF7Component", "MLBV13Component", "MLBInterimComponent",
           "CFBHouseComponent", "NFLComponent",
           "ArmUnavailableError", "NFLComponentRefused", "assert_no_market_fields",
           "assert_firewall_signature", "NFL_MARGIN_SD", "NFL_TOTAL_SD",
           "WNBA_MARGIN_SD_FROZEN", "MODULE_ID"]
