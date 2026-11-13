#!/usr/bin/env python3
"""Validate a multi-hour HRRR surface subset archive for the BTV domain.

This is a non-publishing smoke test. It selects one complete HRRR surface
cycle, downloads each requested hour, decodes the BTV subset, validates
surface fields and grid coverage, and writes an artifact manifest.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mesoscale.download_subset import download
from mesoscale.process_grib import DOMAIN, process_file
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


def _parse_cycle_utc(value: str) -> datetime:
    """Parse the compact UTC cycle format used by the model discovery manifest."""
    try:
        return datetime.strptime(value, "%Y%m%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _parse_valid_time(value: str) -> datetime:
    """Parse an ISO-8601 valid time and normalize it to UTC."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _format_valid_time(value: str) -> str:
    return _parse_valid_time(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def choose_cycle_products_for_valid_times(
    manifest: dict, valid_times: tuple[str, ...]
) -> tuple[str, list[dict]]:
    """Choose one HRRR surface cycle whose forecast hours match every target valid time."""
    targets = tuple(_parse_valid_time(value) for value in valid_times)
    if not targets or len(set(targets)) != len(targets):
        raise ValueError("At least one unique RAP valid time is required")

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
        try:
            cycle_time = _parse_cycle_utc(cycle)
        except (TypeError, ValueError):
            continue
        by_valid_time = {}
        for product in valid:
            if product["cycle_utc"] != cycle:
                continue
            try:
                hour = int(product["forecast_hour"])
                if hour < 0 or hour > 48:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            by_valid_time[cycle_time + timedelta(hours=hour)] = product
        if all(target in by_valid_time for target in targets):
            return cycle, [by_valid_time[target] for target in targets]

    raise RuntimeError(
        "No single HRRR surface cycle contains all requested RAP valid times; "
        "refusing to mix model cycles"
    )


def archive_needs_update(
    manifest: dict,
    existing_archive: dict | None,
    hours: tuple[int, ...],
    valid_times: tuple[str, ...] | None = None,
    archive_root: Path | None = None,
) -> tuple[bool, str]:
    """Skip rebuilding only when HRRR metadata and every referenced grid are complete."""
    if valid_times:
        target_cycle, selected = choose_cycle_products_for_valid_times(manifest, valid_times)
        expected_valid_times = tuple(_format_valid_time(value) for value in valid_times)
        expected_hours = tuple(sorted(int(product["forecast_hour"]) for product in selected))
    else:
        target_cycle, selected = choose_cycle_products(manifest, hours)
        expected_valid_times = None
        expected_hours = tuple(sorted(int(product["forecast_hour"]) for product in selected))

    target_cycle_time = _parse_cycle_utc(target_cycle)
    if target_cycle_time is None or not isinstance(existing_archive, dict):
        return True, target_cycle

    entries = existing_archive.get("hours")
    if not isinstance(entries, list):
        return True, target_cycle
    try:
        archived_hours = tuple(sorted(int(item["forecast_hour"]) for item in entries))
        archived_valid_times = tuple(_format_valid_time(item["valid_time_utc"]) for item in entries)
    except (KeyError, TypeError, ValueError):
        return True, target_cycle

    existing_cycle = existing_archive.get("model_cycle_utc")
    try:
        existing_cycle_time = _parse_cycle_utc(existing_cycle)
    except (TypeError, ValueError):
        existing_cycle_time = None

    required_groups = {"2-m temperature", "10-m u wind", "10-m v wind"}
    def referenced_grid_is_valid(item: dict) -> bool:
        value = item.get("grid_file")
        if not isinstance(value, str) or not value:
            return False
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            return False
        if archive_root is None:
            return True
        path = archive_root / relative
        if not path.is_file() or path.stat().st_size < 100:
            return False
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
            if (
                not isinstance(payload, dict)
                or payload.get("domain") != DOMAIN
                or payload.get("model") != "HRRR"
                or payload.get("model_cycle_utc") != existing_cycle
                or int(payload.get("forecast_hour", -1)) != int(item["forecast_hour"])
                or _format_valid_time(payload.get("valid_time_utc"))
                    != _format_valid_time(item.get("valid_time_utc"))
            ):
                return False
            report = validate_payload(payload, existing_cycle, int(item["forecast_hour"]))
            if (
                report.get("valid_time_utc") != item.get("valid_time_utc")
                or int(report.get("field_count", -1)) != int(item.get("field_count", -2))
                or int(report.get("grid_count", -1)) != int(item.get("grid_count", -2))
            ):
                return False
            recorded_groups = item.get("required_field_groups")
            return (
                isinstance(recorded_groups, dict)
                and required_groups.issubset(set(recorded_groups))
                and required_groups.issubset(set(report.get("required_field_groups", {})))
            )
        except (OSError, EOFError, zlib.error, UnicodeError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
            return False

    files_complete = (
        len(entries) == len(expected_hours)
        and archived_hours == expected_hours
        and all(referenced_grid_is_valid(item) for item in entries)
    )
    if expected_valid_times is not None:
        valid_times_match = archived_valid_times == expected_valid_times
    elif existing_cycle_time is not None:
        expected_from_cycle = tuple(
            (existing_cycle_time + timedelta(hours=int(item["forecast_hour"]))).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            for item in entries
        )
        valid_times_match = archived_valid_times == expected_from_cycle
    else:
        valid_times_match = False

    quality = existing_archive.get("quality")
    quality_passed = isinstance(quality, dict) and quality.get("status") == "passed"
    archive_is_current = (
        existing_archive.get("model") == "HRRR"
        and existing_archive.get("domain") == DOMAIN
        and existing_archive.get("product") == "surface"
        and existing_archive.get("publishing") is True
        and existing_cycle_time is not None
        and existing_cycle_time >= target_cycle_time
        and archived_hours == expected_hours
        and valid_times_match
        and files_complete
        and quality_passed
    )
    return not archive_is_current, target_cycle

def build_archive_manifest(
    cycle: str,
    entries: list[dict],
    valid_times: tuple[str, ...] = (),
    reference_rap_cycle: str | None = None,
) -> dict:
    """Build HRRR archive metadata from the same domain used by the decoder."""
    archive = {
        "schema_version": 1,
        "model": "HRRR",
        "product": "surface",
        "model_cycle_utc": cycle,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "domain": dict(DOMAIN),
        "hours": entries,
        "quality": {"status": "passed", "hours_verified": len(entries)},
        "publishing": False,
    }
    if valid_times and reference_rap_cycle:
        archive["valid_time_alignment"] = {
            "reference_model": "RAP",
            "reference_cycle_utc": reference_rap_cycle,
            "valid_times_utc": [_format_valid_time(value) for value in valid_times],
        }
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--hours", default="0,3,6,9,12,15")
    parser.add_argument(
        "--valid-times",
        default="",
        help="Comma-separated ISO-8601 valid times to align with the published RAP archive",
    )
    parser.add_argument(
        "--reference-rap-cycle",
        default="",
        help="RAP model cycle used to define the requested valid times",
    )
    parser.add_argument("--max-grid-dim", type=int, default=160)
    args = parser.parse_args()

    hours = tuple(sorted({int(value) for value in args.hours.split(",") if value.strip()}))
    valid_times = tuple(value.strip() for value in args.valid_times.split(",") if value.strip())

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if valid_times:
        cycle, products = choose_cycle_products_for_valid_times(manifest, valid_times)
    else:
        if not hours or any(hour < 0 or hour > 48 for hour in hours):
            raise ValueError("HRRR forecast hours must be between 0 and 48")
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

    archive = build_archive_manifest(
        cycle,
        entries,
        valid_times=valid_times,
        reference_rap_cycle=args.reference_rap_cycle or None,
    )
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
        "valid_times_utc": [entry["valid_time_utc"] for entry in entries],
        "reference_rap_cycle": args.reference_rap_cycle or None,
        "manifest": str(manifest_path),
        "publishing": False,
    }, indent=2))


if __name__ == "__main__":
    main()
