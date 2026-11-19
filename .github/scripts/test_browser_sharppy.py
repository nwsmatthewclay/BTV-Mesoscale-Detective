import os
import subprocess
import sys
import time
from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PORT = 8765
server = subprocess.Popen(
    [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    time.sleep(2)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.on("pageerror", lambda error: print("PAGE ERROR:", error))
        page.on("console", lambda message: print("BROWSER:", message.type, message.text) if message.type == "error" else None)
        page.goto(f"http://127.0.0.1:{PORT}/sounding-browser.html", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "() => ['ready','error'].includes(document.querySelector('#runtimeStatus').dataset.state)",
            timeout=120000,
        )
        initial = page.locator("#runtimeStatus").inner_text()
        print("ARCHIVE:", initial)
        if "Verified" not in initial and "Ready" not in initial:
            raise RuntimeError("Verified RAP profile did not load: " + initial)
        page.locator("#initEngine").click()
        page.wait_for_function(
            "() => { const s=document.querySelector('#runtimeStatus'); return s.dataset.state==='error' || s.innerText.includes('ConvectiveProfile passed'); }",
            timeout=300000,
        )
        engine_status = page.locator("#runtimeStatus").inner_text()
        print("ENGINE:", engine_status)
        if "ConvectiveProfile passed" not in engine_status:
            raise RuntimeError("Browser SHARPpy did not pass its baseline: " + engine_status)
        page.locator("#temp").evaluate("(el) => { el.value='2'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
        page.wait_for_function(
            "() => document.querySelector('#calcStatus').innerText.includes('SHARPpy recalculated') || document.querySelector('#runtimeStatus').dataset.state==='error'",
            timeout=120000,
        )
        modified_status = page.locator("#calcStatus").inner_text()
        print("MODIFIED:", modified_status)
        if "SHARPpy recalculated" not in modified_status:
            raise RuntimeError("Modified profile was not recalculated: " + modified_status)
        print("BROWSER SHARPpy SMOKE TEST PASSED")
        archive = browser.new_page()
        archive.goto(f"http://127.0.0.1:{PORT}/bufkit-archive.html", wait_until="domcontentloaded", timeout=60000)
        archive.wait_for_function(
            "() => document.querySelector('#status').innerText.includes('Catalog updated') || document.querySelector('#status').innerText.includes('Archive not populated')",
            timeout=60000,
        )
        archive_status = archive.locator("#status").inner_text()
        print("BUFKIT ARCHIVE:", archive_status)
        if "Catalog updated" not in archive_status:
            raise RuntimeError("BUFKIT archive catalog did not load: " + archive_status)
        model_count = archive.locator("#model option").count()
        if model_count != 4:
            raise RuntimeError(f"Expected four archived models, found {model_count}")
        archive.locator("#model").select_option("RRFS")
        archive.locator("#cycle").select_option(index=0)
        if archive.locator("#station option").count() != 32:
            raise RuntimeError("Expected all 32 BUFKIT stations in RRFS archive")
        print("BUFKIT ARCHIVE SMOKE TEST PASSED: four models, 32 RRFS stations")
        browser.close()
finally:
    server.terminate()
    server.wait(timeout=10)
