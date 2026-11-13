import json
from pathlib import Path

import numpy as np
import pytest

import mesoscale.rrfs_btv_subset as subset


def make_decoded(name, values, lat, lon, step="15m"):
    aliases = {"TMP": "2t", "DPT": "2d", "UGRD": "10u", "VGRD": "10v"}
    return {
        "metadata": {
            "short_name": aliases[name], "type_of_level": "heightAboveGround",
            "level": 2 if name in ("TMP", "DPT") else 10,
            "units": "K" if name in ("TMP", "DPT") else "m s-1",
            "data_date": 20261113, "data_time": 100, "step_range": step,
            "grid_type": "lambert", "ni": 2, "nj": 2, "number_of_points": 4,
            "i_scans_negatively": 0, "j_scans_positively": 1,
            "j_points_are_consecutive": 0, "alternative_row_scanning": 0,
        },
        "values": np.asarray(values, dtype=float),
        "latitudes": np.asarray(lat, dtype=float),
        "longitudes": np.asarray(lon, dtype=float),
    }


def product():
    return {
        "product": "surface_subhourly_3km",
        "cycle_utc": "20261113T01:00:00Z",
        "forecast_step": 1, "forecast_lead_minutes": 15,
        "filename": "rrfs.t01z.2dfld.3km.subh.f001.conus.grib2",
        "url": "https://example.test/rrfs.grib2",
        "index": {
            "url": "https://example.test/rrfs.grib2.idx",
            "messages": [
                {"message": "1", "byte_offset": 0, "short_name": "TMP"},
                {"message": "2", "byte_offset": 100, "short_name": "DPT"},
                {"message": "3", "byte_offset": 200, "short_name": "UGRD"},
                {"message": "4", "byte_offset": 300, "short_name": "VGRD"},
                {"message": "5", "byte_offset": 400, "short_name": "END"},
            ],
        },
    }


def decoded_fields(lat=None, lon=None, overrides=None):
    lat = lat or [44.0, 44.2, 45.4, 43.0]
    lon = lon or [-73.0, -72.5, -73.5, -76.0]
    overrides = overrides or {}
    result = []
    for name in subset.REQUIRED_FIELDS:
        values = overrides.get(name, [270.0, 271.0, 272.0, 273.0] if name in ("TMP", "DPT") else [2.0, 3.0, 4.0, 5.0])
        result.append({
            "index_short_name": name,
            "record": {"message": str(len(result) + 1), "start": len(result) * 100, "end": len(result) * 100 + 99, "bytes": 100},
            "decoded": make_decoded(name, values, lat, lon),
        })
    return result


def test_build_btv_subset_uses_common_finite_mask_and_preserves_fields():
    fields = decoded_fields(overrides={"VGRD": [5.0, float("nan"), 4.0, 5.0]})
    metadata, arrays = subset.build_btv_subset(product(), fields)
    assert metadata["publication"] is False
    assert metadata["subset_type"] == "unstructured_btv_domain_mask"
    assert metadata["forecast_lead_minutes"] == 15
    assert metadata["valid_time_utc"] == "2026-11-13T01:15:00Z"
    assert metadata["native_grid_point_count"] == 4
    assert metadata["btv_point_count"] == 1
    assert set(arrays) == {"latitudes", "longitudes", "TMP", "DPT", "UGRD", "VGRD"}
    assert arrays["latitudes"].tolist() == pytest.approx([44.0])
    assert arrays["longitudes"].tolist() == pytest.approx([-73.0])
    assert arrays["VGRD"].tolist() == pytest.approx([5.0])


def test_build_btv_subset_rejects_grid_mismatch():
    fields = decoded_fields()
    fields[-1]["decoded"]["metadata"]["ni"] = 3
    with pytest.raises(ValueError, match="grid metadata differs"):
        subset.build_btv_subset(product(), fields)


def test_build_btv_subset_rejects_coordinate_mismatch():
    fields = decoded_fields()
    fields[-1]["decoded"]["longitudes"][0] = -72.0
    with pytest.raises(ValueError, match="longitude grid differs"):
        subset.build_btv_subset(product(), fields)


def test_build_btv_subset_rejects_step_range_mismatch():
    fields = decoded_fields()
    fields[-1]["decoded"]["metadata"]["step_range"] = "30m"
    with pytest.raises(ValueError, match="stepRange values"):
        subset.build_btv_subset(product(), fields)


@pytest.mark.parametrize(
    ("field", "key", "value", "message"),
    [
        ("TMP", "level", 10, "must be at 2 m AGL"),
        ("UGRD", "type_of_level", "isobaricInhPa", "must be heightAboveGround"),
        ("VGRD", "units", "knots", "unexpected units"),
    ],
)
def test_build_btv_subset_rejects_wrong_level_or_units(field, key, value, message):
    fields = decoded_fields()
    target = next(item for item in fields if item["index_short_name"] == field)
    target["decoded"]["metadata"][key] = value
    with pytest.raises(ValueError, match=message):
        subset.build_btv_subset(product(), fields)


def test_build_btv_subset_rejects_missing_field():
    with pytest.raises(ValueError, match="requires fields in this order"):
        subset.build_btv_subset(product(), decoded_fields()[:-1])


def test_write_btv_subset_writes_npz_and_provenance(tmp_path):
    metadata, arrays = subset.build_btv_subset(product(), decoded_fields())
    files = subset.write_btv_subset(tmp_path, metadata, arrays)
    npz_path, json_path = Path(files["subset_file"]), Path(files["metadata_file"])
    assert npz_path.is_file() and npz_path.stat().st_size > 0
    assert json_path.is_file()
    with np.load(npz_path) as saved:
        assert saved["latitudes"].size == metadata["btv_point_count"]
        assert saved["TMP"].size == metadata["btv_point_count"]
        assert saved["VGRD"].size == metadata["btv_point_count"]
    sidecar = json.loads(json_path.read_text())
    assert sidecar["publication"] is False
    assert sidecar["model_cycle_utc"] == "2026-11-13T01:00:00Z"


def test_extract_btv_subset_downloads_four_required_indexed_fields(monkeypatch):
    decoded = iter([item["decoded"] for item in decoded_fields()])
    downloaded = []

    def fake_fetch(session, url, record):
        downloaded.append(record["short_name"])
        return b"GRIBpayload7777"

    monkeypatch.setattr(subset, "fetch_indexed_message", fake_fetch)
    metadata, arrays = subset.extract_btv_subset(
        {"models": {"RRFS": {"latest_products": [product()]}}},
        session=object(),
        decoder=lambda payload: next(decoded),
    )
    assert downloaded == list(subset.REQUIRED_FIELDS)
    assert metadata["btv_point_count"] == 2
    assert metadata["valid_time_utc"] == "2026-11-13T01:15:00Z"
    assert arrays["TMP"].size == 2


def test_build_btv_subset_rejects_no_points_inside_domain():
    fields = decoded_fields(
        lat=[30.0, 31.0, 32.0, 33.0],
        lon=[-73.0, -72.5, -73.5, -74.0],
    )
    with pytest.raises(RuntimeError, match="No common finite RRFS grid points"):
        subset.build_btv_subset(product(), fields)
