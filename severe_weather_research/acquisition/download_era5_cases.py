#!/usr/bin/env python3
"""Download daily ERA5 pressure-level and single-level GRIBs for case dates."""
from __future__ import annotations
import csv, os, sys, time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
META = ROOT / "data" / "metadata"
MANIFEST = Path(__file__).with_name("case_manifest.csv")
LOG = META / "acquisition_log.csv"
AREA = [46.0, -76.5, 41.5, -70.5]  # N, W, S, E; padded BTV region
PRESSURE_LEVELS = ["1000", "975", "950", "925", "900", "875", "850", "825", "800", "775", "750", "700", "650", "600", "550", "500", "450", "400", "350", "300", "250", "200", "150", "100", "70", "50", "30", "20", "10"]
PRESSURE_VARIABLES = ["geopotential", "temperature", "u_component_of_wind",
                       "v_component_of_wind", "relative_humidity"]
SINGLE_VARIABLES = ["2m_temperature", "2m_dewpoint_temperature",
                    "10m_u_component_of_wind", "10m_v_component_of_wind",
                    "surface_pressure", "total_precipitation"]

def append_log(case_id, date, dataset, path, status, detail=""):
    META.mkdir(parents=True, exist_ok=True)
    exists = LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["timestamp_utc", "case_id", "date", "dataset", "file", "status", "detail"])
        w.writerow([datetime.utcnow().isoformat(timespec="seconds"), case_id, date, dataset, str(path), status, detail])

def request_for_day(client, dataset, variables, date, target, extra=None):
    year, month, day = date.split("-")
    req = {
        "product_type": ["reanalysis"],
        "variable": variables,
        "year": [year], "month": [month], "day": [day],
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": AREA,
        "data_format": "grib",
        "download_format": "unarchived",
    }
    if extra:
        req.update(extra)
    client.retrieve(dataset, req, str(target))

def main():
    token = os.getenv("CDS_API_KEY", "").strip()
    if not token:
        print("ERROR: CDS_API_KEY environment variable is not set.", file=sys.stderr)
        return 2
    try:
        import cdsapi
    except ImportError:
        print("ERROR: cdsapi is not installed.", file=sys.stderr)
        return 2

    RAW.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=token)
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    failures = 0
    for case in cases:
        case_id, date = case["case_id"], case["event_date_utc"]
        for dataset, variables, suffix, extra in [
            ("reanalysis-era5-pressure-levels", PRESSURE_VARIABLES, "pressure_levels_full.grib",
             {"pressure_level": PRESSURE_LEVELS}),
            ("reanalysis-era5-single-levels", SINGLE_VARIABLES, "single_levels.grib", None),
        ]:
            outdir = RAW / case_id / date
            outdir.mkdir(parents=True, exist_ok=True)
            target = outdir / suffix
            if target.exists() and target.stat().st_size > 0:
                print(f"SKIP existing {target}")
                append_log(case_id, date, dataset, target, "skipped-existing")
                continue
            print(f"REQUEST {case_id} {date} {dataset}")
            try:
                request_for_day(client, dataset, variables, date, target, extra)
                if not target.exists() or target.stat().st_size == 0:
                    raise RuntimeError("request completed but output file missing/empty")
                print(f"OK {target} ({target.stat().st_size:,} bytes)")
                append_log(case_id, date, dataset, target, "success", f"{target.stat().st_size} bytes")
            except Exception as exc:
                failures += 1
                print(f"FAIL {case_id} {dataset}: {exc}", file=sys.stderr)
                append_log(case_id, date, dataset, target, "failed", str(exc)[:1000])
                time.sleep(3)
    print(f"Finished: {len(cases)} cases; failures={failures}")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
