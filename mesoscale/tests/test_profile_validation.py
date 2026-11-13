import json

import pytest

from mesoscale.diagnostics import _finite_profile
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
