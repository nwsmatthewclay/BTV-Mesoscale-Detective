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


def test_pages_deployments_are_serialized_and_wait_for_artifact_metadata():
    workflow_jobs = (
        ("rap_ingestion_smoke.yml", "deploy-pages"),
        ("hrrr_ingestion_smoke.yml", "deploy-pages"),
        ("mesoscale_model_discovery.yml", "deploy-pages"),
    )
    for filename, job_name in workflow_jobs:
        workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        deploy = workflow.split(f"  {job_name}:\n", 1)[1]
        assert "group: github-pages" in deploy
        assert "cancel-in-progress: false" in deploy
        assert "name: Wait for GitHub Pages artifact metadata" in deploy
        assert "run: sleep 10" in deploy

    standalone = (ROOT / ".github/workflows/deploy_pages.yml").read_text(encoding="utf-8")
    assert "group: github-pages" in standalone
    assert "name: Wait for GitHub Pages artifact metadata" in standalone
    assert "run: sleep 10" in standalone


def test_hrRR_browser_smoke_is_independent_of_pages_deployment():
    hrrr = (ROOT / ".github/workflows/hrrr_ingestion_smoke.yml").read_text(encoding="utf-8")
    browser = (ROOT / ".github/workflows/mesoscale_browser_smoke.yml").read_text(encoding="utf-8")

    assert "  browser-smoke:\n    needs: [hrrr-smoke, publish-hrrr]" in hrrr
    assert "needs.hrrr-smoke.result == 'success'" in hrrr
    assert "needs.publish-hrrr.result == 'skipped'" in hrrr
    assert "pytest -q mesoscale/browser_tests" in hrrr
    assert "  workflow_run:" not in browser
