"""Download and retain several cycles of regional BUFKIT point files.

The PSU BUFKIT directory is probed using the model-specific station filename.
Only complete BUFKIT text files with parseable STID/TIME/STIM headers are saved.
The archive is organized by model initialization cycle and station ID.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "bufkit_sites.json"
ARCHIVE = ROOT / "data" / "bufkit" / "archive"
BASE = "https://www.meteo.psu.edu/data/weather/bufkit"
PRODUCTS = {
    "RRFS": ("RRFS", "rrfs", ("latest", "")),
    "GFS": ("GFS", "gfs3", ("latest", "")),
    "RAP": ("RAP", "rap", ("latest", "")),
    "HRRR": ("HRRR", "hrrr", ("latest", "")),
}
USER_AGENT = "BTV-Mesoscale-Detective/1.0 (BUFKIT archive)"
HEADER_RE = re.compile(r"\bSTID\s*=\s*(\S+).*?\bTIME\s*=\s*(\d{6}/\d{4})")

def parse_cycle(text: str) -> tuple[str, str, list[dict[str, Any]]]:
    lines = text.splitlines()
    records = []
    for i, line in enumerate(lines):
        match = HEADER_RE.search(line)
        if not match:
            continue
        stim = None
        for candidate in lines[i + 1:i + 5]:
            found = re.search(r"\bSTIM\s*=\s*([-+]?\d+(?:\.\d+)?)", candidate)
            if found:
                stim = float(found.group(1))
                break
        if stim is None:
            continue
        valid = datetime.strptime(match.group(2), "%y%m%d/%H%M").replace(tzinfo=timezone.utc)
        cycle = valid.timestamp() - stim * 3600
        cycle_dt = datetime.fromtimestamp(cycle, tz=timezone.utc)
        records.append({
            "station_id": match.group(1).strip().upper(),
            "valid_time_utc": valid.isoformat().replace("+00:00", "Z"),
            "forecast_hour": stim,
            "model_cycle_utc": cycle_dt.isoformat().replace("+00:00", "Z"),
        })
    if not records:
        raise ValueError("No parseable BUFKIT STID/TIME/STIM headers")
    cycles = sorted({r["model_cycle_utc"] for r in records})
    if len(cycles) != 1:
        raise ValueError(f"File contains multiple model cycles: {cycles}")
    return cycles[0], records[0]["station_id"], records

def fetch_file(session: requests.Session, model: str, station: str) -> tuple[bytes, str]:
    folder, prefix, variants = PRODUCTS[model]
    errors = []
    for variant in variants:
        middle = f"{variant}/" if variant else ""
        url = f"{BASE}/{folder}/{middle}{prefix}_{station.lower()}.buf"
        try:
            response = session.get(url, timeout=(10, 40))
            if response.status_code == 404:
                errors.append(f"{url}:404")
                continue
            response.raise_for_status()
            content = response.content
            if len(content) < 1000 or b"STID" not in content[:30000]:
                errors.append(f"{url}:not BUFKIT")
                continue
            return content, url
        except requests.RequestException as exc:
            errors.append(f"{url}:{exc.__class__.__name__}")
    raise FileNotFoundError("; ".join(errors))

def prune_model(model: str, keep: int) -> list[str]:
    model_dir = ARCHIVE / model
    if not model_dir.exists():
        return []
    cycles = sorted([p for p in model_dir.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    removed = []
    for old in cycles[keep:]:
        shutil.rmtree(old)
        removed.append(old.name)
    return removed

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=PRODUCTS.keys(), action="append")
    parser.add_argument("--station", action="append")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    models = args.model or config["models"]
    stations = args.station or [s["id"] for s in config["stations"]]
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    summary = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "provider": BASE, "models": {}}
    for model in models:
        successes, failures, cycles_seen = [], [], set()
        for station in stations:
            try:
                content, source_url = fetch_file(session, model, station)
                cycle, file_station, records = parse_cycle(content.decode("ascii", errors="replace"))
                if file_station not in (station.upper(), " "):
                    raise ValueError(f"Requested {station}, file header says {file_station}")
                cycle_key = cycle.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
                target_dir = ARCHIVE / model / cycle_key
                target = target_dir / f"{station.lower()}.buf"
                if not args.dry_run:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(".buf.tmp")
                    temporary.write_bytes(content)
                    temporary.replace(target)
                    metadata = {
                        "model": model, "station": station.upper(),
                        "model_cycle_utc": cycle, "source_url": source_url,
                        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                        "bytes": len(content), "forecast_hours": [r["forecast_hour"] for r in records],
                        "valid_times_utc": [r["valid_time_utc"] for r in records],
                    }
                    target.with_suffix(".json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
                cycles_seen.add(cycle)
                successes.append({"station":station.upper(),"cycle":cycle,"bytes":len(content),"forecast_hours":len(records)})
            except Exception as exc:
                failures.append({"station":station.upper(),"error":str(exc)[:240]})
            time.sleep(0.12)
        removed = [] if args.dry_run else prune_model(model, int(config["retention_cycles"][model]))
        summary["models"][model] = {
            "success_count":len(successes),"failure_count":len(failures),
            "cycles_seen":sorted(cycles_seen),"retention_cycles":config["retention_cycles"][model],
            "pruned_cycles":removed,"successes":successes,"failures":failures,
        }
        print(f"{model}: {len(successes)} successful station files; {len(failures)} unavailable/failed; cycles={sorted(cycles_seen)}")
        for failure in failures:
            print(f"  {failure['station']}: {failure['error']}")
    if not args.dry_run:
        manifest_path = ROOT / "data" / "bufkit" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    # Publish a compact index of every retained model cycle and station file.
    catalog = {"schema_version": 1, "updated_at_utc": summary["created_at_utc"], "provider": BASE, "retention_cycles": config["retention_cycles"], "models": {}}
    for model in config["models"]:
        model_dir = ARCHIVE / model
        entries = []
        if model_dir.exists():
            for cycle_dir in sorted((p for p in model_dir.iterdir() if p.is_dir()), key=lambda p:p.name, reverse=True):
                stations_in_cycle = []
                for meta_path in sorted(cycle_dir.glob("*.json")):
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        buf_path = meta_path.with_suffix(".buf")
                        if buf_path.exists():
                            stations_in_cycle.append({
                                "station": meta["station"], "file": str(buf_path.relative_to(ROOT / "data" / "bufkit")),
                                "bytes": meta["bytes"], "forecast_hours": meta["forecast_hours"],
                                "valid_times_utc": meta["valid_times_utc"], "source_url": meta["source_url"]
                            })
                    except (OSError, ValueError, KeyError):
                        continue
                if stations_in_cycle:
                    entries.append({"cycle_key": cycle_dir.name, "model_cycle_utc": json.loads((cycle_dir / (stations_in_cycle[0]["station"].lower()+".json")).read_text(encoding="utf-8"))["model_cycle_utc"], "stations": stations_in_cycle})
        catalog["models"][model] = entries
    catalog_path = ROOT / "data" / "bufkit" / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2)+"\\n", encoding="utf-8")
    print(json.dumps({m:{k:v for k,v in d.items() if k not in ("successes","failures")} for m,d in summary["models"].items()},indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
