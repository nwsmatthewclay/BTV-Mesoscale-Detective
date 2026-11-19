from datetime import datetime, timezone
import numpy as np
import pytest

from mesoscale.bufkit_feed import MODEL_PRODUCTS, _profile_to_contract, parse_bufkit_record_headers


def test_bufkit_header_extracts_valid_time_and_cycle():
    text = """STID = KBTV STNM = 72617 TIME = 261119/0700
SLAT = 44.47 SLON = -73.15 SELV = 101
STIM = 0.00
PRES TMPC TMWC DWPC THTE DRCT SKNT OMEG CFRL HGHT
STID = KBTV STNM = 72617 TIME = 261119/0800
SLAT = 44.47 SLON = -73.15 SELV = 101
STIM = 1.00
PRES TMPC TMWC DWPC THTE DRCT SKNT OMEG CFRL HGHT
"""
    records = parse_bufkit_record_headers(text)
    assert len(records) == 2
    assert records[0]["forecast_hour"] == 0
    assert records[1]["forecast_hour"] == 1
    assert records[1]["model_cycle_utc"] == datetime(2026, 11, 19, 7, tzinfo=timezone.utc)


def test_supported_model_filename_conventions():
    assert MODEL_PRODUCTS["RAP"] == ("RAP", "rap")
    assert MODEL_PRODUCTS["GFS"] == ("GFS", "gfs3")
    assert MODEL_PRODUCTS["RRFS"] == ("RRFS", "rrfs")
    assert "SREF" not in MODEL_PRODUCTS  # Ensemble members need an explicit selection UI.


def test_sharppy_profile_is_converted_to_si_and_relative_height():
    class Profile:
        pres = np.array([1000., 900., 800., 700., 600., 500., 400., 300., 200., 100.])
        tmpc = np.linspace(15, -55, 10)
        dwpc = np.linspace(10, -60, 10)
        hght = np.linspace(100., 16000., 10)
        u = np.linspace(0, 90, 10)  # SHARPpy wind components are knots
        v = np.linspace(-10, 50, 10)

    result = _profile_to_contract(Profile())
    assert result["height_agl_m"][0] == 0
    assert result["temperature_k"][0] == pytest.approx(288.15)
    assert result["u_ms"][-1] == pytest.approx(90 / 1.9438444924406)
    assert result["pressure_hpa"][0] == 1000
