from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_regional_rap_profile_serializes_grid_id_from_local_variable():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    expected = "distance_km:pt.d,grid_id:gridId,sampling_method:'nearest published RAP grid point'"
    assert expected in html
    assert html.count(expected) == 1
