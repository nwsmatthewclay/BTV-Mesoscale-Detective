#!/usr/bin/env python3
"""Download and decode one indexed RAP pressure-level product for BTV smoke validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cfgrib
import requests

MANIFEST = Path("mesoscale/data/model_manifest.json")
OUT = Path("mesoscale/data/ingestion_smoke")


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
            lat_name = next((n for n in ("latitude", "lat") if n in ds.coords), None)
            lon_name = next((n for n in ("longitude", "lon") if n in ds.coords), None)
            has_btv = False
            if lat_name and lon_name:
                lat = ds[lat_name].values
                lon = ds[lon_name].values
                if getattr(lat, "ndim", 0) == 2 and getattr(lon, "ndim", 0) == 2:
                    import numpy as np
                    mask = ((lon >= -75.2) & (lon <= -71.2) &
                            (lat >= 42.3) & (lat <= 45.3))
                    has_btv = bool(np.any(mask))
            if has_btv:
                btv_datasets.append(i)
            inventory.append({
                "dataset": i,
                "variables": names,
                "coordinates": list(ds.coords),
                "shape": {name: list(var.shape) for name, var in ds.data_vars.items()},
                "has_btv_grid_cells": has_btv,
            })
    finally:
        for ds in datasets:
            ds.close()

    if not inventory:
        raise RuntimeError("cfgrib opened no datasets from the downloaded RAP file")
    if not btv_datasets:
        raise RuntimeError("Decoded RAP datasets contain no grid cells inside the BTV domain")
    all_vars = {name for item in inventory for name in item["variables"]}
    if not ({"t", "gh", "u", "v", "r"} & all_vars):
        raise RuntimeError(f"No expected pressure-level meteorological variables found: {sorted(all_vars)}")

    report = {
        "status": "passed",
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
        "datasets": inventory,
    }
    report_path = OUT / "rap_ingestion_smoke_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "status", "filename", "cycle_utc", "forecast_hour", "file_bytes",
        "cfgrib_dataset_count", "btv_intersecting_dataset_indices", "variables"
    )}, indent=2))


if __name__ == "__main__":
    main()
