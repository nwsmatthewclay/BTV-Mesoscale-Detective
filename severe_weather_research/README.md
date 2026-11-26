# BTV Severe Weather Research

Research workspace for severe convective events in the Burlington (BTV) forecast area, March–September.

## First acquisition run
The initial manifest contains five report-driven candidate cases. These are screening dates—not an environmental classification.

Run the **ERA5 First Five Cases** workflow from GitHub Actions (or it runs on pushes to this acquisition folder). It downloads ERA5 pressure-level and single-level GRIB files for each case day to an Actions artifact. Raw GRIB files are intentionally not committed.

### Secret
Set repository Actions secret `CDS_API_KEY` to your Copernicus Climate Data Store personal access token. The token is passed to the downloader as an environment variable; never place it in a file or commit.

### Files
- `acquisition/case_manifest.csv`: first five cases
- `acquisition/download_era5_cases.py`: downloader, retry-safe skip behavior, manifest logging
- `.github/workflows/acquire_era5_first_five.yml`: manual + path-push workflow
- `data/raw/`: downloads in the workflow workspace (artifact only)
- `data/metadata/acquisition_log.csv`: per-file result log
- `processing/validate_era5_pilot.py`: lightweight GRIB file integrity checks

## Pilot validation
After downloading the workflow artifact ZIP, unpack it so its `raw/` folder matches the expected layout, then run:

```bash
python severe_weather_research/processing/validate_era5_pilot.py --raw-dir severe_weather_research/data/raw
```

The validator checks all ten expected files for existence, nonzero size, GRIB signature, and pilot file-size consistency. Optional `--decode` attempts metadata decoding using `cfgrib`/ecCodes; install `processing/requirements.txt` first. It writes a JSON report under `data/metadata/`.

**Scientific note:** the initial pilot uses only seven pressure levels (1000, 925, 850, 700, 500, 300, 250 hPa). This is adequate for a first acquisition smoke test and coarse diagnostics, but too sparse for trustworthy full-profile parcel calculations, CAPE/CIN, or detailed hail-growth-layer analysis. The next acquisition should expand to a much denser pressure-level set before we treat derived sounding parameters as research results.

## Processing dependencies
Install optional scientific packages:

```bash
python -m pip install -r severe_weather_research/processing/requirements.txt
```
