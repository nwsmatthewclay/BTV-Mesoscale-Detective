from mesoscale.discover_models import RAP_FILENAME_RE, rap_product_role
from mesoscale.discover_models import RRFS_CYCLE_DIR_RE, RRFS_FILENAME_RE, prioritize_latest_products


def test_rrfs_pressure_level_filename():
    match = RRFS_FILENAME_RE.fullmatch("rrfs.t12z.prslev.3km.f018.conus.grib2")
    assert match.groups() == ("12", "prslev", "018")


def test_rrfs_surface_and_subhourly_filenames():
    surface = RRFS_FILENAME_RE.fullmatch("rrfs.t03z.2dfld.3km.f006.conus.grib2")
    subhourly = RRFS_FILENAME_RE.fullmatch("rrfs.t21z.2dfld.subh.3km.f003.conus.grib2")
    assert surface.groups() == ("03", "2dfld", "006")
    assert subhourly.groups() == ("21", "2dfld.subh", "003")


def test_rrfs_cycle_directory_is_two_digits():
    assert RRFS_CYCLE_DIR_RE.fullmatch("00")
    assert RRFS_CYCLE_DIR_RE.fullmatch("21")
    assert not RRFS_CYCLE_DIR_RE.fullmatch("conus")
    assert not RRFS_CYCLE_DIR_RE.fullmatch("20261112")


def test_rap_operational_filename_families():
    early = RAP_FILENAME_RE.fullmatch("rap.t12z.awp130bgrbf00.grib2")
    later = RAP_FILENAME_RE.fullmatch("rap.t12z.awp130pgrbf18.grib2")
    fallback = RAP_FILENAME_RE.fullmatch("rap.t12z.awip32f18.grib2")
    assert early.groups() == ("12", "awp130bgrb", "00")
    assert later.groups() == ("12", "awp130pgrb", "18")
    assert fallback.groups() == ("12", "awip32", "18")
    assert RAP_FILENAME_RE.fullmatch("rap.t12z.wrfprs.f18.grib2") is None



def test_rap_product_roles_distinguish_hybrid_and_pressure_level_files():
    assert rap_product_role("awp130bgrb") == "hybrid_levels_conus_13km"
    assert rap_product_role("awp130pgrb") == "pressure_levels_conus_13km"
    assert rap_product_role("awip32") == "north_american_32km"

def test_manifest_priority_preserves_near_term_rap_hours_before_truncation():
    products = []
    families = [
        "hybrid_levels_conus_13km",
        "pressure_levels_conus_13km",
        "north_american_32km",
    ]
    for hour in range(51):
        for family in families:
            products.append({
                "cycle_utc": "20261112T15:00:00Z",
                "forecast_hour": hour,
                "product": family,
                "url": f"https://example.test/{family}/f{hour:02d}.grib2",
            })

    selected = prioritize_latest_products(products, limit=120)
    hybrid_hours = {
        item["forecast_hour"] for item in selected
        if item["product"] == "hybrid_levels_conus_13km"
    }

    assert len(selected) == 120
    assert {0, 3, 6, 9}.issubset(hybrid_hours)
    assert min(hybrid_hours) == 0
    assert all(item["cycle_utc"] == "20261112T15:00:00Z" for item in selected)


def test_manifest_priority_keeps_newer_cycles_ahead_of_older_cycles():
    products = [
        {"cycle_utc": "20261112T14:00:00Z", "forecast_hour": 0, "product": "surface"},
        {"cycle_utc": "20261112T15:00:00Z", "forecast_hour": 9, "product": "surface"},
        {"cycle_utc": "20261112T15:00:00Z", "forecast_hour": 0, "product": "surface"},
    ]
    selected = prioritize_latest_products(products, limit=10)
    assert [(p["cycle_utc"], p["forecast_hour"]) for p in selected] == [
        ("20261112T15:00:00Z", 0),
        ("20261112T15:00:00Z", 9),
        ("20261112T14:00:00Z", 0),
    ]
