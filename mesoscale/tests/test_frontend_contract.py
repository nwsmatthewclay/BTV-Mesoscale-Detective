from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_github_pages_entry_points_are_byte_identical():
    assert (ROOT / "index.html").read_bytes() == (ROOT / "mesoscale.html").read_bytes()


def test_time_evolution_uses_cycle_and_hour_validated_station_archive():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="trendParameter"' in html
    assert 'id="trendStatus"' in html
    assert "async function loadRapStationCollection" in html
    assert "collection.model_cycle_utc!==rapForecastManifest.model_cycle_utc" in html
    assert "Number(collection.forecast_hour)!==Number(hour)" in html
    assert "async function updateRapTimeEvolution" in html
    assert "diagnostics[document.getElementById('trendParameter').value]" in html
    assert "Custom map points are not filled with a nearby station." in html


def test_inline_dashboard_javascript_parses_with_node_when_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)
    inline = next((script for script in reversed(scripts) if script.strip()), None)
    assert inline is not None, "Dashboard inline JavaScript was not found"
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(inline)
        path = handle.name
    try:
        result = subprocess.run([node, "--check", path], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
    finally:
        Path(path).unlink(missing_ok=True)


def test_model_discovery_orchestrates_rap_and_hrrr_ingestion_and_pages():
    discovery = (ROOT / ".github" / "workflows" / "mesoscale_model_discovery.yml").read_text(encoding="utf-8")
    rap = (ROOT / ".github" / "workflows" / "rap_ingestion_smoke.yml").read_text(encoding="utf-8")
    hrrr = (ROOT / ".github" / "workflows" / "hrrr_ingestion_smoke.yml").read_text(encoding="utf-8")

    # The scheduled ingestion orchestrator refreshes discovery before RAP selection.
    assert 'cron: "47 * * * *"' in rap
    assert "schedule:" not in discovery
    # Discovery must not share a concurrency group with the downstream RAP
    # workflow_run job; otherwise the queued child can cancel its parent.
    assert "group: mesoscale-model-discovery" in discovery
    assert "group: mesoscale-data-updates" in rap
    assert "if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'" in rap
    assert "if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'" in hrrr
    assert '"mesoscale/build_rap_forecast_archive.py"' in discovery
    assert '"mesoscale/download_subset.py"' in discovery
    assert '"mesoscale/data/model_manifest.json"' in discovery
    assert 'workflows: ["Mesoscale Model Discovery and Validation"]' in rap
    assert "if: github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'" in rap
    assert 'workflows: ["RAP BTV Ingestion and Forecast Archive"]' in hrrr
    assert "schedule:" not in hrrr

    discover = rap.index("python mesoscale/discover_models.py --days-back 2 --index-latest")
    manual_refresh = rap.index("if: github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'")
    validate = rap.index("python mesoscale/validate_rap_ingestion.py")
    archive = rap.index("python mesoscale/build_rap_forecast_archive.py")
    assert manual_refresh < discover < validate < archive

    assert "manifest_changed:" in discovery
    assert "needs.discover.outputs.manifest_changed == 'true'" in discovery
    assert 'echo "changed=true"' in discovery
    assert "actions/deploy-pages@v4" in discovery
    assert "archive_needs_update" in rap
    assert "steps.freshness.outputs.needs_update == 'true'" in rap
    assert "needs.rap-ingestion.outputs.published == 'true'" in rap
    assert "needs.rap-ingestion.outputs.manifest_changed == 'true'" in rap
    assert "archive_needs_update" in hrrr
    assert "needs.hrrr-smoke.outputs.needs_update == 'true'" in hrrr


def test_rap_grid_payload_must_match_the_published_archive_cycle():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "payload.model!=='RAP'" in html
    assert "payload.model_cycle_utc!==rapForecastManifest.model_cycle_utc" in html

def test_forecast_hour_slider_snaps_to_published_hours_and_shows_cycle_age():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "function updateRapArchiveFreshness()" in html
    assert "ageMinutes>=120?'var(--amber)':'var(--green)'" in html
    start = html.index("document.getElementById('hour').addEventListener('input'")
    end = html.index("document.getElementById('hour').addEventListener('change'", start)
    handler = html[start:end]
    assert "nearestAvailableRapHour(Number(slider.value))" in handler
    assert "slider.value=String(h)" in handler


def test_verified_hrrr_surface_archive_is_model_aware_and_keeps_profiles_rap_only():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<option value="HRRR">HRRR · 3 km · surface archive</option>' in html
    assert "async function loadHrrrForecastManifest" in html
    assert "async function loadHrrrGrid" in html
    assert "function renderHrrrGridOverlay" in html
    assert "payload.model_cycle_utc!==hrrrForecastManifest.model_cycle_utc" in html
    assert "nearestAvailableHrrrHour(Number(slider.value))" in html
    assert "Cross-sections require RAP hybrid-level profiles" in html
    assert "HRRR surface grids have no vertical profiles" in html
    for parameter in ("hrrr_temp", "hrrr_dewpoint", "hrrr_wind", "hrrr_gust", "hrrr_refc", "hrrr_vis", "hrrr_cin", "hrrr_blh"):
        assert f'value="{parameter}"' in html

    renderer_start = html.index("function renderHrrrGridOverlay")
    renderer_end = html.index("async function updateRapParameter", renderer_start)
    renderer = html[renderer_start:renderer_end]
    for mapping in (
        "hrrr_temp:{names:['2t']",
        "hrrr_dewpoint:{names:['2d']",
        "hrrr_gust:{names:['gust']",
        "hrrr_refc:{names:['refc']",
        "hrrr_vis:{names:['vis']",
        "hrrr_cin:{names:['cin']",
        "hrrr_blh:{names:['blh']",
        "const uField=findHrrrField(payload,['10u'])",
        "const vField=uField&&findHrrrField(payload,['10v'],uField.grid_id)",
    ):
        assert mapping in renderer
