import json

import numpy as np
import pytest

from mesoscale.diagnostics import _finite_profile, _number, diagnose_profile
from mesoscale.extract_profile import write_profile_json
from mesoscale.process_grib import (
    grib_metadata, grid_projection_metadata,
    merge_grib_metadata, merge_grid_projection_metadata, parse_cycle_time,
)


def test_profile_rejects_mismatched_arrays():
    with pytest.raises(ValueError, match="equal length"):
        _finite_profile([1000, 900, 800, 700, 600],
                        [290, 285, 280, 275, 270],
                        [285, 280, 275, 270],
                        [0, 1000, 2000, 3000, 4000])


def test_profile_rejects_duplicate_pressure_levels():
    with pytest.raises(ValueError, match="strictly decrease"):
        _finite_profile([1000, 900, 900, 700, 600],
                        [290, 285, 280, 275, 270],
                        [285, 280, 275, 270, 265],
                        [0, 1000, 2000, 3000, 4000])


def test_profile_rejects_nonmonotonic_height():
    with pytest.raises(ValueError, match="increase upward"):
        _finite_profile([1000, 900, 800, 700, 600],
                        [290, 285, 280, 275, 270],
                        [285, 280, 275, 270, 265],
                        [0, 1000, 900, 3000, 4000])


def test_specific_humidity_precision_is_preserved():
    import numpy as np
    from mesoscale.process_grib import json_values

    values = json_values(np.array([0.00345678]), decimals=7)
    assert values == [0.0034568]



def test_profile_json_writer_writes_parseable_json(tmp_path):
    output = tmp_path / "nested" / "profile.json"
    profile = {"model": "RAP", "forecast_hour": 3, "quality": {"levels": 50}}

    write_profile_json(profile, output)

    serialized = output.read_text(encoding="utf-8")
    assert serialized.endswith("\n")
    assert json.loads(serialized) == profile



def test_grib_projection_metadata_preserves_native_geometry_and_wind_orientation():
    attrs = {
        "GRIB_gridType": "lambert",
        "GRIB_LoVInDegrees": -97.5,
        "GRIB_Latin1InDegrees": 38.5,
        "GRIB_DxInMetres": 13000,
        "GRIB_DyInMetres": 13000,
        "GRIB_uvRelativeToGrid": 1,
        "unrelated": "omit",
    }
    projection = grid_projection_metadata(attrs)
    assert projection["GRIB_gridType"] == "lambert"
    assert projection["GRIB_DxInMetres"] == 13000
    assert projection["GRIB_uvRelativeToGrid"] == 1
    assert "unrelated" not in projection
    assert grib_metadata(attrs)["GRIB_uvRelativeToGrid"] == 1



def test_grib_metadata_merges_projection_from_variable_attributes():
    dataset_attrs = {"GRIB_gridType": "lambert", "GRIB_LoVInDegrees": 265.0}
    variable_attrs = {
        "GRIB_DxInMetres": 13545.0,
        "GRIB_DyInMetres": 13545.0,
        "GRIB_uvRelativeToGrid": 1,
        "GRIB_shortName": "u",
    }
    projection = merge_grid_projection_metadata(dataset_attrs, variable_attrs)
    metadata = merge_grib_metadata(dataset_attrs, variable_attrs)

    assert projection["GRIB_gridType"] == "lambert"
    assert projection["GRIB_DxInMetres"] == 13545.0
    assert projection["GRIB_uvRelativeToGrid"] == 1
    assert metadata["GRIB_shortName"] == "u"


@pytest.mark.parametrize("cycle", [
    "2026-11-13T04:00:00Z",
    "20261113T04:00:00Z",
    "20261113T04:00:00+00:00",
])
def test_parse_cycle_time_accepts_iso_and_compact_nomads_timestamps(cycle):
    from datetime import datetime, timezone

    assert parse_cycle_time(cycle) == datetime(2026, 11, 13, 4, tzinfo=timezone.utc)


def test_parse_cycle_time_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="UTC offset"):
        parse_cycle_time("2026-11-13T04:00:00")



class _FakeQuantity:
    def __init__(self, magnitude):
        self.magnitude = magnitude

    def to(self, _target_unit):
        return self


@pytest.mark.parametrize("magnitude", [
    np.ma.masked,
    float("nan"),
    float("inf"),
    float("-inf"),
])
def test_diagnostic_number_returns_none_for_masked_or_nonfinite_values(magnitude):
    assert _number(_FakeQuantity(magnitude), "dimensionless") is None


def test_diagnostic_number_preserves_finite_scalar():
    assert _number(_FakeQuantity(123.5), "dimensionless") == pytest.approx(123.5)


def test_diagnostic_number_rejects_non_scalar_magnitudes():
    assert _number(_FakeQuantity([1.0, 2.0]), "dimensionless") is None


def test_profile_drops_masked_levels_across_all_collocated_arrays():
    pressure = np.ma.array(
        [1000, 900, 1.0e20, 700, 600, 500, 400],
        mask=[False, False, True, False, False, False, False],
        fill_value=1.0e20,
    )
    temperature = np.ma.array(
        [290, 285, 280, 275, -9999, 265, 260],
        mask=[False, False, False, False, True, False, False],
        fill_value=-9999,
    )
    dewpoint = np.array([285, 280, 275, 270, 265, 260, 255], dtype=float)
    height = np.array([0, 1000, 2000, 3000, 4000, 5000, 6000], dtype=float)
    u_wind = np.array([1, 2, 3, 4, 5, 6, 7], dtype=float)
    v_wind = np.array([-1, -2, -3, -4, -5, -6, -7], dtype=float)

    p, t, td, z, u, v = _finite_profile(
        pressure, temperature, dewpoint, height, u_wind, v_wind
    )

    np.testing.assert_allclose(p, [1000, 900, 700, 500, 400])
    np.testing.assert_allclose(t, [290, 285, 275, 265, 260])
    np.testing.assert_allclose(td, [285, 280, 270, 260, 255])
    np.testing.assert_allclose(z, [0, 1000, 3000, 5000, 6000])
    np.testing.assert_allclose(u, [1, 2, 4, 6, 7])
    np.testing.assert_allclose(v, [-1, -2, -4, -6, -7])


def test_profile_rejects_too_few_complete_levels_after_masking():
    pressure = np.ma.array(
        [1000, 900, 800, 700, 600],
        mask=[False, True, True, False, True],
        fill_value=1.0e20,
        dtype=float,
    )

    with pytest.raises(ValueError, match="five complete finite levels"):
        _finite_profile(
            pressure,
            [290, 285, 280, 275, 270],
            [285, 280, 275, 270, 265],
            [0, 1000, 2000, 3000, 4000],
        )


def test_profile_requires_both_wind_components_together():
    with pytest.raises(ValueError, match="provided together"):
        _finite_profile(
            [1000, 900, 800, 700, 600],
            [290, 285, 280, 275, 270],
            [285, 280, 275, 270, 265],
            [0, 1000, 2000, 3000, 4000],
            u_ms=[1, 2, 3, 4, 5],
        )

def test_diagnose_profile_rejects_incomplete_wind_pair():
    with pytest.raises(ValueError, match="Wind components must be provided together"):
        diagnose_profile(
            [1000, 900, 800, 700, 600],
            [290, 285, 280, 275, 270],
            [285, 280, 275, 270, 265],
            [0, 1000, 2000, 3000, 4000],
            u_ms=[1, 2, 3, 4, 5],
        )
