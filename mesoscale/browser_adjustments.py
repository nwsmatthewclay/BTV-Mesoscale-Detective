"""NumPy-only sounding adjustments for the in-browser SHARPpy prototype."""
from __future__ import annotations
import numpy as np

EPSILON = 0.622
KAPPA = 0.2854

def _dewpoint_to_mixing_ratio(dewpoint_k, pressure_hpa):
    td_c = dewpoint_k - 273.15
    vapor_pressure = 6.112 * np.exp(17.67 * td_c / (td_c + 243.5))
    vapor_pressure = np.minimum(vapor_pressure, pressure_hpa * 0.99)
    return EPSILON * vapor_pressure / (pressure_hpa - vapor_pressure)

def _mixing_ratio_to_dewpoint(mixing_ratio, pressure_hpa):
    vapor_pressure = pressure_hpa * mixing_ratio / (EPSILON + mixing_ratio)
    vapor_pressure = np.maximum(vapor_pressure, 1.0e-6)
    log_ratio = np.log(vapor_pressure / 6.112)
    return 243.5 * log_ratio / (17.67 - log_ratio) + 273.15

def _pressure_mass_weights(pressure_hpa):
    if pressure_hpa.size < 2:
        raise ValueError("At least two levels are required for pressure-mass weighting")
    edges = np.empty(pressure_hpa.size + 1, dtype=float)
    edges[1:-1] = 0.5 * (pressure_hpa[:-1] + pressure_hpa[1:])
    edges[0] = pressure_hpa[0] + 0.5 * (pressure_hpa[0] - pressure_hpa[1])
    edges[-1] = max(0.0, pressure_hpa[-1] - 0.5 * (pressure_hpa[-2] - pressure_hpa[-1]))
    weights = np.maximum(0.0, edges[:-1] - edges[1:])
    total = float(weights.sum())
    if not np.isfinite(total) or total <= 0:
        raise ValueError("Unable to calculate positive pressure-layer weights")
    return weights / total

def adjust_profile(profile, adjustments=None):
    """Return an independent adjusted profile and warnings; never mutate source."""
    adjustments = adjustments or {}
    keys = ("pressure_hpa", "temperature_k", "dewpoint_k", "height_agl_m", "u_ms", "v_ms")
    arrays = {}
    for key in keys:
        if key not in profile:
            raise ValueError(f"Profile is missing {key}")
        values = np.asarray(profile[key], dtype=float)
        if values.ndim != 1 or not np.all(np.isfinite(values)):
            raise ValueError(f"{key} must be a finite one-dimensional array")
        arrays[key] = values.copy()
    lengths = {value.size for value in arrays.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) < 10:
        raise ValueError("Profile arrays must be collocated and contain at least 10 levels")
    p, z, t, td = arrays["pressure_hpa"], arrays["height_agl_m"], arrays["temperature_k"], arrays["dewpoint_k"]
    if np.any(p <= 0) or not np.all(np.diff(p) < 0):
        raise ValueError("Pressure must strictly decrease upward")
    if not np.all(np.diff(z) > 0):
        raise ValueError("Height must strictly increase upward")
    if np.any((t < 150) | (t > 350)) or np.any((td < 130) | (td > 330)):
        raise ValueError("Temperature/dewpoint outside plausible Kelvin bounds")
    temp_offset = float(adjustments.get("temperature_offset_c", 0.0))
    dew_offset = float(adjustments.get("dewpoint_offset_c", 0.0))
    offset_depth = float(adjustments.get("low_level_depth_m", 1000.0))
    mix_depth = float(adjustments.get("mixing_depth_m", 0.0))
    if not -15 <= temp_offset <= 15 or not -15 <= dew_offset <= 15:
        raise ValueError("Temperature/dewpoint offsets must be between -15 and +15 °C")
    if not 0 <= offset_depth <= 5000 or not 0 <= mix_depth <= 5000:
        raise ValueError("Adjustment and mixing depths must be between 0 and 5000 m AGL")
    warnings = []
    offset_mask = z <= offset_depth if offset_depth > 0 else np.zeros(z.shape, dtype=bool)
    t[offset_mask] += temp_offset
    td[offset_mask] += dew_offset
    supersaturated = td > t
    if np.any(supersaturated):
        warnings.append(f"Dewpoint capped at temperature at {int(np.count_nonzero(supersaturated))} levels.")
    td[:] = np.minimum(td, t)
    if mix_depth > 0:
        indices = np.flatnonzero(z <= mix_depth)
        if indices.size < 2:
            warnings.append("Selected mixing depth contains fewer than two model levels; no mixing applied.")
        else:
            layer_p = p[indices]
            weights = _pressure_mass_weights(layer_p)
            theta = t[indices] * (1000.0 / layer_p) ** KAPPA
            mean_theta = float(np.sum(theta * weights))
            ratios = _dewpoint_to_mixing_ratio(td[indices], layer_p)
            mean_ratio = float(np.sum(ratios * weights))
            mean_u = float(np.sum(arrays["u_ms"][indices] * weights))
            mean_v = float(np.sum(arrays["v_ms"][indices] * weights))
            t[indices] = mean_theta * (layer_p / 1000.0) ** KAPPA
            td[indices] = np.minimum(_mixing_ratio_to_dewpoint(mean_ratio, layer_p), t[indices])
            arrays["u_ms"][indices] = mean_u
            arrays["v_ms"][indices] = mean_v
    if np.any(td > t) or np.any((t < 150) | (t > 350)) or np.any((td < 130) | (td > 330)):
        raise ValueError("Adjusted profile is outside plausible thermodynamic bounds")
    adjusted = {key: value.tolist() for key, value in arrays.items()}
    for key in ("location", "latitude", "date", "valid_time_utc", "omega_pa_s"):
        if key in profile:
            adjusted[key] = profile[key]
    return adjusted, warnings
