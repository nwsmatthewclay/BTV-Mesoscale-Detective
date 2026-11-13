import pytest

from mesoscale.download_subset import download


@pytest.mark.parametrize(
    ("cycle", "expected_hour"),
    [
        ("20261112T15:00:00Z", "15"),
        ("2026-11-12T15:00:00Z", "15"),
        ("2026-11-12T10:00:00-05:00", "15"),
    ],
)
def test_download_filename_normalizes_cycle_timestamp_to_utc(tmp_path, cycle, expected_hour):
    product = {
        "model": "HRRR",
        "date": "20261112",
        "cycle_utc": cycle,
        "forecast_hour": 0,
        "product": "surface",
        "filename": "hrrr.t15z.wrfsfcf00.grib2",
        "url": "https://example.test/hrrr.grib2",
    }

    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"GRIB" + b"x" * 1000

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    result = download(FakeSession(), "HRRR", product, tmp_path)
    assert result["file"].endswith(f"hrrr_20261112_{expected_hour}_f00_btv.grib2")
