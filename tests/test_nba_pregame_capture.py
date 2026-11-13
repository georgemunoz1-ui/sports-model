"""Synthetic contract tests, not provider captures or predictive evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import nba_pregame_capture as c
from research.nba_forecast_combination import audit, fit

NOW = "2026-10-30T18:00:00+00:00"
START = "2026-10-30T23:00:00+00:00"
METHOD = b"<p>2026-27: the current model's first live season.</p>"


def schedule():
    competitors = [{"homeAway": side, "team": {"id": tid, "abbreviation": alias}}
                   for side, tid, alias in (("home", "27", "WSH"), ("away", "30", "CHA"))]
    return {"leagues": [{"abbreviation": "NBA"}], "events": [{"id": "synth1", "date": START,
            "season": {"year": 2027}, "competitions": [{"date": START, "competitors": competitors,
            "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre"}}}]}]}


def projection():
    return dict(game_id=99999, home_alias="WAS", away_alias="CHA", season=2027,
                home_team_id=1610612764, away_team_id=1610612766,
                game_dttm="2026-10-30 19:00:00", update_dt="2026-10-30T17:00:00Z",
                status_id=1, p_home_score=114.5, p_away_score=112., p_home_mov=2.5)


def public(rec=None, access=0):
    rec = rec or projection()
    if not access: rec = dict(rec, p_home_score=None, p_away_score=None, p_home_mov=None)
    return ("<script>games:[{" + ",".join(k+":"+json.dumps(v) for k, v in rec.items()) + "}],has_access:" + str(access) + "</script>").encode()


def baseline():
    return dict(league="NBA", as_of_utc="2026-10-30T12:00:00Z", generated_at_utc="2026-10-30T12:01:00Z",
                forecasts=[dict(event_id="NBA:synth1", home_id="27", away_id="30", start_time_utc=START,
                model_id="nba.fixed_parent.synthetic.research", diagnostics={"home_margin": -1.5},
                forecast_procedure_id="synthetic", input_snapshot_hash="synthetic", model_state_config_hash="synthetic",
                numerical_identity=dict(identity_sha256="synthetic", event_id="NBA:synth1",
                    model_id="nba.fixed_parent.synthetic.research", cutoff_utc="2026-10-30T12:00:00Z", start_time_utc=START))])


def dom():
    return dict(url=c.DB, title="NBA Team Stats - Six Factor Analysis | databallr",
                page_text="Six Factor Analysis • 2026-27 Season; calculated directly from box-score components; positive values are good for OFF, DEF, Net, and all six factor components",
                controls=[dict(text=x, html="text-primary-foreground") for x in ("NBA", "Full Season", "Overall")]
                  + [dict(text=x, html="bg-muted/80") for x in ("2026-27", "All", "Per 100")],
                sliders=[dict(value="0"), dict(value="0")],
                table_rows=[["Team", *c.FACTORS]]+[[t, *[f"+{i}.1\n#2" for i in range(6)]] for t in c.TEAMS],
                observed_start="2000-01-01T00:00:00Z", observed_end="2000-01-01T00:00:00Z")


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.b0 = self.parent / "original.json"; self.b0.write_bytes(c.encoded(baseline()))
        self.db = self.parent / "dom.json"; self.db.write_bytes(c.encoded(dom()))
        self.schedule = schedule(); self.rec = projection(); self.status = 200

    def transport(self, url, credential=None):
        if url.startswith(c.ESPN): raw = c.encoded(self.schedule)
        elif "/game-predictions?" in url: raw = c.encoded([self.rec])
        elif "/games?" in url: raw = public()
        elif url.endswith("/about/epm"): raw = METHOD
        elif url == c.DB: raw = b"<html><div id='root'></div></html>"
        else: raise AssertionError(url)
        return c.Response(raw, self.status, {"Date": NOW, "Set-Cookie": "never retain", "Authorization": "never retain"}, url)

    def capture(self, *, api=False, clock=lambda: NOW, name="capture", db=True):
        with patch.dict("os.environ", {"DUNKS_AND_THREES_API_KEY": "SYNTHETIC_TOKEN"} if api else {}, clear=True):
            report = c.run_capture(self.parent/name, "2026-10-30", baseline=self.b0,
                        databallr_dom=self.db if db else None, use_dt_api=api, transport=self.transport, clock=clock)
        root = self.parent/name
        return root, report, json.loads((root/"dataset.json").read_text())["rows"]

    def rebind(self, root, source):
        raw = c.encoded(source["payload"])
        (root/source["artifact_path"]).write_bytes(raw)
        source["artifact_hash"] = c.digest(raw)

    def test_genuine_shape_end_to_end_missing_public_predictions(self):
        root, report, rows = self.capture()
        self.assertEqual(report["events"], 1)
        self.assertEqual(report["baseline_preserved"], 1)
        self.assertEqual(report["databallr_event_pairs"], 1)
        self.assertEqual(report["source_eligible"], {"C1": 0, "C2": 0})
        self.assertIn("SUBSCRIPTION_REQUIRED", rows[0]["source_states"]["B1"])
        self.assertEqual(rows[0]["sources"]["B0"]["payload"]["original_forecast"], baseline()["forecasts"][0])

    def test_documented_api_with_aware_clock_is_c1_source_eligible(self):
        root, report, rows = self.capture(api=True)
        self.assertEqual(report["source_eligible"], {"C1": 1, "C2": 0})
        self.assertEqual(report["fitting_eligible"], 0)
        self.assertEqual(rows[0]["sources"]["B1"]["payload"]["values"]["home_margin"], 2.5)

    def test_fit_still_blocks_without_outcome_or_100_events(self):
        root, report, rows = self.capture(api=True)
        protocol = json.loads(Path("data/research/nba_forecast_combination_v1/protocol.json").read_text())
        result = fit(rows, root, protocol, "2026-10-31T12:00:00Z")
        self.assertFalse(result["fitted"])
        self.assertEqual(result["status"], "BLOCKED_INSUFFICIENT_ELIGIBLE_EVENTS")

    def test_naive_provider_clock_never_inferred(self):
        self.rec["update_dt"] = "2026-10-30 13:00:00"
        root, report, rows = self.capture(api=True)
        self.assertEqual(report["source_eligible"]["C1"], 0)
        self.assertIsNone(rows[0]["sources"]["B1"]["payload"]["source_as_of"])

    def test_dom_claimed_old_time_not_promoted(self):
        root, report, rows = self.capture()
        payload = rows[0]["sources"]["databallr"]["payload"]
        self.assertEqual(payload["captured_at"], NOW)
        self.assertIsNone(payload["source_as_of"])

    def test_late_capture_is_excluded(self):
        root, report, rows = self.capture(api=True, clock=lambda: "2026-10-30T23:01:00Z")
        self.assertEqual(report["pregame_opportunities"], 0)
        self.assertEqual(report["source_eligible"]["C1"], 0)
        self.assertIn("POST_START", rows[0]["opportunity_exclusions"])

    def test_last_five_minutes_are_after_deadline(self):
        root, report, rows = self.capture(api=True, clock=lambda: "2026-10-30T22:56:00Z")
        self.assertEqual(report["source_eligible"]["C1"], 0)
        self.assertIn("AFTER_CAPTURE_DEADLINE", rows[0]["opportunity_exclusions"])

    def test_started_or_postponed_schedule_not_eligible(self):
        for name in ("STATUS_IN_PROGRESS", "STATUS_POSTPONED"):
            with self.subTest(name=name):
                self.schedule["events"][0]["competitions"][0]["status"]["type"]["name"] = name
                root, report, rows = self.capture(api=True, name=name)
                self.assertEqual(report["source_eligible"]["C1"], 0)

    def test_future_provider_timestamp_is_excluded(self):
        self.rec["update_dt"] = "2026-10-30T20:00:00Z"
        root, report, rows = self.capture(api=True)
        self.assertEqual(report["source_eligible"]["C1"], 0)

    def test_api_final_record_never_used_as_pregame(self):
        self.rec["status_id"] = 3
        root, report, rows = self.capture(api=True)
        self.assertEqual(report["source_eligible"]["C1"], 0)

    def test_wrong_team_id_or_season_rejected(self):
        for key, value in (("home_team_id", 1610612738), ("season", 2026)):
            self.rec = projection(); self.rec[key] = value
            root, report, rows = self.capture(api=True, name=key)
            self.assertNotIn("B1", rows[0]["sources"])

    def test_margin_score_conflict_not_eligible(self):
        self.rec["p_home_mov"] = -2.5
        root, report, rows = self.capture(api=True)
        self.assertEqual(report["source_eligible"]["C1"], 0)

    def test_nonfinite_and_boolean_projection_rejected(self):
        for i, value in enumerate((True, float("nan"), float("inf"))):
            self.rec["p_home_mov"] = value
            root, report, rows = self.capture(api=True, name=str(i))
            self.assertEqual(report["source_eligible"]["C1"], 0)

    def test_duplicate_schedule_never_silently_deduplicated(self):
        self.schedule["events"] *= 2
        root, report, rows = self.capture(api=True)
        self.assertEqual(report["schedule_status"], "UNAVAILABLE_OR_INVALID")
        self.assertEqual(report["parser_errors"]["normalization"], "DUPLICATE_SCHEDULE_EVENT")

    def test_duplicate_provider_event_rejected(self):
        parsed = {"records": [self.rec, self.rec], "access": 1, "source": "documented_v2_api"}
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS"):
            c.dt_for_event(parsed, c.parse_schedule(c.encoded(self.schedule), "2026-10-30")[0], c.text_of(METHOD))

    def test_b0_wrong_head_rejected_without_changing_original(self):
        value = baseline(); value["forecasts"][0]["model_id"] = "nba.initial_causal_score.research.v1"
        self.b0.write_bytes(c.encoded(value)); before = self.b0.read_bytes()
        root, report, rows = self.capture()
        self.assertNotIn("B0", rows[0]["sources"])
        self.assertEqual(before, self.b0.read_bytes())

    def test_raw_tampering_rejected_by_real_experiment_audit(self):
        root, report, rows = self.capture(api=True)
        p = rows[0]["sources"]["B1"]["payload"]
        (root/p["raw_receipt"]["path"]).write_bytes(b"tampered")
        self.assertEqual(audit(rows, root)["eligible_events"], 0)

    def test_rehashed_normalized_values_still_require_raw_replay(self):
        root, report, rows = self.capture(api=True)
        source = rows[0]["sources"]["B1"]
        source["payload"]["values"]["home_margin"] = 99
        self.rebind(root, source)
        reasons = audit(rows, root)["records"][0]["exclusions"]
        self.assertIn("B1:CAPTURE_PROVENANCE:CAPTURE_EXTRACTION_MISMATCH:values", reasons)

    def test_rehashed_source_clock_or_generation_cannot_be_forged(self):
        for key, value in (("source_as_of", "2026-10-30T15:00:00Z"), ("source_model_version", "invented"), ("captured_at", "2026-10-30T14:00:00Z")):
            root, report, rows = self.capture(api=True, name=key)
            source = rows[0]["sources"]["B1"]; source["payload"][key] = value; self.rebind(root, source)
            self.assertEqual(audit(rows, root)["eligible_events"], 0)

    def test_rehashed_receipt_hash_is_not_sufficient_to_change_normalized_value(self):
        root, report, rows = self.capture(api=True)
        source = rows[0]["sources"]["B1"]
        source["payload"]["acquisition"]["receipt"]["captured_at"] = "2026-10-30T14:00:00Z"
        self.rebind(root, source)
        self.assertEqual(audit(rows, root)["eligible_events"], 0)

    def test_path_escape_and_symlink_refused(self):
        root, report, rows = self.capture(api=True)
        binding = deepcopy(report["captures"]["dt_api"]); binding["receipt_path"] = "../original.json"
        with self.assertRaisesRegex(ValueError, "UNSAFE_RELATIVE_PATH"): c.verified_raw(root, binding)
        (root/"outside").symlink_to(self.b0)
        with self.assertRaisesRegex(ValueError, "SYMLINK"): c.inside(root, "outside")

    def test_output_is_immutable_and_baseline_bytes_unchanged(self):
        before = self.b0.read_bytes()
        root, report, rows = self.capture()
        saved = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with self.assertRaises(FileExistsError): self.capture()
        self.assertEqual(before, self.b0.read_bytes())
        self.assertEqual(saved, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_auth_denial_preserved_and_no_secret_headers(self):
        self.status = 401
        root, report, rows = self.capture(api=True)
        self.assertEqual(report["captures"]["dt_api"]["receipt"]["status"], "ACCESS_DENIED")
        serialized = (root/"report.json").read_text()
        self.assertNotIn("SYNTHETIC_TOKEN", serialized)
        self.assertNotIn("never retain", serialized)

    def test_missing_api_key_no_authenticated_attempt(self):
        with patch.dict("os.environ", {}, clear=True):
            r = c.run_capture(self.parent/"missing", "2026-10-30", use_dt_api=True, transport=self.transport, clock=lambda: NOW)
        self.assertEqual(r["api_status"], "CREDENTIAL_NOT_CONFIGURED")
        self.assertNotIn("dt_api", r["captures"])

    def test_unapproved_urls_and_redirects_refused(self):
        for url in ("http://dunksandthrees.com/games", "https://dunksandthrees.com/games?token=secret", "https://evil.test/teams", "https://dunksandthrees.com/login"):
            with self.assertRaises(ValueError): c.approved_url(url)
        self.assertIsNone(c.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test"))

    def test_databallr_ranks_are_not_factor_values(self):
        values = c.parse_databallr_dom(c.encoded(dom()), 2027)
        self.assertEqual(values["BOS"]["dTS"], 3.1)

    def test_databallr_missing_duplicate_and_non_numeric_refused(self):
        for mode in ("missing", "duplicate", "numeric", "units", "luck", "semantics"):
            value = dom()
            if mode == "missing": value["table_rows"].pop()
            if mode == "duplicate": value["table_rows"].append(value["table_rows"][-1])
            if mode == "numeric": value["table_rows"][1][1] = "NaN"
            if mode == "units": value["controls"] = [x for x in value["controls"] if x["text"] != "Per 100"]
            if mode == "luck": value["sliders"][0]["value"] = "1"
            if mode == "semantics": value["page_text"] = "RAPM"
            with self.subTest(mode=mode), self.assertRaises(ValueError): c.parse_databallr_dom(c.encoded(value), 2027)

    def test_shell_remains_missing_not_zero_factors(self):
        root, report, rows = self.capture(db=False)
        self.assertNotIn("databallr", rows[0]["sources"])
        self.assertEqual(rows[0]["source_states"]["databallr"], "HTML_SHELL_ONLY_RENDERED_CAPTURE_REQUIRED")

    def test_original_sources_remain_separate_from_outcomes(self):
        root, report, rows = self.capture(api=True)
        self.assertIsNone(rows[0]["outcome"])
        self.assertFalse(report["coefficients_fitted"])
        self.assertFalse(report["canonical_registration"])
        self.assertEqual(report["wagering_authority"], "OFF")


if __name__ == "__main__": unittest.main()
