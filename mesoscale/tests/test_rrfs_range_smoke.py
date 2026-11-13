import pytest

from mesoscale.rrfs_range_smoke import (
    fetch_indexed_message,
    plan_index_ranges,
    run_smoke,
    select_rrfs_product,
    summarize_btv_coverage,
    verify_content_range,
)


def test_plan_index_ranges_uses_next_offset_minus_one():
    messages = [
        {"message": "1", "byte_offset": 0, "short_name": "REFC"},
        {"message": "2", "byte_offset": 100, "short_name": "VIL"},
        {"message": "3", "byte_offset": 250, "short_name": "VIS"},
        {"message": "4", "byte_offset": 400, "short_name": "TMP"},
    ]

    planned = plan_index_ranges(messages, limit=3)

    assert [(item["start"], item["end"], item["bytes"]) for item in planned] == [
        (0, 99, 100),
        (100, 249, 150),
        (250, 399, 150),
    ]


def test_plan_index_ranges_rejects_non_increasing_offsets():
    with pytest.raises(ValueError, match="strictly increasing"):
        plan_index_ranges([
            {"byte_offset": 100},
            {"byte_offset": 100},
        ])


def test_plan_index_ranges_rejects_oversized_message():
    with pytest.raises(ValueError, match="safety cap"):
        plan_index_ranges(
            [{"byte_offset": 0}, {"byte_offset": 1001}],
            max_message_bytes=1000,
        )


def test_verify_content_range_requires_exact_requested_offsets():
    assert verify_content_range("bytes 100-199/1000", 100, 199) == 1000
    with pytest.raises(RuntimeError, match="Content-Range mismatch"):
        verify_content_range("bytes 100-198/1000", 100, 199)
    with pytest.raises(RuntimeError, match="Missing or invalid"):
        verify_content_range(None, 100, 199)


class FakeResponse:
    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = headers
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, status_code=206):
        self.status_code = status_code
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
        payload = b"GRIB" + b"x" * (end - start - 7) + b"7777"
        return FakeResponse(
            self.status_code,
            {"Content-Range": f"bytes {start}-{end}/1000"},
            payload,
        )


def test_fetch_indexed_message_requires_http_206_and_complete_grib():
    session = FakeSession()
    record = {"start": 10, "end": 109, "bytes": 100}

    payload = fetch_indexed_message(session, "https://example.test/rrfs.grib2", record)

    assert payload.startswith(b"GRIB")
    assert payload.endswith(b"7777")
    assert session.calls[0][1]["Range"] == "bytes=10-109"
    assert session.calls[0][1]["Accept-Encoding"] == "identity"

    ignored_range = FakeSession(status_code=200)
    with pytest.raises(RuntimeError, match="expected 206"):
        fetch_indexed_message(ignored_range, "https://example.test/rrfs.grib2", record)


def test_select_rrfs_product_prefers_newest_indexed_subhourly_cycle():
    def item(cycle, lead, filename):
        return {
            "product": "surface_subhourly_3km",
            "cycle_utc": cycle,
            "forecast_lead_minutes": lead,
            "filename": filename,
            "url": f"https://example.test/{filename}",
            "index": {
                "url": f"https://example.test/{filename}.idx",
                "message_count": 2,
                "messages": [{"byte_offset": 0}, {"byte_offset": 100}],
            },
        }

    manifest = {"models": {"RRFS": {"latest_products": [
        item("2026-11-12T22:00:00Z", 15, "old.grib2"),
        item("2026-11-12T23:00:00Z", 30, "newer-later.grib2"),
        item("2026-11-12T23:00:00Z", 15, "newest-near-term.grib2"),
    ]}}}

    selected = select_rrfs_product(manifest)

    assert selected["filename"] == "newest-near-term.grib2"


def test_run_smoke_downloads_and_decodes_only_bounded_messages():
    filename = "rrfs.t23z.2dfld.3km.subh.f001.conus.grib2"
    product = {
        "product": "surface_subhourly_3km",
        "cycle_utc": "20261112T23:00:00Z",
        "forecast_step": 1,
        "forecast_lead_minutes": 15,
        "filename": filename,
        "url": f"https://example.test/{filename}",
        "index": {
            "url": f"https://example.test/{filename}.idx",
            "message_count": 6,
            "messages": [
                {"message": "1", "byte_offset": 0, "short_name": "REFC"},
                {"message": "2", "byte_offset": 100, "short_name": "TMP"},
                {"message": "3", "byte_offset": 200, "short_name": "DPT"},
                {"message": "4", "byte_offset": 300, "short_name": "UGRD"},
                {"message": "5", "byte_offset": 400, "short_name": "VGRD"},
                {"message": "6", "byte_offset": 500, "short_name": "END"},
            ],
        },
    }
    session = FakeSession()
    decoded_names = iter(["2t", "2d", "10u", "10v"])

    def fake_decoder(payload, include_btv_coverage=False):
        decoded = {
            "short_name": next(decoded_names),
            "finite_value_count": 10,
            "data_date": 20261112,
            "data_time": 2300,
        }
        if include_btv_coverage:
            decoded["btv_coverage"] = {"points_inside_domain": 3}
        return decoded

    report = run_smoke(
        {"models": {"RRFS": {"latest_products": [product]}}},
        session,
        message_limit=4,
        decoder=fake_decoder,
    )

    assert report["status"] == "passed"
    assert report["publication"] is False
    assert report["messages_verified"] == 4
    assert report["bytes_downloaded"] == 400
    assert [message["decoded"]["short_name"] for message in report["messages"]] == [
        "2t", "2d", "10u", "10v"
    ]
    assert report["btv_coverage"]["points_inside_domain"] == 3
    assert len(session.calls) == 4


def test_plan_index_ranges_selects_standard_fields_by_index_name():
    messages = [
        {"byte_offset": 0, "short_name": "REFC"},
        {"byte_offset": 100, "short_name": "TMP"},
        {"byte_offset": 250, "short_name": "DPT"},
        {"byte_offset": 500, "short_name": "UGRD"},
        {"byte_offset": 700, "short_name": "VGRD"},
        {"byte_offset": 900, "short_name": "END"},
    ]

    planned = plan_index_ranges(
        messages,
        limit=4,
        preferred_short_names=("TMP", "DPT", "UGRD", "VGRD"),
    )

    assert [item["short_name"] for item in planned] == ["TMP", "DPT", "UGRD", "VGRD"]
    assert [(item["start"], item["end"]) for item in planned] == [
        (100, 249), (250, 499), (500, 699)
    ]


def test_plan_index_ranges_rejects_missing_preferred_field():
    messages = [
        {"byte_offset": 0, "short_name": "TMP"},
        {"byte_offset": 100, "short_name": "UGRD"},
        {"byte_offset": 200, "short_name": "VGRD"},
    ]

    with pytest.raises(ValueError, match="missing required smoke-test fields: DPT"):
        plan_index_ranges(messages, preferred_short_names=("TMP", "DPT", "UGRD"))


def test_validate_decoded_cycle_checks_reference_date_and_time():
    from mesoscale.rrfs_range_smoke import validate_decoded_cycle

    validate_decoded_cycle(
        {"data_date": 20261112, "data_time": 2300},
        "20261112T23:00:00Z",
    )
    validate_decoded_cycle(
        {"data_date": 20261112, "data_time": 2300},
        "2026-11-12T23:00:00Z",
    )
    with pytest.raises(RuntimeError, match="reference time mismatch"):
        validate_decoded_cycle(
            {"data_date": 20261112, "data_time": 2200},
            "2026-11-12T23:00:00Z",
        )



def test_summarize_btv_coverage_normalizes_longitudes_and_counts_domain_points():
    coverage = summarize_btv_coverage(
        [42.0, 43.0, 44.0, 45.5, 44.5, 44.0],
        [285.0, 285.5, 288.7, 287.0, 289.0, 286.0],
    )

    assert coverage["grid_points"] == 6
    assert coverage["points_inside_domain"] == 3
    assert coverage["fraction_inside_domain"] == 0.5
    assert coverage["bounds"]["south"] == 43.0
    assert coverage["bounds"]["north"] == 44.0
    assert coverage["bounds"]["west"] == pytest.approx(-74.5)
    assert coverage["bounds"]["east"] == pytest.approx(-71.3)


def test_summarize_btv_coverage_rejects_mismatched_or_empty_coordinates():
    with pytest.raises(ValueError, match="equal lengths"):
        summarize_btv_coverage([44.0, 45.0], [286.0])
    with pytest.raises(ValueError, match="equal lengths"):
        summarize_btv_coverage([], [])


def test_summarize_btv_coverage_rejects_grid_outside_btv_domain():
    with pytest.raises(RuntimeError, match="does not intersect"):
        summarize_btv_coverage([35.0, 36.0], [280.0, 281.0])


def test_plan_index_ranges_rejects_limit_that_omits_required_wind_component():
    messages = [
        {"byte_offset": 0, "short_name": "TMP"},
        {"byte_offset": 100, "short_name": "DPT"},
        {"byte_offset": 200, "short_name": "UGRD"},
        {"byte_offset": 300, "short_name": "VGRD"},
        {"byte_offset": 400, "short_name": "END"},
    ]

    with pytest.raises(ValueError, match="cannot include all 4 required fields"):
        plan_index_ranges(
            messages,
            limit=3,
            preferred_short_names=("TMP", "DPT", "UGRD", "VGRD"),
        )


def test_plan_index_ranges_requires_both_wind_components():
    messages = [
        {"byte_offset": 0, "short_name": "TMP"},
        {"byte_offset": 100, "short_name": "DPT"},
        {"byte_offset": 200, "short_name": "UGRD"},
        {"byte_offset": 300, "short_name": "END"},
    ]

    with pytest.raises(ValueError, match="missing required smoke-test fields: VGRD"):
        plan_index_ranges(
            messages,
            limit=4,
            preferred_short_names=("TMP", "DPT", "UGRD", "VGRD"),
        )
