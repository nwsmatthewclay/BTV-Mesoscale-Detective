import numpy as np
import pytest

from mesoscale.sharppy_adapter import _profile_arrays, calculate_sharppy_diagnostics


def synthetic_profile():
    pressure = np.array([1000, 950, 900, 850, 800, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300, 250, 200], dtype=float)
    height = np.array([0, 450, 900, 1350, 1800, 2250, 2750, 3250, 3800, 4400, 5050, 5750, 6500, 7350, 8300, 9450, 11000], dtype=float)
    temperature_c = np.array([18, 15, 12, 9, 6, 2, -2, -6, -11, -16, -22, -29, -36, -43, -50, -57, -62], dtype=float)
    dewpoint_c = temperature_c - np.array([2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 22, 24, 26], dtype=float)
    return {
        "pressure_hpa": pressure.tolist(),
        "temperature_k": (temperature_c + 273.15).tolist(),
        "dewpoint_k": (dewpoint_c + 273.15).tolist(),
        "height_agl_m": height.tolist(),
        "u_ms": np.linspace(2, 25, pressure.size).tolist(),
        "v_ms": np.linspace(0, 12, pressure.size).tolist(),
    }


def test_profile_contract_rejects_non_monotonic_pressure():
    profile = synthetic_profile()
    profile["pressure_hpa"][4] = profile["pressure_hpa"][2]
    with pytest.raises(ValueError, match="strictly decrease"):
        _profile_arrays(profile)


def test_profile_contract_rejects_non_finite_values():
    profile = synthetic_profile()
    profile["u_ms"][3] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        _profile_arrays(profile)


def test_sharppy_adapter_runs_when_optional_dependency_is_installed():
    pytest.importorskip("sharppy")
    result = calculate_sharppy_diagnostics(synthetic_profile())
    assert result["library"] == "SHARPpy"
    assert result["quality"]["input_levels"] == 17
    assert result["units"]["cape"] == "J/kg"
    assert set(result["parcels"]) == {"surface", "most_unstable", "mixed_layer"}
    assert "srh_0_1km_m2s2" in result["kinematics"]
