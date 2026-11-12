from playwright.sync_api import sync_playwright


def test_hrrr_surface_parameter_and_hour_switching():
    page_errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())

        page.goto("http://127.0.0.1:8765/", wait_until="domcontentloaded")
        # The initial parameter is observations; select a model grid field to
        # force the first RAP regional-grid request before testing model swaps.
        page.locator("#parameter").select_option("cape")
        page.wait_for_function(
            "() => window.rapGridPayload && window.rapGridPayload.model === 'RAP'",
            timeout=45000,
        )
        assert page.evaluate(
            """async () => {
                const manifest = await (await fetch(
                    './mesoscale/data/fields/forecast/forecast_manifest.json'
                )).json();
                return window.rapGridPayload.model_cycle_utc === manifest.model_cycle_utc
                    && Number(window.rapGridPayload.forecast_hour) === 0;
            }"""
        ), "RAP grid payload must match the published archive cycle and F00"

        page.locator("#model").select_option("HRRR")
        page.wait_for_function(
            "() => window.hrrrGridPayload && window.hrrrGridPayload.model === 'HRRR'",
            timeout=30000,
        )
        assert page.locator("#parameter").input_value() == "hrrr_temp"
        assert "HRRR 2-m temperature" in page.locator("#mapChip").inner_text()
        assert page.locator("#gridSpacing").text_content().strip() == "3 km nominal"
        assert page.evaluate(
            """async () => {
                const rap = await (await fetch(
                    './mesoscale/data/fields/forecast/forecast_manifest.json'
                )).json();
                const rapEntry = rap.hours.find(x => Number(x.forecast_hour) === 0);
                return window.hrrrGridPayload.valid_time_utc === rapEntry.valid_time_utc;
            }"""
        ), "Switching to HRRR must preserve the selected RAP valid time"
        assert page.evaluate(
            """async () => {
                const rap = await (await fetch(
                    './mesoscale/data/fields/forecast/forecast_manifest.json'
                )).json();
                const hrrr = await (await fetch(
                    './mesoscale/data/fields/hrrr/hrrr_forecast_manifest.json'
                )).json();
                return rap.hours.length >= 4
                    && rap.hours.length === hrrr.hours.length
                    && rap.hours.every((entry, index) =>
                        entry.valid_time_utc === hrrr.hours[index].valid_time_utc
                    );
            }"""
        ), "Every published HRRR forecast hour must align with the corresponding RAP valid time"

        aligned_hour = page.evaluate(
            """async () => {
                const rap = await (await fetch(
                    './mesoscale/data/fields/forecast/forecast_manifest.json'
                )).json();
                const hrrr = await (await fetch(
                    './mesoscale/data/fields/hrrr/hrrr_forecast_manifest.json'
                )).json();
                const rapEntry = rap.hours.find(x => Number(x.forecast_hour) === 3);
                const hrrrEntry = hrrr.hours.find(x => x.valid_time_utc === rapEntry.valid_time_utc);
                if (!hrrrEntry) throw new Error('No HRRR grid matches RAP F03 valid time');
                return Number(hrrrEntry.forecast_hour);
            }"""
        )
        page.locator("#hour").evaluate(
            """(element, hour) => {
                element.value = String(hour);
                element.dispatchEvent(new Event("input", { bubbles: true }));
                element.dispatchEvent(new Event("change", { bubbles: true }));
            }""",
            aligned_hour,
        )
        page.wait_for_function(
            "hour => window.hrrrGridPayload && "
            "Number(window.hrrrGridPayload.forecast_hour) === hour && "
            "document.querySelector('#mapChip').textContent.includes('F' + String(hour).padStart(2, '0'))",
            arg=aligned_hour,
            timeout=30000,
        )
        assert page.evaluate(
            """async () => {
                const rap = await (await fetch(
                    './mesoscale/data/fields/forecast/forecast_manifest.json'
                )).json();
                const hrrr = await (await fetch(
                    './mesoscale/data/fields/hrrr/hrrr_forecast_manifest.json'
                )).json();
                const rapEntry = rap.hours.find(x => Number(x.forecast_hour) === 3);
                const hrrrEntry = hrrr.hours.find(x => Number(x.forecast_hour) === Number(window.hrrrGridPayload.forecast_hour));
                return Boolean(hrrrEntry)
                    && hrrrEntry.valid_time_utc === rapEntry.valid_time_utc
                    && window.hrrrGridPayload.valid_time_utc === rapEntry.valid_time_utc;
            }"""
        ), "HRRR forecast-hour selection must stay aligned to RAP F03 valid time"

        page.locator("#parameter").select_option("hrrr_wind")
        page.wait_for_function(
            "() => document.querySelector('#mapChip').textContent.includes('10-m wind speed')",
            timeout=15000,
        )
        assert "F03" in page.locator("#mapChip").inner_text()

        page.locator("#model").select_option("RAP")
        page.wait_for_function(
            "() => window.rapGridPayload && window.rapGridPayload.model === 'RAP' && "
            "Number(window.rapGridPayload.forecast_hour) === 3 && "
            "document.querySelector('#mapChip').textContent.includes('RAP')",
            timeout=30000,
        )
        assert page.locator("#gridSpacing").text_content().strip() == "13 km nominal"

        browser.close()

    assert not page_errors, "Uncaught browser errors: " + "; ".join(page_errors)
