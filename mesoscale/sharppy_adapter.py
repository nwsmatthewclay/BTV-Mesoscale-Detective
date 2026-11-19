"""Full SHARPpy ConvectiveProfile adapter for forecast soundings.

Input contract: pressure (hPa), height (m AGL), temperature/dewpoint (K),
and horizontal wind components (m/s). All conversions into SHARPpy's native
hPa/m/C/kt units are explicit. ConvectiveProfile runs the same broad NSHARP
diagnostic families used by SHARPpy's operational-style GUI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

import numpy as np


def _finite(value):
    if value is None or np.ma.is_masked(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _json_safe(value):
    """Recursively convert SHARPpy scalars, masked arrays, and tuples to JSON."""
    if value is None:
        return None
    if isinstance(value, np.ma.MaskedArray):
        data = np.asarray(value.data)
        mask = np.ma.getmaskarray(value)
        if data.ndim == 0:
            return None if bool(mask) else _json_safe(data.item())
        return [_json_safe(None if mask[i] else data[i]) for i in range(data.shape[0])]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if np.ma.is_masked(value):
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    number = _finite(value)
    if number is not None:
        return number
    return str(value)


def _get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _profile_arrays(profile: dict) -> tuple[np.ndarray, ...]:
    required = (
        "pressure_hpa", "temperature_k", "dewpoint_k",
        "height_agl_m", "u_ms", "v_ms",
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
    if len(lengths) != 1 or not lengths or next(iter(lengths)) < 10 or next(iter(lengths)) > 500:
        raise ValueError("SHARPpy requires 10–500 collocated profile levels")
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
    if np.any(dewpoint_k > temperature_k):
        raise ValueError("Dewpoint cannot exceed temperature")
    return arrays


def _parcel_summary(parcel) -> dict:
    return {
        "cape_jkg": _finite(_get(parcel, "bplus")),
        "cin_jkg": _finite(_get(parcel, "bminus")),
        "lcl_pressure_hpa": _finite(_get(parcel, "lclpres")),
        "lcl_height_agl_m": _finite(_get(parcel, "lclhght")),
        "lfc_pressure_hpa": _finite(_get(parcel, "lfcpres")),
        "lfc_height_agl_m": _finite(_get(parcel, "lfchght")),
        "equilibrium_level_pressure_hpa": _finite(_get(parcel, "elpres")),
        "equilibrium_level_agl_m": _finite(_get(parcel, "elhght")),
        "maximum_parcel_level_pressure_hpa": _finite(_get(parcel, "mplpres")),
        "maximum_parcel_level_agl_m": _finite(_get(parcel, "mplhght")),
        "parcel_start_pressure_hpa": _finite(_get(parcel, "pres")),
        "parcel_start_temperature_c": _finite(_get(parcel, "tmpc")),
        "parcel_start_dewpoint_c": _finite(_get(parcel, "dwpc")),
    }


def _magnitude(vector):
    if vector is None:
        return None
    try:
        values = np.asarray(vector, dtype=float).reshape(-1)
        if values.size < 2 or not np.all(np.isfinite(values[:2])):
            return None
        return float(np.hypot(values[0], values[1]))
    except Exception:
        return None


def _pair(value):
    if value is None or np.ma.is_masked(value):
        return None
    try:
        values = list(value)
        return [_finite(values[0]), _finite(values[1])] if len(values) >= 2 else None
    except Exception:
        return None


def _at(value, index):
    if value is None:
        return None
    try:
        return _finite(value[index])
    except Exception:
        return None


def calculate_sharppy_diagnostics(profile: dict) -> dict:
    """Run the full SHARPpy ConvectiveProfile diagnostic suite."""
    pressure, temperature_k, dewpoint_k, height, u_ms, v_ms = _profile_arrays(profile)

    try:
        from sharppy.sharptab import profile as sharp_profile
    except ImportError as exc:
        raise ImportError(
            "SHARPpy is required; use mesoscale/environment-sharppy.yml "
            "or mesoscale/environment-sharppy-api.yml"
        ) from exc

    station_id = str(profile.get("location") or "KBTV").upper()
    # SHARPpy's PWV climatology database uses 3-character U.S. station IDs;
    # retain the original ICAO ID separately in the returned metadata.
    location = station_id[1:] if station_id.startswith("K") and len(station_id) == 4 else station_id
    latitude = float(profile.get("latitude", 44.47))
    date_text = profile.get("date") or profile.get("valid_time_utc")
    if isinstance(date_text, datetime):
        valid_date = date_text
    elif date_text:
        valid_date = datetime.fromisoformat(str(date_text).replace("Z", "+00:00"))
    else:
        valid_date = datetime.now(timezone.utc)
    if valid_date.tzinfo is None:
        valid_date = valid_date.replace(tzinfo=timezone.utc)

    kwargs = {
        "profile": "convective",
        "pres": pressure.copy(),
        "hght": height.copy(),
        "tmpc": temperature_k - 273.15,
        "dwpc": dewpoint_k - 273.15,
        "u": u_ms * 1.9438444924406,
        "v": v_ms * 1.9438444924406,
        "strictQC": False,
        "location": location,
        "station_id": station_id,
        "latitude": latitude,
        "date": valid_date,
    }
    omega_values = profile.get("omega_pa_s")
    if omega_values is not None:
        omega = np.asarray(
            [np.nan if value is None else float(value) for value in omega_values],
            dtype=float,
        )
        if omega.size == pressure.size and np.any(np.isfinite(omega)):
            kwargs["omeg"] = np.ma.masked_invalid(omega)

    # ConvectiveProfile invokes SHARPpy's parcels, thermo, kinematics, severe,
    # precip/winter, fire, SARS, PWV-climo, trajectory, and watch routines.
    sounding = sharp_profile.create_profile(**kwargs)

    parcel_objects = {
        "surface": _get(sounding, "sfcpcl"),
        "most_unstable": _get(sounding, "mupcl"),
        "mixed_layer": _get(sounding, "mlpcl"),
        "forecast_surface": _get(sounding, "fcstpcl"),
        "effective": _get(sounding, "effpcl"),
    }
    parcels = {
        name: _parcel_summary(parcel) if parcel is not None else {}
        for name, parcel in parcel_objects.items()
    }

    shear_1km = _get(sounding, "sfc_1km_shear")
    shear_3km = _get(sounding, "sfc_3km_shear")
    shear_6km = _get(sounding, "sfc_6km_shear")
    shear_8km = _get(sounding, "sfc_8km_shear")
    shear_9km = _get(sounding, "sfc_9km_shear")
    bunkers = _get(sounding, "bunkers")
    right_esrh = _get(sounding, "right_esrh")
    left_esrh = _get(sounding, "left_esrh")
    srh_1km = _get(sounding, "srh1km")
    srh_3km = _get(sounding, "srh3km")

    kinematics = {
        "bunkers_motion_kt": _json_safe(bunkers),
        "right_mover_u_kt": _at(bunkers, 0),
        "right_mover_v_kt": _at(bunkers, 1),
        "left_mover_u_kt": _at(bunkers, 2),
        "left_mover_v_kt": _at(bunkers, 3),
        "bulk_shear_0_1km_kt": _magnitude(shear_1km),
        "bulk_shear_0_3km_kt": _magnitude(shear_3km),
        "bulk_shear_0_6km_kt": _magnitude(shear_6km),
        "bulk_shear_0_8km_kt": _magnitude(shear_8km),
        "bulk_shear_0_9km_kt": _magnitude(shear_9km),
        "effective_bulk_shear_kt": _finite(_get(sounding, "ebwspd")),
        "srh_0_1km_m2s2": _at(srh_1km, 0),
        "srh_0_3km_m2s2": _at(srh_3km, 0),
        "effective_srh_right_m2s2": _at(right_esrh, 0),
        "effective_srh_left_m2s2": _at(left_esrh, 0),
        "effective_layer_bottom_hpa": _finite(_get(sounding, "ebottom")),
        "effective_layer_top_hpa": _finite(_get(sounding, "etop")),
        "effective_layer_bottom_agl_m": _finite(_get(sounding, "ebotm")),
        "effective_layer_top_agl_m": _finite(_get(sounding, "etopm")),
        "surface_1km_shear_vector_kt": _pair(shear_1km),
        "surface_3km_shear_vector_kt": _pair(shear_3km),
        "surface_6km_shear_vector_kt": _pair(shear_6km),
        "mean_wind_0_1km": _json_safe(_get(sounding, "mean_1km")),
        "mean_wind_0_3km": _json_safe(_get(sounding, "mean_3km")),
        "mean_wind_0_6km": _json_safe(_get(sounding, "mean_6km")),
        "mean_wind_0_8km": _json_safe(_get(sounding, "mean_8km")),
        "mean_wind_effective_layer": _json_safe(_get(sounding, "mean_eff")),
    }

    thermodynamics = {
        "precipitable_water_in": _finite(_get(sounding, "pwat")),
        "k_index": _finite(_get(sounding, "k_idx")),
        "totals_totals": _finite(_get(sounding, "totals_totals")),
        "lapse_rate_0_3km_c_km": _finite(_get(sounding, "lapserate_3km")),
        "lapse_rate_3_6km_c_km": _finite(_get(sounding, "lapserate_3_6km")),
        "lapse_rate_850_500_c_km": _finite(_get(sounding, "lapserate_850_500")),
        "lapse_rate_700_500_c_km": _finite(_get(sounding, "lapserate_700_500")),
        "maximum_lapse_rate_2_6km_c_km": _finite(_get(sounding, "max_lapse_rate_2_6")),
        "convective_temperature_f": _finite(_get(sounding, "convT")),
        "maximum_temperature_f": _finite(_get(sounding, "maxT")),
        "mean_mixing_ratio_gkg": _finite(_get(sounding, "mean_mixr")),
        "low_level_mean_rh_pct": _finite(_get(sounding, "low_rh")),
        "mid_level_mean_rh_pct": _finite(_get(sounding, "mid_rh")),
        "inferred_temperature_advection": _finite(_get(sounding, "inf_temp_adv")),
        "boundary_layer_height_agl_m": _finite(_get(sounding, "pbl_h")),
        "surface_relative_humidity_pct": _finite(_get(sounding, "sfc_rh")),
        "mean_rh_0_1km_pct": _finite(_get(sounding, "rh01km")),
        "mean_rh_boundary_layer_pct": _finite(_get(sounding, "pblrh")),
        "mean_wind_0_1km_components_kt": _json_safe(_get(sounding, "meanwind01km")),
        "mean_wind_boundary_layer_components_kt": _json_safe(_get(sounding, "meanwindpbl")),
        "maximum_boundary_layer_wind_components_kt": _json_safe(_get(sounding, "pblmaxwind")),
    }

    winter = {
        "precipitation_type": _json_safe(_get(sounding, "precip_type")),
        "initial_phase": _json_safe(_get(sounding, "phase")),
        "initial_phase_pressure_hpa": _finite(_get(sounding, "plevel")),
        "initial_phase_temperature_c": _finite(_get(sounding, "tmp")),
        "initial_phase_state": _json_safe(_get(sounding, "st")),
        "dendritic_growth_zone_bottom_hpa": _finite(_get(sounding, "dgz_pbot")),
        "dendritic_growth_zone_top_hpa": _finite(_get(sounding, "dgz_ptop")),
        "dendritic_growth_zone_mean_rh_pct": _finite(_get(sounding, "dgz_meanrh")),
        "dendritic_growth_zone_precipitable_water_in": _finite(_get(sounding, "dgz_pw")),
        "dendritic_growth_zone_mean_mixing_ratio": _finite(_get(sounding, "dgz_meanq")),
        "dendritic_growth_zone_mean_omega_microbar_s": _finite(_get(sounding, "dgz_meanomeg")),
        "overlap_precip_rh_omega": _finite(_get(sounding, "ophr")),
        "positive_temperature_layers": _json_safe(_get(sounding, "tpos")),
        "negative_temperature_layers": _json_safe(_get(sounding, "tneg")),
        "positive_wetbulb_layers": _json_safe(_get(sounding, "wpos")),
        "negative_wetbulb_layers": _json_safe(_get(sounding, "wneg")),
        "temperature_layer_top_bottom_hpa": [_finite(_get(sounding, "ttop")), _finite(_get(sounding, "tbot"))],
        "wetbulb_layer_top_bottom_hpa": [_finite(_get(sounding, "wtop")), _finite(_get(sounding, "wbot"))],
    }

    severe = {
        "supercell_composite_right": _finite(_get(sounding, "right_scp")),
        "supercell_composite_left": _finite(_get(sounding, "left_scp")),
        "significant_tornado_parameter_fixed_right": _finite(_get(sounding, "right_stp_fixed")),
        "significant_tornado_parameter_fixed_left": _finite(_get(sounding, "left_stp_fixed")),
        "significant_tornado_parameter_effective_right": _finite(_get(sounding, "right_stp_cin")),
        "significant_tornado_parameter_effective_left": _finite(_get(sounding, "left_stp_cin")),
        "significant_hail_parameter": _finite(_get(sounding, "ship")),
        "significant_severe_parameter": _finite(_get(sounding, "sig_severe")),
        "sherb": _finite(_get(sounding, "sherbe")),
        "enhanced_sig_tornado_parameter": _finite(_get(sounding, "esp")),
        "microburst_parameter": _finite(_get(sounding, "mburst")),
        "wind_damage_parameter": _finite(_get(sounding, "wndg")),
        "tei": _finite(_get(sounding, "tei")),
        "dcape_jkg": _finite(_get(sounding, "dcape")),
        "downburst_max_temperature_f": _finite(_get(sounding, "drush")),
        "watch_type": _json_safe(_get(sounding, "watch_type")),
    }

    fire = {
        "fosberg_fire_weather_index": _finite(_get(sounding, "fosberg")),
        "haines_index_low": _finite(_get(sounding, "haines_low")),
        "haines_index_mid": _finite(_get(sounding, "haines_mid")),
        "haines_index_high": _finite(_get(sounding, "haines_high")),
    }

    thermodynamic_profiles = {
        "wetbulb_c": _json_safe(_get(sounding, "wetbulb")),
        "potential_temperature_k": _json_safe(_get(sounding, "theta")),
        "equivalent_potential_temperature_k": _json_safe(_get(sounding, "thetae")),
        "water_vapor_mixing_ratio_gkg": _json_safe(_get(sounding, "wvmr")),
        "relative_humidity_pct": _json_safe(_get(sounding, "relh")),
    }

    try:
        library_version = version("SHARPpy")
    except PackageNotFoundError:
        library_version = None

    warnings = []
    if not any(value is not None for value in (thermodynamics["precipitable_water_in"], thermodynamics["k_index"])):
        warnings.append("Some SHARPpy thermodynamic diagnostics were unavailable.")
    if not any(value is not None for value in (kinematics["bulk_shear_0_6km_kt"], kinematics["srh_0_1km_m2s2"])):
        warnings.append("Some SHARPpy kinematic diagnostics were unavailable.")

    return {
        "library": "SHARPpy",
        "library_version": library_version,
        "profile_class": "ConvectiveProfile",
        "location": location,
        "latitude": latitude,
        "valid_time_utc": valid_date.isoformat().replace("+00:00", "Z"),
        "units": {
            "cape": "J/kg", "cin": "J/kg", "height": "m AGL",
            "wind": "kt", "srh": "m2/s2", "precipitable_water": "in",
            "lapse_rate": "C/km", "dcape": "J/kg",
        },
        "parcels": parcels,
        "kinematics": kinematics,
        "thermodynamics": thermodynamics,
        "winter": winter,
        "severe": severe,
        "fire": fire,
        "thermodynamic_profiles": thermodynamic_profiles,
        "sars": {
            "hail_matches": _json_safe(_get(sounding, "matches")),
            "supercell_matches": _json_safe(_get(sounding, "supercell_matches")),
        },
        "quality": {
            "input_levels": int(pressure.size),
            "pressure_decreases_upward": True,
            "height_increases_upward": True,
            "profile_class": "ConvectiveProfile",
            "warnings": warnings,
        },
    }
