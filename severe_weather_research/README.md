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

The validator checks all ten expected files for existence, nonzero size, GRIB signature, and the single-level pilot file-size consistency. It expects the expanded `pressure_levels_full.grib` profile. Optional `--decode` attempts metadata decoding using `cfgrib`/ecCodes; install `processing/requirements.txt` first. It writes a JSON report under `data/metadata/`.

**Scientific note:** the first smoke-test artifact contained only seven pressure levels, which is too sparse for trustworthy full-profile parcel calculations. The downloader has now been expanded to request 30 pressure levels from 1000 to 10 hPa, with a new filename (`pressure_levels_full.grib`) so it will not mistakenly reuse the earlier sparse file. This denser profile is the basis for the next parameter-extraction step.

## Processing dependencies
Install optional scientific packages:

```bash
python -m pip install -r severe_weather_research/processing/requirements.txt
```

## First environmental analog ranking

The 30-case validation workflow now creates an exploratory analog reference dataset from case-mean environmental diagnostics at all available sites and hours. It is included in the workflow artifact under `analog_reference_output/`.

The initial ranking script uses a weighted standardized distance:
- Robust scale is the feature IQR; standard deviation is used if IQR is unavailable/zero.
- The distance is weighted RMS across shared valid features.
- A display similarity score is `100 * exp(-distance)`; this is **not a probability**.
- Forecast input is a JSON object using the diagnostic column names.

Example (after downloading/extracting the workflow artifact so diagnostics CSV is available):

```bash
python severe_weather_research/processing/analog_ranker.py \
  --diagnostics diagnostics_output/hourly_environmental_parameters.csv \
  --forecast severe_weather_research/processing/forecast_environment_example.json \
  --output analog_output/ranked_analogs.csv
```

Outputs: ranked analog CSV and adjacent JSON method/report file.

**Research limitations:** The case means pool all ERA5 sites and hourly samples, so they are not storm-time matched. No storm-report time linkage is implemented. The expanded case set and event labels remain provisional and analog results should be treated as exploratory.
