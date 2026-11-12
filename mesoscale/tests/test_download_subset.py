from urllib.parse import parse_qs, urlparse

import pytest

from mesoscale.download_subset import filter_url, select_product


def product(model, cycle, hour, family, filename):
    return {
        "model": model,
        "date": cycle[:10].replace("-", ""),
        "cycle_utc": cycle,
        "forecast_hour": hour,
        "product": family,
        "filename": filename,
        "url": f"https://nomads.ncep.noaa.gov/{filename}",
    }


def test_rap_filter_uses_current_pressure_level_filename_and_btv_region():
    item = product(
        "RAP", "2026-11-12T11:00:00Z", 0, "pressure_levels_conus_13km",
        "rap.t11z.awp130pgrbf00.grib2",
    )
    url = filter_url("RAP", item)
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    assert parsed.path == "/cgi-bin/filter_rap.pl"
    assert params["file"] == ["rap.t11z.awp130pgrbf00.grib2"]
    assert params["dir"] == ["/rap.20261112"]
    assert params["subregion"] == [""]
    assert params["leftlon"] == ["-75.2"]
    assert params["rightlon"] == ["-71.2"]
    assert params["var_TMP"] == ["on"]
    assert params["lev_1000_mb"] == ["on"]


def test_hrrr_filter_uses_current_surface_filename_and_btv_region():
    item = product(
        "HRRR", "2026-11-12T12:00:00Z", 0, "surface",
        "hrrr.t12z.wrfsfcf00.grib2",
    )
    url = filter_url("HRRR", item)
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    assert parsed.path == "/cgi-bin/filter_hrrr_2d.pl"
    assert params["file"] == ["hrrr.t12z.wrfsfcf00.grib2"]
    assert params["dir"] == ["/hrrr.20261112/conus"]
    assert params["subregion"] == [""]
    assert params["var_CAPE"] == ["on"]
    assert params["lev_2_m_above_ground"] == ["on"]


def test_select_product_uses_current_manifest_product_families_and_latest_cycle():
    manifest = {"models": {
        "RAP": {"latest_products": [
            product("RAP", "2026-11-12T10:00:00Z", 0, "pressure_levels_full_domain",
                    "rap.t10z.wrfprs.f00.grib2"),
            product("RAP", "2026-11-12T10:00:00Z", 0, "pressure_levels_conus_13km",
                    "rap.t10z.awp130pgrbf00.grib2"),
            product("RAP", "2026-11-12T11:00:00Z", 0, "pressure_levels_conus_13km",
                    "rap.t11z.awp130pgrbf00.grib2"),
        ]},
        "HRRR": {"latest_products": [
            product("HRRR", "2026-11-12T11:00:00Z", 0, "surface",
                    "hrrr.t11z.wrfsfcf00.grib2"),
            product("HRRR", "2026-11-12T12:00:00Z", 0, "surface",
                    "hrrr.t12z.wrfsfcf00.grib2"),
        ]},
    }}

    rap = select_product(manifest, "RAP", 0)
    hrrr = select_product(manifest, "HRRR", 0)

    assert rap["cycle_utc"] == "2026-11-12T11:00:00Z"
    assert rap["filename"] == "rap.t11z.awp130pgrbf00.grib2"
    assert hrrr["cycle_utc"] == "2026-11-12T12:00:00Z"
    assert hrrr["filename"] == "hrrr.t12z.wrfsfcf00.grib2"


def test_select_product_respects_requested_cycle_and_rejects_unsupported_families():
    manifest = {"models": {"RAP": {"latest_products": [
        product("RAP", "2026-11-12T10:00:00Z", 0, "pressure_levels_conus_13km",
                "rap.t10z.awp130pgrbf00.grib2"),
        product("RAP", "2026-11-12T11:00:00Z", 0, "pressure_levels_conus_13km",
                "rap.t11z.awp130pgrbf00.grib2"),
        product("RAP", "2026-11-12T11:00:00Z", 0, "hybrid_levels_conus_13km",
                "rap.t11z.awp130bgrbf00.grib2"),
    ]}}}

    selected = select_product(manifest, "RAP", 0, "2026-11-12T10:00:00Z")
    assert selected["filename"] == "rap.t10z.awp130pgrbf00.grib2"
    assert select_product(manifest, "RAP", 0, "2026-11-12T09:00:00Z") is None
    with pytest.raises(ValueError, match="Unsupported subset model"):
        select_product(manifest, "RRFS", 0)
