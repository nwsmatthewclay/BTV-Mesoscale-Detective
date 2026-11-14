from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]



def test_hourly_model_refresh_is_owned_by_discovery_and_triggers_one_rap_check():
    rap = (ROOT / ".github/workflows/rap_ingestion_smoke.yml").read_text(encoding="utf-8")
    discovery = (ROOT / ".github/workflows/mesoscale_model_discovery.yml").read_text(encoding="utf-8")

    schedule_start = discovery.index("  schedule:")
    schedule_end = discovery.index("  workflow_dispatch:", schedule_start)
    paths_start = discovery.index("    paths:")
    paths_end = discovery.index("  schedule:", paths_start)
    schedule = discovery[schedule_start:schedule_end]
    paths = discovery[paths_start:paths_end]

    assert '    - cron: "17 * * * *"' in schedule
    assert "mesoscale/data/model_manifest.json" not in paths
    assert "  schedule:" not in rap
    assert '    workflows: ["Mesoscale Model Discovery and Validation"]' in rap
    assert "    types: [completed]" in rap
    assert "    branches: [main]" in rap
    assert "if: github.event_name == 'workflow_dispatch'" in rap
    assert "github.event_name == 'schedule'" not in rap

    # RAP no longer owns a Pages deployment or job outputs; it only evaluates
    # freshness and publishes a verified archive for the downstream HRRR run.
    assert "manifest_changed" not in rap
    assert "outputs:" not in rap
    assert "deploy-pages:" not in rap
    assert "pages: write" not in rap
    assert "id-token: write" not in rap


def test_pages_deployments_are_serialized_and_use_attempt_scoped_artifacts():
    def assert_attempt_scoped_deployment(workflow, job_name):
        marker = f"  {job_name}:\n"
        assert marker in workflow, f"missing Pages deployment job {job_name}"
        deploy = workflow.split(marker, 1)[1]
        # Discovery/tile scope concurrency at the job; the standalone
        # site workflow declares it at workflow scope.
        assert "group: github-pages" in workflow
        assert "cancel-in-progress: false" in workflow
        assert "name: Wait for GitHub Pages artifact metadata" in deploy
        assert "run: sleep 10" in deploy

        upload = deploy.split("uses: actions/upload-pages-artifact@v5", 1)[1].split(
            "\n      - name:", 1
        )[0]
        deploy_step = deploy.split("uses: actions/deploy-pages@v5", 1)[1]
        artifact_name = "github-pages-${{ github.run_id }}-${{ github.run_attempt }}"
        assert f"name: {artifact_name}" in upload
        assert f"artifact_name: {artifact_name}" in deploy_step

    # Only discovery metadata and the final, browser-gated tile publication
    # deploy Pages. RAP and HRRR publish data commits, not intermediate sites.
    for filename in ("rap_ingestion_smoke.yml", "hrrr_ingestion_smoke.yml"):
        workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        assert "deploy-pages:" not in workflow
        assert "upload-pages-artifact" not in workflow
        assert "actions/deploy-pages@" not in workflow

    for filename, job_name in (
        ("mesoscale_model_discovery.yml", "deploy-pages"),
        ("model_tile_render.yml", "deploy-pages"),
        ("deploy_pages.yml", "deploy"),
    ):
        workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
        assert_attempt_scoped_deployment(workflow, job_name)

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
    assert "!mesoscale/tests/**" in paths
    assert ".github/workflows/deploy_pages.yml" not in paths
    assert "  workflow_run:" not in standalone

def test_tile_deployment_runs_only_when_catalog_changes_or_is_manually_requested():
    tile = (ROOT / ".github/workflows/model_tile_render.yml").read_text(encoding="utf-8")
    render_job = tile.split("  render-and-publish:\n", 1)[1].split("\n  deploy-pages:\n", 1)[0]
    assert "changed: ${{ steps.publish.outputs.changed }}" in render_job
    publish = render_job.split("      - name: Publish tile archive\n", 1)[1]
    assert 'echo "changed=false" >> "$GITHUB_OUTPUT"' in publish
    assert 'echo "changed=true" >> "$GITHUB_OUTPUT"' in publish

    deploy = tile.split("  deploy-pages:\n", 1)[1]
    assert "needs.render-and-publish.outputs.changed == 'true'" in deploy
    assert "github.event_name == 'workflow_dispatch'" in deploy

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

def test_model_discovery_does_not_run_for_test_only_changes():
    discovery = (ROOT / ".github/workflows/mesoscale_model_discovery.yml").read_text(encoding="utf-8")
    paths = discovery.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]

    assert "mesoscale/tests/**" not in paths
    assert "mesoscale/hrrr_tests/**" not in paths
    assert "mesoscale/build_rap_forecast_archive.py" in paths
    assert "mesoscale/validate_hrrr_archive.py" in paths
    assert "pytest -q mesoscale/tests mesoscale/hrrr_tests" in discovery


def test_rap_freshness_decision_is_archived_after_every_successful_check():
    rap = (ROOT / ".github/workflows/rap_ingestion_smoke.yml").read_text(encoding="utf-8")
    freshness = rap.split(
        "- name: Check whether a newer complete RAP cycle needs publication", 1
    )[1].split("- name: Download and decode current RAP hybrid-level product", 1)[0]
    upload = rap.split(
        "- name: Upload RAP freshness and ingestion report", 1
    )[1].split("\n\n  deploy-pages:", 1)[0]

    assert "build_rap_freshness_report" in freshness
    assert "rap-freshness-report.json" in freshness
    assert "steps.freshness.outcome == 'success'" in upload
    assert "${{ runner.temp }}/rap-freshness-report.json" in upload
    assert "rap-ingestion-report-${{ github.run_id }}-${{ github.run_attempt }}" in upload
    assert "retention-days: 7" in upload



def test_workflows_use_node24_compatible_action_majors():
    expected_versions = {
        "checkout": "v5",
        "setup-python": "v6",
        "setup-miniconda": "v4",
        "upload-artifact": "v7",
        "download-artifact": "v7",
        "configure-pages": "v6",
        "upload-pages-artifact": "v5",
        "deploy-pages": "v5",
    }
    workflow_root = ROOT / ".github" / "workflows"
    workflow_files = sorted(workflow_root.glob("*.yml")) + sorted(workflow_root.glob("*.yaml"))
    assert workflow_files, "expected GitHub Actions workflow files"

    for workflow_path in workflow_files:
        workflow = workflow_path.read_text(encoding="utf-8")
        for action, expected in expected_versions.items():
            namespace = "conda-incubator" if action == "setup-miniconda" else "actions"
            pattern = rf"uses:\s*{re.escape(namespace)}/{action}@(v\d+)"
            versions = re.findall(pattern, workflow)
            assert all(version == expected for version in versions), (
                f"{workflow_path.relative_to(ROOT)} uses actions/{action} versions {versions}; "
                f"expected {expected}"
            )



def test_standalone_pages_deploy_triggers_only_for_browser_assets_and_published_model_data():
    workflow = (ROOT / ".github/workflows/deploy_pages.yml").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    paths = workflow.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]

    assert '"index.html"' in paths
    assert '"mesoscale.html"' in paths
    assert '"mesoscale/data/**"' in paths
    assert '"!mesoscale/data/model_tiles/**"' in paths
    assert '"mesoscale/**"' not in paths
    assert "mesoscale/diagnostics.py" not in paths

    # Browser-loaded model manifests and native grids live under this data root.
    assert "fetch('./mesoscale/data/model_manifest.json" in html
    assert "fetch('./mesoscale/data/fields/forecast/forecast_manifest.json" in html
    assert "fetch('./mesoscale/data/fields/hrrr/hrrr_forecast_manifest.json" in html
