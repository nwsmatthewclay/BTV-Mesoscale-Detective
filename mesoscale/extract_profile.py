#!/usr/bin/env python3
"""Extract a nearest-grid RAP hybrid-level sounding and diagnose it with MetPy."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import metpy.calc as mpcalc
from metpy.units import units

from diagnostics import diagnose_profile


def nearest_grid_index(grid: dict, latitude: float, longitude: float):
    lat = np.asarray(grid["latitude"], dtype=float)
    lon = np.asarray(grid["longitude"], dtype=float)
    if lat.shape != lon.shape or lat.ndim != 2:
        raise ValueError("Grid latitude/longitude must be matching 2-D arrays")
    # Haversine distance is robust across longitude wrap.
    lat1 = np.deg2rad(latitude)
    lat2 = np.deg2rad(lat)
    dlat = lat2 - lat1
    dlon = np.deg2rad(lon - longitude)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    distance = 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    distance[~(np.isfinite(lat) & np.isfinite(lon))] = np.inf
    if not np.isfinite(distance).any():
        raise ValueError("No finite grid coordinates available")
    iy, ix = np.unravel_index(np.argmin(distance), distance.shape)
    return int(iy), int(ix), float(distance[iy, ix]), float(lat[iy, ix]), float(lon[iy, ix])


def _find_field(payload, short_name, grid_id=None, require_hybrid=False):
    matches = [
        field for field in payload["fields"].values()
        if field["short_name"] == short_name
        and (grid_id is None or field["grid_id"] == grid_id)
        and (not require_hybrid or "hybrid" in field.get("dimensions", []))
    ]
    if not matches:
        raise ValueError(f"Required RAP field missing: {short_name}")
    # Prefer the hybrid-level field and a field with explicit units.
    return matches[0]


def extract_profile(payload: dict, latitude: float, longitude: float, label="custom"):
    # Select the hybrid-level temperature grid first, then require every
    # atmospheric variable to be collocated on that exact grid.
    temperature = _find_field(payload, "t", require_hybrid=True)
    grid_id = temperature["grid_id"]
    if temperature.get("units") != "K":
        raise ValueError(f"Unexpected temperature units: {temperature.get('units')}")
    grid = payload["grids"][grid_id]
    iy, ix, distance_km, grid_lat, grid_lon = nearest_grid_index(grid, latitude, longitude)

    selected = {}
    for short_name in ("pres", "t", "q", "gh", "u", "v"):
        field = _find_field(payload, short_name, grid_id=grid_id, require_hybrid=True)
        values = np.asarray(field["data"], dtype=float)
        if values.ndim != 3 or values.shape[1:] != tuple(grid["shape"]):
            raise ValueError(f"{short_name} is not a 3-D hybrid field on {grid_id}")
        selected[short_name] = values[:, iy, ix]

    pressure = selected["pres"] / 100.0  # Pa -> hPa
    temperature_k = selected["t"]
    specific_humidity = selected["q"]
    height_msl = selected["gh"]  # gpm is geopotential metres for this product
    u_ms, v_ms = selected["u"], selected["v"]

    if not (np.all(np.isfinite(pressure)) and np.all(pressure > 0)):
        raise ValueError("Invalid pressure values in sampled RAP column")
    if np.any((specific_humidity < 0) | (specific_humidity >= 1)):
        raise ValueError("Specific humidity outside physical bounds")
    # MetPy's thermodynamic conversion uses actual pressure at each hybrid level.
    dewpoint = mpcalc.dewpoint_from_specific_humidity(
        pressure * units.hPa,
        temperature_k * units.kelvin,
        specific_humidity * units("dimensionless"),
    )
    dewpoint_k = dewpoint.to("kelvin").magnitude

    # Convert MSL geopotential height to AGL using the collocated RAP orography.
    orog_field = _find_field(payload, "orog")
    orog_grid = payload["grids"][orog_field["grid_id"]]
    oy, ox, orog_distance, _, _ = nearest_grid_index(orog_grid, latitude, longitude)
    terrain = float(np.asarray(orog_field["data"], dtype=float)[oy, ox])
    height_agl = height_msl - terrain

    # Sort the entire collocated column by descending pressure; never sort
    # individual variables independently.
    order = np.argsort(pressure)[::-1]
    pressure, temperature_k, dewpoint_k, height_agl, u_ms, v_ms = [
        np.asarray(a)[order] for a in
        (pressure, temperature_k, dewpoint_k, height_agl, u_ms, v_ms)
    ]
    keep = np.ones(pressure.shape, dtype=bool)
    for array in (temperature_k, dewpoint_k, height_agl, u_ms, v_ms):
        keep &= np.isfinite(array)
    pressure, temperature_k, dewpoint_k, height_agl, u_ms, v_ms = [
        a[keep] for a in (pressure, temperature_k, dewpoint_k, height_agl, u_ms, v_ms)
    ]
    diagnostics = diagnose_profile(
        pressure, temperature_k, dewpoint_k, height_agl, u_ms, v_ms
    )
    return {
        "label": label,
        "requested_location": {"latitude": latitude, "longitude": longitude},
        "sampled_grid_point": {
            "latitude": grid_lat, "longitude": grid_lon,
            "distance_km": distance_km, "grid_id": grid_id,
            "grid_index": {"y": iy, "x": ix},
            "terrain_elevation_m": terrain,
            "orography_grid_distance_km": orog_distance,
            "sampling_method": "nearest_grid_point",
        },
        "model": payload["model"],
        "model_cycle_utc": payload["model_cycle_utc"],
        "forecast_hour": payload["forecast_hour"],
        "valid_time_utc": payload["valid_time_utc"],
        "source_file": payload["source_file"],
        "profile": {
            "pressure_hpa": pressure.tolist(),
            "temperature_k": temperature_k.tolist(),
            "dewpoint_k": dewpoint_k.tolist(),
            "height_agl_m": height_agl.tolist(),
            "u_ms": u_ms.tolist(),
            "v_ms": v_ms.tolist(),
        },
        "diagnostics": diagnostics,
        "quality": {
            "levels": int(len(pressure)),
            "pressure_decreases_upward": bool(np.all(np.diff(pressure) < 0)),
            "height_increases_upward": bool(np.all(np.diff(height_agl) > 0)),
            "profile_warnings": diagnostics["quality"]["warnings"],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Gzip-compressed regional fields JSON")
    parser.add_argument("--latitude", type=float, default=44.4719)
    parser.add_argument("--longitude", type=float, default=-73.1533)
    parser.add_argument("--label", default="KBTV")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with gzip.open(args.input, "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    result = extract_profile(payload, args.latitude, args.longitude, args.label)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\\n", encoding="utf-8")
    print(json.dumps({
        "label": result["label"],
        "sampled_grid_point": result["sampled_grid_point"],
        "levels": result["quality"]["levels"],
        "quality": result["quality"],
        "diagnostics": result["diagnostics"]["diagnostics"],
    }, indent=2))
    if result["quality"]["levels"] < 20 or not result["quality"]["pressure_decreases_upward"]:
        raise RuntimeError("Extracted sounding failed vertical completeness checks")


if __name__ == "__main__":
    main()
