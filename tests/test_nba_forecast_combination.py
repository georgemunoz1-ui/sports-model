"""Synthetic engineering fixtures only: these are not predictive evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

import numpy as np

from research.nba_forecast_combination import (
    FACTOR_VERSION, FACTORS, FEATURES, SCHEMA, TARGET, audit, audit_row,
    digest, factor_features, fit, predict, timestamp,
)


class CombinationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = b"SYNTHETIC ENGINEERING FIXTURE, NOT A PROVIDER CAPTURE"
        (self.root / "raw.txt").write_bytes(self.raw)
        self.protocol = {"schema": SCHEMA, "target": TARGET, "frozen_at": "2020-01-01T00:00:00Z",
                         "alpha_ridge": 1e-8, "weight_ridge": 1e-8, "factor_ridge": 1.,
                         "weight_bounds": [0, 1], "features": list(FEATURES), "min_training_events": 3}
        self.rows = [self.row(i) for i in range(8)]
        self.end = "2021-02-01T00:00:00Z"

    def bind(self, payload, name):
        path = name + ".json"
        raw = json.dumps(payload, sort_keys=True).encode()
        (self.root / path).write_bytes(raw)
        return {"artifact_path": path, "artifact_hash": hashlib.sha256(raw).hexdigest(), "payload": deepcopy(payload)}

    def row(self, i):
        start = datetime(2021, 1, 1, 23, tzinfo=timezone.utc) + timedelta(days=i)
        row = {"event_id": "synthetic:"+str(i), "league": "NBA", "home": "BOS", "away": "CLE",
               "target": TARGET, "scheduled_start": start.isoformat(),
               "feature_cutoff": (start-timedelta(hours=1)).isoformat(), "evidence_population": "point_in_time_live", "sources": {}}
        base = {k: row[k] for k in ("event_id", "league", "home", "away", "target", "scheduled_start")}
        base.update({"historical_record_type": "live", "availability_basis": "captured_before_cutoff",
                     "source_as_of": (start-timedelta(hours=3)).isoformat(),
                     "captured_at": (start-timedelta(hours=2)).isoformat(),
                     "raw_receipt": {"path": "raw.txt", "sha256": hashlib.sha256(self.raw).hexdigest(), "extraction_review": "REVIEWED"}})
        for key, m in (("B0", 2.), ("B1", 2.+i-3.5)):
            payload = dict(base, source_model_version="synthetic."+key, forecast_identity=key+str(i), values={"home_margin": m})
            row["sources"][key] = self.bind(payload, key+str(i))
        factors = dict(base, source_model_version=FACTOR_VERSION, units="points_per_100_possessions", sign="positive_good",
                       values={"home_factors": {k: float(i) for k in FACTORS}, "away_factors": {k: 0. for k in FACTORS}})
        row["sources"]["databallr"] = self.bind(factors, "factors"+str(i))
        outcome = {k: row[k] for k in ("event_id", "league", "home", "away", "target")}
        outcome.update(home_margin=3.+.6*(i-3.5), available_at=(start+timedelta(hours=4)).isoformat(), status="FINAL")
        row["outcome"] = dict(self.bind(outcome, "outcome"+str(i)), **{k:outcome[k] for k in ("home_margin", "available_at", "status")})
        return row

    def rebind(self, row, key):
        row["sources"][key] = self.bind(row["sources"][key]["payload"], "changed"+row["event_id"].split(":")[1]+key)

    def test_fit_recovers_known_blend(self):
        s = fit(self.rows, self.root, self.protocol, self.end)
        self.assertAlmostEqual(s["alpha"], 1., places=6)
        self.assertAlmostEqual(s["weight"], .6, places=6)
        self.assertIsNone(s["probabilities"])

    def test_weight_constraints_both_boundaries(self):
        for slope, expected in ((3., 1.), (-2., 0.)):
            rows = deepcopy(self.rows)
            for i, r in enumerate(rows):
                p = r["outcome"]["payload"];p["home_margin"] = 3+slope*(i-3.5)
                r["outcome"] = dict(self.bind(p, "bound"+str(i)), **{k:p[k] for k in ("home_margin", "available_at", "status")})
            self.assertEqual(fit(rows, self.root, self.protocol, self.end)["weight"], expected)

    def test_regularization_shrinks_toward_baseline(self):
        p = dict(self.protocol, alpha_ridge=10., weight_ridge=100.)
        s = fit(self.rows, self.root, p, self.end)
        self.assertLess(s["alpha"], .1)
        self.assertLess(s["weight"], .1)

    def test_training_only_scaling(self):
        s = fit(self.rows, self.root, self.protocol, self.end, "C2")
        self.assertEqual(s["scaler"]["mean"], [7., 7., 7.])
        saved = deepcopy(s)
        predict(self.row(50), self.root, s, self.protocol)
        self.assertEqual(s, saved)

    def test_c2_compared_to_c1_on_same_population(self):
        c1 = fit(self.rows, self.root, self.protocol, self.end)
        c2 = fit(self.rows, self.root, self.protocol, self.end, "C2")
        self.assertEqual(c1["trained_events"], c2["trained_events"])
        self.assertEqual(c1["weight"], c2["weight"])

    def test_constant_factors_have_zero_adjustment(self):
        for r in self.rows:
            r["sources"]["databallr"]["payload"]["values"]["home_factors"] = dict.fromkeys(FACTORS, 1.)
            self.rebind(r, "databallr")
        s = fit(self.rows, self.root, self.protocol, self.end, "C2")
        self.assertEqual(s["gamma"], [0., 0., 0.])

    def test_c2_learns_increment_after_blend(self):
        for i,r in enumerate(self.rows):
            z=-1. if i%2==0 else 1.
            r["sources"]["B1"]["payload"]["values"]["home_margin"]=2.
            self.rebind(r,"B1")
            factors=dict.fromkeys(FACTORS,0.);factors["oTS"]=z
            r["sources"]["databallr"]["payload"]["values"]["home_factors"]=factors
            self.rebind(r,"databallr")
            op=r["outcome"]["payload"];op["home_margin"]=2.+2*z
            r["outcome"]=dict(self.bind(op,"increment"+str(i)),**{k:op[k] for k in ("home_margin","status","available_at")})
        s=fit(self.rows,self.root,self.protocol,self.end,"C2")
        self.assertAlmostEqual(s["alpha"],0.)
        self.assertEqual(s["weight"],0.)
        np.testing.assert_allclose(s["gamma"],[1.,0.,0.],atol=1e-12)

    def test_factor_orientation(self):
        p = deepcopy(self.rows[1]["sources"]["databallr"]["payload"])
        z = factor_features(p)
        p["values"]["home_factors"], p["values"]["away_factors"] = p["values"]["away_factors"], p["values"]["home_factors"]
        self.assertEqual(factor_features(p), [-v for v in z])

    def test_factor_semantics_rejected(self):
        for key, val in (("units", "percent"), ("sign", "negative_good"), ("source_model_version", "WNBA_VPM")):
            r = deepcopy(self.rows[0]);r["sources"]["databallr"]["payload"][key] = val;self.rebind(r,"databallr")
            self.assertIn("databallr:VALUES_INVALID", audit_row(r,self.root,"C2"))

    def test_missing_source_fallback_is_explicit(self):
        s = fit(self.rows,self.root,self.protocol,self.end)
        r = self.row(40);r["sources"].pop("B1")
        out = predict(r,self.root,s,self.protocol)
        self.assertEqual(out["emitted_stage"],"B0_FALLBACK")
        self.assertFalse(out["challenger_emitted"])

    def test_missing_base_never_fabricates_fallback(self):
        s = fit(self.rows,self.root,self.protocol,self.end)
        r = self.row(40);r["sources"].pop("B0")
        self.assertIsNone(predict(r,self.root,s,self.protocol)["home_margin"])

    def test_versions_not_pooled(self):
        self.rows[0]["sources"]["B1"]["payload"]["source_model_version"] = "earlier-live-model"
        self.rebind(self.rows[0],"B1")
        with self.assertRaisesRegex(ValueError,"MIXED_SOURCE_VERSION"):
            fit(self.rows,self.root,self.protocol,self.end)

    def test_unknown_version_excluded(self):
        r=self.rows[0];r["sources"]["B1"]["payload"]["source_model_version"]=None;self.rebind(r,"B1")
        self.assertIn("B1:SOURCE_VERSION_UNKNOWN",audit_row(r,self.root))

    def test_reconstructed_history_excluded(self):
        r=self.rows[0];r["sources"]["B1"]["payload"]["historical_record_type"]="reconstructed_backtest";self.rebind(r,"B1")
        self.assertIn("B1:NOT_LIVE_HISTORY",audit_row(r,self.root))

    def test_late_capture_excluded(self):
        r=self.rows[0];r["sources"]["B1"]["payload"]["captured_at"]=self.end;self.rebind(r,"B1")
        self.assertIn("B1:SOURCE_CHRONOLOGY",audit_row(r,self.root))

    def test_naive_timestamp_and_unknown_availability(self):
        with self.assertRaises(ValueError): timestamp("2026-10-30T10:00:00")
        r=self.rows[0];r["sources"]["B1"]["payload"]["availability_basis"]=None;self.rebind(r,"B1")
        self.assertIn("B1:POINT_IN_TIME_UNPROVEN",audit_row(r,self.root))

    def test_identity_mismatch(self):
        for key,val in (("home","NYK"),("league","WNBA"),("target","total")):
            r=deepcopy(self.rows[0]);r["sources"]["B1"]["payload"][key]=val;self.rebind(r,"B1")
            self.assertIn("B1:IDENTITY_MISMATCH:"+key,audit_row(r,self.root))

    def test_tampered_payload_and_hash(self):
        r=self.rows[0];r["sources"]["B1"]["payload"]["values"]["home_margin"]=99.
        self.assertIn("B1:PAYLOAD_BINDING_MISMATCH",audit_row(r,self.root))
        r["sources"]["B1"]["artifact_hash"]="0"*64
        self.assertIn("B1:ARTIFACT_HASH_MISMATCH",audit_row(r,self.root))

    def test_raw_capture_tampering(self):
        (self.root/"raw.txt").write_text("different")
        self.assertIn("B0:RAW_HASH_MISMATCH",audit_row(self.rows[0],self.root))

    def test_duplicate_events_rejected(self):
        result=audit([self.rows[0],self.rows[0]],self.root)
        self.assertEqual(result["eligible_events"],0)
        self.assertEqual(result["unique_events"],1)

    def test_alternate_event_ids_cannot_inflate_sample(self):
        alias=deepcopy(self.rows[0]);alias["event_id"]="another-provider:123"
        result=audit([self.rows[0],alias],self.root)
        self.assertEqual(result["eligible_events"],0)
        self.assertEqual(result["unique_events"],1)

    def test_future_labels_excluded(self):
        result=audit(self.rows,self.root,train_before="2021-01-02T00:00:00Z")
        self.assertEqual(result["eligible_events"],0)

    def test_forged_outcome_rejected(self):
        r=self.rows[0];r["outcome"]["home_margin"]=999
        self.assertIn("OUTCOME_VALUE_MISMATCH:home_margin",audit_row(r,self.root,train_before=self.end))

    def test_nonfinite_inputs_rejected(self):
        for value in (float("nan"),float("inf"),True,"3"):
            r=deepcopy(self.rows[0]);r["sources"]["B1"]["payload"]["values"]["home_margin"]=value
            self.assertIn("B1:VALUES_INVALID",audit_row(r,self.root))

    def test_production_floor_blocks_small_sample(self):
        p=dict(self.protocol,min_training_events=100)
        self.assertFalse(fit(self.rows,self.root,p,self.end)["fitted"])

    def test_old_fit_and_training_reuse_rejected(self):
        s=fit(self.rows,self.root,self.protocol,self.end)
        out=predict(self.rows[0],self.root,s,self.protocol)
        self.assertIn("FIT_AFTER_FORECAST_CUTOFF",out["reasons"])
        self.assertIn("TRAINING_EVENT_REUSE",out["reasons"])

    def test_state_and_protocol_tamper_rejected(self):
        s=fit(self.rows,self.root,self.protocol,self.end)
        bad=deepcopy(s);bad["weight"]=.999
        with self.assertRaisesRegex(ValueError,"INVALID_FITTED_STATE"):predict(self.row(40),self.root,bad,self.protocol)
        p=dict(self.protocol,weight_ridge=2.)
        with self.assertRaisesRegex(ValueError,"PROTOCOL_MISMATCH"):predict(self.row(40),self.root,s,p)

    def test_no_probabilities_or_market_influence(self):
        s=fit(self.rows,self.root,self.protocol,self.end);r=self.row(40)
        before=predict(r,self.root,s,self.protocol)
        r["market"]={"spread":-99,"odds":5000}
        after=predict(r,self.root,s,self.protocol)
        self.assertEqual(before,after)
        self.assertIsNone(after["probabilities"])
        self.assertFalse(after["action_authority"])

    def test_diagnostic_rows_never_enter_fit(self):
        for r in self.rows:r["evidence_population"]="retrospective_diagnostic"
        s=fit(self.rows,self.root,self.protocol,self.end)
        self.assertFalse(s["fitted"])
        self.assertEqual(s["audit"]["eligible_events"],0)

    def test_cli_fit_block_and_immutable_output(self):
        dataset=self.root/'dataset.json';dataset.write_text(json.dumps({'rows':self.rows}))
        p=self.root/'protocol.json';p.write_text(json.dumps(dict(self.protocol,min_training_events=100)))
        output=self.root/'result.json'
        cli=Path(__file__).resolve().parents[1]/'scripts/run_nba_forecast_combination.py'
        args=[sys.executable,str(cli),'fit','--dataset',str(dataset),'--protocol',str(p),
              '--train-before',self.end,'--output',str(output)]
        first=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(first.returncode,2,first.stderr)
        original=output.read_bytes()
        second=subprocess.run(args,capture_output=True,text=True)
        self.assertNotEqual(second.returncode,0)
        self.assertEqual(original,output.read_bytes())


if __name__ == "__main__":
    unittest.main()
