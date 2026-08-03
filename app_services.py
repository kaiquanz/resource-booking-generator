from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import openpyxl
import pandas as pd
import yaml


APP_ROOT = Path(__file__).resolve().parent
IMPORTER_PATH = APP_ROOT / "ocs" / "importer.py"


@dataclass
class PreparedAutomation:
    module: ModuleType
    extractor: Any


def load_automation_module() -> ModuleType:
    """Load the numeric-directory module without changing its source file."""
    module_name = "tp_importer"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, IMPORTER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load automation from {IMPORTER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def resolve_configured_path(raw_path: str | os.PathLike[str]) -> Path:
    """Resolve repository-relative paths consistently on local and hosted runs."""
    path = Path(os.path.expandvars(os.path.expanduser(str(raw_path))))
    return path if path.is_absolute() else APP_ROOT / path


def _required_path(config: dict[str, Any], key: str) -> Path:
    raw_path = str(config.get("paths", {}).get(key, "")).strip()
    if not raw_path:
        raise ValueError(f"Set the {key.replace('_', ' ')} path in Settings first.")
    path = resolve_configured_path(raw_path)
    if not path.is_file():
        raise FileNotFoundError(f"The configured {key.replace('_', ' ')} file was not found: {path}")
    return path


def prepare_automation(
    config: dict[str, Any],
    *,
    siao_template_path: Path | None = None,
    require_siao_files: bool = True,
) -> PreparedAutomation:
    """Run the original importer preparation exactly as its entrypoint does."""
    module = load_automation_module()
    input_path = _required_path(config, "input_data")
    if require_siao_files:
        lesson_plan_path = _required_path(config, "lesson_plan")
        template_path = siao_template_path or _required_path(config, "siao_template")
    else:
        lesson_plan_path = resolve_configured_path(config.get("paths", {}).get("lesson_plan", ""))
        template_path = resolve_configured_path(config.get("paths", {}).get("siao_template", ""))

    importer = module.Importer(str(input_path))
    data = importer.import_data()
    data_transposed = data.transpose()
    data_transposed.columns = data_transposed.iloc[0]
    extract_columns = importer.check_date_row(data_transposed)
    data_transposed = data_transposed.drop(data_transposed.index[0])
    functional_data = importer.fill(data_transposed)

    extractor = module.Extractor(
        functional_data,
        extract_columns=extract_columns,
        lesson_plan_path=str(lesson_plan_path),
        siao_template_path=str(template_path),
        conduct_catalog_path=str(get_conduct_catalog_path(config)),
    )
    return PreparedAutomation(module=module, extractor=extractor)


def generate_siao(config: dict[str, Any], cadet_size: int) -> dict[str, bytes]:
    """Call ``draft_siao`` on a disposable template and return download bytes."""
    source_template = _required_path(config, "siao_template")

    with tempfile.TemporaryDirectory(prefix="tp_siao_") as temp_dir:
        output_path = Path(temp_dir) / "draft_siao.xlsx"
        shutil.copy2(source_template, output_path)
        prepared = prepare_automation(config, siao_template_path=output_path)

        # draft_siao expects the entrypoint's module-level name. Supplying the
        # same name here preserves the original function without editing it.
        prepared.module.data_change = prepared.extractor
        prepared.extractor.draft_siao(cadet_size=cadet_size)

        workbook_bytes = output_path.read_bytes()
        workbook = openpyxl.load_workbook(output_path, data_only=False)
        worksheet = workbook["(Fill In) SIAO"]
        rows = list(worksheet.values)
        csv_bytes = pd.DataFrame(rows).to_csv(index=False, header=False).encode("utf-8-sig")
        workbook.close()

    return {
        "xlsx": workbook_bytes,
        "csv": csv_bytes,
        "match_report": pd.DataFrame(prepared.extractor.match_report),
        "catalog_validation_errors": prepared.extractor.catalog_validation_errors,
    }


def get_conduct_catalog_path(config: dict[str, Any]) -> Path:
    configured = str(config.get("paths", {}).get("conduct_catalog", "")).strip()
    module = load_automation_module()
    return resolve_configured_path(configured) if configured else Path(module.DEFAULT_CONDUCT_CATALOG_PATH)


def load_editable_conduct_catalog(config: dict[str, Any]) -> dict[str, Any]:
    path = get_conduct_catalog_path(config)
    if not path.is_file():
        raise FileNotFoundError(f"Conduct catalogue was not found: {path}")
    return load_automation_module().load_conduct_catalog(str(path))


def validate_editable_conduct_catalog(
    config: dict[str, Any],
    catalog: dict[str, Any],
) -> list[str]:
    lesson_plan_path = _required_path(config, "lesson_plan")
    lesson_plan = pd.read_csv(lesson_plan_path)
    header = lesson_plan.iloc[0:1].copy().ffill(axis=1)
    lesson_plan.columns = header.iloc[0]
    lesson_plan = lesson_plan.iloc[1:].reset_index(drop=True)
    lesson_names = lesson_plan.iloc[2:, 2].dropna().astype(str)
    return load_automation_module().validate_conduct_catalog(catalog, lesson_names)


def save_editable_conduct_catalog(
    config: dict[str, Any],
    catalog: dict[str, Any],
) -> Path:
    errors = validate_editable_conduct_catalog(config, catalog)
    if errors:
        raise ValueError("Catalogue validation failed:\n- " + "\n- ".join(errors))

    path = get_conduct_catalog_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(serialized, encoding="utf-8")
    os.replace(temporary_path, path)
    return path


def generate_bookings(config: dict[str, Any]) -> dict[str, Any]:
    """Call ``resource_booking`` without credentials so it only creates a draft."""
    email = str(config.get("user", {}).get("email", "")).strip()
    if not email:
        raise ValueError("Set the recipient email in Settings first.")

    with tempfile.TemporaryDirectory(prefix="tp_booking_") as temp_dir:
        output_path = Path(temp_dir) / "ocs_booking.csv"
        prepared = prepare_automation(config, require_siao_files=False)
        result = prepared.extractor.resource_booking(
            your_email=email,
            output_path=str(output_path),
            gmail_address=None,
            gmail_app_password=None,
        )
        result["ocs_csv"] = output_path.read_bytes()
        result["ocs_copy_text"] = result["ocs"].to_csv(index=False, sep="\t")
    return result


def send_booking_email(config: dict[str, Any], draft: dict[str, str]) -> None:
    """Send a reviewed draft with an HTML table and plain-text fallback."""
    gmail = config.get("gmail", {})
    address = str(gmail.get("address", "")).strip()
    password = str(gmail.get("app_password", "")).strip()
    if not address or not password:
        raise ValueError("Add the Gmail address and app password in Settings before sending.")

    module = load_automation_module()
    introduction = draft["body"]
    table_text = draft.get("table_text", "")
    table_html = draft.get("table_html", "")
    plain_body = f"{introduction}\n\n{table_text}".rstrip()
    html_body = (
        module.build_booking_email_html(introduction, table_html)
        if table_html
        else ""
    )
    module.send_email(
        subject=draft["subject"],
        body=html_body or plain_body,
        to_address=draft["to"],
        from_address=address,
        app_password=password,
        html=bool(html_body),
        plain_body=plain_body if html_body else None,
    )
