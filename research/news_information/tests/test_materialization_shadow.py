from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from research.news_information.contracts import digest, sha256_file
from research.news_information.model_adapters import verify_materialized_snapshot
from research.news_information.model_registry import candidates
from research.news_information.shadow_features import export_shadow_vector


class MaterializationShadowTests(unittest.TestCase):
    def test_fake_materialization_receipt_is_hash_verified(self):
        c=candidates()["gliner25_base"]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"snapshot"; root.mkdir(); f=root/"config.json"; f.write_text("{}")
            files=[{"path":"config.json","bytes":f.stat().st_size,"sha256":sha256_file(f)}]
            core={"schema_version":"sports_news_model_materialization_receipt.v1","candidate_id":c.id,"hf_repo":c.hf_repo,"revision":c.revision,
                  "role":c.role,"license":c.license,"license_status":c.license_status,"research_only":True,"trusted":False,"enabled_by_default":False,
                  "forecast_adjustment_eligible":False,"snapshot_path":str(root),"files":files,"snapshot_sha256":digest(files)}
            receipt={**core,"receipt_sha256":digest(core)}; rp=Path(td)/"receipt.json"; rp.write_text(json.dumps(receipt))
            verified=verify_materialized_snapshot(c.id,rp); self.assertEqual(verified.root,root); self.assertEqual(verified.candidate.revision,c.revision)
            f.write_text("tampered")
            with self.assertRaisesRegex(Exception,"hash mismatch"): verify_materialized_snapshot(c.id,rp)

    def test_shadow_vector_has_no_probability_or_run_transform(self):
        core={"schema_version":"sports_information_state_snapshot.v1","feature_contract_version":"sports_information_state.v0_1.research","event_id":"G1","cutoff_utc":"2026-09-08T10:00:00Z","information_event_ids":[],"event_type_counts":{"PLAYER_OUT":1},"conflicting_information_event_count":0,"research_only":True,"forecast_adjustment_enabled":False,"market_input":False,"action_authority":"OFF"}
        snap={**core,"snapshot_sha256":digest(core)}; out=export_shadow_vector(snap)
        self.assertEqual(out["features"]["news_count__player_out"],1); self.assertEqual(out["model_use"],"SHADOW_ONLY_NO_TRANSFORM")
        self.assertNotIn("probability_delta",out); self.assertNotIn("run_delta",out)

if __name__=="__main__": unittest.main()
