#!/usr/bin/env python3
"""Validate ERA5 pilot artifacts; optionally decode metadata with cfgrib."""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "acquisition" / "case_manifest.csv"
EXPECTED = {
    "pressure_levels.grib": 888720,
    "single_levels.grib": 152352,
}

def grib_signature(path: Path) -> bool:
    with path.open("rb") as f:
        head = f.read(4)
    return head == b"GRIB"

def inspect_with_cfgrib(path: Path):
    try:
        import cfgrib
    except ImportError:
        return {"decode": "unavailable", "reason": "cfgrib/eccodes not installed"}
    try:
        datasets = cfgrib.open_datasets(str(path))
        summary = []
        for ds in datasets:
            summary.append({
                "variables": list(ds.data_vars),
                "dimensions": {k: int(v) for k, v in ds.sizes.items()},
                "coordinates": {
                    k: (str(ds[k].values.min()), str(ds[k].values.max()))
                    for k in ds.coords if ds[k].size
                },
            })
        return {"decode": "success", "datasets": summary}
    except Exception as exc:
        return {"decode": "failed", "reason": str(exc)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "metadata" / "validation_report.json")
    parser.add_argument("--decode", action="store_true", help="Attempt GRIB metadata decoding (requires cfgrib/eccodes)")
    args = parser.parse_args()

    with MANIFEST.open(newline="", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    results = []
    failures = []
    for case in cases:
        case_id, date = case["case_id"], case["event_date_utc"]
        folder = args.raw_dir / case_id / date
        for filename, expected_size in EXPECTED.items():
            path = folder / filename
            item = {"case_id": case_id, "date": date, "file": filename}
            if not path.exists():
                item.update(status="missing", bytes=0, grib_signature=False)
                failures.append(f"{case_id}: missing {filename}")
            else:
                size = path.stat().st_size
                signature = grib_signature(path)
                item.update(status="ok" if size > 0 and signature else "invalid",
                            bytes=size, expected_bytes=expected_size, grib_signature=signature,
                            size_matches_pilot= size == expected_size)
                if size <= 0 or not signature:
                    failures.append(f"{case_id}: invalid GRIB file {filename}")
                if args.decode:
                    item["metadata"] = inspect_with_cfgrib(path)
            results.append(item)

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cases_expected": len(cases),
        "files_expected": len(cases) * len(EXPECTED),
        "files_found": sum(1 for r in results if r.get("status") == "ok"),
        "failures": failures,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["cases_expected", "files_expected", "files_found", "failures"]}, indent=2))
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
