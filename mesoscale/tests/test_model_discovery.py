from datetime import datetime, timezone
from urllib.parse import urljoin

import pytest

from mesoscale import discover_models
from mesoscale.discover_models import (
    RAP_FILENAME_RE,
    RRFS_CYCLE_DIR_RE,
    RRFS_FILENAME_RE,
    index_summary,
    include_index_targets_in_manifest,
    prioritize_latest_products,
    product_lead_label,
    product_lead_minutes,
    rap_product_role,
    rrfs_product_role,
    select_index_targets,
)


def test_rrfs_pressure_level_filename():
    match = RRFS_FILENAME_RE.fullmatch("rrfs.t12z.prslev.3km.f018.conus.grib2")
    assert match is not None
    assert match.groupdict() == {
        "cycle": "12",
        "family": "prslev",
        "subhourly": None,
        "forecast": "018",
    }
    assert rrfs_product_role(match.group("family")) == "pressure_levels_3km"


def test_rrfs_surface_and_official_subhourly_filenames():
    surface = RRFS_FILENAME_RE.fullmatch("rrfs.t03z.2dfld.3km.f006.conus.grib2")
    subhourly = RRFS_FILENAME_RE.fullmatch("rrfs.t21z.2dfld.3km.subh.f003.conus.grib2")
    assert surface is not None
    assert subhourly is not None
    assert surface.groupdict() == {
        "cycle": "03",
        "family": "2dfld",
        "subhourly": None,
        "forecast": "006",
    }
    assert subhourly.groupdict() == {
        "cycle": "21",
        "family": "2dfld",
        "subhourly": ".subh",
        "forecast": "003",
    }
    assert rrfs_product_role("2dfld") == "surface_2d_3km"
    assert rrfs_product_role("2dfld", subhourly=True) == "surface_subhourly_3km"
    # Reject the previously assumed token order; NOMADS uses 2dfld.3km.subh.
    assert RRFS_FILENAME_RE.fullmatch("rrfs.t21z.2dfld.subh.3km.f003.conus.grib2") is None


def test_rrfs_cycle_directory_is_two_digits():
    assert RRFS_CYCLE_DIR_RE.fullmatch("00")
    assert RRFS_CYCLE_DIR_RE.fullmatch("21")
    assert not RRFS_CYCLE_DIR_RE.fullmatch("conus")
    assert not RRFS_CYCLE_DIR_RE.fullmatch("20261112")


def test_discover_rrfs_records_subhourly_lead_in_minutes(monkeypatch):
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    day_dir = f"{discover_models.BASE}/rrfs/prod/rrfs.{date}/"
    filename = "rrfs.t21z.2dfld.3km.subh.f003.conus.grib2"

    def fake_get_listing(session, url):
        if url == day_dir:
            return [urljoin(url, "21/")]
        if url.endswith("/21/"):
            return [urljoin(url, filename)]
        return []

    monkeypatch.setattr(discover_models, "get_listing", fake_get_listing)
    products = discover_models.discover_rrfs(object(), 0)
    item = next(product for product in products if product["filename"] == filename)

    assert item["product"] == "surface_subhourly_3km"
    assert item["forecast_step"] == 3
    assert item["forecast_lead_minutes"] == 45
    assert item["forecast_interval_minutes"] == 15
    assert "forecast_hour" not in item


def test_prioritize_latest_products_uses_true_subhourly_lead_minutes():
    cycle = "20261112T22:00:00Z"
    products = [
        {"cycle_utc": cycle, "forecast_hour": 1, "product": "surface_2d_3km"},
        {"cycle_utc": cycle, "forecast_step": 3, "forecast_lead_minutes": 45,
         "product": "surface_subhourly_3km"},
        {"cycle_utc": cycle, "forecast_step": 1, "forecast_lead_minutes": 15,
         "product": "surface_subhourly_3km"},
    ]

    ordered = prioritize_latest_products(products)

    assert [product_lead_minutes(product) for product in ordered] == [15, 45, 60]


def test_product_lead_labels_preserve_subhourly_units():
    assert product_lead_label({"forecast_hour": 3}) == "F03"
    assert product_lead_label({"forecast_step": 1, "forecast_lead_minutes": 15}) == "+15 min"
    assert product_lead_label({"forecast_step": 3, "forecast_lead_minutes": 45}) == "+45 min"


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



class FakeIndexResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeIndexSession:
    def __init__(self, text):
        self.text = text
        self.requested_url = None

    def get(self, url, timeout):
        self.requested_url = url
        return FakeIndexResponse(self.text)


def test_index_summary_parses_only_valid_nomads_grib_index_records():
    session = FakeIndexSession(
        "1:0:d=2026111216:TMP:2 m above ground:anl:\n"
        "12.1:801427:d=2026111216:UGRD:100 mb:anl:\n"
    )

    result = index_summary(session, "https://example.test/rap.grib2")

    assert session.requested_url == "https://example.test/rap.grib2.idx"
    assert result["message_count"] == 2
    assert result["messages"][0]["byte_offset"] == 0
    assert result["messages"][1]["message"] == "12.1"
    assert result["messages"][1]["short_name"] == "UGRD"
    assert result["messages"][1]["level"] == "100 mb"


def test_index_summary_rejects_html_error_pages_returned_with_http_200():
    session = FakeIndexSession(
        "<!doctype html><html><head><style>body { font: 16px Helvetica; }</style>"
        "</head><body>Not Found</body></html>"
    )

    with pytest.raises(ValueError, match="no valid GRIB index records"):
        index_summary(session, "https://example.test/rrfs.grib2")



def test_select_index_targets_keeps_two_rrfs_subhourly_cycles_for_fallback():
    products = [
        {
            "product": "surface_subhourly_3km",
            "cycle_utc": "2026-11-13T00:00:00Z",
            "forecast_step": 1,
            "forecast_lead_minutes": 15,
            "url": "https://example.test/rrfs00_f001.grib2",
        },
        {
            "product": "surface_subhourly_3km",
            "cycle_utc": "2026-11-13T00:00:00Z",
            "forecast_step": 2,
            "forecast_lead_minutes": 30,
            "url": "https://example.test/rrfs00_f002.grib2",
        },
        {
            "product": "surface_subhourly_3km",
            "cycle_utc": "2026-11-12T23:00:00Z",
            "forecast_step": 1,
            "forecast_lead_minutes": 15,
            "url": "https://example.test/rrfs23_f001.grib2",
        },
        {
            "product": "surface_subhourly_3km",
            "cycle_utc": "2026-11-12T22:00:00Z",
            "forecast_step": 1,
            "forecast_lead_minutes": 15,
            "url": "https://example.test/rrfs22_f001.grib2",
        },
        {
            "product": "surface_2d_3km",
            "cycle_utc": "2026-11-13T00:00:00Z",
            "forecast_hour": 0,
            "url": "https://example.test/rrfs00_surface.grib2",
        },
        {
            "product": "pressure_levels_3km",
            "cycle_utc": "2026-11-13T00:00:00Z",
            "forecast_hour": 0,
            "url": "https://example.test/rrfs00_pressure.grib2",
        },
    ]

    selected = select_index_targets(products)
    subhourly = [item for item in selected if item["product"] == "surface_subhourly_3km"]

    assert [(item["cycle_utc"], item["forecast_step"]) for item in subhourly] == [
        ("2026-11-13T00:00:00Z", 1),
        ("2026-11-12T23:00:00Z", 1),
    ]
    assert sum(item["product"] == "surface_2d_3km" for item in selected) == 1
    assert sum(item["product"] == "pressure_levels_3km" for item in selected) == 1


def test_select_index_targets_rejects_zero_fallback_cycles():
    with pytest.raises(ValueError, match="limit must be at least one"):
        select_index_targets([], subhourly_cycle_limit=0)



def test_indexed_fallback_product_is_retained_beyond_manifest_display_limit():
    newest = [
        {
            "cycle_utc": "2026-11-13T00:00:00Z",
            "forecast_hour": hour,
            "product": "surface",
            "url": f"https://example.test/newest/f{hour:03d}.grib2",
        }
        for hour in range(5)
    ]
    fallback = {
        "cycle_utc": "2026-11-12T23:00:00Z",
        "forecast_step": 1,
        "forecast_lead_minutes": 15,
        "product": "surface_subhourly_3km",
        "url": "https://example.test/fallback/rrfs23_f001.grib2",
        "index": {"message_count": 149, "messages": [{"byte_offset": 0}, {"byte_offset": 100}]},
    }

    selected = include_index_targets_in_manifest(newest + [fallback], [fallback], limit=3)

    assert len(selected) == 4
    assert [item["url"] for item in selected[:3]] == [
        "https://example.test/newest/f000.grib2",
        "https://example.test/newest/f001.grib2",
        "https://example.test/newest/f002.grib2",
    ]
    assert selected[3]["url"] == fallback["url"]
    assert selected[3]["index"]["message_count"] == 149


def test_indexed_target_already_in_manifest_is_not_duplicated():
    product = {
        "cycle_utc": "2026-11-13T00:00:00Z",
        "forecast_hour": 0,
        "product": "surface",
        "url": "https://example.test/current.grib2",
    }

    selected = include_index_targets_in_manifest([product], [product], limit=120)

    assert len(selected) == 1
