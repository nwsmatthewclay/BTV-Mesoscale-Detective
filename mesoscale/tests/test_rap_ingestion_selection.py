import pytest

from mesoscale.validate_rap_ingestion import choose_product


def product(cycle, hour, family="hybrid"):
    token = "awp130bgrb" if family == "hybrid" else "awp130pgrb"
    return {
        "cycle_utc": cycle,
        "forecast_hour": hour,
        "filename": f"rap.t15z.{token}f{hour:02d}.grib2",
        "url": f"https://example.test/{token}/f{hour:02d}.grib2",
        "product": "hybrid_levels_conus_13km" if family == "hybrid" else "pressure_levels_conus_13km",
    }


def test_rap_validation_selects_f00_hybrid_without_requiring_index_metadata():
    manifest = {"models": {"RAP": {"latest_products": [
        product("20261112T14:00:00Z", 0),
        product("20261112T15:00:00Z", 50),
        product("20261112T15:00:00Z", 0),
        {**product("20261112T15:00:00Z", 0, "pressure"), "index": {"message_count": 359}},
    ]}}}

    selected = choose_product(manifest)

    assert selected["cycle_utc"] == "20261112T15:00:00Z"
    assert selected["forecast_hour"] == 0
    assert selected["product"] == "hybrid_levels_conus_13km"


def test_rap_validation_rejects_manifest_without_hybrid_products():
    manifest = {"models": {"RAP": {"latest_products": [
        product("20261112T15:00:00Z", 0, "pressure"),
    ]}}}
    with pytest.raises(RuntimeError, match="No RAP 13-km CONUS hybrid-level product"):
        choose_product(manifest)
