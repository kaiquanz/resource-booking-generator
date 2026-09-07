import copy
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
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

    def test_loader_does_not_reuse_legacy_streamlit_importer_cache(self):
        stale_module = ModuleType("tp_importer")
        previous = sys.modules.get("tp_importer")
        sys.modules["tp_importer"] = stale_module
        try:
            loaded = load_automation_module()
            self.assertIsNot(loaded, stale_module)
            self.assertTrue(loaded.__name__.startswith("tp_importer_"))
        finally:
            if previous is None:
                sys.modules.pop("tp_importer", None)
            else:
                sys.modules["tp_importer"] = previous

    def test_every_conduct_has_preparation_fields(self):
        for rule in self.catalog["conducts"]:
            self.assertTrue(
                {"medic", "ammo_collection", "transport", "vehicle"}.issubset(
                    rule["preparation"]
                )
            )
            self.assertIsInstance(rule["bus_required"], bool)
            self.assertIsInstance(rule["active"], bool)
            self.assertIn(rule["timing"], ("in_camp", "external", None))
            for item_name in (
                "medic",
                "ammo_collection",
                "transport",
                "vehicle",
            ):
                item = rule["preparation"][item_name]
                self.assertIn("duration_minutes", item)
                self.assertNotIn("days_before", item)
                self.assertNotIn("time", item)

    def test_screenshot_preparation_windows_are_recorded(self):
        rules = {
            rule["conduct_id"]: rule for rule in self.catalog["conducts"]
        }

        expected_durations = {
            "xaw_co_uo": {
                "medic": 2220,
                "ammo_collection": 2430,
                "vehicle": 2430,
            },
            "xaw_compass_pf": {
                "medic": 1019,
                "ammo_collection": 1020,
                "vehicle": 1109,
            },
            "m203_live_firing": {
                "medic": 1065,
                "ammo_collection": 690,
                "transport": 585,
                "vehicle": 1065,
            },
            "gpmg_live_firing": {
                "medic": 1305,
                "ammo_collection": 1140,
                "transport": 1125,
                "vehicle": 1305,
            },
            "ippt": {
                "medic": 240,
                "vehicle": 240,
            },
            "interval_fast_march": {
                "medic": 210,
                "vehicle": 210,
            },
            "lmg_qualification_shoot": {
                "transport": 600
            },
        }

        for conduct_id, preparation in expected_durations.items():
            for item_name, duration in preparation.items():
                item = rules[conduct_id]["preparation"][item_name]
                self.assertEqual(item["duration_minutes"], duration)

        self.assertTrue(rules["m203_live_firing"]["active"])
        self.assertTrue(rules["gpmg_live_firing"]["active"])
        self.assertTrue(rules["ex_relentless"]["active"])
        self.assertTrue(rules["xaw_co_uo"]["active"])
        self.assertEqual(rules["m203_live_firing"]["timing"], "external")
        self.assertEqual(rules["gpmg_live_firing"]["timing"], "external")
        self.assertEqual(rules["ex_relentless"]["timing"], "external")
        self.assertEqual(rules["xaw_co_uo"]["timing"], "in_camp")

        bus_rules = {
            rule["conduct_id"]: rule["bus_required"]
            for rule in self.catalog["conducts"]
        }
        self.assertTrue(bus_rules["lmg_qualification_shoot"])
        self.assertTrue(bus_rules["m203_live_firing"])
        self.assertTrue(bus_rules["gpmg_live_firing"])
        self.assertTrue(bus_rules["signal_package"])
        self.assertFalse(bus_rules["xaw_co_uo"])

    def test_csb_and_leo_catalogue_entries_are_available(self):
        rules = {
            rule["conduct_id"]: rule for rule in self.catalog["conducts"]
        }

        csb = rules["csb"]
        self.assertEqual(csb["lesson_plan_name"], "Combat Skills Badge")
        self.assertEqual(csb["aliases"], ["Combat Skills Badge", "csb"])
        self.assertTrue(csb["active"])
        self.assertEqual(csb["timing"], "in_camp")

        leo = rules["leo II"]
        self.assertEqual(leo["lesson_plan_name"], "Ex. LEO II")
        self.assertEqual(
            leo["exclusions"],
            ["Inspection", "Prep", "SDL", "Brief", "Chat"],
        )
        self.assertTrue(leo["active"])
        self.assertEqual(leo["timing"], "in_camp")

        xaw_rule = next(
            rule for rule in self.catalog["conducts"]
            if rule["conduct_id"] == "xaw_co_uo"
        )
        self.assertEqual(xaw_rule["duration_days"], 2)

    def test_xaw_multi_day_range_is_limited_to_two_days(self):
        extractor = self.module.Extractor.__new__(self.module.Extractor)
        extractor.conduct_catalog = self.catalog
        target = "Ex Adaptive Warrior ( CO + UO)"
        dates = [
            "12-Oct-26",
            "13-Oct-26",
            "14-Oct-26",
            "15-Oct-26",
            "16-Oct-26",
        ]
        conduct_mapping = {date: [target, target] for date in dates}

        ranges = extractor.conduct_exercises(conduct_mapping)

        self.assertEqual(ranges[target], ["12-Oct-26", "13-Oct-26"])

        single_date_range = extractor.conduct_exercises({
            "12-Oct-26": [target, target],
        })
        self.assertEqual(
            single_date_range[target],
            ["12-Oct-26", "13-Oct-26"],
        )

    def test_parkover_uses_previous_working_day(self):
        for conduct_day, expected in (
            (date(2026, 10, 24), date(2026, 10, 23)),
            (date(2026, 10, 25), date(2026, 10, 23)),
            (date(2026, 10, 26), date(2026, 10, 23)),
            (date(2026, 10, 27), date(2026, 10, 26)),
        ):
            with self.subTest(conduct_day=conduct_day):
                self.assertEqual(
                    self.module._previous_working_day(conduct_day), expected
                )

    def test_shared_timing_preset_builds_requested_window(self):
        rule = {
            "active": True,
            "timing": "external",
            "preparation": {
                "medic": {
                    "duration_minutes": 45,
                },
                "ammo_collection": {
                    "duration_minutes": 30,
                },
                "transport": {
                    "duration_minutes": 60,
                },
                "vehicle": {
                    "duration_minutes": 45,
                },
            }
        }

        schedule = self.module.build_preparation_schedule(
            rule,
            "2026-10-15",
            "07:00",
            {
                "external": {
                    "medic": "04:45",
                    "ammo_collection": "04:45",
                    "transport": "06:15",
                    "vehicle": "04:45",
                },
            },
            {
                "medic": True,
                "ammo_collection": True,
                "transport": True,
                "vehicle": True,
                "luv_hq": True,
                "souv": True,
                "mmrc": False,
            },
        )

        self.assertEqual(schedule[0]["start"], datetime(2026, 10, 15, 4, 45))
        self.assertEqual(schedule[0]["end"], datetime(2026, 10, 15, 5, 30))
        self.assertEqual(schedule[1]["start"], datetime(2026, 10, 15, 4, 45))
        self.assertEqual(schedule[2]["start"], datetime(2026, 10, 15, 6, 15))

    def test_mmrc_suppresses_ammo_and_luv_windows(self):
        rule = {
            "active": True,
            "timing": "in_camp",
            "preparation": {
                "medic": {"duration_minutes": 0},
                "ammo_collection": {"duration_minutes": 30},
                "transport": {"duration_minutes": 60},
                "vehicle": {"duration_minutes": 45},
            },
        }

        schedule = {
            item["item"]: item
            for item in self.module.build_preparation_schedule(
                rule,
                "2026-10-15",
                "07:00",
                resource_flags={
                    "medic": False,
                    "ammo_collection": True,
                    "transport": True,
                    "vehicle": True,
                    "luv_hq": True,
                    "souv": True,
                    "mmrc": True,
                },
            )
        }

        self.assertIsNone(schedule["ammo_collection"]["start"])
        self.assertIsNone(schedule["vehicle"]["start"])
        self.assertEqual(
            schedule["transport"]["start"],
            datetime(2026, 10, 15, 7, 0),
        )

    def test_invalid_timing_profile_is_rejected(self):
        catalog = {
            "conducts": [{
                "conduct_id": "test",
                "lesson_plan_name": "M203 L/F",
                "aliases": ["TEST"],
                "active": True,
                "timing": "somewhere_else",
                "preparation": {
                    "medic": {
                        "duration_minutes": 45,
                    },
                    "ammo_collection": {
                        "duration_minutes": 0,
                    },
                    "transport": {
                        "duration_minutes": 0,
                    },
                    "vehicle": {
                        "duration_minutes": 0,
                    },
                },
            }]
        }

        errors = self.module.validate_conduct_catalog(catalog, ["M203 L/F"])

        self.assertTrue(any("timing must be" in error for error in errors))

    def test_active_switch_must_be_boolean(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["conducts"][0]["active"] = "yes"

        errors = self.module.validate_conduct_catalog(catalog)

        self.assertTrue(any("active must be true or false" in error for error in errors))

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
        self.assertEqual(rule["timing"], "in_camp")

    def test_combat_circuit_is_active_without_a_timing_profile(self):
        rule = next(
            rule for rule in self.catalog["conducts"]
            if rule["conduct_id"] == "combat_circuit"
        )
        self.assertTrue(rule["active"])
        self.assertIsNone(rule["timing"])

        schedule = self.module.build_preparation_schedule(
            rule,
            "2026-10-13",
            "07:00",
            resource_flags={"medic": True, "vehicle": True, "souv": True},
        )
        self.assertTrue(
            all(item["start"] is None and item["end"] is None for item in schedule)
        )

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
                    "timing": "in_camp",
                },
                {
                    "conduct_id": "two",
                    "lesson_plan_name": "GPMG L/F",
                    "aliases": ["LOCAL NAME"],
                    "active": True,
                    "timing": "in_camp",
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
        always_highlighted = (
            "F", "H", "I", "J", "M", "N", "O", "BU", "BV", "BW",
            "BZ", "CA", "CB", "CC",
        )
        for column in always_highlighted:
            self.assertEqual(sheet[f"{column}13"].fill.fgColor.rgb, "FFFFF2CC")

        for column in (
            "R", "S", "T", "CG", "CH", "CI", "CJ", "CK", "CL", "CM",
            "CN", "CU", "CV", "CW",
        ):
            self.assertIsNone(sheet[f"{column}13"].fill.fill_type)

        sheet["W14"] = 120
        sheet["CN14"] = 1
        sheet["CX14"] = "2 x 45-seater buses"
        self.module.highlight_siao_manual_inputs(sheet, 14)

        for column in (
            "R", "S", "T", "CG", "CH", "CI", "CJ", "CL", "CN",
            "CU", "CV", "CW",
        ):
            self.assertEqual(sheet[f"{column}14"].fill.fgColor.rgb, "FFFFF2CC")
        for column in ("CK", "CM"):
            self.assertIsNone(sheet[f"{column}14"].fill.fill_type)

        sheet["T15"] = "SAFTI Ammo Point"
        self.module.highlight_siao_manual_inputs(sheet, 15)
        self.assertEqual(sheet["R15"].fill.fgColor.rgb, "FFFFF2CC")
        self.assertEqual(sheet["S15"].fill.fgColor.rgb, "FFFFF2CC")
        self.assertEqual(sheet["T15"].fill.fgColor.rgb, "FFFFF2CC")

        workbook.close()


if __name__ == "__main__":
    unittest.main()
