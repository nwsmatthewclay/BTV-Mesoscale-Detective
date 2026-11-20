from pathlib import Path
import gzip
import tempfile

from portable_sharppy.bufkit_archive import parse_headers, scan_archive

SAMPLE = """STID = KBTV
TIME = 261120/1200
STIM = 3.0
"""

def test_parse_bufkit_headers_extracts_cycle_station_and_lead():
    records = parse_headers(SAMPLE)
    assert len(records) == 1
    assert records[0]["station"] == "KBTV"
    assert records[0]["forecast_hour"] == 3
    assert records[0]["cycle_utc"].strftime("%Y%m%d%H") == "26112009"

def test_scan_archive_handles_plain_and_gzip_files():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        model_dir = root / "RAP"
        model_dir.mkdir()
        (model_dir / "rap_kbtv.buf").write_text(SAMPLE, encoding="latin-1")
        with gzip.open(model_dir / "hrrr_kmpv.buf.gz", "wt", encoding="latin-1") as stream:
            stream.write(SAMPLE.replace("KBTV", "KMPV"))
        result = scan_archive(root)
        assert result["available"]
        assert result["file_count_scanned"] == 2
        assert result["record_count"] == 2
        assert set(result["stations"]) == {"KBTV", "KMPV"}
        assert set(result["models"]) == {"RAP", "HRRR"}
        assert result["forecast_hours"] == [3.0]
