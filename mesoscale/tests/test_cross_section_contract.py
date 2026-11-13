from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_regional_rap_profile_serializes_grid_id_from_local_variable():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "distance_km:pt.d,grid_id:gridId,sampling_method:'nearest RAP grid point'" in html
    assert "distance_km:pt.d,grid_id,sampling_method:'nearest RAP grid point'" not in html.replace(
        "distance_km:pt.d,grid_id:gridId,sampling_method:'nearest RAP grid point'", ""
    )
