#!/usr/bin/env python3
"""Validate a multi-hour HRRR surface subset archive for the BTV domain.

This is a non-publishing smoke test. It selects one complete HRRR surface
cycle, downloads each requested hour, decodes the BTV subset, validates
surface fields and grid coverage, and writes an artifact manifest.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mesoscale.download_subset import download
from mesoscale.process_grib import process_file
from mesoscale.validate_hrrr_ingestion import validate_payload

DEFAULT_MANIFEST = Path("mesoscale/data/model_manifest.json")
DEFAULT_OUTPUT = Path("mesoscale/data/ingestion_smoke/hrrr")
SURFACE_FILENAME_RE = re.compile(r"hrrr\.t\d{2}z\.wrfsfcf\d{2,3}\.grib2$")


def choose_cycle_products(manifest: dict, hours: tuple[int, ...]) -> tuple[str, list[dict]]:
    """Choose one latest HRRR surface cycle containing every requested hour."""
    products = manifest.get("models", {}).get("HRRR", {}).get("latest_products", [])
    valid = [
        product for product in products
        if product.get("product") == "surface"
        and product.get("url")
        and SURFACE_FILENAME_RE.fullmatch(product.get("filename", ""))
        and product.get("cycle_utc")
    ]
    if not valid:
        raise RuntimeError("No HRRR surface GRIB2 products are available in the model manifest")

    cycles = sorted({product["cycle_utc"] for product in valid}, reverse=True)
    for cycle in cycles:
        by_hour = {}
        for product in valid:
            if product["cycle_utc"] == cycle:
                try:
                    by_hour[int(product["forecast_hour"])] = product
                except (KeyError, TypeError, ValueError):
                    continue
        if all(hour in by_hour for hour in hours):
            return cycle, [by_hour[hour] for hour in hours]

    raise RuntimeError(
        "No single HRRR surface cycle contains all requested forecast hours; "
        "refusing to mix model cycles"
    )


def archive_needs_update(manifest: dict, existing_archive: dict | None,
                         hours: tuple[int, ...]) -> tuple[bool, str]:
    """Skip a rebuild when the published HRRR archive covers the newest complete cycle."""
    target_cycle, _ = choose_cycle_products(manifest, hours)
    expected_hours = tuple(sorted(int(hour) for hour in hours))
    if not isinstance(existing_archive, dict):
        return True, target_cycle

    entries = existing_archive.get("hours") or []
    try:
        archived_hours = tuple(sorted(int(item["forecast_hour"]) for item in entries))
    except (KeyError, TypeError, ValueError):
        return True, target_cycle

    required_groups = {"2-m temperature", "10-m u wind", "10-m v wind"}
    files_complete = (
        len(entries) == len(expected_hours)
        and all(item.get("grid_file") for item in entries)
        and all(required_groups.issubset(set((item.get("required_field_groups") or {}).keys()))
                for item in entries)
    )
    quality_passed = (existing_archive.get("quality") or {}).get("status") == "passed"
    existing_cycle = existing_archive.get("model_cycle_utc")
    archive_is_current = (
        existing_archive.get("model") == "HRRR"
        and existing_archive.get("product") == "surface"
        and existing_archive.get("publishing") is True
        and isinstance(existing_cycle, str)
        and existing_cycle >= target_cycle
        and archived_hours == expected_hours
        and files_complete
        and quality_passed
    )
    return not archive_is_current, target_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--hours", default="0,3,6,9")
    parser.add_argument("--max-grid-dim", type=int, default=160)
    args = parser.parse_args()

    hours = tuple(sorted({int(value) for value in args.hours.split(",") if value.strip()}))
    if not hours or any(hour < 0 or hour > 48 for hour in hours):
        raise ValueError("HRRR forecast hours must be between 0 and 48")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    cycle, products = choose_cycle_products(manifest, hours)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "BTV-Mesoscale-Detective/0.1 (NWS forecast office research)"
    })
    entries = []
    for product in products:
        hour = int(product["forecast_hour"])
        downloaded = download(session, "HRRR", product, output_dir)
        grid_path = output_dir / f"hrrr_f{hour:02d}_btv.json.gz"
        payload = process_file(
            Path(downloaded["file"]), "HRRR", cycle, hour,
            grid_path, max_grid_dim=args.max_grid_dim
        )
        quality = validate_payload(payload, cycle, hour)
        entries.append({
            "forecast_hour": hour,
            "valid_time_utc": quality["valid_time_utc"],
            "source_file": downloaded["source_file"],
            "download_bytes": downloaded["bytes"],
            "grid_file": grid_path.name,
            "decoded_bytes": grid_path.stat().st_size,
            "grid_count": quality["grid_count"],
            "field_count": quality["field_count"],
            "available_short_names": quality["available_short_names"],
            "required_field_groups": quality["required_field_groups"],
            "warnings": quality["warnings"],
        })
        print(
            f"Verified HRRR F{hour:02d}: {downloaded['bytes']:,} GRIB bytes, "
            f"{quality['grid_count']} BTV grids, {quality['field_count']} fields"
        )

    archive = {
        "schema_version": 1,
        "model": "HRRR",
        "product": "surface",
        "model_cycle_utc": cycle,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "domain": {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3},
        "hours": entries,
        "quality": {"status": "passed", "hours_verified": len(entries)},
        "publishing": False,
    }
    manifest_path = output_dir / "hrrr_forecast_manifest.json"
    manifest_path.write_text(
        json.dumps(archive, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "passed",
        "model": "HRRR",
        "cycle": cycle,
        "hours": [entry["forecast_hour"] for entry in entries],
        "manifest": str(manifest_path),
        "publishing": False,
    }, indent=2))


if __name__ == "__main__":
    main()
