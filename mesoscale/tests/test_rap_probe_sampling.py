from mesoscale import probe_rap_projection as probe
from mesoscale.process_grib import RAP_MAX_GRID_DIM


def test_projection_probe_uses_production_rap_sampling_cap(monkeypatch, tmp_path):
    captured = {}

    def fake_process_file(path, model, cycle, forecast_hour, output, max_grid_dim):
        captured.update({
            "model": model,
            "cycle": cycle,
            "forecast_hour": forecast_hour,
            "max_grid_dim": max_grid_dim,
        })
        return {"processing": {"max_grid_dim": max_grid_dim}}

    monkeypatch.setattr(probe, "process_file", fake_process_file)

    payload = probe.decode_probe_product(
        tmp_path / "rap.grib2",
        "2026-11-13T14:00:00Z",
        tmp_path / "rap.json.gz",
    )

    assert captured == {
        "model": "RAP",
        "cycle": "2026-11-13T14:00:00Z",
        "forecast_hour": 0,
        "max_grid_dim": RAP_MAX_GRID_DIM,
    }
    assert payload["processing"]["max_grid_dim"] == RAP_MAX_GRID_DIM
