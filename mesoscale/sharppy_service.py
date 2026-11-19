"""SHARPpy-backed sounding adjustment API for the Forecast Sounding Workbench.

Run with:
  conda env create -f mesoscale/environment-sharppy.yml
  conda activate btv-sharppy
  pip install fastapi uvicorn
  uvicorn mesoscale.sharppy_service:app --host 0.0.0.0 --port 8000

The service accepts a verified model profile, applies explicit environmental
adjustments, and recalculates the modified profile with SHARPpy. It never
changes or overwrites the source profile.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import metpy.calc as mpcalc
from metpy.units import units

from .sharppy_adapter import calculate_sharppy_diagnostics


def _profile_arrays(profile: dict[str, Any]) -> dict[str, np.ndarray]:
    keys = ("pressure_hpa", "temperature_k", "dewpoint_k", "height_agl_m", "u_ms", "v_ms")
    arrays = {key: np.asarray(profile[key], dtype=float).copy() for key in keys}
    lengths = {a.size for a in arrays.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) < 10:
        raise ValueError("Profile arrays must be collocated and contain at least 10 levels")
    if any(a.ndim != 1 or not np.all(np.isfinite(a)) for a in arrays.values()):
        raise ValueError("Profile arrays must be finite one-dimensional arrays")
    p, z = arrays["pressure_hpa"], arrays["height_agl_m"]
    if np.any(p <= 0) or not np.all(np.diff(p) < 0):
        raise ValueError("Pressure must strictly decrease upward")
    if not np.all(np.diff(z) > 0):
        raise ValueError("Height must strictly increase upward")
    if np.any((arrays["temperature_k"] < 150) | (arrays["temperature_k"] > 350)):
        raise ValueError("Temperature is outside plausible Kelvin bounds")
    if np.any((arrays["dewpoint_k"] < 130) | (arrays["dewpoint_k"] > 330)):
        raise ValueError("Dewpoint is outside plausible Kelvin bounds")
    return arrays


def adjust_profile(profile: dict[str, Any], adjustments: dict[str, Any]) -> tuple[dict, list[str]]:
    """Apply low-level offsets and a pressure-mass-weighted mixed layer.

    Mixing uses layer-mean potential temperature, water-vapor mixing ratio,
    and horizontal momentum. The top of the layer is the selected AGL depth;
    only native levels within that depth are modified. This is an idealized
    parcel-mixing experiment, not a boundary-layer scheme or model forecast.
    """
    arrays = _profile_arrays(profile)
    warnings: list[str] = []
    temp_offset = float(adjustments.get("temperature_offset_c", 0.0))
    dew_offset = float(adjustments.get("dewpoint_offset_c", 0.0))
    depth = float(adjustments.get("mixing_depth_m", 0.0))
    offset_depth = float(adjustments.get("low_level_depth_m", 1000.0))
    if not -15 <= temp_offset <= 15 or not -15 <= dew_offset <= 15:
        raise ValueError("Temperature and dewpoint offsets must be between -15 and +15 °C")
    if not 0 <= depth <= 5000:
        raise ValueError("Mixing depth must be between 0 and 5000 m AGL")
    if not 0 <= offset_depth <= 5000:
        raise ValueError("Low-level adjustment depth must be between 0 and 5000 m AGL")

    t = arrays["temperature_k"]
    td = arrays["dewpoint_k"]
    z = arrays["height_agl_m"]
    p = arrays["pressure_hpa"]
    offset_layer = z <= offset_depth if offset_depth > 0 else np.zeros(z.shape, dtype=bool)
    layer = z <= depth if depth > 0 else np.zeros(z.shape, dtype=bool)
    if temp_offset:
        t[offset_layer] += temp_offset
    if dew_offset:
        td[offset_layer] += dew_offset
    supersaturated = td > t
    if np.any(supersaturated):
        warnings.append(f"Dewpoint capped at temperature at {int(np.count_nonzero(supersaturated))} levels to prevent supersaturation.")
    td[:] = np.minimum(td, t)

    if depth > 0 and int(layer.sum()) >= 2:
        idx = np.flatnonzero(layer)
        # Pressure thickness approximates layer mass weighting in a hydrostatic column.
        p_layer = p[idx]
        weights = np.empty(idx.size, dtype=float)
        if idx.size == 1:
            weights[:] = 1.0
        else:
            edges = np.empty(idx.size + 1, dtype=float)
            edges[1:-1] = 0.5 * (p_layer[:-1] + p_layer[1:])
            edges[0] = p_layer[0] + 0.5 * (p_layer[0] - p_layer[1])
            edges[-1] = max(0.0, p_layer[-1] - 0.5 * (p_layer[-2] - p_layer[-1]))
            weights = np.maximum(0.0, edges[:-1] - edges[1:])
        weights /= weights.sum()

        theta = t[idx] * (1000.0 / p_layer) ** 0.2854
        mean_theta = float(np.sum(theta * weights))
        mixing_ratio = mpcalc.mixing_ratio_from_dewpoint(
            p_layer * units.hPa, td[idx] * units.kelvin
        ).to("dimensionless").magnitude
        mean_ratio = float(np.sum(np.asarray(mixing_ratio) * weights))
        mean_u = float(np.sum(arrays["u_ms"][idx] * weights))
        mean_v = float(np.sum(arrays["v_ms"][idx] * weights))

        t[idx] = mean_theta * (p_layer / 1000.0) ** 0.2854
        specific_humidity = mpcalc.specific_humidity_from_mixing_ratio(
            mean_ratio * units.dimensionless
        )
        td_mixed = mpcalc.dewpoint_from_specific_humidity(
            p_layer * units.hPa,
            t[idx] * units.kelvin,
            specific_humidity,
        ).to("kelvin").magnitude
        td[idx] = np.minimum(np.asarray(td_mixed, dtype=float), t[idx])
        arrays["u_ms"][idx] = mean_u
        arrays["v_ms"][idx] = mean_v
    elif depth > 0:
        warnings.append("Selected mixing depth contains fewer than two native model levels; no mixing applied.")

    if np.any((t < 150) | (t > 350)) or np.any((td < 130) | (td > 330)):
        raise ValueError("Adjusted temperature/dewpoint profile is outside plausible Kelvin bounds")
    if np.any(td > t):
        raise ValueError("Adjusted dewpoint exceeds temperature after mixing")
    adjusted = {key: value.tolist() for key, value in arrays.items()}
    # Preserve profile metadata and optional BUFKIT vertical velocity for the
    # ConvectiveProfile diagnostic suite; the source object itself is untouched.
    for key in ("location", "latitude", "date", "valid_time_utc", "omega_pa_s"):
        if key in profile:
            adjusted[key] = profile[key]
    return adjusted, warnings


def diagnose_adjusted_profile(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("profile")
    if not isinstance(source, dict):
        raise ValueError("Request must include a profile object")
    adjustments = payload.get("adjustments") or {}
    adjusted, warnings = adjust_profile(source, adjustments)
    diagnostics = calculate_sharppy_diagnostics(adjusted)
    return {
        "engine": "SHARPpy",
        "diagnostics": diagnostics,
        "adjusted_profile": adjusted,
        "adjustments": {
            "temperature_offset_c": float(adjustments.get("temperature_offset_c", 0.0)),
            "dewpoint_offset_c": float(adjustments.get("dewpoint_offset_c", 0.0)),
            "mixing_depth_m": float(adjustments.get("mixing_depth_m", 0.0)),
            "low_level_depth_m": float(adjustments.get("low_level_depth_m", 1000.0)),
        },
        "quality": {
            "status": "passed",
            "warnings": warnings + diagnostics["quality"]["warnings"],
            "source_profile_unchanged": True,
            "mixing_method": "pressure-mass-weighted potential temperature, mixing ratio, and horizontal momentum",
        },
    }


try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import requests

    class DiagnoseRequest(BaseModel):
        profile: dict
        adjustments: dict = {}

    app = FastAPI(title="BTV SHARPpy Sounding API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://nwsmatthewclay.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        from importlib.metadata import version
        return {"status": "ok", "engine": "SHARPpy", "version": version("SHARPpy")}

    @app.get("/bufkit/models")
    def bufkit_models():
        from .bufkit_feed import MODEL_PRODUCTS
        return {"provider": "Penn State BUFKIT", "models": sorted(MODEL_PRODUCTS)}

    @app.get("/bufkit/{model}/{station}")
    def bufkit_profile_feed(model: str, station: str):
        from .bufkit_feed import fetch_and_parse_bufkit
        try:
            return fetch_and_parse_bufkit(model, station)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"BUFKIT provider request failed: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"BUFKIT decode failed: {type(exc).__name__}: {exc}") from exc

    @app.post("/diagnose")
    def diagnose(request: DiagnoseRequest):
        try:
            return diagnose_adjusted_profile(request.model_dump())
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"SHARPpy calculation failed: {type(exc).__name__}: {exc}") from exc

except ImportError:
    app = None
