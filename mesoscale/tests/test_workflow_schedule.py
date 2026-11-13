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


def test_pages_deployments_are_serialized_and_use_attempt_scoped_artifacts():
    workflow_jobs = (
        ("rap_ingestion_smoke.yml", "deploy-pages"),
        ("hrrr_ingestion_smoke.yml", "deploy-pages"),
        ("mesoscale_model_discovery.yml", "deploy-pages"),
        ("model_tile_render.yml", "deploy-pages"),
    )
    for filename, job_name in workflow_jobs:
        workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        deploy = workflow.split(f"  {job_name}:\n", 1)[1]
        assert "group: github-pages" in deploy
        assert "cancel-in-progress: false" in deploy
        assert "name: Wait for GitHub Pages artifact metadata" in deploy
        assert "run: sleep 10" in deploy
        upload = deploy.split("uses: actions/upload-pages-artifact@v3", 1)[1].split("\n      - name:", 1)[0]
        deploy_step = deploy.split("uses: actions/deploy-pages@v4", 1)[1]
        artifact_name = "github-pages-${{ github.run_id }}-${{ github.run_attempt }}"
        assert f"name: {artifact_name}" in upload
        assert f"artifact_name: {artifact_name}" in deploy_step

    standalone = (ROOT / ".github/workflows/deploy_pages.yml").read_text(encoding="utf-8")
    assert "group: github-pages" in standalone
    assert "name: Wait for GitHub Pages artifact metadata" in standalone
    assert "run: sleep 10" in standalone
    upload = standalone.split("uses: actions/upload-pages-artifact@v3", 1)[1].split("\n      - name:", 1)[0]
    deploy_step = standalone.split("uses: actions/deploy-pages@v4", 1)[1]
    artifact_name = "github-pages-${{ github.run_id }}-${{ github.run_attempt }}"
    assert f"name: {artifact_name}" in upload
    assert f"artifact_name: {artifact_name}" in deploy_step



def test_tile_workflow_owns_its_pages_deployment_without_duplicate_pushes():
    tile = (ROOT / ".github/workflows/model_tile_render.yml").read_text(encoding="utf-8")
    trigger = tile.split("  workflow_run:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert "      - HRRR BTV Surface Ingestion and Archive" in trigger
    assert "RAP BTV Ingestion and Forecast Archive" not in trigger
    assert "  deploy-pages:\n    needs: render-and-publish" in tile

    standalone = (ROOT / ".github/workflows/deploy_pages.yml").read_text(encoding="utf-8")
    paths = standalone.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert "!mesoscale/data/model_tiles/**" in paths
    assert "!mesoscale/render_model_tiles.py" in paths
    assert "!mesoscale/tests/test_model_tiles.py" in paths
    assert ".github/workflows/deploy_pages.yml" not in paths
    assert "  workflow_run:" not in standalone

def test_hrRR_browser_smoke_is_independent_of_pages_deployment():
    hrrr = (ROOT / ".github/workflows/hrrr_ingestion_smoke.yml").read_text(encoding="utf-8")
    browser = (ROOT / ".github/workflows/mesoscale_browser_smoke.yml").read_text(encoding="utf-8")

    assert "  browser-smoke:\n    needs: [hrrr-smoke, publish-hrrr]" in hrrr
    assert "needs.hrrr-smoke.result == 'success'" in hrrr
    assert "needs.publish-hrrr.result == 'skipped'" in hrrr
    assert "pytest -q mesoscale/browser_tests" in hrrr
    assert "  workflow_run:" not in browser

def test_hrrr_workflow_run_checks_out_latest_main_before_freshness_decision():
    hrrr = (ROOT / ".github/workflows/hrrr_ingestion_smoke.yml").read_text(encoding="utf-8")
    smoke_job = hrrr.split("  hrrr-smoke:\n", 1)[1].split("\n  publish-hrrr:\n", 1)[0]
    checkout = smoke_job.split("      - name: Check out latest repository state\n", 1)[1].split("      - name:", 1)[0]

    assert "          ref: main" in checkout
    assert smoke_job.index("          ref: main") < smoke_job.index(
        "name: Check whether a newer complete HRRR cycle needs publication"
    )
