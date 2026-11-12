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
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_grib import process_file
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
HOURS = (0, 3, 6, 9)
HYBRID_FILENAME_RE = re.compile(r"rap\.t\d{2}z\.awp130bgrbf\d{2,3}\.grib2$")
MAX_BYTES = 180_000_000


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
    parser.add_argument("--hours", default="0,3,6,9")
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
        payload = process_file(grib_path, "RAP", cycle, hour, field_path, max_grid_dim=160)
        names = {item["short_name"] for item in payload["fields"].values()}
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
            "station_count": len(station_profiles),
        })
        print(f"Verified RAP F{hour:02d}: {size:,} GRIB bytes, {len(names)} fields, {len(station_profiles)} station profiles")
    archive = {
        "schema_version": 1, "model": "RAP", "model_cycle_utc": cycle,
        "created_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "domain": payload["domain"], "hours": entries,
        "quality": {"status": "passed", "hours_verified": len(entries)},
    }
    (OUT / "forecast_manifest.json").write_text(
        json.dumps(archive, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "passed", "cycle": cycle, "hours": [e["forecast_hour"] for e in entries]}))


if __name__ == "__main__":
    main()
