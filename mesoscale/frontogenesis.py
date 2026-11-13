"""Projection-aware Petterssen frontogenesis cross-section diagnostics.

Frontogenesis is derived from potential temperature and horizontal wind
gradients on a verified native projection grid. The routine refuses to guess
projection spacing or wind orientation when GRIB metadata are unavailable.
"""
from __future__ import annotations

import math
from typing import Mapping

import numpy as np
import metpy.calc as mpcalc
from metpy.units import units

from .cross_section import _pressure_hpa, _select_field, build_cross_section


def _grid_field_on_pressure(pressure_hpa: np.ndarray, values: np.ndarray,
                            target_hpa: float) -> np.ndarray:
    ny, nx = pressure_hpa.shape[1:]
    result = np.full((ny, nx), np.nan, dtype=float)
    log_target = math.log(float(target_hpa))
    for iy in range(ny):
        for ix in range(nx):
            p = pressure_hpa[:, iy, ix]
            v = values[:, iy, ix]
            valid = np.isfinite(p) & np.isfinite(v) & (p > 0)
            if valid.sum() < 2:
                continue
            p, v = p[valid], v[valid]
            order = np.argsort(p)
            p, v = p[order], v[order]
            if np.any(np.diff(p) <= 0):
                raise ValueError(f"Hybrid pressure is not unique at grid cell ({iy}, {ix})")
            if p[0] <= target_hpa <= p[-1]:
                result[iy, ix] = np.interp(log_target, np.log(p), v)
    return result


def build_frontogenesis_cross_section(
    payload: Mapping,
    start: tuple[float, float],
    end: tuple[float, float],
    pressure_levels_hpa: list[float],
    sample_count: int = 50,
) -> dict:
    """Calculate Petterssen 2-D frontogenesis at pressure levels along a transect.

    Required metadata:
      * Lambert grid type and native Dx/Dy in metres on the sampled grid.
      * U/V wind components explicitly marked grid-relative by GRIB metadata.
      * Collocated hybrid pressure, temperature, and U/V fields.

    Frontogenesis is returned in K per 100 km per 3 h. It is a derived
    diagnostic, not a directly supplied model field.
    """
    targets = np.asarray(pressure_levels_hpa, dtype=float)
    if targets.ndim != 1 or targets.size < 1 or not np.all(np.isfinite(targets)):
        raise ValueError("Pressure levels must be a finite one-dimensional array")
    if np.any(targets <= 0) or (targets.size > 1 and not np.all(np.diff(targets) < 0)):
        raise ValueError("Pressure levels must be positive and strictly descending")

    temperature_candidates = [
        field for field in payload.get("fields", {}).values()
        if field.get("short_name") == "t" and "hybrid" in field.get("dimensions", [])
    ]
    if len(temperature_candidates) != 1:
        raise ValueError(f"Expected one hybrid temperature field; found {len(temperature_candidates)}")
    reference = temperature_candidates[0]
    grid_id = reference.get("grid_id")
    if grid_id not in payload.get("grids", {}):
        raise ValueError("Hybrid temperature field has no valid grid reference")

    grid = payload["grids"][grid_id]
    projection = grid.get("projection") or {}
    grid_type = str(projection.get("GRIB_gridType", "")).lower()
    if "lambert" not in grid_type:
        raise ValueError(f"Unsupported or missing native projection: {grid_type or 'unknown'}")
    try:
        dx = float(projection["GRIB_DxInMetres"]) * float(grid.get("stride", 1))
        dy = float(projection["GRIB_DyInMetres"]) * float(grid.get("stride", 1))
    except (KeyError, TypeError, ValueError):
        raise ValueError("Lambert grid spacing metadata (DxInMetres/DyInMetres) is required")
    if not (math.isfinite(dx) and math.isfinite(dy) and dx > 0 and dy > 0):
        raise ValueError("Lambert grid spacing must be finite and positive")

    pressure_field = _select_field(payload, "pres", grid_id)
    u_field = _select_field(payload, "u", grid_id)
    v_field = _select_field(payload, "v", grid_id)
    for name, field in (("pressure", pressure_field), ("u", u_field), ("v", v_field)):
        if field.get("dimensions") != reference.get("dimensions") or field.get("levels") != reference.get("levels"):
            raise ValueError(f"{name} field does not share temperature's hybrid coordinates")
    if reference.get("units") != "K":
        raise ValueError(f"Unexpected temperature units: {reference.get('units')!r}")
    if u_field.get("units") != "m s**-1" or v_field.get("units") != "m s**-1":
        raise ValueError("Frontogenesis requires U/V wind in m s**-1")

    u_relative = (u_field.get("grib_metadata") or {}).get("GRIB_uvRelativeToGrid")
    v_relative = (v_field.get("grib_metadata") or {}).get("GRIB_uvRelativeToGrid")
    if u_relative not in (1, True, "1") or v_relative not in (1, True, "1"):
        raise ValueError("U/V must be explicitly identified as grid-relative; wind rotation is not guessed")

    p = _pressure_hpa(pressure_field)
    t = np.asarray(reference.get("data"), dtype=float)
    u = np.asarray(u_field.get("data"), dtype=float)
    v = np.asarray(v_field.get("data"), dtype=float)
    expected = (len(next(iter(reference.get("levels", {}).values()))), *tuple(grid["shape"]))
    if any(array.shape != expected for array in (p, t, u, v)):
        raise ValueError("Pressure, temperature, and wind arrays do not share the expected 3-D grid shape")

    # Reuse the validated transect sampler for native-cell de-duplication,
    # pressure interpolation metadata, and the exact native grid indices.
    section = build_cross_section(
        payload, start, end, {"temperature": "t"}, targets.tolist(), sample_count
    )
    transect_points = section["transect"]["points"]
    scale_to_common_unit = 1.08e9  # K m-1 s-1 -> K (100 km)-1 (3 h)-1
    output = [[] for _ in targets]

    for level_index, pressure_level in enumerate(targets):
        temp_grid = _grid_field_on_pressure(p, t, float(pressure_level))
        u_grid = _grid_field_on_pressure(p, u, float(pressure_level))
        v_grid = _grid_field_on_pressure(p, v, float(pressure_level))
        valid = np.isfinite(temp_grid) & np.isfinite(u_grid) & np.isfinite(v_grid)
        if valid.sum() < 9:
            raise ValueError(
                f"Insufficient collocated T/U/V coverage at {pressure_level:g} hPa"
            )
        theta = mpcalc.potential_temperature(
            pressure_level * units.hPa, temp_grid * units.kelvin
        )
        frontogenesis = mpcalc.frontogenesis(
            theta,
            u_grid * units("m/s"),
            v_grid * units("m/s"),
            dx=dx * units.meter,
            dy=dy * units.meter,
        ).to("kelvin / meter / second").magnitude
        frontogenesis = np.asarray(frontogenesis, dtype=float) * scale_to_common_unit
        for point in transect_points:
            value = frontogenesis[int(point["grid_y"]), int(point["grid_x"])]
            output[level_index].append(float(value) if np.isfinite(value) else None)

    values = [
        [output[level_index][point_index] for level_index in range(len(targets))]
        for point_index in range(len(transect_points))
    ]
    return {
        "model": payload.get("model"),
        "model_cycle_utc": payload.get("model_cycle_utc"),
        "forecast_hour": payload.get("forecast_hour"),
        "valid_time_utc": payload.get("valid_time_utc"),
        "source_file": payload.get("source_file"),
        "grid_id": grid_id,
        "transect": section["transect"],
        "vertical_coordinate": section["vertical_coordinate"],
        "fields": {
            "frontogenesis": {
                "short_name": "derived_petterssen_frontogenesis",
                "units": "K (100 km)-1 (3 h)-1",
                "long_name": "2-D kinematic Petterssen frontogenesis",
                "values": values,
            }
        },
        "provenance": {
            "formula": "F = 0.5 * |grad(theta)| * (D*cos(2*beta) - divergence)",
            "theta": "potential temperature derived from model temperature and pressure",
            "wind_components": "GRIB U/V explicitly marked grid-relative",
            "grid_type": grid_type,
            "grid_spacing_m": {"dx": dx, "dy": dy},
            "conversion_factor": scale_to_common_unit,
        },
        "quality": {
            "status": "passed",
            "sample_count": len(transect_points),
            "pressure_levels_hpa": targets.tolist(),
            "extrapolation": "disabled",
            "note": "Diagnostic is calculated on the native projected grid before transect sampling.",
        },
    }
