"""Native-grid RAP vertical cross-section sampling utilities.

This module samples already-decoded, collocated 3-D fields along a great-circle
transect and interpolates each column to a common pressure coordinate. It does
not infer field identity: callers must supply the exact GRIB short names from
the source-file inventory (for example, an omega field only after verifying
its GRIB metadata and units).
"""
from __future__ import annotations

import math
from typing import Mapping

import numpy as np


EARTH_RADIUS_KM = 6371.0088


def _unit_vector(lat: float, lon: float) -> np.ndarray:
    lat_r, lon_r = math.radians(lat), math.radians(lon)
    return np.array([
        math.cos(lat_r) * math.cos(lon_r),
        math.cos(lat_r) * math.sin(lon_r),
        math.sin(lat_r),
    ])


def _latlon(vector: np.ndarray) -> tuple[float, float]:
    v = vector / np.linalg.norm(vector)
    return math.degrees(math.asin(float(v[2]))), math.degrees(math.atan2(float(v[1]), float(v[0])))


def great_circle_points(start: tuple[float, float], end: tuple[float, float],
                        count: int) -> tuple[list[tuple[float, float]], np.ndarray]:
    """Return evenly spaced great-circle points and cumulative distance in km."""
    if count < 2:
        raise ValueError("A transect requires at least two sample points")
    if any(not math.isfinite(float(v)) for v in (*start, *end)):
        raise ValueError("Transect endpoints must be finite")
    if not (-90 <= start[0] <= 90 and -90 <= end[0] <= 90):
        raise ValueError("Transect latitudes must be between -90 and 90")
    a, b = _unit_vector(*start), _unit_vector(*end)
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    angle = math.acos(dot)
    if angle < 1e-10:
        vectors = [a.copy() for _ in range(count)]
    elif abs(math.pi - angle) < 1e-8:
        raise ValueError("Antipodal transect endpoints do not define a unique great circle")
    else:
        vectors = [
            (math.sin((1 - f) * angle) * a + math.sin(f * angle) * b) / math.sin(angle)
            for f in np.linspace(0.0, 1.0, count)
        ]
    points = [_latlon(v) for v in vectors]
    total_km = angle * EARTH_RADIUS_KM
    distances = np.linspace(0.0, total_km, count)
    return points, distances


def _nearest_grid_indices(grid: Mapping, points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    lat = np.asarray(grid["latitude"], dtype=float)
    lon = np.asarray(grid["longitude"], dtype=float)
    if lat.ndim != 2 or lon.shape != lat.shape:
        raise ValueError("Grid latitude and longitude must be matching 2-D arrays")
    valid = np.isfinite(lat) & np.isfinite(lon)
    if not valid.any():
        raise ValueError("Grid has no finite geographic coordinates")
    lat_r = np.deg2rad(lat)
    lon_r = np.deg2rad(lon)
    result = []
    for point_lat, point_lon in points:
        p_lat, p_lon = math.radians(point_lat), math.radians(point_lon)
        dlat = lat_r - p_lat
        dlon = (lon_r - p_lon + np.pi) % (2 * np.pi) - np.pi
        a = np.sin(dlat / 2) ** 2 + math.cos(p_lat) * np.cos(lat_r) * np.sin(dlon / 2) ** 2
        distance = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        distance[~valid] = np.inf
        iy, ix = np.unravel_index(int(np.argmin(distance)), distance.shape)
        result.append((int(iy), int(ix)))
    return result


def _select_field(payload: Mapping, short_name: str, grid_id: str) -> Mapping:
    matches = [
        field for field in payload.get("fields", {}).values()
        if field.get("short_name") == short_name
        and field.get("grid_id") == grid_id
        and "hybrid" in field.get("dimensions", [])
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one hybrid {short_name!r} field on {grid_id}; found {len(matches)}"
        )
    return matches[0]


def _pressure_hpa(field: Mapping) -> np.ndarray:
    values = np.asarray(field.get("data"), dtype=float)
    units = str(field.get("units", "")).strip().lower().replace(" ", "")
    if units in {"pa", "pascal", "pascals"}:
        values = values / 100.0
    elif units not in {"hpa", "mb", "millibar", "millibars"}:
        raise ValueError(f"Unsupported hybrid pressure units: {field.get('units')!r}")
    return values


def _interpolate_log_pressure(pressure_hpa: np.ndarray, values: np.ndarray,
                              target_hpa: np.ndarray) -> list[float | None]:
    valid = np.isfinite(pressure_hpa) & np.isfinite(values) & (pressure_hpa > 0)
    if valid.sum() < 2:
        return [None] * int(target_hpa.size)
    p, v = pressure_hpa[valid], values[valid]
    order = np.argsort(p)
    p, v = p[order], v[order]
    if np.any(np.diff(p) <= 0):
        raise ValueError("Native hybrid pressure must be unique within each column")
    result: list[float | None] = []
    for target in target_hpa:
        if target < p[0] or target > p[-1]:
            result.append(None)
        else:
            result.append(float(np.interp(math.log(target), np.log(p), v)))
    return result


def build_cross_section(payload: Mapping, start: tuple[float, float],
                        end: tuple[float, float], fields: Mapping[str, str],
                        pressure_levels_hpa: list[float] | None = None,
                        sample_count: int = 50) -> dict:
    """Build a pressure-coordinate cross-section from named hybrid fields.

    Args:
        payload: One decoded regional grid payload from process_grib.py.
        start/end: (latitude, longitude) endpoints.
        fields: Output-name -> exact GRIB shortName mapping. Must not be guessed.
        pressure_levels_hpa: Optional strictly descending common pressure levels.
        sample_count: Number of nearest-native-grid samples along the transect.

    The result retains native grid indices and source metadata. Interpolation
    onto pressure levels is a display coordinate transformation, not a claim
    of finer vertical or horizontal model resolution.
    """
    if not fields:
        raise ValueError("At least one explicitly selected field is required")
    targets = np.asarray(
        pressure_levels_hpa if pressure_levels_hpa is not None
        else np.arange(1000.0, 74.0, -25.0),
        dtype=float,
    )
    if targets.ndim != 1 or targets.size < 2 or not np.all(np.isfinite(targets)):
        raise ValueError("Pressure levels must be a finite one-dimensional array")
    if np.any(targets <= 0) or not np.all(np.diff(targets) < 0):
        raise ValueError("Pressure levels must be positive and strictly descending")

    reference = next(
        (field for field in payload.get("fields", {}).values()
         if field.get("short_name") == "t" and "hybrid" in field.get("dimensions", [])),
        None,
    )
    if reference is None:
        raise ValueError("No hybrid temperature field found to establish the RAP grid")
    grid_id = reference.get("grid_id")
    if not grid_id or grid_id not in payload.get("grids", {}):
        raise ValueError("Hybrid temperature field has no valid grid reference")
    reference_levels = reference.get("levels", {})
    reference_dims = reference.get("dimensions", [])
    grid = payload["grids"][grid_id]
    grid_shape = tuple(grid.get("shape", ()))
    if len(grid_shape) != 2:
        raise ValueError("Reference grid must declare a two-dimensional shape")

    pressure_field = _select_field(payload, "pres", grid_id)
    if pressure_field.get("dimensions") != reference_dims or pressure_field.get("levels") != reference_levels:
        raise ValueError("Pressure and temperature do not share identical hybrid coordinates")
    pressure_data = _pressure_hpa(pressure_field)
    expected_shape = (len(next(iter(reference_levels.values()))), *grid_shape)
    if pressure_data.shape != expected_shape:
        raise ValueError(f"Pressure array shape {pressure_data.shape} does not match {expected_shape}")

    selected = {}
    for output_name, short_name in fields.items():
        field = _select_field(payload, short_name, grid_id)
        if field.get("dimensions") != reference_dims or field.get("levels") != reference_levels:
            raise ValueError(f"Field {short_name!r} does not share reference hybrid coordinates")
        values = np.asarray(field.get("data"), dtype=float)
        if values.shape != expected_shape:
            raise ValueError(f"Field {short_name!r} shape {values.shape} does not match {expected_shape}")
        selected[output_name] = field, values

    points, distances = great_circle_points(start, end, sample_count)
    indices = _nearest_grid_indices(grid, points)
    sampled = {name: [] for name in selected}
    for iy, ix in indices:
        column_pressure = pressure_data[:, iy, ix]
        for name, (_, data) in selected.items():
            sampled[name].append(
                _interpolate_log_pressure(column_pressure, data[:, iy, ix], targets)
            )

    return {
        "model": payload.get("model"),
        "model_cycle_utc": payload.get("model_cycle_utc"),
        "forecast_hour": payload.get("forecast_hour"),
        "valid_time_utc": payload.get("valid_time_utc"),
        "source_file": payload.get("source_file"),
        "grid_id": grid_id,
        "sampling_method": "nearest_native_grid_point",
        "native_grid_shape": list(grid_shape),
        "native_grid_stride": grid.get("stride", 1),
        "transect": {
            "start": {"latitude": float(start[0]), "longitude": float(start[1])},
            "end": {"latitude": float(end[0]), "longitude": float(end[1])},
            "points": [
                {"latitude": point[0], "longitude": point[1],
                 "distance_km": float(distance), "grid_y": index[0], "grid_x": index[1]}
                for point, distance, index in zip(points, distances, indices)
            ],
            "total_distance_km": float(distances[-1]),
        },
        "vertical_coordinate": {"type": "pressure", "levels_hpa": targets.tolist()},
        "fields": {
            name: {
                "short_name": field["short_name"],
                "units": field.get("units"),
                "long_name": field.get("long_name"),
                "values": values,
            }
            for name, (field, values) in sampled.items()
        },
        "quality": {
            "status": "passed",
            "sample_count": len(points),
            "native_grid_sampling": True,
            "vertical_interpolation": "linear in log-pressure",
            "extrapolation": "disabled; out-of-column values are null",
            "note": "Interpolation does not increase native model resolution.",
        },
    }
