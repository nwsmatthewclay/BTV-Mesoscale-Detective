import json

import pytest

from mesoscale.diagnostics import _finite_profile
from mesoscale.extract_profile import write_profile_json


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
