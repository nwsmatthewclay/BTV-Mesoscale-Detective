from pathlib import Path
import json
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
    assert "const metricKey=document.getElementById('trendParameter').value" in html
    assert "const value=diagnostics[metricKey]" in html
    assert "collection.valid_time_utc===validTime" in html
    assert "connectgaps:false" in html
    assert "Unavailable at '+unavailable.map(point=>" in html
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


def test_rap_cross_section_uses_selected_archive_hour_and_reports_effective_spacing():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "async function runRapCrossSection(points)" in html
    assert "const payload=await loadRapGrid(activeRapHour)" in html
    assert "function greatCircleTransect(start,end,count)" in html
    assert "const path=greatCircleTransect(points[0],points[1],samples+1)" in html
    assert "extractRegionalRapProfile(payload,probe.latitude,probe.longitude,'Transect '+i)" in html
    assert "function nativeGridSampleOffsetLimitKm(grid)" in html
    assert "function validateTransectSampleDistance(grid,point)" in html
    assert "validateTransectSampleDistance(payload.grids?.[point.grid_id],point)" in html
    assert "great-circle distance '+path.totalDistanceKm.toFixed(1)+' km" in html
    assert "transect columns passed profile QC" in html
    assert "transect columns passed profile QC" in html
    assert "sampled_grid_point:{latitude:pt.lat,longitude:pt.lon,distance_km:pt.d,grid_id:gridId" in html
    assert "await Plotly.react('crossSectionPlot'" in html
    assert "vertical interpolation to 250 m spacing only" in html
    assert "formatEffectiveGridSpacing(payload,sampledGridId)" in html
    assert "effective horizontal spacing '+effectiveSpacing" in html
    assert "no horizontal upscaling." in html
    assert "usable nearest-grid samples" in html


def test_model_comparison_requires_exact_shared_valid_time_and_samples_both_models():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="modelComparisonPanel"' in html
    assert "async function updateModelComparison()" in html
    assert "item.valid_time_utc===validTime" in html
    assert "rap.valid_time_utc!==validTime||hrrr.valid_time_utc!==validTime" in html
    assert "No exact shared valid time exists" in html
    assert "window.updateModelComparison=updateModelComparison" in html
    assert "comparableWind" in html
    assert "function findRapSurfaceField(payload,names,gridId)" in html
    assert "Nearest-cell offsets RAP " in html
    assert "Missing source fields or unsupported units remain Unavailable" in html
    assert "findRapSurfaceField(payload,['10v'],uField.grid_id)" in html


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


def test_rrfs_is_labeled_as_a_nonpublished_experimental_subset():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    config = json.loads((ROOT / "mesoscale" / "config" / "diagnostics.json").read_text(encoding="utf-8"))
    assert "RRFS · experimental · unverified" in html
    assert "RRFS · 3 km" not in html
    assert "RRFS EXPERIMENTAL" in html
    assert config["models"]["RRFS"]["status"] == "experimental_non_published_subset_multi_hour_archive_pending"


def test_automatic_browser_smoke_is_downstream_of_hrrr_alignment():
    standalone = (ROOT / ".github" / "workflows" / "mesoscale_browser_smoke.yml").read_text(encoding="utf-8")
    hrrr = (ROOT / ".github" / "workflows" / "hrrr_ingestion_smoke.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in standalone
    assert "push:" not in standalone
    assert "browser-smoke:" in hrrr
    assert "needs: [hrrr-smoke, publish-hrrr]" in hrrr
    assert "needs.hrrr-smoke.result == 'success'" in hrrr
    assert "needs.publish-hrrr.result == 'success' || needs.publish-hrrr.result == 'skipped'" in hrrr


def test_verified_hrrr_surface_archive_is_model_aware_and_keeps_profiles_rap_only():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<option value="HRRR">HRRR · surface archive</option>' in html
    assert "async function loadHrrrForecastManifest" in html
    assert "async function loadHrrrGrid" in html
    assert "function renderHrrrGridOverlay" in html
    assert "payload.model_cycle_utc!==hrrrForecastManifest.model_cycle_utc" in html
    assert "nearestAvailableHrrrHour(Number(slider.value))" in html
    assert "Cross-sections require RAP hybrid-level profiles" in html
    assert "HRRR surface grids have no vertical profiles" in html
    assert "updateGridSpacing(payload,'HRRR')" in html
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


def test_expanded_upstream_domain_and_dynamic_map_legends_are_wired():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    process = (ROOT / "mesoscale" / "process_grib.py").read_text(encoding="utf-8")
    subset = (ROOT / "mesoscale" / "download_subset.py").read_text(encoding="utf-8")
    assert 'fitBounds(REGIONAL_BOUNDS' in html
    assert 'id="mapLegend"' in html
    assert "function updateMapLegend(label,min,max,units" in html
    assert "updateMapLegend(field.long_name||shortName,range.min,range.max,field.units" in html
    assert "updateMapLegend(cfg.label,cfg.min,cfg.max,field.units||cfg.units)" in html
    assert "updateMapLegend(cfg.label,cfg.min,cfg.max,cfg.units)" in html
    assert '"west": -90.0, "east": -60.0, "south": 32.0, "north": 55.0' in process
    assert '"leftlon": -90.0, "rightlon": -60.0, "toplat": 55.0, "bottomlat": 32.0' in subset


def test_workstation_uses_valid_non_nested_main_structure_and_geometry_aware_fields():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<div class="app-shell layout">' in html
    assert html.count('<main class="layout">') == 1
    assert "body > .app-shell.layout > main.layout" in html
    assert "function hasMatchingGridGeometry(payload,field)" in html
    assert "const data=meta&&squeezeRap2D(meta.data)" in html
