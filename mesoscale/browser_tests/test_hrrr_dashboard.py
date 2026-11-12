from playwright.sync_api import sync_playwright


def _select_and_wait_for_hour(page, model, entry):
    hour = int(entry["forecast_hour"])
    payload_name = "hrrrGridPayload" if model == "HRRR" else "rapGridPayload"
    page.locator("#hour").evaluate(
        """(element, value) => {
            element.value = String(value);
            element.dispatchEvent(new Event("input", { bubbles: true }));
            element.dispatchEvent(new Event("change", { bubbles: true }));
        }""",
        hour,
    )
    page.wait_for_function(
        """expected => {
            const payload = window[expected.payloadName];
            const label = document.querySelector("#mapChip")?.textContent || "";
            return payload
                && Number(payload.forecast_hour) === expected.hour
                && payload.valid_time_utc === expected.validTime
                && label.includes("F" + String(expected.hour).padStart(2, "0"));
        }""",
        arg={
            "payloadName": payload_name,
            "hour": hour,
            "validTime": entry["valid_time_utc"],
        },
        timeout=30000,
    )


def test_hrrr_surface_parameter_and_all_forecast_hours():
    page_errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())

        page.goto("http://127.0.0.1:8765/", wait_until="domcontentloaded")
        archives = page.evaluate(
            """async () => {
                const load = async path => {
                    const response = await fetch(path);
                    if (!response.ok) throw new Error(path + " HTTP " + response.status);
                    return response.json();
                };
                return {
                    rap: await load("./mesoscale/data/fields/forecast/forecast_manifest.json"),
                    hrrr: await load("./mesoscale/data/fields/hrrr/hrrr_forecast_manifest.json")
                };
            }"""
        )
        rap = archives["rap"]
        hrrr = archives["hrrr"]
        assert rap["model"] == "RAP" and rap["quality"]["status"] == "passed"
        assert hrrr["model"] == "HRRR" and hrrr["quality"]["status"] == "passed"
        assert len(rap["hours"]) >= 4
        assert len(rap["hours"]) == len(hrrr["hours"])
        assert [entry["valid_time_utc"] for entry in rap["hours"]] == [
            entry["valid_time_utc"] for entry in hrrr["hours"]
        ]

        # Keep the browser's asynchronously loaded archive manifests distinct
        # from the direct test fetches above. The first grid request can briefly
        # use the single-hour fallback while the archive manifests initialize.
        page.evaluate("(manifest) => { window.__testRapManifest = manifest; }", rap)
        page.evaluate("(manifest) => { window.__testHrrrManifest = manifest; }", hrrr)

        # Force the initial RAP request and wait until it is the archived cycle,
        # not the temporary latest-grid fallback.
        page.locator("#parameter").select_option("cape")
        page.wait_for_function(
            """() => window.rapGridPayload
                && window.rapGridPayload.model === "RAP"
                && window.rapGridPayload.model_cycle_utc === window.__testRapManifest.model_cycle_utc
                && window.rapGridPayload.valid_time_utc === window.__testRapManifest.hours[0].valid_time_utc""",
            timeout=45000,
        )
        for entry in rap["hours"]:
            _select_and_wait_for_hour(page, "RAP", entry)
            assert page.evaluate(
                """expected => window.rapGridPayload.model_cycle_utc === expected.cycle
                    && Number(window.rapGridPayload.forecast_hour) === expected.hour
                    && window.rapGridPayload.valid_time_utc === expected.validTime""",
                {
                    "cycle": rap["model_cycle_utc"],
                    "hour": int(entry["forecast_hour"]),
                    "validTime": entry["valid_time_utc"],
                },
            ), f"RAP F{entry['forecast_hour']:02d} payload must match its manifest"

        # Switching models must retain the last selected RAP valid time.
        initial_hrrr_valid_time = rap["hours"][-1]["valid_time_utc"]
        page.evaluate(
            "(value) => { window.__testInitialHrrrValidTime = value; }",
            initial_hrrr_valid_time,
        )
        page.locator("#model").select_option("HRRR")
        page.wait_for_function(
            """() => window.hrrrGridPayload
                && window.hrrrGridPayload.model === "HRRR"
                && window.hrrrGridPayload.model_cycle_utc === window.__testHrrrManifest.model_cycle_utc
                && window.hrrrGridPayload.valid_time_utc === window.__testInitialHrrrValidTime""",
            timeout=30000,
        )
        assert page.locator("#parameter").input_value() == "hrrr_temp"
        assert "HRRR 2-m temperature" in page.locator("#mapChip").inner_text()
        assert page.locator("#gridSpacing").text_content().strip() == "3 km nominal"

        for entry in hrrr["hours"]:
            _select_and_wait_for_hour(page, "HRRR", entry)
            assert page.evaluate(
                """expected => window.hrrrGridPayload.model_cycle_utc === expected.cycle
                    && Number(window.hrrrGridPayload.forecast_hour) === expected.hour
                    && window.hrrrGridPayload.valid_time_utc === expected.validTime""",
                {
                    "cycle": hrrr["model_cycle_utc"],
                    "hour": int(entry["forecast_hour"]),
                    "validTime": entry["valid_time_utc"],
                },
            ), f"HRRR F{entry['forecast_hour']:02d} payload must match its manifest"

        page.locator("#parameter").select_option("hrrr_wind")
        page.wait_for_function(
            "() => document.querySelector('#mapChip').textContent.includes('10-m wind speed')",
            timeout=15000,
        )
        last_hrrr_hour = int(hrrr["hours"][-1]["forecast_hour"])
        assert f"F{last_hrrr_hour:02d}" in page.locator("#mapChip").inner_text()

        # Switching back to RAP must also preserve the selected valid time.
        page.locator("#model").select_option("RAP")
        last_rap_entry = rap["hours"][-1]
        page.wait_for_function(
            """expected => window.rapGridPayload
                && window.rapGridPayload.model === "RAP"
                && Number(window.rapGridPayload.forecast_hour) === expected.hour
                && window.rapGridPayload.valid_time_utc === expected.validTime
                && document.querySelector("#mapChip").textContent.includes("RAP")""",
            arg={
                "hour": int(last_rap_entry["forecast_hour"]),
                "validTime": last_rap_entry["valid_time_utc"],
            },
            timeout=30000,
        )
        assert page.locator("#gridSpacing").text_content().strip() == "13 km nominal"
        for entry in rap["hours"]:
            _select_and_wait_for_hour(page, "RAP", entry)

        browser.close()

    assert not page_errors, "Uncaught browser errors: " + "; ".join(page_errors)
