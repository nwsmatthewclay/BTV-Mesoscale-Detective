#!/usr/bin/env python3
"""Non-publishing HRRR surface-subset smoke test for the BTV domain."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# Support direct execution as `python mesoscale/validate_hrrr_ingestion.py`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests

from mesoscale.download_subset import download, select_product
from mesoscale.process_grib import HRRR_MAX_GRID_DIM, process_file

DEFAULT_MANIFEST = Path("mesoscale/data/model_manifest.json")
DEFAULT_OUTPUT = Path("mesoscale/data/ingestion_smoke/hrrr")
BTV = {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3}
REQUIRED_GROUPS = {
    "2-m temperature": {"2t", "t2m"},
    "10-m u wind": {"10u", "u10"},
    "10-m v wind": {"10v", "v10"},
}


def iter_finite_numbers(value):
    if isinstance(value, list):
        for item in value:
            yield from iter_finite_numbers(item)
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        yield float(value)


def finite_value_count(value) -> int:
    return sum(1 for _ in iter_finite_numbers(value))


def validate_payload(payload: dict, expected_cycle: str, expected_hour: int) -> dict:
    """Validate decoded HRRR metadata, BTV grid coverage, and core surface fields."""
    if payload.get("model") != "HRRR":
        raise RuntimeError(f"Expected HRRR payload, got {payload.get('model')!r}")
    if payload.get("model_cycle_utc") != expected_cycle:
        raise RuntimeError(
            f"HRRR cycle mismatch: expected {expected_cycle}, got {payload.get('model_cycle_utc')!r}"
        )
    if int(payload.get("forecast_hour", -1)) != int(expected_hour):
        raise RuntimeError(
            f"HRRR forecast-hour mismatch: expected F{expected_hour:02d}, "
            f"got {payload.get('forecast_hour')!r}"
        )

    grids = payload.get("grids") or {}
    fields = payload.get("fields") or {}
    if not grids or not fields:
        raise RuntimeError("Decoded HRRR payload contains no regional grids or fields")

    btv_coverage = False
    for grid in grids.values():
        latitudes = list(iter_finite_numbers(grid.get("latitude")))
        longitudes = list(iter_finite_numbers(grid.get("longitude")))
        if any(
            BTV["south"] <= lat <= BTV["north"]
            and BTV["west"] <= lon <= BTV["east"]
            for lat, lon in zip(latitudes, longitudes)
        ):
            btv_coverage = True
            break
    if not btv_coverage:
        raise RuntimeError("Decoded HRRR grids contain no coordinates inside the BTV domain")

    found_groups = {}
    missing_groups = []
    for label, accepted_names in REQUIRED_GROUPS.items():
        matches = [
            field for field in fields.values()
            if field.get("short_name") in accepted_names
            and finite_value_count(field.get("data")) > 0
        ]
        if not matches:
            missing_groups.append(label)
        else:
            found_groups[label] = sorted({field["short_name"] for field in matches})
    if missing_groups:
        raise RuntimeError(
            "HRRR subset is missing finite BTV data for: " + ", ".join(missing_groups)
        )

    return {
        "status": "passed",
        "model": "HRRR",
        "cycle_utc": expected_cycle,
        "forecast_hour": int(expected_hour),
        "valid_time_utc": payload.get("valid_time_utc"),
        "grid_count": len(grids),
        "field_count": len(fields),
        "available_short_names": sorted({
            str(field.get("short_name")) for field in fields.values()
            if field.get("short_name")
        }),
        "required_field_groups": found_groups,
        "warnings": (payload.get("quality") or {}).get("warnings", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--forecast-hour", type=int, default=0)
    parser.add_argument("--max-grid-dim", type=int, default=HRRR_MAX_GRID_DIM)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "hrrr_smoke_report.json"
    report = {"status": "failed", "model": "HRRR", "forecast_hour": args.forecast_hour}

    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        product = select_product(manifest, "HRRR", args.forecast_hour)
        if not product:
            raise RuntimeError(
                f"No HRRR surface product at F{args.forecast_hour:02d} is available in the model manifest"
            )

        session = requests.Session()
        session.headers.update({
            "User-Agent": "BTV-Mesoscale-Detective/0.1 (NWS forecast office research)"
        })
        downloaded = download(session, "HRRR", product, output_dir)
        grid_path = output_dir / f"hrrr_f{args.forecast_hour:02d}_btv.json.gz"
        payload = process_file(
            Path(downloaded["file"]), "HRRR", product["cycle_utc"],
            int(product["forecast_hour"]), grid_path, max_grid_dim=args.max_grid_dim
        )
        report = validate_payload(payload, product["cycle_utc"], args.forecast_hour)
        report["processing"] = payload.get("processing")
        report["grid_sampling"] = {grid_id: grid.get("sampling") for grid_id, grid in payload.get("grids", {}).items()}
        report.update({
            "source_file": downloaded["source_file"],
            "download_bytes": downloaded["bytes"],
            "decoded_file": grid_path.name,
            "decoded_bytes": grid_path.stat().st_size,
            "request_url": downloaded["request_url"],
        })
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report_path.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        raise

    report_path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
