# BTV Mesoscale Detective

Interactive, map-first mesoscale analysis workspace for the NWS Burlington forecast area (Vermont and northern New York).

## Try it online

Enable GitHub Pages under **Settings → Pages → Build and deployment → GitHub Actions**. The included Pages workflow deploys the repository root on pushes to `main`.

Expected URL: https://nwsmatthewclay.github.io/BTV-Mesoscale-Detective/

## Interface controls

- Select KBTV, KPBG, KMSS, KSLK, KMPV, KRUT, 1V4, or KEFK, or click any map point.
- Draw and clear a two-point transect.
- Change model, cycle, forecast hour, and map parameter.
- Explore Environment, Soundings, Kinematics & Forcing, Cross-Sections, Model Compare, and Time Evolution tabs.
- Model manifest reader reports discovered files without implying that fields are decoded.

## Data status and safety

This is an interactive development build. Map controls and navigation are functional, but model-data ingestion is not connected end-to-end. Diagnostic values intentionally remain blank until real model fields are downloaded, decoded, and validated. Do not use this development build for operational decision-making.

RRFS discovery is included, but RRFS extraction remains gated on validating index offsets and HTTP byte-range behavior. RAP/HRRR subset and GRIB processing utilities are included as a pipeline foundation.

## Local setup

Run the static interface locally with `python -m http.server 8000`, then open http://localhost:8000.

Python pipeline setup:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r mesoscale/requirements.txt
```

See [mesoscale/README.md](mesoscale/README.md) for pipeline details.

## Structure

- `index.html`: GitHub Pages entry point.
- `mesoscale.html`: source copy of the interactive interface.
- `mesoscale/`: discovery, GRIB utilities, diagnostics, tests, and configuration.
- `.github/workflows/`: discovery and Pages workflows.

## Development principles

- Never display fabricated meteorological values.
- Keep observations distinct from model output.
- Carry source, initialization, valid time, units, and provenance with each diagnostic.
- Avoid full CONUS downloads when a verified regional extraction method is available.
- Keep this project independent of the operational SA Dashboard until validated.
