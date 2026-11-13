#!/usr/bin/env python3
"""Create a non-published, BTV-masked RRFS 3-km point subset from indexed GRIB messages."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from mesoscale.rrfs_range_smoke import (
    BTV_DOMAIN, fetch_indexed_message, plan_index_ranges,
    select_rrfs_product, validate_decoded_cycle,
)

HEADERS = {
    "User-Agent": "BTV-Mesoscale-Detective/0.1 (forecast office research)",
    "Accept-Encoding": "identity",
}
REQUIRED_FIELDS = ("TMP", "DPT", "UGRD", "VGRD")
ECCODES_ALIASES = {"TMP": "2t", "DPT": "2d", "UGRD": "10u", "VGRD": "10v"}
EXPECTED_LEVELS = {"TMP": 2, "DPT": 2, "UGRD": 10, "VGRD": 10}
EXPECTED_UNITS = {"TMP": {"k"}, "DPT": {"k"}, "UGRD": {"ms-1", "m/s"}, "VGRD": {"ms-1", "m/s"}}


def normalize_units(value):
    return str(value or "").strip().lower().replace(" ", "").replace("**", "").replace("^", "")
GRID_KEYS = (
    "grid_type", "ni", "nj", "number_of_points",
    "i_scans_negatively", "j_scans_positively",
    "j_points_are_consecutive", "alternative_row_scanning",
)


def parse_cycle(value):
    match = re.fullmatch(
        r"(\d{4})(\d{2})(\d{2})T(\d{2})(?::?(\d{2}))?(?::?(\d{2}))?Z?",
        str(value),
    )
    if match:
        parts = [int(part or 0) for part in match.groups()]
        return datetime(*parts, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Model cycle must include a UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def step_range_minutes(value):
    match = re.fullmatch(r"(\d+)\s*(?:m|min|minutes?)", str(value or "").strip(), re.I)
    if not match:
        raise ValueError(f"Unsupported RRFS stepRange; expected minutes, got {value!r}")
    return int(match.group(1))


def decode_grib_message_arrays(payload):
    try:
        from eccodes import (
            codes_get, codes_get_array, codes_new_from_message, codes_release,
        )
    except ImportError as exc:
        raise RuntimeError("RRFS subset extraction requires ecCodes") from exc

    handle = codes_new_from_message(payload)
    if handle is None:
        raise RuntimeError("ecCodes could not create a handle for the RRFS message")

    def optional(key):
        try:
            return codes_get(handle, key)
        except Exception:
            return None

    try:
        values = np.asarray(codes_get_array(handle, "values"), dtype=np.float64).reshape(-1)
        latitudes = np.asarray(codes_get_array(handle, "latitudes"), dtype=np.float64).reshape(-1)
        longitudes = np.asarray(codes_get_array(handle, "longitudes"), dtype=np.float64).reshape(-1)
        if not values.size or values.size != latitudes.size or values.size != longitudes.size:
            raise RuntimeError("RRFS values and coordinate arrays must be non-empty and equal length")
        metadata = {
            "short_name": optional("shortName"),
            "type_of_level": optional("typeOfLevel"),
            "level": optional("level"),
            "units": optional("units"),
            "data_date": optional("dataDate"),
            "data_time": optional("dataTime"),
            "step_range": optional("stepRange"),
            "grid_type": optional("gridType"),
            "ni": optional("Ni"),
            "nj": optional("Nj"),
            "number_of_points": int(values.size),
            "i_scans_negatively": optional("iScansNegatively"),
            "j_scans_positively": optional("jScansPositively"),
            "j_points_are_consecutive": optional("jPointsAreConsecutive"),
            "alternative_row_scanning": optional("alternativeRowScanning"),
        }
        return {
            "metadata": metadata, "values": values,
            "latitudes": latitudes, "longitudes": longitudes,
        }
    finally:
        codes_release(handle)


def build_btv_subset(product, decoded_fields, domain=BTV_DOMAIN):
    names = tuple(str(item.get("index_short_name") or "").upper() for item in decoded_fields)
    if names != REQUIRED_FIELDS:
        raise ValueError(f"RRFS subset requires fields in this order: {', '.join(REQUIRED_FIELDS)}")

    first = decoded_fields[0]["decoded"]
    base_meta = first["metadata"]
    lat = np.asarray(first["latitudes"], dtype=np.float64).reshape(-1)
    lon = np.asarray(first["longitudes"], dtype=np.float64).reshape(-1)
    if not lat.size or lat.size != lon.size:
        raise ValueError("RRFS latitude/longitude arrays must be non-empty and equal length")
    ni, nj = base_meta.get("ni"), base_meta.get("nj")
    if ni is None or nj is None or int(ni) * int(nj) != lat.size:
        raise ValueError("RRFS grid Ni/Nj do not match decoded coordinate-array length")

    lon = ((lon + 180.0) % 360.0) - 180.0
    inside = (
        np.isfinite(lat) & np.isfinite(lon)
        & (lon >= float(domain["west"])) & (lon <= float(domain["east"]))
        & (lat >= float(domain["south"])) & (lat <= float(domain["north"]))
    )
    common = inside.copy()
    field_values = {}
    field_meta = {}

    for item in decoded_fields:
        name = str(item["index_short_name"]).upper()
        decoded = item["decoded"]
        meta = decoded["metadata"]
        alias = str(meta.get("short_name") or "").lower()
        if alias != ECCODES_ALIASES[name]:
            raise ValueError(f"RRFS {name} decoded as {alias!r}; expected {ECCODES_ALIASES[name]!r}")
        expected_level = EXPECTED_LEVELS[name]
        if str(meta.get("type_of_level") or "").lower() != "heightaboveground":
            raise ValueError(f"RRFS {name} must be heightAboveGround; got {meta.get('type_of_level')!r}")
        if meta.get("level") is None or int(meta["level"]) != expected_level:
            raise ValueError(f"RRFS {name} must be at {expected_level} m AGL; got {meta.get('level')!r}")
        units = normalize_units(meta.get("units"))
        if units not in EXPECTED_UNITS[name]:
            raise ValueError(f"RRFS {name} has unexpected units {meta.get('units')!r}")
        for key in GRID_KEYS:
            if meta.get(key) != base_meta.get(key):
                raise ValueError(f"RRFS {name} grid metadata differs at {key}")

        field_lat = np.asarray(decoded["latitudes"], dtype=np.float64).reshape(-1)
        field_lon = np.asarray(decoded["longitudes"], dtype=np.float64).reshape(-1)
        if field_lat.size != lat.size or field_lon.size != lat.size:
            raise ValueError(f"RRFS {name} coordinate-array length differs")
        if not np.allclose(field_lat, np.asarray(first["latitudes"]).reshape(-1), rtol=0, atol=1e-6, equal_nan=True):
            raise ValueError(f"RRFS {name} latitude grid differs")
        if not np.allclose(field_lon, np.asarray(first["longitudes"]).reshape(-1), rtol=0, atol=1e-6, equal_nan=True):
            raise ValueError(f"RRFS {name} longitude grid differs")

        values = np.asarray(decoded["values"], dtype=np.float64).reshape(-1)
        if values.size != lat.size:
            raise ValueError(f"RRFS {name} value-array length differs from grid")
        common &= np.isfinite(values)
        field_values[name] = values
        record = item.get("record") or {}
        field_meta[name] = {
            "index_short_name": name,
            "eccodes_short_name": alias,
            "units": meta.get("units"),
            "type_of_level": meta.get("type_of_level"),
            "level": meta.get("level"),
            "step_range": meta.get("step_range"),
            "index_message": record.get("message"),
            "byte_start": record.get("start"),
            "byte_end": record.get("end"),
            "bytes": record.get("bytes"),
        }

    point_count = int(common.sum())
    if point_count < 1:
        raise RuntimeError("No common finite RRFS grid points fall inside the BTV analysis domain")
    lead = int(product.get("forecast_lead_minutes") or 0)
    if lead < 1:
        raise ValueError("RRFS product is missing a positive forecast_lead_minutes")
    cycle = parse_cycle(product["cycle_utc"])
    valid = cycle + timedelta(minutes=lead)
    steps = {step_range_minutes(item["decoded"]["metadata"].get("step_range")) for item in decoded_fields}
    if steps != {lead}:
        raise ValueError(f"RRFS GRIB stepRange values {sorted(steps)} do not match {lead} minutes")

    selected_lat = lat[common].astype(np.float32)
    selected_lon = lon[common].astype(np.float32)
    arrays = {
        "latitudes": selected_lat,
        "longitudes": selected_lon,
        **{name: values[common].astype(np.float32) for name, values in field_values.items()},
    }
    metadata = {
        "schema_version": 1,
        "model": "RRFS",
        "product": product.get("product"),
        "source_file": product.get("filename"),
        "source_url": product.get("url"),
        "index_url": (product.get("index") or {}).get("url"),
        "model_cycle_utc": cycle.isoformat().replace("+00:00", "Z"),
        "forecast_step": product.get("forecast_step"),
        "forecast_lead_minutes": lead,
        "valid_time_utc": valid.isoformat().replace("+00:00", "Z"),
        "domain": dict(domain),
        "subset_type": "unstructured_btv_domain_mask",
        "grid": {key: base_meta.get(key) for key in GRID_KEYS},
        "native_grid_point_count": int(lat.size),
        "btv_point_count": point_count,
        "btv_bounds": {
            "south": float(selected_lat.min()), "north": float(selected_lat.max()),
            "west": float(selected_lon.min()), "east": float(selected_lon.max()),
        },
        "fields": field_meta,
        "quality": {
            "status": "passed", "common_finite_points": point_count,
            "required_fields": list(REQUIRED_FIELDS), "field_count": len(REQUIRED_FIELDS),
        },
        "publication": False,
    }
    return metadata, arrays


def extract_btv_subset(manifest, session, decoder=decode_grib_message_arrays):
    product = select_rrfs_product(manifest)
    index = product["index"]
    if index.get("url") != product.get("url", "") + ".idx":
        raise ValueError("RRFS index URL does not match selected GRIB product URL")
    records = plan_index_ranges(
        index.get("messages") or [],
        limit=len(REQUIRED_FIELDS),
        preferred_short_names=REQUIRED_FIELDS,
    )
    decoded_fields = []
    for record in records:
        payload = fetch_indexed_message(session, product["url"], record)
        decoded = decoder(payload)
        meta = decoded["metadata"]
        if meta.get("data_date") is None or meta.get("data_time") is None:
            raise ValueError("RRFS GRIB message is missing reference date/time metadata")
        validate_decoded_cycle(meta, product["cycle_utc"])
        decoded_fields.append({
            "index_short_name": str(record.get("short_name") or "").upper(),
            "record": record,
            "decoded": decoded,
        })
    return build_btv_subset(product, decoded_fields)


def write_btv_subset(output_dir, metadata, arrays):
    output_dir.mkdir(parents=True, exist_ok=True)
    cycle = parse_cycle(metadata["model_cycle_utc"])
    step = int(metadata.get("forecast_step") or 0)
    stem = (
        f"rrfs_btv_{cycle:%Y%m%d}_{cycle:%H}z_f{step:03d}_"
        f"{metadata['forecast_lead_minutes']}m"
    )
    npz_path = output_dir / f"{stem}.npz"
    json_path = output_dir / f"{stem}.json"
    npz_temp = output_dir / f"{stem}.npz.part"
    json_temp = output_dir / f"{stem}.json.part"
    try:
        with npz_temp.open("wb") as stream:
            np.savez_compressed(stream, **arrays)
        json_temp.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        npz_temp.replace(npz_path)
        json_temp.replace(json_path)
    except Exception:
        npz_temp.unlink(missing_ok=True)
        json_temp.unlink(missing_ok=True)
        raise
    return {
        "subset_file": str(npz_path),
        "metadata_file": str(json_path),
        "subset_bytes": npz_path.stat().st_size,
        "metadata_bytes": json_path.stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="mesoscale/data/model_manifest.json")
    parser.add_argument("--output-dir", default="mesoscale/data/rrfs_smoke")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    report_path = output_dir / "rrfs_btv_subset_report.json"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        session = requests.Session()
        session.headers.update(HEADERS)
        metadata, arrays = extract_btv_subset(manifest, session)
        files = write_btv_subset(output_dir, metadata, arrays)
        report = {
            "status": "passed", "model": "RRFS",
            "model_cycle_utc": metadata["model_cycle_utc"],
            "forecast_step": metadata["forecast_step"],
            "forecast_lead_minutes": metadata["forecast_lead_minutes"],
            "valid_time_utc": metadata["valid_time_utc"],
            "btv_point_count": metadata["btv_point_count"],
            "field_count": metadata["quality"]["field_count"],
            "fields": metadata["fields"],
            "publication": False,
            **files,
        }
    except Exception as exc:
        report = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "publication": False,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), file=sys.stderr)
        return 1
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
