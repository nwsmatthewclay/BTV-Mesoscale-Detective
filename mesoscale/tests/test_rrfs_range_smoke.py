import pytest

from mesoscale.rrfs_range_smoke import (
    fetch_indexed_message,
    plan_index_ranges,
    run_smoke,
    select_rrfs_product,
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
        "cycle_utc": "2026-11-12T23:00:00Z",
        "forecast_step": 1,
        "forecast_lead_minutes": 15,
        "filename": filename,
        "url": f"https://example.test/{filename}",
        "index": {
            "url": f"https://example.test/{filename}.idx",
            "message_count": 3,
            "messages": [
                {"message": "1", "byte_offset": 0, "short_name": "REFC"},
                {"message": "2", "byte_offset": 100, "short_name": "VIL"},
                {"message": "3", "byte_offset": 200, "short_name": "VIS"},
                {"message": "4", "byte_offset": 300, "short_name": "TMP"},
            ],
        },
    }
    session = FakeSession()
    decoded_names = iter(["refc", "vil", "vis"])

    report = run_smoke(
        {"models": {"RRFS": {"latest_products": [product]}}},
        session,
        message_limit=3,
        decoder=lambda payload: {"short_name": next(decoded_names), "finite_value_count": 10},
    )

    assert report["status"] == "passed"
    assert report["publication"] is False
    assert report["messages_verified"] == 3
    assert report["bytes_downloaded"] == 300
    assert [message["decoded"]["short_name"] for message in report["messages"]] == [
        "refc", "vil", "vis"
    ]
    assert len(session.calls) == 3
