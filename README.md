# BTV Mesoscale Detective

Interactive, map-first mesoscale analysis workspace for the NWS Burlington forecast area (Vermont and northern New York).

## Live workspace

[Open BTV Mesoscale Detective](https://nwsmatthewclay.github.io/BTV-Mesoscale-Detective/)

GitHub Pages is deployed from the repository and is refreshed after successful RAP ingestion as well as interface changes.

## Verified data status

The workspace now has a functioning, automated RAP data path:

- The ingestion workflow downloads and decodes RAP 13-km CONUS hybrid-level GRIB2 data, crops it to the BTV analysis domain, and validates the resulting fields.
- The published forecast archive contains F00, F03, F06 and F09 from one RAP cycle. The live [forecast manifest](mesoscale/data/fields/forecast/forecast_manifest.json) is the source of truth for the available cycle, valid times and files.
- Each published forecast hour includes a regional grid product and eight station profiles: KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 and KEFK. The latest verified profiles contain 50 vertical levels and pass pressure/height monotonicity checks.
- A separate latest RAP field grid and KBTV profile are also published.
- Model discovery identifies RAP, HRRR and RRFS products. **Discovery is not ingestion:** RAP is the only model currently decoded and published end-to-end. HRRR and RRFS remain gated until their regional extraction and field validation are complete.

The dashboard reads available RAP forecast hours from the manifest; it does not invent missing hours or substitute illustrative meteorological values.

## Interface controls

- Select KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4 or KEFK, or click a map point.
- Draw and clear a two-point transect.
- Change model, cycle, available forecast hour and map parameter.
- Explore Environment, Soundings, Kinematics & Forcing, Cross-Sections, Model Compare and Time Evolution.
- The model manifest reader distinguishes discovered products from decoded and published fields.

## Data safety

This remains a development and research workspace, not an operationally approved decision-support system. Do not use it as the sole basis for warning, forecast or aviation decisions.

- Never display fabricated meteorological values.
- Keep observations distinct from model output.
- Carry source, initialization time, valid time, units and provenance with every diagnostic.
- Do not compare models unless fields have compatible definitions, units and valid times.
- Keep this project independent of the operational NWS_SA_Dashboard until separately validated.

## Local setup

Run the static interface locally with `python -m http.server 8000`, then open http://localhost:8000.

Python pipeline setup:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r mesoscale/requirements.txt
pytest -q mesoscale/tests
```

See [mesoscale/README.md](mesoscale/README.md) for pipeline details.

## Structure

- `index.html`: GitHub Pages entry point.
- `mesoscale.html`: synchronized source copy of the interface.
- `mesoscale/`: model discovery, GRIB acquisition/processing, diagnostics, tests and configuration.
- `.github/workflows/`: model discovery, RAP ingestion/archive and Pages deployment.

## Development principles

- Never fabricate meteorological values.
- Preserve source model, cycle, forecast hour, valid time, units and quality metadata.
- Validate every field and vertical profile before publishing.
- Keep this project separate from the operational SA Dashboard until it has completed its own validation.
