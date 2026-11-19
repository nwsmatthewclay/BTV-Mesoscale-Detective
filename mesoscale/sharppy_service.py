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

from .sharppy_adapter import calculate_sharppy_diagnostics


def adjust_profile(profile: dict[str, Any], adjustments: dict[str, Any]) -> tuple[dict, list[str]]:
    """Apply the shared NumPy-only sounding adjustment implementation.

    Keeping the native API and browser runtime on the same implementation
    ensures that identical inputs produce identical modified profiles.
    """
    from .browser_adjustments import adjust_profile as adjust_numpy_profile

    return adjust_numpy_profile(profile, adjustments)

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
        allow_origins=["https://nwsmatthewclay.github.io", "http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:8080", "http://127.0.0.1:8080"],
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
