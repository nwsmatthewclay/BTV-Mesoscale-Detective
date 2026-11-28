#!/usr/bin/env python3
"""Phase 1C: broad physical plausibility and profile/diagnostic consistency audit.

This is a screening QC layer, not independent scientific validation. Thresholds are
intentionally broad to flag suspicious values for review rather than reject valid
extreme environments.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

PROFILE_KEY = ["case_id", "date", "site", "valid_time_utc", "pressure_hpa"]
DIAG_KEY = ["case_id", "date", "site", "valid_time_utc"]
PROFILE_REQUIRED = PROFILE_KEY + ["temperature_c", "dewpoint_c", "u_ms", "v_ms"]
DIAG_RANGES = {
    "sbcape_jkg": (0, 10000), "mlcape_100hpa_jkg": (0, 10000),
    "mucape_300hpa_jkg": (0, 10000), "sbcin_jkg": (-5000, 500),
    "mlcin_100hpa_jkg": (-5000, 500), "mucin_300hpa_jkg": (-5000, 500),
    "lcl_pressure_hpa": (50, 1100), "lcl_temperature_c": (-100, 60),
    "pwat_mm": (0, 100), "shear_0_1km_kt": (0, 200),
    "shear_0_3km_kt": (0, 200), "shear_0_6km_kt": (0, 200),
    "lapse_0_3km_c_per_km": (-15, 15), "lapse_700_500_c_per_km": (-15, 15),
    "freezing_level_agl_m": (0, 10000),
    "hail_growth_layer_10_to_30c_depth_m": (0, 10000),
}
EXPECTED_SITES = {"KBTV", "KPBG", "KMSS", "KSLK", "KMPV", "KRUT"}

def add_flag(flags, level, key, field, value, code, detail):
    flags.append({"severity": level, **key, "field": field, "value": value, "flag": code, "detail": detail})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", type=Path, required=True)
    ap.add_argument("--diagnostics", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    profiles = pd.read_csv(args.profiles)
    diagnostics = pd.read_csv(args.diagnostics)
    missing_profile = [c for c in PROFILE_REQUIRED if c not in profiles.columns]
    missing_diag_keys = [c for c in DIAG_KEY if c not in diagnostics.columns]
    if missing_profile or missing_diag_keys:
        raise SystemExit(f"Required columns missing. profiles={missing_profile}; diagnostics={missing_diag_keys}")

    pflags, dflags, integrity = [], [], []
    for keyvals, group in profiles.groupby(DIAG_KEY, dropna=False, sort=True):
        key = dict(zip(DIAG_KEY, keyvals))
        p = pd.to_numeric(group.pressure_hpa, errors="coerce")
        t = pd.to_numeric(group.temperature_c, errors="coerce")
        td = pd.to_numeric(group.dewpoint_c, errors="coerce")
        u = pd.to_numeric(group.u_ms, errors="coerce")
        v = pd.to_numeric(group.v_ms, errors="coerce")
        if group.duplicated("pressure_hpa").any():
            add_flag(pflags, "WARN", key, "pressure_hpa", None, "duplicate_pressure_level", "Duplicate pressure level in profile.")
        if len(group) < 20:
            add_flag(pflags, "WARN", key, "profile_rows", int(len(group)), "sparse_profile", "Profile contains fewer than 20 pressure levels.")
        if p.isna().any() or t.isna().any() or td.isna().any() or u.isna().any() or v.isna().any():
            add_flag(pflags, "WARN", key, "profile_values", int(group.isna().any(axis=1).sum()), "missing_profile_values", "One or more required profile values are missing or nonnumeric.")
        if ((p < 50) | (p > 1100)).any():
            add_flag(pflags, "WARN", key, "pressure_hpa", float(p.min()), "pressure_out_of_range", "Pressure outside broad 50–1100 hPa screening bounds.")
        if ((t < -100) | (t > 60)).any():
            add_flag(pflags, "WARN", key, "temperature_c", float(t.min()), "temperature_out_of_range", "Temperature outside broad -100 to 60 C screening bounds.")
        if ((td < -100) | (td > 60)).any():
            add_flag(pflags, "WARN", key, "dewpoint_c", float(td.min()), "dewpoint_out_of_range", "Dewpoint outside broad -100 to 60 C screening bounds.")
        supersat = td - t
        if (supersat > 1.0).any():
            add_flag(pflags, "WARN", key, "dewpoint_minus_temperature_c", float(supersat.max()), "dewpoint_above_temperature", "Dewpoint exceeds temperature by more than 1 C; review RH/dewpoint conversion.")
        wind = np.hypot(u, v)
        if (wind > 100).any():
            add_flag(pflags, "WARN", key, "wind_speed_ms", float(wind.max()), "extreme_profile_wind", "Wind speed exceeds 100 m/s; review source/unit handling.")
        if ((u.abs() > 100) | (v.abs() > 100)).any():
            add_flag(pflags, "WARN", key, "wind_component_ms", float(max(u.abs().max(), v.abs().max())), "wind_component_out_of_range", "Wind component exceeds 100 m/s.")
        if p.dropna().duplicated().any():
            integrity.append({**key, "check": "unique_pressure_levels", "status": "FAIL", "detail": "Duplicate pressure values"})
        if len(p.dropna()) and not p.dropna().is_monotonic_decreasing:
            add_flag(pflags, "INFO", key, "pressure_hpa", None, "pressure_order_review", "Pressure rows are not descending; calculations sort internally.")

    for _, row in diagnostics.iterrows():
        key = {k: row.get(k) for k in DIAG_KEY}
        for field, (lo, hi) in DIAG_RANGES.items():
            if field not in diagnostics.columns:
                continue
            value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
            if pd.isna(value):
                add_flag(dflags, "WARN", key, field, None, "diagnostic_missing", "Diagnostic value is missing/non-numeric.")
            elif value < lo or value > hi:
                add_flag(dflags, "WARN", key, field, float(value), "diagnostic_out_of_range", f"Value outside broad screening bounds [{lo}, {hi}].")
        for cape, cin in [("sbcape_jkg", "sbcin_jkg"), ("mlcape_100hpa_jkg", "mlcin_100hpa_jkg"), ("mucape_300hpa_jkg", "mucin_300hpa_jkg")]:
            if cape in diagnostics.columns and cin in diagnostics.columns:
                cval = pd.to_numeric(pd.Series([row.get(cape)]), errors="coerce").iloc[0]
                iv = pd.to_numeric(pd.Series([row.get(cin)]), errors="coerce").iloc[0]
                if pd.notna(cval) and cval < 0:
                    add_flag(dflags, "WARN", key, cape, float(cval), "negative_cape", "CAPE is negative; review diagnostic sign.")
                if pd.notna(iv) and iv > 50:
                    add_flag(dflags, "WARN", key, cin, float(iv), "positive_cin", "CIN is strongly positive; review sign convention.")
        if "lcl_pressure_hpa" in diagnostics.columns:
            lclp = pd.to_numeric(pd.Series([row.get("lcl_pressure_hpa")]), errors="coerce").iloc[0]
            subset = profiles[(profiles.case_id == row.get("case_id")) & (profiles.site == row.get("site")) & (profiles.valid_time_utc == row.get("valid_time_utc"))]
            basep = pd.to_numeric(subset.pressure_hpa, errors="coerce").max() if not subset.empty else np.nan
            if pd.notna(lclp) and pd.notna(basep) and lclp > basep + 5:
                add_flag(dflags, "WARN", key, "lcl_pressure_hpa", float(lclp), "lcl_pressure_above_surface", "LCL pressure exceeds lowest profile pressure by >5 hPa.")

    pkeys = set(map(tuple, profiles[DIAG_KEY].drop_duplicates().to_numpy()))
    dkeys = set(map(tuple, diagnostics[DIAG_KEY].drop_duplicates().to_numpy()))
    for missing in sorted(dkeys - pkeys):
        integrity.append({"case_id": missing[0], "date": missing[1], "site": missing[2], "valid_time_utc": missing[3], "check": "profile_diagnostic_pairing", "status": "FAIL", "detail": "Diagnostic record has no matching profile group."})
    for extra in sorted(pkeys - dkeys):
        integrity.append({"case_id": extra[0], "date": extra[1], "site": extra[2], "valid_time_utc": extra[3], "check": "profile_diagnostic_pairing", "status": "WARN", "detail": "Profile group has no matching diagnostic record."})
    cases = sorted(profiles.case_id.dropna().unique().tolist())
    sites = sorted(profiles.site.dropna().unique().tolist())
    for site in sorted(EXPECTED_SITES - set(sites)):
        integrity.append({"check": "expected_site_coverage", "status": "WARN", "detail": f"Expected site {site} missing from profile archive."})

    pd.DataFrame(pflags).to_csv(args.out_dir / "phase1c_profile_flags.csv", index=False)
    pd.DataFrame(dflags).to_csv(args.out_dir / "phase1c_diagnostic_flags.csv", index=False)
    pd.DataFrame(integrity).to_csv(args.out_dir / "phase1c_integrity_findings.csv", index=False)
    counts = {"profile_flags": len(pflags), "diagnostic_flags": len(dflags), "integrity_findings": len(integrity),
              "profile_groups": len(pkeys), "diagnostic_groups": len(dkeys), "cases": len(cases), "sites": sites,
              "profile_diagnostic_key_overlap": len(pkeys & dkeys), "profile_only_keys": len(pkeys - dkeys), "diagnostic_only_keys": len(dkeys - pkeys)}
    status = "PASS" if len(pflags) == 0 and len(dflags) == 0 and not any(x.get("status") == "FAIL" for x in integrity) else "REVIEW"
    report = {"phase": "phase1c_physical_plausibility_and_cross_file_audit", "overall_status": status,
        "audit_scope": "Broad physical plausibility bounds, thermodynamic consistency checks, and profile/diagnostic key alignment. This is screening QC, not independent validation.",
        "counts": counts, "diagnostic_screening_bounds": DIAG_RANGES,
        "notes": ["Bounds are deliberately broad and flag values for review, not automatically invalidating meteorological extremes.",
                   "This audit does not compare ERA5 with independent observations or validate case classification.",
                   "ERA5 profiles and diagnostics remain reanalysis-derived; surface and height approximations from prior phases remain in effect."]}
    (args.out_dir / "phase1c_audit.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md = ["# Phase 1C — Physical Plausibility & Cross-file Audit", "", f"**Status: {status}**", "",
        "## Summary", "", f"- Profile groups: {len(pkeys)}", f"- Diagnostic groups: {len(dkeys)}",
        f"- Profile groups without diagnostics: {len(pkeys - dkeys)}", f"- Diagnostic groups without profiles: {len(dkeys - pkeys)}",
        f"- Profile flags: {len(pflags)}", f"- Diagnostic flags: {len(dflags)}", f"- Integrity findings: {len(integrity)}", "",
        "## Scope and caveats", "", report["audit_scope"], "", *[f"- {n}" for n in report["notes"]]]
    (args.out_dir / "phase1c_audit.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"status": status, **counts, "output_dir": str(args.out_dir)}, indent=2))

if __name__ == "__main__":
    main()
