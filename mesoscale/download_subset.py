#!/usr/bin/env python3
"""Download compact BTV-area GRIB2 subsets from current NOMADS products.

RAP uses the current 13-km CONUS pressure-level family. HRRR uses its hourly
2-D surface family. Exact filenames come from model_manifest.json so this
script cannot silently reconstruct obsolete product names.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode

import requests

BASE = "https://nomads.ncep.noaa.gov/cgi-bin"
REGION = {"leftlon": -75.2, "rightlon": -71.2, "toplat": 45.3, "bottomlat": 42.3}
MAX_DOWNLOAD_BYTES = 100_000_000

RAP_PRODUCT = "pressure_levels_conus_13km"
HRRR_PRODUCT = "surface"

RAP_VARIABLES = ["TMP", "RH", "HGT", "UGRD", "VGRD"]
RAP_LEVELS = [
    1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 725,
    700, 675, 650, 625, 600, 575, 550, 525, 500, 475, 450, 425,
    400, 375, 350, 325, 300, 275, 250, 225, 200, 175, 150, 125, 100,
]
HRRR_VARIABLES = ["CAPE", "CIN", "PWAT", "DPT", "TMP", "UGRD", "VGRD",
                  "REFC", "GUST", "HPBL", "VIS", "PRATE", "APCP"]
HRRR_LEVELS = [
    "2_m_above_ground", "10_m_above_ground", "80_m_above_ground",
    "surface", "mean_sea_level", "entire_atmosphere",
    "0-3000_m_above_ground", "925_mb", "850_mb", "700_mb", "500_mb",
]


def select_product(manifest: dict, model: str, forecast_hour: int, cycle: str | None = None):
    """Select a current, explicitly supported product family from the manifest."""
    expected_product = {"RAP": RAP_PRODUCT, "HRRR": HRRR_PRODUCT}.get(model)
    if expected_product is None:
        raise ValueError(f"Unsupported subset model: {model}")
    products = manifest.get("models", {}).get(model, {}).get("latest_products", [])
    matches = [
        product for product in products
        if product.get("product") == expected_product
        and product.get("forecast_hour") == forecast_hour
        and product.get("filename")
        and product.get("url")
        and (not cycle or product.get("cycle_utc") == cycle)
    ]
    if not matches:
        return None
    return max(matches, key=lambda product: product["cycle_utc"])


def filter_url(model: str, product: dict) -> str:
    if model == "RAP":
        if product.get("product") != RAP_PRODUCT:
            raise ValueError(f"RAP subset requires {RAP_PRODUCT}, got {product.get('product')!r}")
        script = "filter_rap.pl"
        directory = f"/rap.{product['date']}"
        variables = RAP_VARIABLES
        levels = [f"{level}_mb" for level in RAP_LEVELS]
    elif model == "HRRR":
        if product.get("product") != HRRR_PRODUCT:
            raise ValueError(f"HRRR subset requires {HRRR_PRODUCT}, got {product.get('product')!r}")
        script = "filter_hrrr_2d.pl"
        directory = f"/hrrr.{product['date']}/conus"
        variables = HRRR_VARIABLES
        levels = HRRR_LEVELS
    else:
        raise ValueError(f"Unsupported subset model: {model}")

    params = {
        "file": product["filename"],
        "dir": directory,
        # NOMADS' grib-filter form emits an empty subregion value.
        "subregion": "",
        **REGION,
    }
    params.update({f"var_{name}": "on" for name in variables})
    params.update({f"lev_{name}": "on" for name in levels})
    return f"{BASE}/{script}?{urlencode(params)}"


def download(session, model, product, output_dir):
    url = filter_url(model, product)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        cycle_hour = datetime.fromisoformat(
            product["cycle_utc"].replace("Z", "+00:00")
        ).strftime("%H")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid model cycle timestamp: {product.get('cycle_utc')!r}") from exc
    filename = (
        f"{model.lower()}_{product['date']}_{cycle_hour}_"
        f"f{int(product['forecast_hour']):02d}_btv.grib2"
    )
    destination = output_dir / filename
    temp = destination.with_suffix(destination.suffix + ".part")
    total = 0
    first = b""

    try:
        with session.get(url, stream=True, timeout=(20, 180)) as response:
            response.raise_for_status()
            declared = int(response.headers.get("Content-Length", "0"))
            if declared and declared > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(
                    f"Filtered {model} response exceeds {MAX_DOWNLOAD_BYTES} byte safety cap: {declared}"
                )
            with temp.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    if len(first) < 4:
                        first += chunk[:4 - len(first)]
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError(
                            f"Filtered {model} download exceeded {MAX_DOWNLOAD_BYTES} byte safety cap"
                        )
                    stream.write(chunk)
        if first != b"GRIB":
            raise RuntimeError(f"NOMADS did not return GRIB data for {model}: {first[:300]!r}")
        if total < 1000:
            raise RuntimeError(f"Filtered {model} subset unexpectedly small ({total} bytes): {url}")
        temp.replace(destination)
    except Exception:
        temp.unlink(missing_ok=True)
        raise

    return {
        "model": model, "file": str(destination), "bytes": total, "request_url": url,
        "cycle_utc": product["cycle_utc"], "forecast_hour": product["forecast_hour"],
        "source_file": product["filename"], "product": product["product"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="mesoscale/data/model_manifest.json")
    parser.add_argument("--output-dir", default="mesoscale/data/grib")
    parser.add_argument("--model", choices=["RAP", "HRRR", "both"], default="both")
    parser.add_argument("--forecast-hour", type=int, default=0)
    parser.add_argument("--cycle", help="Optional cycle ISO timestamp, e.g. 2026-11-12T12:00:00Z")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers.update({"User-Agent": "BTV-Mesoscale-Detective/0.1 (NWS forecast office research)"})
    models = ["RAP", "HRRR"] if args.model == "both" else [args.model]
    results, errors = [], []
    for model in models:
        product = select_product(manifest, model, args.forecast_hour, args.cycle)
        if not product:
            errors.append({
                "model": model,
                "error": f"No {model} {RAP_PRODUCT if model == 'RAP' else HRRR_PRODUCT} "
                         f"product at F{args.forecast_hour:02d} in the requested cycle",
            })
            continue
        try:
            results.append(download(session, model, product, Path(args.output_dir)))
        except Exception as exc:
            errors.append({"model": model, "error": f"{type(exc).__name__}: {exc}"})

    report = {"results": results, "errors": errors}
    print(json.dumps(report, indent=2))
    if errors or not results:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
