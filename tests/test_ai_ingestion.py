import io
import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pandas as pd
import yaml

from ai_ingestion import (
    EVENT_COLUMNS,
    TrainingPlanExtraction,
    build_ai_input,
    extract_training_plan_with_ai,
    validate_reviewed_events,
)
from app_services import (
    canonical_events_to_functional_data,
    generate_bookings_from_events,
    generate_siao_from_events,
)


ROOT = Path(__file__).resolve().parents[1]


def event_frame(rows):
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        parsed = TrainingPlanExtraction.model_validate({
            "document_title": "Mock TP",
            "events": [{
                "date": "2026-10-01",
                "start_time": "08:00",
                "end_time": "09:00",
                "conduct": "STRENGTH TRAINING",
                "location": "CA1",
                "remarks": "",
                "source_reference": "page 1, box A",
                "confidence": 0.96,
                "needs_review": False,
            }],
            "warnings": [],
        })
        return SimpleNamespace(
            status="completed",
            output_parsed=parsed,
            output=[],
            model="gpt-test",
            id="resp_test",
        )


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


class AIIngestionTests(unittest.TestCase):
    def test_pdf_uses_ephemeral_file_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "visual-plan.pdf"
            source.write_bytes(b"%PDF-1.4 test")
            content = build_ai_input(source)

        self.assertEqual(content[0]["type"], "input_file")
        self.assertEqual(content[0]["filename"], "visual-plan.pdf")
        self.assertEqual(content[0]["detail"], "high")
        self.assertTrue(content[0]["file_data"].startswith("data:application/pdf;base64,"))
        self.assertEqual(content[1]["type"], "input_text")

    def test_tsv_uses_an_accepted_mime_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "plan.tsv"
            source.write_text("date\tconduct\n", encoding="utf-8")
            content = build_ai_input(source)

        self.assertTrue(content[0]["file_data"].startswith("data:text/tsv;base64,"))

    def test_xlsm_is_converted_to_supported_xlsx_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "plan.xlsm"
            workbook = openpyxl.Workbook()
            workbook.active["A1"] = "Training plan"
            workbook.save(source)
            workbook.close()
            content = build_ai_input(source)

        self.assertEqual(content[0]["filename"], "plan.xlsx")
        self.assertTrue(
            content[0]["file_data"].startswith(
                "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
            )
        )

    def test_image_uses_original_detail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "boxed-plan.png"
            source.write_bytes(b"not-a-real-image")
            content = build_ai_input(source)

        self.assertEqual(content[0]["type"], "input_image")
        self.assertEqual(content[0]["detail"], "original")
        self.assertTrue(content[0]["image_url"].startswith("data:image/png;base64,"))

    def test_structured_extraction_request_and_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "plan.pdf"
            source.write_bytes(b"%PDF-1.4 test")
            client = FakeClient()
            result = extract_training_plan_with_ai(
                source,
                api_key="test-key",
                model="gpt-test",
                client=client,
            )

        request = client.responses.kwargs
        self.assertEqual(request["model"], "gpt-test")
        self.assertIs(request["text_format"], TrainingPlanExtraction)
        self.assertFalse(request["store"])
        self.assertEqual(result["model"], "gpt-test")
        self.assertEqual(result["events"].loc[0, "conduct"], "STRENGTH TRAINING")

    def test_review_validation_preserves_iso_dates(self):
        reviewed = event_frame([{
            "date": "2026-10-01",
            "start_time": "800",
            "end_time": "09:15",
            "conduct": "STRENGTH TRAINING",
            "location": "CA1",
            "remarks": "",
            "source_reference": "page 1",
            "confidence": 0.9,
            "needs_review": "false",
        }])
        cleaned, errors, warnings = validate_reviewed_events(reviewed)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(cleaned.loc[0, "date"], "2026-10-01")
        self.assertEqual(cleaned.loc[0, "start_time"], "08:00")
        self.assertFalse(bool(cleaned.loc[0, "needs_review"]))

    def test_adapter_preserves_legacy_positions(self):
        reviewed = event_frame([
            {
                "date": "2026-10-01", "start_time": "08:00", "end_time": "09:00",
                "conduct": "STRENGTH TRAINING", "location": "CA1", "remarks": "First note",
                "source_reference": "page 1", "confidence": 1.0, "needs_review": False,
            },
            {
                "date": "2026-10-02", "start_time": "10:00", "end_time": "11:00",
                "conduct": "IPPT", "location": "", "remarks": "Second note",
                "source_reference": "page 2", "confidence": 1.0, "needs_review": False,
            },
        ])
        functional, date_columns = canonical_events_to_functional_data(reviewed)

        self.assertEqual(date_columns, [2, 5])
        self.assertEqual(functional.columns[2], "01-Oct-26")
        self.assertEqual(functional.columns[5], "02-Oct-26")
        self.assertEqual(functional.index[13], "REMARKS")
        self.assertEqual(functional.iloc[0, 3], "LOC")
        self.assertEqual(functional.iloc[0, 6], "LOC")
        self.assertEqual(functional.iloc[1, 0], "0800-0900")
        self.assertEqual(functional.iloc[2, 6], "-")
        self.assertEqual(functional.iloc[13, 1], "First note")
        self.assertEqual(functional.iloc[13, 4], "Second note")

    def test_ai_events_preserve_the_automation_workbook_shape(self):
        config = yaml.safe_load((ROOT / "ocs" / "config.yaml").read_text(encoding="utf-8"))
        reviewed = event_frame([{
            "date": "2026-10-01", "start_time": "08:00", "end_time": "09:00",
            "conduct": "STRENGTH TRAINING", "location": "CA1", "remarks": "",
            "source_reference": "page 1", "confidence": 1.0, "needs_review": False,
        }])
        with contextlib.redirect_stdout(io.StringIO()):
            result = generate_siao_from_events(config, reviewed, cadet_size=120)

        template = openpyxl.load_workbook(ROOT / "ocs" / "template_siao.xlsx")
        roundtrip_bytes = io.BytesIO()
        template.save(roundtrip_bytes)
        roundtrip_bytes.seek(0)
        automation_baseline = openpyxl.load_workbook(roundtrip_bytes)
        generated = openpyxl.load_workbook(io.BytesIO(result["xlsx"]))
        self.assertEqual(generated.sheetnames, automation_baseline.sheetnames)
        for sheet_name in automation_baseline.sheetnames:
            expected = automation_baseline[sheet_name]
            actual = generated[sheet_name]
            self.assertEqual(actual.max_row, expected.max_row)
            self.assertEqual(actual.max_column, expected.max_column)
            self.assertEqual(
                list(actual.merged_cells.ranges),
                list(expected.merged_cells.ranges),
            )
        template.close()
        automation_baseline.close()
        generated.close()
        self.assertIn("exact", set(result["match_report"]["status"]))

    def test_ai_events_generate_ocs_and_safti_products(self):
        config = yaml.safe_load((ROOT / "ocs" / "config.yaml").read_text(encoding="utf-8"))
        config["user"]["email"] = "reviewer@example.com"
        reviewed = event_frame([
            {
                "date": "2026-10-01", "start_time": "08:00", "end_time": "09:00",
                "conduct": "STRENGTH TRAINING", "location": "CA1", "remarks": "",
                "source_reference": "page 1", "confidence": 1.0, "needs_review": False,
            },
            {
                "date": "2026-10-02", "start_time": "10:00", "end_time": "11:00",
                "conduct": "IPPT", "location": "Stadium", "remarks": "",
                "source_reference": "page 2", "confidence": 1.0, "needs_review": False,
            },
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            result = generate_bookings_from_events(config, reviewed)

        self.assertEqual(result["ocs"].loc[0, "FACILITY"], "CA1")
        self.assertEqual(result["safti"].loc[0, "FACILITY"], "Stadium")
        self.assertEqual(result["email_draft"]["to"], "reviewer@example.com")
        self.assertIn("<table", result["email_draft"]["table_html"])


if __name__ == "__main__":
    unittest.main()
