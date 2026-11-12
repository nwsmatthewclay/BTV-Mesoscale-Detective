import os
import subprocess
import sys
from pathlib import Path

import pytest

from mesoscale.validate_hrrr_ingestion import validate_payload


CYCLE = "2026-11-12T15:00:00Z"


def sample_payload():
    return {
        "model": "HRRR",
        "model_cycle_utc": CYCLE,
        "forecast_hour": 0,
        "valid_time_utc": CYCLE,
        "grids": {
            "grid_0": {
                "latitude": [[44.5, 44.6]],
                "longitude": [[-73.2, -73.3]],
            }
        },
        "fields": {
            "temperature": {"short_name": "2t", "data": [[280.0, 281.0]]},
            "u_wind": {"short_name": "10u", "data": [[2.0, 3.0]]},
            "v_wind": {"short_name": "10v", "data": [[-1.0, -2.0]]},
        },
        "quality": {"field_count": 3, "grid_count": 1, "warnings": []},
    }


def test_hrrr_validator_accepts_matching_btv_surface_payload():
    report = validate_payload(sample_payload(), CYCLE, 0)
    assert report["status"] == "passed"
    assert report["grid_count"] == 1
    assert report["field_count"] == 3
    assert report["required_field_groups"] == {
        "2-m temperature": ["2t"],
        "10-m u wind": ["10u"],
        "10-m v wind": ["10v"],
    }


def test_hrrr_validator_rejects_wrong_cycle():
    with pytest.raises(RuntimeError, match="cycle mismatch"):
        validate_payload(sample_payload(), "2026-11-12T14:00:00Z", 0)


def test_hrrr_validator_rejects_missing_surface_wind_component():
    payload = sample_payload()
    del payload["fields"]["v_wind"]
    with pytest.raises(RuntimeError, match="10-m v wind"):
        validate_payload(payload, CYCLE, 0)


def test_hrrr_validator_rejects_grid_outside_btv_domain():
    payload = sample_payload()
    payload["grids"]["grid_0"]["latitude"] = [[40.0, 40.1]]
    payload["grids"]["grid_0"]["longitude"] = [[-73.2, -73.3]]
    with pytest.raises(RuntimeError, match="no coordinates inside the BTV domain"):
        validate_payload(payload, CYCLE, 0)


def test_hrrr_validator_runs_as_script_without_pythonpath():
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(repo_root / "mesoscale" / "validate_hrrr_ingestion.py"), "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Non-publishing HRRR surface-subset smoke test" in result.stdout
