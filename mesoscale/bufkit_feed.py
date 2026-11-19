"""Acquire and decode real-time BUFKIT point soundings using SHARPpy's native decoder.

The Penn State BUFKIT Data Distribution System publishes per-model, per-station
files over HTTPS. Files are cached locally for a short TTL; no private FTP
server or bulk national archive is required.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import numpy as np
import requests

PSU_ROOT = "https://www.meteo.psu.edu/data/weather/bufkit"
MODEL_PRODUCTS = {
    "RAP": ("RAP", "rap"),
    "HRRR": ("HRRR", "hrrr"),
    "GFS": ("GFS", "gfs3"),
    "NAM": ("NAM", "nam"),
    "NAMNEST": ("NAMNEST", "namnest"),
    "RRFS": ("RRFS", "rrfs"),
    "HIRESW": ("HIRESW", "hiresw"),
}
CACHE_TTL_SECONDS = int(os.getenv("BUFKIT_CACHE_TTL_SECONDS", "300"))


def parse_bufkit_record_headers(text: str) -> list[dict[str, Any]]:
    """Extract station, valid time, and STIM lead from each BUFKIT time block."""
    lines = text.splitlines()
    records = []
    for index, line in enumerate(lines):
        if "STID" not in line or "TIME" not in line:
            continue
        station_match = re.search(r"\bSTID\s*=\s*(\S+)", line)
        time_match = re.search(r"\bTIME\s*=\s*(\d{6}/\d{4})", line)
        if not station_match or not time_match:
            continue
        stim = None
        for candidate in lines[index + 1:index + 5]:
            match = re.search(r"\bSTIM\s*=\s*([-+]?\d+(?:\.\d+)?)", candidate)
            if match:
                stim = float(match.group(1))
                break
        if stim is None:
            raise ValueError(f"BUFKIT record at line {index + 1} has no STIM forecast lead")
        valid_time = datetime.strptime(time_match.group(1), "%y%m%d/%H%M").replace(tzinfo=timezone.utc)
        records.append({
            "station_id": station_match.group(1).upper(),
            "valid_time_utc": valid_time,
            "forecast_hour": stim,
            "model_cycle_utc": valid_time - timedelta(hours=stim),
        })
    if not records:
        raise ValueError("No BUFKIT STID/TIME/STIM records found")
    return records


def _array(values, name: str) -> np.ndarray:
    array = np.ma.asarray(values, dtype=float)
    data = np.asarray(np.ma.getdata(array), dtype=float)
    mask = np.ma.getmaskarray(array) | ~np.isfinite(data)
    if data.ndim != 1:
        raise ValueError(f"SHARPpy BUFKIT field {name} is not one-dimensional")
    return np.ma.array(data, mask=mask)


def _profile_to_contract(profile) -> dict[str, list[float]]:
    """Convert a SHARPpy BUFKIT profile to the common SI profile contract."""
    fields = {
        "pressure_hpa": _array(profile.pres, "PRES"),
        "temperature_c": _array(profile.tmpc, "TMPC"),
        "dewpoint_c": _array(profile.dwpc, "DWPC"),
        "height_msl": _array(profile.hght, "HGHT"),
        "u_kt": _array(profile.u, "U"),
        "v_kt": _array(profile.v, "V"),
    }
    if len({value.size for value in fields.values()}) != 1:
        raise ValueError("SHARPpy BUFKIT profile fields have inconsistent level counts")
    mask = np.ones(fields["pressure_hpa"].shape, dtype=bool)
    for value in fields.values():
        mask &= ~np.ma.getmaskarray(value)
    arrays = {key: np.asarray(value.data[mask], dtype=float) for key, value in fields.items()}
    if len(arrays["pressure_hpa"]) < 10:
        raise ValueError("BUFKIT profile contains fewer than 10 complete levels")
    order = np.argsort(arrays["pressure_hpa"])[::-1]
    arrays = {key: value[order] for key, value in arrays.items()}
    pressure = arrays["pressure_hpa"]
    height = arrays["height_msl"]
    if np.any(pressure <= 0) or not np.all(np.diff(pressure) < 0):
        raise ValueError("BUFKIT pressure must strictly decrease upward")
    if not np.all(np.diff(height) > 0):
        raise ValueError("BUFKIT height must strictly increase upward")
    # BUFKIT height is MSL. The lowest valid model level is used as the
    # profile's zero-height reference, avoiding an invented station elevation.
    height_agl = height - height[0]
    return {
        "pressure_hpa": pressure.tolist(),
        "temperature_k": (arrays["temperature_c"] + 273.15).tolist(),
        "dewpoint_k": (arrays["dewpoint_c"] + 273.15).tolist(),
        "height_agl_m": height_agl.tolist(),
        "u_ms": (arrays["u_kt"] / 1.9438444924406).tolist(),
        "v_ms": (arrays["v_kt"] / 1.9438444924406).tolist(),
    }


def _cache_path(model: str, station: str, cache_dir: str | Path | None = None) -> Path:
    root = Path(cache_dir or os.getenv("BUFKIT_CACHE_DIR", "~/.cache/btv-bufkit")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{model.lower()}_{station.lower()}.buf"


def fetch_and_parse_bufkit(model: str, station: str, cache_dir: str | Path | None = None) -> dict:
    """Download one current PSU BUFKIT file and return all SHARPpy-decoded times."""
    model = model.upper()
    station = station.lower()
    if model not in MODEL_PRODUCTS:
        raise ValueError(f"Unsupported BUFKIT model: {model}")
    if not re.fullmatch(r"[a-z0-9]{3,6}", station):
        raise ValueError("Station identifier must be 3–6 alphanumeric characters")
    folder, prefix = MODEL_PRODUCTS[model]
    source_url = f"{PSU_ROOT}/{folder}/{prefix}_{station}.buf"
    cache_file = _cache_path(model, station, cache_dir)
    metadata_file = cache_file.with_suffix(".json")
    metadata: dict[str, Any] = {}
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = {}

    cache_age = time.time() - cache_file.stat().st_mtime if cache_file.exists() else float("inf")
    if cache_age > CACHE_TTL_SECONDS:
        response = requests.get(
            source_url,
            timeout=(10, 45),
            headers={"User-Agent": "BTV-Mesoscale-Detective/1.0"},
        )
        if response.status_code == 404:
            raise FileNotFoundError(f"No {model} BUFKIT file is published for {station.upper()}")
        response.raise_for_status()
        content = response.content
        if len(content) < 1024 or b"STID" not in content[:20000]:
            raise ValueError("BUFKIT provider response is not a valid sounding file")
        temporary = cache_file.with_suffix(".buf.tmp")
        temporary.write_bytes(content)
        temporary.replace(cache_file)
        metadata = {
            "source_url": source_url,
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
            "bytes": len(content),
        }
        metadata_file.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    text = cache_file.read_text(encoding="utf-8")
    headers = parse_bufkit_record_headers(text)
    try:
        from sharppy.io.buf_decoder import BufDecoder
    except ImportError as exc:
        raise ImportError("SHARPpy's native BUFKIT decoder is required") from exc

    decoder = BufDecoder(str(cache_file))
    collection = decoder.getProfiles()
    profiles = []
    for index, header in enumerate(headers):
        if index:
            collection.advanceTime(1)
        current = collection.getCurrentProfs()
        member = collection.getHighlightedMemberName()
        if member not in current:
            raise ValueError(f"SHARPpy BUFKIT decoder did not return profile {index}")
        profile = current[member]
        if header["station_id"] not in (station.upper(), " "):
            raise ValueError(
                f"BUFKIT station mismatch: requested {station.upper()}, file says {header['station_id']}"
            )
        profile_data = _profile_to_contract(profile)
        profiles.append({
            "model": model,
            "station": station.upper(),
            "model_cycle_utc": header["model_cycle_utc"].isoformat().replace("+00:00", "Z"),
            "forecast_hour": header["forecast_hour"],
            "valid_time_utc": header["valid_time_utc"].isoformat().replace("+00:00", "Z"),
            "profile": profile_data,
            "quality": {
                "status": "passed",
                "levels": len(profile_data["pressure_hpa"]),
                "height_reference": "lowest valid BUFKIT model level (relative AGL)",
                "decoder": "SHARPpy BufDecoder",
            },
        })
    if len(profiles) != len(headers):
        raise ValueError("SHARPpy decoder profile count does not match BUFKIT time-block count")
    return {
        "model": model,
        "station": station.upper(),
        "source": "Penn State BUFKIT Data Distribution System",
        "source_url": source_url,
        "download": metadata,
        "profile_count": len(profiles),
        "profiles": profiles,
    }
