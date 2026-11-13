"""Optional SHARPpy diagnostics adapter for verified model soundings.

SHARPpy expects pressure (hPa), height (m), temperature/dewpoint (C), and
wind components (kt). The model profile contract in this project stores
temperature in K and wind components in m/s, so all conversions are explicit.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import numpy as np


def _finite(value):
    """Convert a SHARPpy scalar/masked scalar to JSON-safe float or None."""
    if value is None or np.ma.is_masked(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _profile_arrays(profile: dict) -> tuple[np.ndarray, ...]:
    required = (
        "pressure_hpa",
        "temperature_k",
        "dewpoint_k",
        "height_agl_m",
        "u_ms",
        "v_ms",
    )
    arrays = []
    for key in required:
        if key not in profile:
            raise ValueError(f"SHARPpy input profile is missing {key}")
        values = np.asarray(profile[key], dtype=float)
        if values.ndim != 1:
            raise ValueError(f"SHARPpy input {key} must be one-dimensional")
        arrays.append(values)

    lengths = {array.size for array in arrays}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) < 10:
        raise ValueError("SHARPpy requires at least 10 collocated profile levels")
    if not all(np.all(np.isfinite(array)) for array in arrays):
        raise ValueError("SHARPpy input profile contains non-finite values")

    pressure, temperature_k, dewpoint_k, height, u_ms, v_ms = arrays
    if np.any(pressure <= 0) or not np.all(np.diff(pressure) < 0):
        raise ValueError("Pressure must be positive and strictly decrease upward")
    if not np.all(np.diff(height) > 0):
        raise ValueError("Height AGL must strictly increase upward")
    if np.any((temperature_k < 150) | (temperature_k > 350)):
        raise ValueError("Temperature values are not plausible Kelvin values")
    if np.any((dewpoint_k < 130) | (dewpoint_k > 330)):
        raise ValueError("Dewpoint values are not plausible Kelvin values")

    return arrays


def calculate_sharppy_diagnostics(profile: dict) -> dict:
    """Calculate SHARPpy parcel, Bunkers, shear, and SRH diagnostics.

    Args:
        profile: Profile mapping with pressure_hpa, temperature_k,
            dewpoint_k, height_agl_m, u_ms, and v_ms arrays.

    Returns:
        A JSON-serializable dictionary with independent SHARPpy provenance.
    """
    pressure, temperature_k, dewpoint_k, height, u_ms, v_ms = _profile_arrays(profile)

    try:
        from sharppy.sharptab import interp, params, profile as sharp_profile, winds
    except ImportError as exc:
        raise ImportError(
            "SHARPpy is optional; install mesoscale/requirements-sharppy.txt "
            "to enable SHARPpy sounding diagnostics"
        ) from exc

    # SHARPpy's BasicProfile API requires Celsius and knots.
    sounding = sharp_profile.create_profile(
        profile="default",
        pres=pressure.copy(),
        hght=height.copy(),
        tmpc=temperature_k - 273.15,
        dwpc=dewpoint_k - 273.15,
        u=u_ms * 1.9438444924406,
        v=v_ms * 1.9438444924406,
        strictQC=False,
    )

    parcels = {}
    parcel_flags = {"surface": 1, "most_unstable": 3, "mixed_layer": 4}
    for name, flag in parcel_flags.items():
        try:
            parcel = params.parcelx(sounding, flag=flag)
            parcels[name] = {
                "cape_jkg": _finite(parcel.bplus),
                "cin_jkg": _finite(parcel.bminus),
                "lcl_height_agl_m": _finite(parcel.lclhght),
                "lfc_height_agl_m": _finite(parcel.lfchght),
                "equilibrium_level_agl_m": _finite(parcel.elhght),
                "parcel_pressure_hpa": _finite(parcel.pres),
                "parcel_temperature_c": _finite(parcel.tmpc),
                "parcel_dewpoint_c": _finite(parcel.dwpc),
            }
        except Exception as exc:
            parcels[name] = {
                "cape_jkg": None,
                "cin_jkg": None,
                "warning": f"{type(exc).__name__}: {exc}",
            }

    mu_parcel = None
    if parcels["most_unstable"].get("cape_jkg") is not None:
        try:
            mu_parcel = params.parcelx(sounding, flag=3)
        except Exception:
            mu_parcel = None

    bunkers = None
    srh_0_1km = None
    if mu_parcel is not None:
        try:
            motion = params.bunkers_storm_motion(sounding, mupcl=mu_parcel)
            if len(motion) >= 4:
                right_u, right_v, left_u, left_v = (_finite(x) for x in motion[:4])
                if right_u is not None and right_v is not None:
                    bunkers = {
                        "right_mover_u_kt": right_u,
                        "right_mover_v_kt": right_v,
                        "left_mover_u_kt": left_u,
                        "left_mover_v_kt": left_v,
                    }
                    srh = winds.helicity(
                        sounding, 0, 1000, stu=right_u, stv=right_v, exact=True
                    )
                    srh_0_1km = _finite(srh[0])
        except Exception:
            bunkers = None
            srh_0_1km = None

    shear_0_6km = None
    try:
        surface_pressure = _finite(sounding.pres[sounding.sfc])
        six_km_pressure = _finite(interp.pres(sounding, interp.to_msl(sounding, 6000)))
        if surface_pressure is not None and six_km_pressure is not None:
            du, dv = winds.wind_shear(
                sounding, pbot=surface_pressure, ptop=six_km_pressure
            )
            du, dv = _finite(du), _finite(dv)
            if du is not None and dv is not None:
                shear_0_6km = float(np.hypot(du, dv))
    except Exception:
        shear_0_6km = None

    try:
        library_version = version("SHARPpy")
    except PackageNotFoundError:
        library_version = None

    return {
        "library": "SHARPpy",
        "library_version": library_version,
        "units": {
            "cape": "J/kg",
            "cin": "J/kg",
            "height": "m AGL",
            "wind": "kt",
            "srh": "m2/s2",
        },
        "parcels": parcels,
        "kinematics": {
            "bunkers_motion": bunkers,
            "srh_0_1km_m2s2": srh_0_1km,
            "bulk_shear_0_6km_kt": shear_0_6km,
        },
        "quality": {
            "input_levels": int(pressure.size),
            "pressure_decreases_upward": True,
            "height_increases_upward": True,
            "warnings": [
                name for name, result in parcels.items()
                if result.get("cape_jkg") is None
            ],
        },
    }
