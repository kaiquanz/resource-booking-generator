import copy
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pandas as pd
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

    def test_every_conduct_has_preparation_fields(self):
        for rule in self.catalog["conducts"]:
            self.assertTrue(
                {"medic", "ammo_collection", "transport", "vehicle"}.issubset(
                    rule["preparation"]
                )
            )
            self.assertIsInstance(rule["bus_required"], bool)
            for item_name in (
                "medic",
                "ammo_collection",
                "transport",
                "vehicle",
            ):
                item = rule["preparation"][item_name]
                self.assertIn("duration_minutes", item)
                self.assertIn("days_before", item)
                self.assertIn("time", item)

    def test_screenshot_preparation_windows_are_recorded(self):
        rules = {
            rule["conduct_id"]: rule for rule in self.catalog["conducts"]
        }

        expected = {
            "xaw_co_uo": {
                "medic": (2220, 0, "08:00"),
                "ammo_collection": (2430, 0, "05:30"),
                "vehicle": (2430, 0, "05:30"),
            },
            "xaw_compass_pf": {
                "medic": (1019, 0, "07:00"),
                "ammo_collection": (1020, 0, "05:30"),
                "vehicle": (1109, 0, "05:30"),
            },
            "m203_live_firing": {
                "medic": (1065, 0, "04:45"),
                "ammo_collection": (690, 0, "05:30"),
                "transport": (585, 0, "06:15"),
                "vehicle": (1065, 0, "04:45"),
            },
            "gpmg_live_firing": {
                "medic": (1305, 0, "04:45"),
                "ammo_collection": (1140, 0, "05:30"),
                "transport": (1125, 0, "06:15"),
                "vehicle": (1305, 0, "04:45"),
            },
            "ippt": {
                "medic": (240, 0, "05:30"),
                "vehicle": (240, 0, "05:30"),
            },
            "interval_fast_march": {
                "medic": (210, 0, "06:00"),
                "vehicle": (210, 0, "06:00"),
            },
            "lmg_qualification_shoot": {
                "transport": (600, 0, "07:00")
            },
        }

        for conduct_id, preparation in expected.items():
            for item_name, values in preparation.items():
                item = rules[conduct_id]["preparation"][item_name]
                self.assertEqual(
                    (item["duration_minutes"], item["days_before"], item["time"]),
                    values,
                )

        bus_rules = {
            rule["conduct_id"]: rule["bus_required"]
            for rule in self.catalog["conducts"]
        }
        self.assertTrue(bus_rules["lmg_qualification_shoot"])
        self.assertTrue(bus_rules["m203_live_firing"])
        self.assertTrue(bus_rules["gpmg_live_firing"])
        self.assertTrue(bus_rules["signal_package"])
        self.assertFalse(bus_rules["xaw_co_uo"])

    def test_optional_preparation_backtrack_builds_requested_window(self):
        rule = {
            "preparation": {
                "medic": {
                    "duration_minutes": 45,
                    "days_before": 2,
                    "time": "04:45",
                },
                "ammo_collection": {
                    "duration_minutes": 30,
                    "days_before": None,
                    "time": "",
                },
                "transport": {
                    "duration_minutes": 60,
                    "days_before": None,
                    "time": "",
                },
            }
        }

        schedule = self.module.build_preparation_schedule(
            rule,
            "2026-10-15",
            "07:00",
        )

        self.assertEqual(schedule[0]["start"], datetime(2026, 10, 13, 4, 45))
        self.assertEqual(schedule[0]["end"], datetime(2026, 10, 13, 5, 30))
        self.assertEqual(schedule[1]["start"], datetime(2026, 10, 15, 6, 30))

    def test_preparation_backtrack_requires_both_day_and_time(self):
        catalog = {
            "conducts": [{
                "conduct_id": "test",
                "lesson_plan_name": "M203 L/F",
                "aliases": ["TEST"],
                "active": True,
                "preparation": {
                    "medic": {
                        "duration_minutes": 45,
                        "days_before": 2,
                        "time": "",
                    },
                    "ammo_collection": {
                        "duration_minutes": 0,
                        "days_before": None,
                        "time": "",
                    },
                    "transport": {
                        "duration_minutes": 0,
                        "days_before": None,
                        "time": "",
                    },
                },
            }]
        }

        errors = self.module.validate_conduct_catalog(catalog, ["M203 L/F"])

        self.assertTrue(any("must both be set" in error for error in errors))

    def test_catalog_does_not_require_manual_priority(self):
        self.assertTrue(
            all("priority" not in rule for rule in self.catalog["conducts"])
        )

    def test_bus_count_rounds_up_to_40_seaters(self):
        self.assertEqual(self.module.calculate_40_seater_buses(140), 4)
        self.assertEqual(self.module.calculate_40_seater_buses(40), 1)
        self.assertEqual(self.module.calculate_40_seater_buses(41), 2)

    def test_bus_required_must_be_boolean(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["conducts"][0]["bus_required"] = "yes"

        errors = self.module.validate_conduct_catalog(catalog)

        self.assertTrue(any("bus_required must be true or false" in error for error in errors))

    def test_local_alias_maps_to_stable_lesson_plan_target(self):
        catalog = copy.deepcopy(self.catalog)
        hunter = next(
            rule for rule in catalog["conducts"] if rule["conduct_id"] == "ex_hunter"
        )
        hunter["active"] = True
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

    def test_vehicle_columns_resolve_from_current_lesson_plan_headers(self):
        lesson_plan = pd.read_csv(ROOT / "SIAO - Lesson Plan.csv")
        header = lesson_plan.iloc[0:1].copy().ffill(axis=1)
        lesson_plan.columns = header.iloc[0]
        lesson_plan = lesson_plan.iloc[1:].reset_index(drop=True)

        mapping = self.module.resolve_siao_vehicle_columns(lesson_plan)

        self.assertEqual(mapping["LUV (HQ)"], 176)
        self.assertEqual(mapping["MB290 (HQ)"], 177)
        self.assertEqual(mapping["LUV (PLC)"], 178)
        self.assertEqual(mapping["Military Transport Venue From"], 192)
        self.assertEqual(mapping["Military Transport Venue To"], 193)
        self.assertEqual(mapping["Others"], 225)
        self.assertLess(max(mapping.values()), lesson_plan.shape[1])

    def test_vehicle_columns_do_not_overrun_an_older_lesson_plan(self):
        lesson_plan = pd.DataFrame([[None] * 225 for _ in range(2)])
        old_headers = {
            176: "OUV",
            177: "SOUV",
            178: "5-Ton",
            179: "GP Car",
            180: "Other Vehicles (Boats, Trailers, F550)",
            181: "TO",
            182: "Reporting Venue",
            183: "Destination Venue",
            184: "Parkover",
            185: "Remarks",
            186: "Indent ID",
            192: "20 - seater",
            193: "40 - seater",
            194: "60 - seater",
            195: "1 way / 2 way / Disposal",
            196: "POC + Contact Number",
            197: "Indent ID",
            199: "RPL",
            203: "Fast Craft",
            219: "ICCT Instructors",
            220: "SOC Key",
            221: "Link Bridge Key",
            222: "M1 Gate Key",
            223: "Others",
        }
        for index, value in old_headers.items():
            lesson_plan.iat[0, index] = value
        lesson_plan.iloc[1, 200:202] = ["From", "To"]
        lesson_plan.iloc[1, 204:207] = [
            "From",
            "To",
            "Vehicle Details (with Authorised Troops)",
        ]

        mapping = self.module.resolve_siao_vehicle_columns(lesson_plan)

        self.assertNotIn("LUV (HQ)", mapping)
        self.assertNotIn("MB290 (HQ)", mapping)
        self.assertNotIn("LUV (PLC)", mapping)
        self.assertEqual(mapping["SOUV"], 177)
        self.assertEqual(mapping["Others"], 223)
        self.assertLess(max(mapping.values()), lesson_plan.shape[1])

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

    def test_relentless_recovery_is_not_folded_into_exercise_range(self):
        lesson_index = {
            self.module.normalize_conduct_name("EX.RELENTLESS"): "EX.RELENTLESS"
        }
        result = self.module.match_catalog_conduct(
            "EX Relentless Warrior Recovery",
            self.catalog,
            lesson_index,
        )
        self.assertEqual(result["status"], "unmatched")

    def test_ptco_judgemental_video_maps_to_jvlf(self):
        lesson_index = {
            self.module.normalize_conduct_name("PTCO JVLF"): "PTCO JVLF"
        }
        result = self.module.match_catalog_conduct(
            "PTCO Judgemental Video IGTS",
            self.catalog,
            lesson_index,
        )
        self.assertEqual(result["status"], "catalog")
        self.assertEqual(result["target"], "PTCO JVLF")
        self.assertTrue(result["use_display_name"])
        self.assertEqual(result["display_name"], "PTCO JVLF")

    def test_xaw_dates_map_to_separate_lesson_plan_sections(self):
        lesson_index = {
            self.module.normalize_conduct_name("Ex Adaptive Warrior ( CO + UO)"):
                "Ex Adaptive Warrior ( CO + UO)",
            self.module.normalize_conduct_name("Compass Course + PF LF"):
                "Compass Course + PF LF",
        }

        co_uo = self.module.match_catalog_conduct(
            "XAW: Grass Drills",
            self.catalog,
            lesson_index,
        )
        compass = self.module.match_catalog_conduct(
            "Prismatic Compass Course (Day)/ Pengun Live Firing",
            self.catalog,
            lesson_index,
        )

        self.assertEqual(co_uo["target"], "Ex Adaptive Warrior ( CO + UO)")
        self.assertEqual(compass["target"], "Compass Course + PF LF")

    def test_lmg_qualification_shoot_maps_to_lesson_plan(self):
        lesson_index = {
            self.module.normalize_conduct_name("LMG QUALIFICATION SHOOT"):
                "LMG QUALIFICATION SHOOT"
        }
        result = self.module.match_catalog_conduct(
            "LMG Qualification Shoot",
            self.catalog,
            lesson_index,
        )

        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["target"], "LMG QUALIFICATION SHOOT")
        rule = next(
            rule for rule in self.catalog["conducts"]
            if rule["conduct_id"] == "lmg_qualification_shoot"
        )
        self.assertTrue(rule["active"])

    def test_lesson_plan_contains_both_xaw_sections(self):
        lesson_plan = pd.read_csv(ROOT / "SIAO - Lesson Plan.csv", header=None)
        section_names = set(lesson_plan.iloc[:, 2].dropna().astype(str))
        self.assertIn("Ex Adaptive Warrior ( CO + UO)", section_names)
        self.assertIn("Compass Course + PF LF", section_names)

    def test_combined_mut_has_an_exact_unambiguous_rule(self):
        lesson_index = {
            self.module.normalize_conduct_name("INTERVAL FAST MARCH"):
                "INTERVAL FAST MARCH",
            self.module.normalize_conduct_name("STRENGTH TRAINING"):
                "STRENGTH TRAINING",
        }
        result = self.module.match_catalog_conduct(
            "IFM/ST/MC MUT",
            self.catalog,
            lesson_index,
        )
        self.assertEqual(result["status"], "catalog")
        self.assertEqual(result["target"], "INTERVAL FAST MARCH")

    def test_excel_text_boxes_are_limited_to_columns_a_to_o(self):
        importer = self.module.Importer("training_plan.xlsx")
        data = pd.DataFrame([[None] * 15 for _ in range(3)])
        data.iat[1, 1] = "Lesson"
        boxes = [
            {"row": 8, "column": 3, "text": "NE Tour"},
            {"row": 8, "column": 16, "text": "False helper data"},
        ]
        with patch.object(importer, "_read_excel_text_boxes", return_value=boxes):
            overlaid = importer._add_excel_text_boxes(
                data,
                sheet_name="ST COMBINED",
                skip_rows=5,
            )
        self.assertEqual(overlaid.iat[1, 2], "NE Tour")
        self.assertEqual(overlaid.shape[1], 15)
        self.assertNotIn("False helper data", overlaid.to_string())

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

    def test_siao_manual_input_highlights_follow_allocations(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active

        self.module.highlight_siao_manual_inputs(sheet, 13)
        always_highlighted = ("F", "H", "I", "J", "M", "N", "O", "BV", "BW")
        for column in always_highlighted:
            self.assertEqual(sheet[f"{column}13"].fill.fgColor.rgb, "FFFFF2CC")

        for column in ("R", "S", "CJ", "CK", "CL", "CM", "CU", "CV", "CW"):
            self.assertIsNone(sheet[f"{column}13"].fill.fill_type)

        sheet["W14"] = 120
        sheet["CN14"] = 1
        sheet["CX14"] = "2 x 45-seater buses"
        self.module.highlight_siao_manual_inputs(sheet, 14)

        for column in ("R", "S", "CJ", "CK", "CL", "CM", "CU", "CV", "CW"):
            self.assertEqual(sheet[f"{column}14"].fill.fgColor.rgb, "FFFFF2CC")

        sheet["T15"] = "SAFTI Ammo Point"
        self.module.highlight_siao_manual_inputs(sheet, 15)
        self.assertEqual(sheet["R15"].fill.fgColor.rgb, "FFFFF2CC")
        self.assertEqual(sheet["S15"].fill.fgColor.rgb, "FFFFF2CC")

        workbook.close()


if __name__ == "__main__":
    unittest.main()
