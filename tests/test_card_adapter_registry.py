"""Import/selection smoke tests for the common registered card surface."""
import importlib
import unittest

from pipelines.cards.selection import SelectionError, inventory

REGISTERED = {
    "mlb": "pipelines.cards.adapters.mlb",
    "nfl": "pipelines.cards.adapters.nfl",
    "wnba": "pipelines.cards.adapters.wnba",
    "cfb": "pipelines.cards.adapters.cfb",
}
OPTIONAL_RESEARCH = {
    "nba": "pipelines.cards.adapters.nba",
}


class CardAdapterSmoke(unittest.TestCase):
    def test_registered_selected_adapters_import(self):
        for league, module in REGISTERED.items():
            with self.subTest(league=league):
                m = importlib.import_module(module)
                for attr in ("load_schedule", "build_context", "forecast_event"):
                    self.assertTrue(callable(getattr(m, attr, None)), (league, attr))

    def test_supported_selected_models_have_adapters(self):
        inv = inventory()["profiles"]
        for league in REGISTERED:
            key = league + ":winner"
            self.assertIn(key, inv)
            self.assertTrue(inv[key].get("default_model_id"), key)
            self.assertNotIn("blocked_reason", inv[key], key)

    def test_optional_research_adapters_import_without_claiming_default(self):
        for league, module in OPTIONAL_RESEARCH.items():
            with self.subTest(league=league):
                importlib.import_module(module)
                self.assertIn("blocked_reason", inventory()["profiles"][league + ":winner"])


if __name__ == "__main__":
    unittest.main()
