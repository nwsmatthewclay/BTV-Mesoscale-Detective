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
