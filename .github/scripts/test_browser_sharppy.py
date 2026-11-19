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
        if "BUFKIT archive catalog loaded" not in initial:
            raise RuntimeError("BUFKIT archive catalog did not load: " + initial)
        page.locator("#model").select_option("RRFS")
        page.locator("#station").select_option("KBTV")
        page.locator("#initEngine").click()
        page.wait_for_function(
            "() => { const s=document.querySelector('#runtimeStatus'); return s.dataset.state==='error' || s.innerText.includes('ConvectiveProfile passed'); }",
            timeout=300000,
        )
        engine_status = page.locator("#runtimeStatus").inner_text()
        print("ENGINE:", engine_status)
        if "ConvectiveProfile passed" not in engine_status:
            raise RuntimeError("Browser SHARPpy did not decode and diagnose archived BUFKIT: " + engine_status)
        profile_meta = page.locator("#profileMeta").inner_text()
        print("DECODED PROFILE:", profile_meta)
        if "RRFS BUFKIT" not in profile_meta or "SHARPpy BufDecoder" not in profile_meta:
            raise RuntimeError("Profile did not come from archived RRFS BUFKIT: " + profile_meta)
        parcel_traces = page.locator("#skewt").evaluate("(el) => (el.data || []).map(trace => trace.name)")
        print("SKEW-T TRACES:", parcel_traces)
        if not any(name in parcel_traces for name in ("SFC parcel", "ML parcel", "MU parcel")):
            raise RuntimeError("Native SHARPpy parcel ascent traces were not plotted: " + str(parcel_traces))
        page.locator("#temp").evaluate("(el) => { el.value='2'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
        page.wait_for_function(
            "() => document.querySelector('#calcStatus').innerText.includes('SHARPpy recalculated') || document.querySelector('#runtimeStatus').dataset.state==='error'",
            timeout=120000,
        )
        modified_status = page.locator("#calcStatus").inner_text()
        print("MODIFIED:", modified_status)
        if "SHARPpy recalculated" not in modified_status:
            raise RuntimeError("Modified profile was not recalculated: " + modified_status)
        for model in ("GFS", "RAP", "HRRR", "RRFS"):
            page.locator("#model").select_option(model)
            page.wait_for_function(
                "(m) => document.querySelector('#profileMeta').innerText.includes(m + ' BUFKIT') && document.querySelector('#runtimeStatus').innerText.includes('ConvectiveProfile passed')",
                arg=model,
                timeout=120000,
            )
            print("MODEL SHARPpy PASSED:", model, page.locator("#profileMeta").inner_text())
        print("BROWSER SHARPpy SMOKE TEST PASSED: all four BUFKIT models decoded and diagnosed")
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
        nsharp = browser.new_page(viewport={"width": 1600, "height": 1000})
        nsharp.on("pageerror", lambda error: print("NSHARP PAGE ERROR:", error))
        nsharp.goto(f"http://127.0.0.1:{PORT}/nsharp-web.html", wait_until="domcontentloaded", timeout=60000)
        nsharp.wait_for_function(
            "() => ['ready','error'].includes(document.querySelector('#runtimeStatus').dataset.state)",
            timeout=300000,
        )
        nsharp_status = nsharp.locator("#runtimeStatus").inner_text()
        print("NSHARP WEB:", nsharp_status)
        if "ConvectiveProfile passed" not in nsharp_status:
            raise RuntimeError("NSHARP web page did not initialize the actual SHARPpy engine: " + nsharp_status)
        for panel in ("skewt", "hodo", "parcelTable", "thermoTable", "kinTable", "severeTable"):
            if nsharp.locator("#" + panel).count() != 1:
                raise RuntimeError("NSHARP panel missing: " + panel)
        if nsharp.locator("#skewt .js-plotly-plot").count() != 1 or nsharp.locator("#hodo .js-plotly-plot").count() != 1:
            raise RuntimeError("NSHARP Skew-T or hodograph did not render")
        print("NSHARP WEB SMOKE TEST PASSED: actual SHARPpy, Skew-T, hodograph, and diagnostic panels")
        browser.close()
finally:
    server.terminate()
    server.wait(timeout=10)
