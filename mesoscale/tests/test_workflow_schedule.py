from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_hourly_model_refresh_is_owned_by_rap_ingestion():
    rap = (ROOT / ".github/workflows/rap_ingestion_smoke.yml").read_text(encoding="utf-8")
    discovery = (ROOT / ".github/workflows/mesoscale_model_discovery.yml").read_text(encoding="utf-8")

    assert '    - cron: "47 * * * *"' in rap
    assert "github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'" in rap
    assert "manifest_changed: ${{ steps.refresh.outputs.changed }}" in rap
    assert "needs.rap-ingestion.outputs.manifest_changed == 'true'" in rap
    assert "  schedule:" not in discovery
