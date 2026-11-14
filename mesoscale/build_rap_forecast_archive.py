#!/usr/bin/env python3
"""Build a small, verified RAP forecast-hour archive for the BTV domain.

The archive contains a handful of forecast hours from one RAP cycle. Each
hour is independently decoded, cropped, quality-checked, and accompanied by
station profiles. The manifest is published only after all selected hours
complete successfully.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_grib import DOMAIN, RAP_MAX_GRID_DIM, process_file
from extract_profile import extract_profile

MANIFEST = Path("mesoscale/data/model_manifest.json")
OUT = Path("mesoscale/data/forecast_archive")
FIELDS_OUT = OUT / "fields"
STATIONS = {
    "KBTV": (44.4719, -73.1533), "KPBG": (44.6509, -73.4681),
    "KMSS": (44.9358, -74.8456), "KSLK": (44.3853, -74.2062),
    "KMPV": (44.2035, -72.5623), "KRUT": (43.5294, -72.9496),
    "1V4": (44.4193, -72.0194), "KEFK": (44.8888, -72.2292),
}
HOURS = (0, 3, 6, 9, 12, 15)
HYBRID_FILENAME_RE = re.compile(r"rap\.t\d{2}z\.awp130bgrbf\d{2,3}\.grib2$")
MAX_BYTES = 180_000_000


def summarize_rap_field_inventory(payload: dict) -> tuple[int, set[str]]:
    """Return decoded field records separately from unique GRIB short names."""
    fields = payload.get("fields")
    quality = payload.get("quality")
    if not isinstance(fields, dict) or not isinstance(quality, dict):
        raise ValueError("RAP payload must contain field and quality mappings")
    field_record_count = int(quality.get("field_count", -1))
    if field_record_count != len(fields):
        raise ValueError(
            "RAP quality field_count does not match decoded field records: "
            f"{field_record_count} != {len(fields)}"
        )
    unique_short_names = {
        field["short_name"]
        for field in fields.values()
        if isinstance(field, dict) and field.get("short_name")
    }
    return field_record_count, unique_short_names


def choose_cycle_products(manifest: dict, hours: tuple[int, ...]) -> tuple[str, list[dict]]:
    products = manifest["models"]["RAP"]["latest_products"]
    # Select by the actual NOMADS filename token, not a loosely named
    # manifest family. awp130bgrb is the verified 13-km native/hybrid-level
    # product; awip32 does not provide the hybrid column required for soundings.
    valid = [
        p for p in products
        if p.get("url") and HYBRID_FILENAME_RE.fullmatch(p.get("filename", ""))
    ]
    if not valid:
        raise RuntimeError("No RAP 13-km CONUS hybrid-level files found in model manifest")
    cycles = sorted({p["cycle_utc"] for p in valid}, reverse=True)
    for cycle in cycles:
        cycle_items = [p for p in valid if p["cycle_utc"] == cycle]
        by_hour = {int(p["forecast_hour"]): p for p in cycle_items}
        if all(hour in by_hour for hour in hours):
            return cycle, [by_hour[hour] for hour in hours]
    raise RuntimeError(
        "No single RAP 13-km CONUS hybrid-level cycle contains all requested forecast hours"
    )


def _parse_utc(value: object) -> datetime | None:
    """Parse an ISO UTC timestamp, accepting compact NOMADS and standard ISO forms."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _expected_valid_time(cycle: object, hour: int) -> str | None:
    cycle_time = _parse_utc(cycle)
    if cycle_time is None:
        return None
    return (cycle_time + timedelta(hours=int(hour))).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _archive_file_matches(path: Path, item: dict, cycle: str, kind: str) -> bool:
    """Return whether a published RAP grid or station JSON matches its manifest entry."""
    try:
        if kind == "grid":
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return False
        if (
            payload.get("model") != "RAP"
            or payload.get("model_cycle_utc") != cycle
            or int(payload.get("forecast_hour", -1)) != int(item["forecast_hour"])
            or payload.get("valid_time_utc") != item.get("valid_time_utc")
        ):
            return False
        if kind == "grid":
            # Rebuild older archives when the geographic crop definition changes.
            if payload.get("domain") != DOMAIN:
                return False
            processing = payload.get("processing")
            if not isinstance(processing, dict) or int(processing.get("max_grid_dim", -1)) != RAP_MAX_GRID_DIM:
                return False
            fields = payload.get("fields")
            grids = payload.get("grids")
            quality = payload.get("quality")
            sampling_matches = isinstance(grids, dict) and bool(grids) and all(
                isinstance(grid, dict)
                and int(grid.get("max_grid_dim", -1)) == RAP_MAX_GRID_DIM
                and isinstance(grid.get("sampling"), dict)
                and int(grid["sampling"].get("max_grid_dim", -1)) == RAP_MAX_GRID_DIM
                and int(grid.get("stride", -1)) == int(grid["sampling"].get("stride", -2))
                for grid in grids.values()
            )
            return (
                isinstance(fields, dict) and bool(fields)
                and isinstance(grids, dict) and bool(grids)
                and sampling_matches
                and isinstance(quality, dict)
                and len(fields) == int(quality.get("field_count", -1))
                and len(grids) == int(quality.get("grid_count", -1))
                and len(fields) == int(item.get("field_count", -2))
                and len(grids) == int(item.get("grid_count", -2))
            )
        stations = payload.get("stations")
        if not isinstance(stations, dict) or len(stations) != int(item.get("station_count", -1)):
            return False
        return all(
            profile.get("model") == "RAP"
            and profile.get("model_cycle_utc") == cycle
            and int(profile.get("forecast_hour", -1)) == int(item["forecast_hour"])
            and profile.get("valid_time_utc") == item.get("valid_time_utc")
            and int((profile.get("quality") or {}).get("levels", 0)) >= 20
            and (profile.get("quality") or {}).get("pressure_decreases_upward") is True
            and (profile.get("quality") or {}).get("height_increases_upward") is True
            for profile in stations.values()
            if isinstance(profile, dict)
        ) and all(isinstance(profile, dict) for profile in stations.values())
    except (OSError, EOFError, zlib.error, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        return False


def archive_needs_update(manifest: dict, existing_archive: dict | None,
                         hours: tuple[int, ...],
                         archive_root: Path | None = None) -> tuple[bool, str]:
    """Skip rebuilding only when archive metadata and referenced files are complete."""
    target_cycle, _ = choose_cycle_products(manifest, hours)
    target_time = _parse_utc(target_cycle)
    expected_hours = tuple(sorted(int(hour) for hour in hours))
    if target_time is None or not isinstance(existing_archive, dict):
        return True, target_cycle

    entries = existing_archive.get("hours")
    if not isinstance(entries, list):
        return True, target_cycle
    try:
        archived_hours = tuple(sorted(int(item["forecast_hour"]) for item in entries))
    except (KeyError, TypeError, ValueError):
        return True, target_cycle

    existing_cycle = existing_archive.get("model_cycle_utc")
    existing_time = _parse_utc(existing_cycle)
    quality_passed = (existing_archive.get("quality") or {}).get("status") == "passed"

    def referenced_file_matches(value: object, item: dict, kind: str) -> bool:
        if not isinstance(value, str) or not value:
            return False
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            return False
        if archive_root is None:
            return True
        path = archive_root / relative
        return path.is_file() and path.stat().st_size > 0 and _archive_file_matches(
            path, item, existing_cycle, kind
        )

    files_complete = (
        len(entries) == len(expected_hours)
        and archived_hours == expected_hours
        and all(
            referenced_file_matches(item.get("grid_file"), item, "grid")
            and referenced_file_matches(item.get("station_file"), item, "station")
            for item in entries
        )
    )
    valid_times_match = (
        existing_time is not None
        and len(entries) == len(expected_hours)
        and all(
            item.get("valid_time_utc")
            == _expected_valid_time(existing_cycle, int(item["forecast_hour"]))
            for item in entries
        )
    )
    archive_is_current = (
        existing_archive.get("model") == "RAP"
        and existing_time is not None
        and existing_time >= target_time
        and (existing_archive.get("processing") or {}).get("max_grid_dim") == RAP_MAX_GRID_DIM
        and archived_hours == expected_hours
        and files_complete
        and valid_times_match
        and quality_passed
    )
    return not archive_is_current, target_cycle

def download(url: str, destination: Path, session: requests.Session) -> int:
    if destination.exists() and destination.stat().st_size >= 100_000:
        return destination.stat().st_size
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    total = 0
    with session.get(url, stream=True, timeout=(30, 240)) as response:
        response.raise_for_status()
        declared = int(response.headers.get("Content-Length", "0"))
        if declared and declared > MAX_BYTES:
            raise RuntimeError(f"RAP file exceeds {MAX_BYTES} byte safety cap: {declared}")
        with temp.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError(f"RAP download exceeded {MAX_BYTES} byte safety cap")
                stream.write(chunk)
    with temp.open("rb") as stream:
        if stream.read(4) != b"GRIB":
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"Invalid GRIB header for {url}")
    temp.replace(destination)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", default="0,3,6,9,12,15")
    args = parser.parse_args()
    hours = tuple(sorted({int(v) for v in args.hours.split(",") if v.strip()}))
    if not hours or any(h < 0 or h > 21 for h in hours):
        raise ValueError("Forecast hours must be between 0 and 21")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cycle, products = choose_cycle_products(manifest, hours)
    OUT.mkdir(parents=True, exist_ok=True)
    FIELDS_OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "BTV-Mesoscale-Detective/0.1"})
    entries = []
    for product in products:
        hour = int(product["forecast_hour"])
        grib_path = OUT / "downloads" / product["filename"]
        size = download(product["url"], grib_path, session)
        field_path = FIELDS_OUT / f"rap_f{hour:02d}.json.gz"
        payload = process_file(grib_path, "RAP", cycle, hour, field_path, max_grid_dim=RAP_MAX_GRID_DIM)
        field_record_count, names = summarize_rap_field_inventory(payload)
        required = {"t", "gh", "u", "v", "q", "pres"}
        if not required.issubset(names):
            raise RuntimeError(f"F{hour:02d} missing required profile fields: {sorted(required-names)}")
        station_profiles = {}
        for station, (lat, lon) in STATIONS.items():
            profile = extract_profile(payload, lat, lon, station)
            if (profile["quality"]["levels"] < 20
                    or not profile["quality"]["pressure_decreases_upward"]
                    or not profile["quality"]["height_increases_upward"]):
                raise RuntimeError(f"F{hour:02d} station profile quality failure at {station}")
            station_profiles[station] = profile
        station_path = FIELDS_OUT / f"rap_f{hour:02d}_stations.json"
        station_path.write_text(json.dumps({
            "model": "RAP", "model_cycle_utc": cycle, "forecast_hour": hour,
            "valid_time_utc": payload["valid_time_utc"], "stations": station_profiles
        }, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
        entries.append({
            "forecast_hour": hour, "valid_time_utc": payload["valid_time_utc"],
            "source_file": product["filename"], "download_bytes": size,
            "grid_file": f"fields/{field_path.name}",
            "station_file": f"fields/{station_path.name}",
            "field_count": payload["quality"]["field_count"],
            "grid_count": payload["quality"]["grid_count"],
            "grid_sampling": {grid_id: grid.get("sampling") for grid_id, grid in payload["grids"].items()},
            "station_count": len(station_profiles),
        })
        print(f"Verified RAP F{hour:02d}: {size:,} GRIB bytes, {field_record_count} field records across {len(names)} unique short names, {len(station_profiles)} station profiles")
    archive = {
        "schema_version": 1, "model": "RAP", "model_cycle_utc": cycle,
        "created_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "domain": payload["domain"], "hours": entries,
        "processing": {"max_grid_dim": RAP_MAX_GRID_DIM, "sampling_method": "uniform row/column stride"},
        "quality": {"status": "passed", "hours_verified": len(entries)},
    }
    (OUT / "forecast_manifest.json").write_text(
        json.dumps(archive, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "passed", "cycle": cycle, "hours": [e["forecast_hour"] for e in entries]}))


if __name__ == "__main__":
    main()
