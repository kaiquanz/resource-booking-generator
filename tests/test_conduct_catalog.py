import copy
import unittest
from pathlib import Path

import yaml

from app_services import load_automation_module


ROOT = Path(__file__).resolve().parents[1]


class ConductCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_automation_module()
        cls.catalog = cls.module.load_conduct_catalog(
            ROOT / "ocs" / "conduct_catalog.yaml"
        )
        cls.lesson_names = [
            "Ex. HUNTER",
            "M203 L/F",
            "MAT / M203 LIVE FIRING",
            "GPMG L/F",
            "STRENGTH TRAINING",
        ]
        cls.lesson_index = {
            cls.module.normalize_conduct_name(name): name for name in cls.lesson_names
        }

    def test_catalog_has_unique_stable_ids(self):
        conduct_ids = [rule["conduct_id"] for rule in self.catalog["conducts"]]
        self.assertEqual(len(conduct_ids), len(set(conduct_ids)))

    def test_catalog_does_not_require_manual_priority(self):
        self.assertTrue(
            all("priority" not in rule for rule in self.catalog["conducts"])
        )

    def test_local_alias_maps_to_stable_lesson_plan_target(self):
        catalog = copy.deepcopy(self.catalog)
        hunter = next(
            rule for rule in catalog["conducts"] if rule["conduct_id"] == "ex_hunter"
        )
        hunter["aliases"].append("EX LEOPARD")
        result = self.module.match_catalog_conduct(
            "Ex Leopard",
            catalog,
            self.lesson_index,
        )
        self.assertEqual(result["status"], "catalog")
        self.assertEqual(result["target"], "Ex. HUNTER")

    def test_numbers_are_preserved_during_normalization(self):
        self.assertNotEqual(
            self.module.normalize_conduct_name("INTERVAL FAST MARCH - 4KM"),
            self.module.normalize_conduct_name("INTERVAL FAST MARCH - 8KM"),
        )

    def test_inactive_rule_blocks_exact_name_and_alias(self):
        catalog = copy.deepcopy(self.catalog)
        strength_training = next(
            rule for rule in catalog["conducts"]
            if rule["conduct_id"] == "strength_training"
        )
        strength_training["active"] = False
        exact = self.module.match_catalog_conduct(
            "STRENGTH TRAINING",
            catalog,
            self.lesson_index,
        )
        alias = self.module.match_catalog_conduct(
            "S&P",
            catalog,
            self.lesson_index,
        )
        self.assertEqual(exact["status"], "inactive")
        self.assertEqual(alias["status"], "inactive")

    def test_conflicting_alias_is_ambiguous(self):
        catalog = {
            "conducts": [
                {
                    "conduct_id": "one",
                    "lesson_plan_name": "M203 L/F",
                    "aliases": ["LOCAL NAME"],
                    "active": True,
                },
                {
                    "conduct_id": "two",
                    "lesson_plan_name": "GPMG L/F",
                    "aliases": ["LOCAL NAME"],
                    "active": True,
                },
            ]
        }
        result = self.module.match_catalog_conduct(
            "Local Name",
            catalog,
            self.lesson_index,
        )
        self.assertEqual(result["status"], "ambiguous")

    def test_yaml_is_parseable(self):
        raw = (ROOT / "ocs" / "conduct_catalog.yaml").read_text(encoding="utf-8")
        self.assertIsInstance(yaml.safe_load(raw), dict)


if __name__ == "__main__":
    unittest.main()
