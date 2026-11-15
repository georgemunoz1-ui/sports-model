"""Bounded study regression for coherent claim and downstream-reference edits."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from research.validation_20261110.forward_registry import verify_bundle


HERE = Path(__file__).resolve().parent
REGISTERED_AT = "2026-11-10T14:00:00+00:00"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ForwardDerivedClaimsTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        with zipfile.ZipFile(HERE / "forward-bundle.zip") as archive:
            archive.extractall(self.root)
        self.originals = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }

    def test_authentic_bounded_cohort(self):
        result = verify_bundle(self.root, REGISTERED_AT)
        self.assertEqual(len(result["events"]), 85)
        self.assertEqual(len(result["forecasts"]), 266)
        self.assertEqual(len(result["refusals"]), 13)

    def test_coherent_derived_claim_mutations(self):
        cases = [("arm", field, value) for field, value in (
            ("margin_pmf_sha256", "0" * 64),
            ("law_median_home_margin", 999),
            ("intervals", {"80": {"lower": 999, "upper": 999, "width": 0}}),
            ("retained_residual_pairs", 1),
        )] + [("top", field, value) for field, value in (
            ("qualification", "APPROVED"),
            ("wagering_authority", "ON"),
            ("units", 1),
            ("official_selections", 1),
            ("forecast_count", 1),
            ("refusal_count", 0),
            ("canonical_registration", "PRODUCTION_REGISTERED"),
            ("date", "2026-11-11"),
        )] + [("row", field, value) for field, value in (
            ("season_phase", "LATE"),
            ("fitted_baseline_margin_group", "30_PLUS"),
            ("market_handicap_group", "30_PLUS"),
            ("returning_roster_information", {"verified": True}),
            ("source_forecast_status", "UNAVAILABLE"),
        )] + [("quote", field, value) for field, value in (
            ("provider", "OtherProvider"),
            ("league", "NHL"),
            ("settlement_evidence", "BOOKMAKER_RULES_AUTHENTICATED"),
        )]
        for scope, field, value in cases:
            with self.subTest(scope=scope, field=field):
                changed = self.apply_mutation(scope, field, value)
                try:
                    with self.assertRaises(ValueError):
                        verify_bundle(self.root, REGISTERED_AT)
                finally:
                    for member in changed + ["bundle-manifest.json"]:
                        (self.root / member).write_bytes(self.originals[member])

    def apply_mutation(self, scope, field, value):
        if scope == "quote":
            member = "quotes/nba-nhl.json"
            ledger = json.loads(self.originals[member])
            quote = ledger["quotes"][0]
            old_id = quote["quote_id"]
            quote[field] = value
            body = {k: v for k, v in quote.items() if k != "quote_id"}
            quote["quote_id"] = "quote-" + hashlib.sha256(canonical(body)).hexdigest()
            event = next(e for e in ledger["events"] if e["event_id"] == quote["event_id"])
            event["quote_ids"] = [quote["quote_id"] if q == old_id else q for q in event["quote_ids"]]
            (self.root / member).write_bytes(canonical(ledger))
            changed = [member]
        else:
            member = "cbb/forward-candidates.json"
            data = json.loads(self.originals[member])
            row = next(r for r in data["rows"] if "arms" in r)
            target = row["arms"]["LOCATION_ONLY"] if scope == "arm" else row if scope == "row" else data
            target[field] = value
            (self.root / member).write_bytes(canonical(data))
            new_parent = sha(self.root / member)
            quote_member = "quotes/cfb-cbb.json"
            ledger = json.loads(self.originals[quote_member])
            for binding in ledger["forecast_bindings"]:
                if binding["league"] == "CBB":
                    binding["sha256"] = new_parent
            id_changes = {}
            for quote in ledger["quotes"]:
                if quote["league"] == "CBB":
                    old_id = quote["quote_id"]
                    quote["forecast_sha256"] = new_parent
                    body = {k: v for k, v in quote.items() if k != "quote_id"}
                    quote["quote_id"] = "quote-" + hashlib.sha256(canonical(body)).hexdigest()
                    id_changes[old_id] = quote["quote_id"]
            for event in ledger["events"]:
                if event["league"] == "CBB":
                    event["forecast_sha256"] = new_parent
                    event["quote_ids"] = [id_changes.get(q, q) for q in event["quote_ids"]]
            (self.root / quote_member).write_bytes(canonical(ledger))
            changed = [member, quote_member]
        manifest = json.loads(self.originals["bundle-manifest.json"])
        for member in changed:
            manifest["files"][member] = sha(self.root / member)
        (self.root / "bundle-manifest.json").write_bytes(canonical(manifest))
        return changed


if __name__ == "__main__":
    unittest.main()
