#!/usr/bin/env python3
"""Download, decode, and validate compact regional RAP pressure-level extraction for BTV."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cfgrib
import requests

# Allow this script to run directly from the repository root in GitHub Actions.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_grib import process_file

MANIFEST = Path("mesoscale/data/model_manifest.json")
OUT = Path("mesoscale/data/ingestion_smoke")
BTV_BOUNDS = {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3}


def choose_product(manifest: dict) -> dict:
    products = manifest["models"]["RAP"]["latest_products"]
    candidates = [
        p for p in products
        if p.get("index", {}).get("message_count", 0) > 0
        and p.get("product") in {"pressure_levels_conus_early", "pressure_levels_conus"}
    ]
    if not candidates:
        raise RuntimeError("No indexed RAP pressure-level product is available in the manifest")
    return max(candidates, key=lambda p: (p["cycle_utc"], p["forecast_hour"]))


def coordinate_summary(ds, name):
    import numpy as np
    if name not in ds.variables:
        return None
    var = ds[name]
    values = np.asarray(var.values)
    finite = values[np.isfinite(values)] if np.issubdtype(values.dtype, np.number) else []
    sample = values.reshape(-1)[:8].tolist() if values.size else []
    return {
        "dims": list(var.dims),
        "shape": list(var.shape),
        "dtype": str(values.dtype),
        "min": float(np.min(finite)) if len(finite) else None,
        "max": float(np.max(finite)) if len(finite) else None,
        "sample": sample,
        "attrs": {k: str(v) for k, v in var.attrs.items()},
    }


def btv_intersection(ds):
    import numpy as np
    lat_name = next((n for n in ("latitude", "lat") if n in ds.variables), None)
    lon_name = next((n for n in ("longitude", "lon") if n in ds.variables), None)
    if not lat_name or not lon_name:
        return False, {"reason": "latitude/longitude variables absent", "lat_name": lat_name, "lon_name": lon_name}
    lat = np.asarray(ds[lat_name].values)
    lon = np.asarray(ds[lon_name].values)
    try:
        lat, lon = np.broadcast_arrays(lat, lon)
    except ValueError:
        return False, {"reason": "latitude/longitude shapes cannot broadcast",
                       "latitude_shape": list(lat.shape), "longitude_shape": list(lon.shape)}
    lon = ((lon + 180.0) % 360.0) - 180.0
    finite = np.isfinite(lat) & np.isfinite(lon)
    mask = (finite & (lon >= BTV_BOUNDS["west"]) & (lon <= BTV_BOUNDS["east"]) &
            (lat >= BTV_BOUNDS["south"]) & (lat <= BTV_BOUNDS["north"]))
    return bool(np.any(mask)), {
        "latitude_name": lat_name, "longitude_name": lon_name,
        "latitude_shape": list(lat.shape), "longitude_shape": list(lon.shape),
        "latitude_min": float(np.nanmin(lat)), "latitude_max": float(np.nanmax(lat)),
        "longitude_min_normalized": float(np.nanmin(lon)),
        "longitude_max_normalized": float(np.nanmax(lon)),
        "btv_cell_count": int(np.count_nonzero(mask)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-bytes", type=int, default=180_000_000)
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    product = choose_product(manifest)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / product["filename"]

    if not target.exists():
        with requests.get(product["url"], stream=True, timeout=(30, 240),
                          headers={"User-Agent": "BTV-Mesoscale-Detective/0.1"}) as response:
            response.raise_for_status()
            declared = int(response.headers.get("Content-Length", "0"))
            if declared and declared > args.max_bytes:
                raise RuntimeError(f"RAP file too large for smoke test: {declared} bytes")
            first = b""
            total = 0
            temp = target.with_suffix(target.suffix + ".part")
            with temp.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    if not first:
                        first = chunk[:4]
                    total += len(chunk)
                    if total > args.max_bytes:
                        raise RuntimeError(f"Download exceeded safety cap of {args.max_bytes} bytes")
                    stream.write(chunk)
            if first != b"GRIB":
                temp.unlink(missing_ok=True)
                raise RuntimeError(f"Downloaded response is not GRIB2 (header={first!r})")
            temp.replace(target)

    if target.stat().st_size < 100_000:
        raise RuntimeError(f"Downloaded GRIB is unexpectedly small: {target.stat().st_size} bytes")

    datasets = cfgrib.open_datasets(str(target), backend_kwargs={"indexpath": ""})
    inventory = []
    btv_datasets = []
    try:
        for i, ds in enumerate(datasets):
            names = list(ds.data_vars)
            has_btv, grid = btv_intersection(ds)
            if has_btv:
                btv_datasets.append(i)
            inventory.append({
                "dataset": i,
                "variables": names,
                "dimensions": {k: int(v) for k, v in ds.sizes.items()},
                "coordinates": list(ds.coords),
                "all_variables": list(ds.variables),
                "coordinate_details": {
                    n: coordinate_summary(ds, n)
                    for n in ("latitude", "longitude", "lat", "lon", "x", "y")
                    if n in ds.variables
                },
                "grid_check": grid,
                "global_attrs": {k: str(v) for k, v in ds.attrs.items()},
                "shape": {name: list(var.shape) for name, var in ds.data_vars.items()},
                "has_btv_grid_cells": has_btv,
            })
    finally:
        for ds in datasets:
            ds.close()

    all_vars = {name for item in inventory for name in item["variables"]}
    passed = bool(inventory) and bool(btv_datasets) and bool({"t", "gh", "u", "v", "r"} & all_vars)
    processed = None
    if passed:
        field_path = OUT / f"rap_f{int(product['forecast_hour']):02d}_btv.json.gz"
        payload = process_file(
            target, "RAP", product["cycle_utc"], int(product["forecast_hour"]),
            field_path, max_grid_dim=160
        )
        required_fields = {"t", "gh", "u", "v"}
        extracted_short_names = {item["short_name"] for item in payload["fields"].values()}
        processed = {
            "output_file": field_path.name,
            "output_bytes": field_path.stat().st_size,
            "field_count": payload["quality"]["field_count"],
            "grid_count": payload["quality"]["grid_count"],
            "warnings": payload["quality"]["warnings"],
            "extracted_short_names": sorted(extracted_short_names),
            "required_fields_present": sorted(required_fields & extracted_short_names),
        }
        if not required_fields.issubset(extracted_short_names):
            passed = False
            processed["error"] = "One or more required upper-air fields were not extracted"
    report = {
        "status": "passed" if passed else "failed",
        "model": "RAP",
        "product": product["product"],
        "filename": product["filename"],
        "url": product["url"],
        "cycle_utc": product["cycle_utc"],
        "forecast_hour": product["forecast_hour"],
        "file_bytes": target.stat().st_size,
        "cfgrib_dataset_count": len(inventory),
        "btv_intersecting_dataset_indices": btv_datasets,
        "variables": sorted(all_vars),
        "btv_bounds": BTV_BOUNDS,
        "processed_btv_payload": processed,
        "datasets": inventory,
    }
    report_path = OUT / "rap_ingestion_smoke_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "status", "filename", "cycle_utc", "forecast_hour", "file_bytes",
        "cfgrib_dataset_count", "btv_intersecting_dataset_indices", "variables", "processed_btv_payload"
    )}, indent=2))
    if not passed:
        raise RuntimeError(f"RAP ingestion validation failed; inspect {report_path}")


if __name__ == "__main__":
    main()
