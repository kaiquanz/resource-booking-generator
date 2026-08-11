"""Run one GPT extraction and exercise the local SIAO/booking outputs."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_ingestion import (  # noqa: E402
    DEFAULT_AI_MODEL,
    extract_training_plan_with_ai,
    validate_reviewed_events,
)
from app_services import (  # noqa: E402
    generate_bookings_from_events,
    generate_siao_from_events,
)


LOCAL_SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
DEFAULT_OUTPUT_DIRECTORY = ROOT / "outputs" / "dev_gpt_smoke"
SYNTHETIC_TP = """date,start_time,end_time,conduct,location,remarks
2026-10-01,08:00,09:00,STRENGTH TRAINING,CA1,Local GPT smoke test
2026-10-02,10:00,11:00,IPPT,Stadium,Local GPT smoke test
"""


def _local_secrets() -> dict[str, Any]:
    if not LOCAL_SECRETS_PATH.is_file():
        return {}
    try:
        return tomllib.loads(LOCAL_SECRETS_PATH.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"Invalid TOML in {LOCAL_SECRETS_PATH}: {exc}") from exc


def _setting(name: str, default: str = "") -> str:
    environment_value = os.environ.get(name)
    if environment_value:
        return environment_value.strip()
    return str(_local_secrets().get(name, default) or default).strip()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send one training plan to GPT, validate the structured events, then "
            "exercise the local SIAO and booking generators."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional real TP file. If omitted, a safe synthetic CSV is used.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=f"Output folder (default: {DEFAULT_OUTPUT_DIRECTORY}).",
    )
    parser.add_argument("--cadet-size", type=int, default=120)
    parser.add_argument("--email", default="dev-reviewer@example.invalid")
    return parser.parse_args()


def _write_outputs(
    output_directory: Path,
    events,
    extraction: dict[str, Any],
    siao_result: dict[str, Any],
    booking_result: dict[str, Any],
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_directory / "reviewed_events.csv", index=False)
    (output_directory / "draft_siao.xlsx").write_bytes(siao_result["xlsx"])
    (output_directory / "draft_siao.csv").write_bytes(siao_result["csv"])
    siao_result["match_report"].to_csv(
        output_directory / "conduct_match_report.csv",
        index=False,
    )
    (output_directory / "ocs_booking.csv").write_bytes(booking_result["ocs_csv"])
    booking_result["safti"].to_csv(
        output_directory / "safti_booking.csv",
        index=False,
    )
    email_draft = booking_result["email_draft"]
    (output_directory / "safti_email_preview.html").write_text(
        email_draft.get("html_body") or email_draft.get("table_html", ""),
        encoding="utf-8",
    )
    (output_directory / "run_summary.txt").write_text(
        "\n".join([
            f"document={extraction.get('document_title') or 'Untitled'}",
            f"model={extraction.get('model') or ''}",
            f"response_id={extraction.get('response_id') or ''}",
            f"events={len(events)}",
            f"ocs_bookings={len(booking_result['ocs'])}",
            f"safti_bookings={len(booking_result['safti'])}",
        ]) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = _arguments()
    api_key = _setting("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "Add OPENAI_API_KEY to .streamlit/secrets.toml, then run this command again. "
            "Do not paste the key into config.yaml or commit it to Git."
        )

    if args.cadet_size < 1:
        raise SystemExit("--cadet-size must be at least 1.")

    with tempfile.TemporaryDirectory(prefix="tp_gpt_smoke_") as temp_dir:
        if args.input:
            source_path = args.input.expanduser().resolve()
            if not source_path.is_file():
                raise SystemExit(f"Input file was not found: {source_path}")
            print(f"Sending selected file to OpenAI: {source_path.name}")
        else:
            source_path = Path(temp_dir) / "synthetic_training_plan.csv"
            source_path.write_text(SYNTHETIC_TP, encoding="utf-8")
            print("Sending the built-in synthetic training plan to OpenAI.")

        print(f"Model: {DEFAULT_AI_MODEL}")
        extraction = extract_training_plan_with_ai(
            source_path,
            api_key=api_key,
        )

    reviewed_events, errors, warnings = validate_reviewed_events(extraction["events"])
    if errors:
        raise SystemExit("GPT output failed validation:\n- " + "\n- ".join(errors))
    for warning in extraction.get("warnings", []) + warnings:
        print(f"Review warning: {warning}")

    config = yaml.safe_load(
        (ROOT / "ocs" / "config.yaml").read_text(encoding="utf-8")
    )
    config.setdefault("user", {})["email"] = args.email
    siao_result = generate_siao_from_events(
        config,
        reviewed_events,
        cadet_size=args.cadet_size,
    )
    booking_result = generate_bookings_from_events(config, reviewed_events)

    output_directory = args.output_dir.expanduser().resolve()
    _write_outputs(
        output_directory,
        reviewed_events,
        extraction,
        siao_result,
        booking_result,
    )
    print(f"Extracted events: {len(reviewed_events)}")
    print(f"OCS bookings: {len(booking_result['ocs'])}")
    print(f"SAFTI bookings: {len(booking_result['safti'])}")
    print(f"Outputs: {output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
