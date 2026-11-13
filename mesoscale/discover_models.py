#!/usr/bin/env python3
"""Discover recent RAP/HRRR/RRFS GRIB2 products and inspect their indexes.

This is a discovery/metadata step, not a bulk downloader. It probes the
official NCEP production directory listings, selects recent files using
published naming conventions, and records GRIB index metadata so the next
stage can request only the needed fields and BTV subregion.

Examples:
  python mesoscale/discover_models.py
  python mesoscale/discover_models.py --days-back 2 --output mesoscale/data/model_manifest.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com"
HEADERS = {"User-Agent": "BTV-Mesoscale-Detective/0.1 (NWS forecast office research)"}
TIMEOUT = 25
RAP_FILENAME_RE = re.compile(r"rap\.t(\d{2})z\.(awp130[bp]grb|awip32)f(\d{2,3})\.grib2$")
RRFS_FILENAME_RE = re.compile(
    r"rrfs\.t(?P<cycle>\d{2})z\.(?P<family>prslev|2dfld)\.3km(?P<subhourly>\.subh)?\.f(?P<forecast>\d{3})\.conus\.grib2$"
)
RRFS_CYCLE_DIR_RE = re.compile(r"\d{2}")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def get_listing(session: requests.Session, url: str) -> list[str]:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    parser = Links()
    parser.feed(response.text)
    return [urljoin(url, href) for href in parser.hrefs]


def index_summary(session: requests.Session, grib_url: str) -> dict:
    """Parse a NOMADS GRIB index, rejecting HTML/error pages returned as HTTP 200."""
    idx_url = grib_url + ".idx"
    response = session.get(idx_url, timeout=TIMEOUT)
    response.raise_for_status()
    lines = [line.strip().lstrip("\ufeff") for line in response.text.splitlines() if line.strip()]
    messages = []
    for line in lines:
        parts = line.split(":")
        if (
            len(parts) < 5
            or not re.fullmatch(r"\d+(?:\.\d+)?", parts[0])
            or not parts[1].isdigit()
            or not parts[2].startswith("d=")
            or not parts[3].strip()
        ):
            continue
        messages.append({
            "message": parts[0],
            "byte_offset": int(parts[1]),
            "reference": parts[2],
            "level": parts[3],
            "description": ":".join(parts[4:]),
        })
    if not messages:
        raise ValueError(f"NOMADS index response contained no valid GRIB index records: {idx_url}")
    return {"url": idx_url, "message_count": len(messages), "messages": messages}


def rap_product_role(family: str) -> str:
    """Return the physical RAP product family represented by its filename token.

    awp130bgrb contains native/hybrid model levels (used for soundings);
    awp130pgrb is pressure-level output; awip32 is a separate 32-km product.
    """
    return {
        "awp130bgrb": "hybrid_levels_conus_13km",
        "awp130pgrb": "pressure_levels_conus_13km",
        "awip32": "north_american_32km",
    }[family]


def rrfs_product_role(family: str, subhourly: bool = False) -> str:
    """Normalize RRFS 3-km filename variants to explicit product roles."""
    if family == "prslev" and not subhourly:
        return "pressure_levels_3km"
    if family == "2dfld" and subhourly:
        return "surface_subhourly_3km"
    if family == "2dfld":
        return "surface_2d_3km"
    raise ValueError(f"Unsupported RRFS product family: {family}")


def discover_model(session, model, days_back):
    found = []
    today = datetime.now(timezone.utc).date()
    for day_offset in range(days_back + 1):
        day = today - timedelta(days=day_offset)
        date_str = day.strftime("%Y%m%d")
        if model == "RAP":
            directory = f"{BASE}/rap/prod/rap.{date_str}/"
            # Operational 13-km CONUS RAP includes native hybrid-level
            # awp130bgrb and isobaric awp130pgrb products. awip32 is a
            # separate 32-km product and must not be treated as a sounding source.
            pattern = RAP_FILENAME_RE
        else:
            directory = f"{BASE}/hrrr/prod/hrrr.{date_str}/conus/"
            pattern = re.compile(r"hrrr\.t(\d{2})z\.(wrfprsf|wrfsfcf)(\d{2,3})\.grib2$")
            role = None
        try:
            urls = get_listing(session, directory)
        except requests.RequestException as exc:
            found.append({"date": date_str, "directory": directory,
                          "error": f"{type(exc).__name__}: {exc}"})
            continue
        for url in urls:
            filename = url.rsplit("/", 1)[-1]
            match = pattern.match(filename)
            if not match:
                continue
            if model == "RAP":
                cycle, family, forecast = match.groups()
                product_role = rap_product_role(family)
            else:
                cycle, family, forecast = match.groups()
                product_role = "pressure_levels" if family == "wrfprsf" else "surface"
            found.append({
                "model": model,
                "date": date_str,
                "cycle_utc": f"{date_str}T{cycle}:00:00Z",
                "forecast_hour": int(forecast),
                "product": product_role,
                "filename": filename,
                "url": url,
            })
    return found



def discover_rrfs(session, days_back):
    """Discover deterministic 3-km CONUS RRFS pressure and 2-D products."""
    found = []
    today = datetime.now(timezone.utc).date()
    pattern = RRFS_FILENAME_RE
    for day_offset in range(days_back + 1):
        date_str = (today - timedelta(days=day_offset)).strftime("%Y%m%d")
        day_dir = f"{BASE}/rrfs/prod/rrfs.{date_str}/"
        try:
            cycle_dirs = get_listing(session, day_dir)
        except requests.RequestException as exc:
            found.append({"date": date_str, "directory": day_dir,
                          "error": f"{type(exc).__name__}: {exc}"})
            continue
        for cycle_dir in cycle_dirs:
            cycle_name = cycle_dir.rstrip("/").rsplit("/", 1)[-1]
            if not RRFS_CYCLE_DIR_RE.fullmatch(cycle_name):
                continue
            try:
                urls = get_listing(session, cycle_dir)
            except requests.RequestException as exc:
                found.append({"date": date_str, "directory": cycle_dir,
                              "error": f"{type(exc).__name__}: {exc}"})
                continue
            for url in urls:
                filename = url.rsplit("/", 1)[-1]
                match = pattern.match(filename)
                if not match:
                    continue
                cycle = match.group("cycle")
                family = match.group("family")
                forecast = match.group("forecast")
                subhourly = bool(match.group("subhourly"))
                found.append({
                    "model": "RRFS", "date": date_str,
                    "cycle_utc": f"{date_str}T{cycle}:00:00Z",
                    "forecast_hour": int(forecast),
                    "product": rrfs_product_role(family, subhourly=subhourly),
                    "resolution_km": 3, "domain": "conus",
                    "filename": filename, "url": url,
                })
    return found


def prioritize_latest_products(products: list[dict], limit: int = 120) -> list[dict]:
    """Keep the newest cycle first while retaining the shortest forecast hours.

    Short-range RAP fields are needed for the BTV forecast archive. Sorting
    forecast hour descending before truncation silently dropped F00-F09 once
    longer RAP forecast hours became available.
    """
    ordered = sorted(
        products,
        key=lambda p: (p["cycle_utc"], -int(p["forecast_hour"]), p["product"]),
        reverse=True,
    )
    return ordered[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days-back", type=int, default=2,
                        help="Search today and this many previous UTC dates")
    parser.add_argument("--output", default="mesoscale/data/model_manifest.json")
    parser.add_argument("--index-latest", action="store_true",
                        help="Fetch .idx metadata for newest discovered product in each model family")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)
    report = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": "NCEP NOMADS operational production directories",
        "domain": {"west": -75.2, "east": -71.2, "south": 42.3, "north": 45.3},
        "models": {},
        "errors": [],
    }
    for model in ("RAP", "HRRR", "RRFS"):
        products = (discover_rrfs(session, max(0, args.days_back))
                    if model == "RRFS"
                    else discover_model(session, model, max(0, args.days_back)))
        all_valid = [p for p in products if p.get("url")]
        valid = prioritize_latest_products(all_valid)
        if args.index_latest:
            # Index the nearest-term product in each family (F00 where available).
            # This keeps useful index metadata without making ingestion depend on it.
            chosen = []
            families = sorted({p["product"] for p in valid})
            for family in families:
                item = next((p for p in valid if p["product"] == family), None)
                if item:
                    chosen.append(item)
            for item in chosen:
                try:
                    item["index"] = index_summary(session, item["url"])
                except (requests.RequestException, ValueError) as exc:
                    item["index_error"] = f"{type(exc).__name__}: {exc}"
        report["models"][model] = {
            "products_found": len(all_valid),
            "latest_products": valid[:120],
            "directory_errors": [p for p in products if p.get("error")],
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for model, data in report["models"].items():
        print(f"{model}: {data['products_found']} product(s) discovered")
        for item in data["latest_products"][:3]:
            print(f"  {item['cycle_utc']} F{item['forecast_hour']:02d} {item['product']} {item['filename']}")
    print(f"Manifest written: {output}")
    if not any(report["models"][m]["products_found"] for m in report["models"]):
        print("No products discovered. Check NOMADS reachability and directory conventions.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
