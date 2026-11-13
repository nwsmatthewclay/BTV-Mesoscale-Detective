from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_regional_rap_profile_serializes_native_grid_identity_and_indices():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    expected = (
        "sampled_grid_point:{latitude:pt.lat,longitude:pt.lon,distance_km:pt.d,"
        "grid_id:gridId,y:pt.y,x:pt.x,sampling_method:'nearest RAP grid point'}"
    )
    assert expected in html
    assert "const gridId=profiles.find(Boolean).sampled_grid_point.grid_id" in html
