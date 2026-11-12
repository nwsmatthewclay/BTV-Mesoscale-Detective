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

        page.locator("#model").select_option("HRRR")
        page.wait_for_function(
            "() => window.hrrrGridPayload && "
            "window.hrrrGridPayload.model === 'HRRR' && "
            "Number(window.hrrrGridPayload.forecast_hour) === 0",
            timeout=30000,
        )
        assert page.locator("#parameter").input_value() == "hrrr_temp"
        assert "HRRR 2-m temperature" in page.locator("#mapChip").inner_text()

        page.locator("#hour").evaluate(
            """element => {
                element.value = "3";
                element.dispatchEvent(new Event("input", { bubbles: true }));
                element.dispatchEvent(new Event("change", { bubbles: true }));
            }"""
        )
        page.wait_for_function(
            "() => window.hrrrGridPayload && "
            "Number(window.hrrrGridPayload.forecast_hour) === 3 && "
            "document.querySelector('#mapChip').textContent.includes('F03')",
            timeout=30000,
        )

        page.locator("#parameter").select_option("hrrr_wind")
        page.wait_for_function(
            "() => document.querySelector('#mapChip').textContent.includes('10-m wind speed')",
            timeout=15000,
        )
        assert "F03" in page.locator("#mapChip").inner_text()

        page.locator("#model").select_option("RAP")
        page.wait_for_function(
            "() => window.rapGridPayload && window.rapGridPayload.model === 'RAP' && "
            "document.querySelector('#mapChip').textContent.includes('RAP')",
            timeout=30000,
        )

        browser.close()

    assert not page_errors, "Uncaught browser errors: " + "; ".join(page_errors)
