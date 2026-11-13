from playwright.sync_api import sync_playwright


def _select_and_wait_for_hour(page, model, entry, cycle):
    hour = int(entry["forecast_hour"])
    payload_name = "hrrrGridPayload" if model == "HRRR" else "rapGridPayload"
    expected = {
        "payloadName": payload_name,
        "cycle": cycle,
        "hour": hour,
        "validTime": entry["valid_time_utc"],
    }
    current = page.evaluate(
        """expected => {
            const payload = window[expected.payloadName];
            const label = document.querySelector("#mapChip")?.textContent || "";
            return {
                matches: Boolean(payload)
                    && payload.model_cycle_utc === expected.cycle
                    && Number(payload.forecast_hour) === expected.hour
                    && payload.valid_time_utc === expected.validTime
                    && label.includes("F" + String(expected.hour).padStart(2, "0")),
                model: payload?.model,
                cycle: payload?.model_cycle_utc,
                hour: payload?.forecast_hour,
                validTime: payload?.valid_time_utc,
                mapChip: label,
                slider: document.querySelector("#hour")?.value,
                hourLabel: document.querySelector("#hourOut")?.textContent
            };
        }""",
        expected,
    )
    if current["matches"]:
        return

    page.locator("#hour").evaluate(
        """(element, value) => {
            element.value = String(value);
            element.dispatchEvent(new Event("input", { bubbles: true }));
            element.dispatchEvent(new Event("change", { bubbles: true }));
        }""",
        hour,
    )
    try:
        page.wait_for_function(
            """expected => {
                const payload = window[expected.payloadName];
                const label = document.querySelector("#mapChip")?.textContent || "";
                return payload
                    && payload.model_cycle_utc === expected.cycle
                    && Number(payload.forecast_hour) === expected.hour
                    && payload.valid_time_utc === expected.validTime
                    && label.includes("F" + String(expected.hour).padStart(2, "0"));
            }""",
            arg=expected,
            timeout=30000,
        )
    except Exception as exc:
        state = page.evaluate(
            """expected => {
                const payload = window[expected.payloadName];
                return {
                    model: payload?.model,
                    cycle: payload?.model_cycle_utc,
                    hour: payload?.forecast_hour,
                    validTime: payload?.valid_time_utc,
                    mapChip: document.querySelector("#mapChip")?.textContent,
                    slider: document.querySelector("#hour")?.value,
                    hourLabel: document.querySelector("#hourOut")?.textContent
                };
            }""",
            expected,
        )
        raise AssertionError(
            f"{model} F{hour:02d} did not load from its archive entry: {state}"
        ) from exc

def test_hrrr_surface_parameter_and_all_forecast_hours():
    page_errors = []
    console_errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
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

        # The category selector should filter to model-supported variables.
        page.locator("#category").select_option("thermodynamics")
        assert page.locator("#parameter").input_value() == "cape"
        visible_parameters = page.locator("#parameter option").evaluate_all(
            "(options) => options.filter(option => !option.hidden && !option.disabled).map(option => option.value)"
        )
        assert {"cape", "lapse", "native_RAP_2t"}.issubset(set(visible_parameters))
        assert "fronto" not in visible_parameters
        page.locator("#category").select_option("forcing")
        visible_parameters = page.locator("#parameter option").evaluate_all(
            "(options) => options.filter(option => !option.hidden && !option.disabled).map(option => option.value)"
        )
        assert set(visible_parameters) == {"fronto", "omega", "moisture"}
        page.locator("#category").select_option("all")

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

        # The catalog is built from actual decoded fields, not a fixed menu.
        page.wait_for_function(
            "() => Array.from(document.querySelector('#parameter').options).some(option => option.value === 'native_RAP_sde')",
            timeout=15000,
        )
        page.locator("#category").select_option("winter")
        page.locator("#parameter").select_option("native_RAP_sde")
        page.wait_for_function(
            "() => document.querySelector('#mapChip').textContent.includes('Snow depth')",
            timeout=15000,
        )
        page.locator("#category").select_option("all")
        page.locator("#parameter").select_option("cape")

        # Verify the published RAP sounding and hodograph, not just the map grid.
        page.wait_for_function(
            """() => window.rapKbtvProfile
                && window.rapKbtvProfile.profile?.pressure_hpa?.length >= 20
                && window.rapKbtvProfile.quality?.pressure_decreases_upward === true
                && window.rapKbtvProfile.quality?.height_increases_upward === true""",
            timeout=30000,
        )
        page.wait_for_function(
            "() => document.querySelector('#profile')?.data?.length >= 2 && document.querySelector('#hodograph')?.data?.length >= 1",
            timeout=30000,
        )
        for entry in rap["hours"]:
            _select_and_wait_for_hour(page, "RAP", entry, rap["model_cycle_utc"])
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

        # HRRR adds its own decoded fields, including CAPE, to the same catalog.
        page.wait_for_function(
            "() => Array.from(document.querySelector('#parameter').options).some(option => option.value === 'native_HRRR_cape')",
            timeout=15000,
        )
        page.locator("#category").select_option("thermodynamics")
        page.locator("#parameter").select_option("native_HRRR_cape")
        page.wait_for_function(
            "() => document.querySelector('#mapChip').textContent.includes('Convective available potential energy')",
            timeout=15000,
        )
        page.locator("#category").select_option("all")
        page.locator("#parameter").select_option("hrrr_temp")

        for entry in hrrr["hours"]:
            _select_and_wait_for_hour(page, "HRRR", entry, hrrr["model_cycle_utc"])
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
            _select_and_wait_for_hour(page, "RAP", entry, rap["model_cycle_utc"])

        # Validate forecast soundings and six-hour diagnostics at all eight supported stations.
        page.locator('button[data-tab="evolution"]').click()
        page.wait_for_function(
            "() => document.querySelector('#trendStatus').textContent.includes('6/6 verified values')",
            timeout=45000,
        )
        assert page.locator("#trend").evaluate("(element) => element.data?.[0]?.x?.length") == 6
        for station_name in ["KPBG", "KMSS", "KSLK", "KMPV", "KRUT", "1V4", "KEFK"]:
            page.evaluate(
                """name => {
                    const station = stations.find(item => item[0] === name);
                    if (!station) throw new Error("Unsupported station " + name);
                    selectPoint(station[1], station[2], station[0]);
                }""",
                station_name,
            )
            page.wait_for_function(
                """name => window.rapKbtvProfile?.label === name
                    && window.rapKbtvProfile.profile?.pressure_hpa?.length >= 20
                    && document.querySelector('#trendStatus').textContent.includes(name)
                    && document.querySelector('#trendStatus').textContent.includes('6/6 verified values')""",
                arg=station_name,
                timeout=20000,
            )
            assert page.locator("#trend").evaluate("(element) => element.data?.[0]?.x?.length") == 6
        page.evaluate("selectPoint(44.4719, -73.1533, 'KBTV')")

        # Model comparison must load both grids at the same exact valid time.
        page.locator('button[data-tab="compare"]').click()
        page.wait_for_function(
            "() => document.querySelector('#comparisonStatus').textContent.includes('Exact valid-time match')",
            timeout=45000,
        )
        comparison_status = page.locator("#comparisonStatus").inner_text()
        assert "RAP " + rap["model_cycle_utc"] in comparison_status
        assert "HRRR " + hrrr["model_cycle_utc"] in comparison_status
        assert rap["hours"][-1]["valid_time_utc"] in page.locator("#comparisonMeta").inner_text()
        comparison_rows = page.locator("#comparisonRows tr").all_text_contents()
        assert len(comparison_rows) == 3, comparison_rows
        assert "Unavailable" not in comparison_rows[0], comparison_rows[0]
        assert "Unavailable" not in comparison_rows[2], comparison_rows[2]
        assert "RAP " in page.locator("#comparisonMeta").inner_text()
        assert "HRRR " in page.locator("#comparisonMeta").inner_text()

        # Exercise the real Leaflet map-click handler using known in-domain coordinates.
        page.locator('button[data-tab="cross"]').click()
        page.locator("#drawTransect").click()
        assert page.locator("#drawTransect").inner_text() == "Click start, then end point"
        page.evaluate(
            """() => {
                window.__testMap.fire('click', { latlng: L.latLng(44.9, -74.7) });
                window.__testMap.fire('click', { latlng: L.latLng(43.1, -72.4) });
            }"""
        )
        assert page.locator("#drawTransect").inner_text() == "Draw cross-section line"
        try:
            page.wait_for_function(
                """() => {
                    const status = document.querySelector('#crossSectionStatus')?.textContent || '';
                    return status.includes('nearest-grid samples') || status.startsWith('Cross-section unavailable:');
                }""",
                timeout=60000,
            )
        except Exception as exc:
            state = page.evaluate(
                """() => ({
                    status: document.querySelector('#crossSectionStatus')?.textContent,
                    drawingLabel: document.querySelector('#drawTransect')?.textContent,
                    model: document.querySelector('#model')?.value,
                    hour: document.querySelector('#hour')?.value
                })"""
            )
            raise AssertionError(f"RAP transect did not finish: {state}; page errors: {page_errors}; console errors: {console_errors}") from exc
        cross_status = page.locator("#crossSectionStatus").inner_text()
        assert "nearest-grid samples" in cross_status, f"RAP transect failed: {cross_status}"

        browser.close()

    assert not page_errors, "Uncaught browser errors: " + "; ".join(page_errors)
