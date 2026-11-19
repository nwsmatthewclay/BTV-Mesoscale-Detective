import copy
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mesoscale.sharppy_service import adjust_profile


def profile():
    p = np.array([1000, 975, 950, 925, 900, 875, 850, 825, 800, 750, 700, 650], float)
    z = np.array([20, 220, 430, 650, 870, 1090, 1320, 1550, 1780, 2250, 2750, 3300], float)
    t = 290 - z * 0.006
    td = t - 5
    return {
        "pressure_hpa": p.tolist(), "temperature_k": t.tolist(),
        "dewpoint_k": td.tolist(), "height_agl_m": z.tolist(),
        "u_ms": np.linspace(2, 20, len(p)).tolist(),
        "v_ms": np.linspace(-2, 8, len(p)).tolist(),
        "location": "KBTV", "latitude": 44.47, "date": "2026-11-19T12:00:00Z",
    }


def test_zero_adjustments_preserve_profile():
    original = profile()
    adjusted, warnings = adjust_profile(original, {})
    assert adjusted == original
    assert original["temperature_k"] == profile()["temperature_k"]


def test_mixing_depth_homogenizes_thermodynamics_and_wind():
    adjusted, _ = adjust_profile(profile(), {"mixing_depth_m": 1500})
    layer = np.array(adjusted["height_agl_m"]) <= 1500
    t = np.array(adjusted["temperature_k"])
    u = np.array(adjusted["u_ms"])
    v = np.array(adjusted["v_ms"])
    assert np.ptp(u[layer]) < 1e-10
    assert np.ptp(v[layer]) < 1e-10
    theta = t[layer] * (1000 / np.array(adjusted["pressure_hpa"])[layer]) ** 0.2854
    assert np.ptp(theta) < 1e-8


def test_offsets_only_change_levels_inside_mixing_depth():
    source = profile()
    adjusted, _ = adjust_profile(source, {
        "temperature_offset_c": 2, "dewpoint_offset_c": 1, "low_level_depth_m": 500, "mixing_depth_m": 0
    })
    layer = np.array(source["height_agl_m"]) <= 500
    outside = ~layer
    assert np.allclose(np.array(adjusted["temperature_k"])[outside], np.array(source["temperature_k"])[outside])
    assert np.allclose(np.array(adjusted["dewpoint_k"])[outside], np.array(source["dewpoint_k"])[outside])


def test_rejects_unphysical_adjustment_range():
    with pytest.raises(ValueError):
        adjust_profile(profile(), {"mixing_depth_m": 6000})
