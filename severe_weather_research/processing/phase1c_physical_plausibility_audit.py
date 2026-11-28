#!/usr/bin/env python3
"""Phase 1C: physical plausibility, missing-data detail, and cross-file QC.

Screening QC only: flags suspicious data without rejecting meteorologically
legitimate extremes. This audit does not independently validate ERA5.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

PROFILE_KEY = ["case_id", "date", "site", "valid_time_utc", "pressure_hpa"]
DIAG_KEY = ["case_id", "date", "site", "valid_time_utc"]
PROFILE_REQUIRED = PROFILE_KEY + ["temperature_c", "dewpoint_c", "u_ms", "v_ms"]
PROFILE_VALUE_FIELDS = ["temperature_c", "dewpoint_c", "u_ms", "v_ms"]
# ERA5 pressure-level archive includes 10 hPa. Use bounds that encompass the
# configured archive rather than the previous erroneous 50 hPa floor.
PRESSURE_BOUNDS_HPA = (10, 1100)
DIAG_RANGES = {
    # Negative CAPE is not silently clipped. It is separately flagged once,
    # and this broad range prevents duplicate out-of-range/negative flags.
    "sbcape_jkg": (-500, 10000), "mlcape_100hpa_jkg": (-500, 10000),
    "mucape_300hpa_jkg": (-500, 10000),
    "sbcin_jkg": (-5000, 500), "mlcin_100hpa_jkg": (-5000, 500),
    "mucin_300hpa_jkg": (-5000, 500),
    "lcl_pressure_hpa": (10, 1100), "lcl_temperature_c": (-100, 60),
    "pwat_mm": (0, 100), "shear_0_1km_kt": (0, 200),
    "shear_0_3km_kt": (0, 200), "shear_0_6km_kt": (0, 200),
    "lapse_0_3km_c_per_km": (-15, 15), "lapse_700_500_c_per_km": (-15, 15),
    "freezing_level_agl_m": (0, 10000),
    "hail_growth_layer_10_to_30c_depth_m": (0, 10000),
}
EXPECTED_SITES = {"KBTV", "KPBG", "KMSS", "KSLK", "KMPV", "KRUT"}

def add_flag(flags, level, key, field, value, code, detail):
    flags.append({"severity": level, **key, "field": field, "value": value, "flag": code, "detail": detail})

def num(series):
    return pd.to_numeric(series, errors="coerce")

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
    missing_value_detail = []
    for keyvals, group in profiles.groupby(DIAG_KEY, dropna=False, sort=True):
        key = dict(zip(DIAG_KEY, keyvals))
        p = num(group.pressure_hpa)
        t, td, u, v = (num(group[c]) for c in ["temperature_c", "dewpoint_c", "u_ms", "v_ms"])
        duplicate_pressures = group.pressure_hpa.duplicated(keep=False)
        if duplicate_pressures.any():
            add_flag(pflags, "WARN", key, "pressure_hpa", sorted(pd.to_numeric(group.loc[duplicate_pressures,"pressure_hpa"],errors="coerce").dropna().unique().tolist()), "duplicate_pressure_level", "Duplicate pressure level(s) in profile.")
            integrity.append({**key, "check": "unique_pressure_levels", "status": "FAIL", "detail": "Duplicate pressure level(s) within profile-time group."})
        if len(group) < 20:
            add_flag(pflags, "WARN", key, "profile_rows", int(len(group)), "sparse_profile", "Profile contains fewer than 20 pressure levels.")
        # Report missing/non-numeric fields by variable and pressure level,
        # avoiding the previous one-size-fits-all profile warning.
        for field, series in [("temperature_c",t),("dewpoint_c",td),("u_ms",u),("v_ms",v)]:
            bad = series.isna()
            if bad.any():
                for idx in group.index[bad]:
                    pressure = group.loc[idx,"pressure_hpa"]
                    missing_value_detail.append({**key,"pressure_hpa":pressure,"variable":field,"source_row_index":int(idx),"issue":"missing_or_nonnumeric"})
                add_flag(pflags, "WARN", key, field, int(bad.sum()), "missing_profile_values", f"{int(bad.sum())} missing/non-numeric value(s) in {field}; detailed pressure levels are listed in missing_profile_value_details.csv.")
        if p.isna().any():
            add_flag(pflags, "WARN", key, "pressure_hpa", int(p.isna().sum()), "missing_pressure_values", "Pressure values missing or nonnumeric.")
        validp=p.dropna()
        if ((validp < PRESSURE_BOUNDS_HPA[0]) | (validp > PRESSURE_BOUNDS_HPA[1])).any():
            add_flag(pflags, "WARN", key, "pressure_hpa", [float(validp.min()),float(validp.max())], "pressure_out_of_range", f"Pressure outside screening bounds {PRESSURE_BOUNDS_HPA} hPa.")
        for field, series, lo, hi in [("temperature_c",t,-100,60),("dewpoint_c",td,-100,60)]:
            valid=series.dropna()
            if ((valid<lo)|(valid>hi)).any():
                add_flag(pflags,"WARN",key,field,float(valid.min()),f"{field}_out_of_range",f"Values outside broad {lo} to {hi} C bounds.")
        # Dewpoint-temperature check is row-specific; tolerate <=1 C supersaturation.
        supersat=td-t
        bad_sup=supersat>1
        if bad_sup.any():
            add_flag(pflags,"WARN",key,"dewpoint_minus_temperature_c",float(supersat[bad_sup].max()),"dewpoint_above_temperature","Dewpoint exceeds temperature by more than 1 C; review RH/dewpoint conversion.")
        wind=np.hypot(u,v)
        validwind=wind.dropna()
        if (validwind>100).any():
            add_flag(pflags,"WARN",key,"wind_speed_ms",float(validwind.max()),"extreme_profile_wind","Wind speed exceeds 100 m/s; review source/unit handling.")
        for component,series in [("u_ms",u),("v_ms",v)]:
            valid=series.dropna()
            if (valid.abs()>100).any():
                add_flag(pflags,"WARN",key,component,float(valid.abs().max()),"wind_component_out_of_range","Wind component exceeds 100 m/s.")
        if len(validp) and not validp.is_monotonic_decreasing:
            add_flag(pflags,"INFO",key,"pressure_hpa",None,"pressure_order_review","Pressure rows are not descending; calculations sort internally.")

    for _, row in diagnostics.iterrows():
        key={k:row.get(k) for k in DIAG_KEY}
        for field,(lo,hi) in DIAG_RANGES.items():
            if field not in diagnostics.columns: continue
            value=pd.to_numeric(pd.Series([row.get(field)]),errors="coerce").iloc[0]
            if pd.isna(value):
                add_flag(dflags,"WARN",key,field,None,"diagnostic_missing","Diagnostic value is missing/non-numeric.")
            elif value<lo or value>hi:
                add_flag(dflags,"WARN",key,field,float(value),"diagnostic_out_of_range",f"Value outside broad screening bounds [{lo}, {hi}].")
        # One flag per negative CAPE field. Values remain untouched in source
        # diagnostics; the audit does not assume the cause or force CAPE to zero.
        for cape in ["sbcape_jkg","mlcape_100hpa_jkg","mucape_300hpa_jkg"]:
            if cape in diagnostics.columns:
                value=pd.to_numeric(pd.Series([row.get(cape)]),errors="coerce").iloc[0]
                if pd.notna(value) and value < 0:
                    add_flag(dflags,"WARN",key,cape,float(value),"negative_cape","Negative CAPE value; investigate MetPy parcel/integration behavior. Value is preserved, not clipped.")
        for cin in ["sbcin_jkg","mlcin_100hpa_jkg","mucin_300hpa_jkg"]:
            if cin in diagnostics.columns:
                value=pd.to_numeric(pd.Series([row.get(cin)]),errors="coerce").iloc[0]
                if pd.notna(value) and value>50:
                    add_flag(dflags,"WARN",key,cin,float(value),"positive_cin","CIN is strongly positive; review sign convention.")
        if "lcl_pressure_hpa" in diagnostics.columns:
            lclp=pd.to_numeric(pd.Series([row.get("lcl_pressure_hpa")]),errors="coerce").iloc[0]
            subset=profiles[(profiles.case_id==row.get("case_id"))&(profiles.site==row.get("site"))&(profiles.valid_time_utc==row.get("valid_time_utc"))]
            basep=num(subset.pressure_hpa).max() if not subset.empty else np.nan
            if pd.notna(lclp) and pd.notna(basep) and lclp>basep+5:
                add_flag(dflags,"WARN",key,"lcl_pressure_hpa",float(lclp),"lcl_pressure_above_surface","LCL pressure exceeds lowest profile pressure by >5 hPa.")

    pkeys=set(map(tuple,profiles[DIAG_KEY].drop_duplicates().to_numpy()))
    dkeys=set(map(tuple,diagnostics[DIAG_KEY].drop_duplicates().to_numpy()))
    for missing in sorted(dkeys-pkeys):
        integrity.append({"case_id":missing[0],"date":missing[1],"site":missing[2],"valid_time_utc":missing[3],"check":"profile_diagnostic_pairing","status":"FAIL","detail":"Diagnostic record has no matching profile group."})
    for extra in sorted(pkeys-dkeys):
        integrity.append({"case_id":extra[0],"date":extra[1],"site":extra[2],"valid_time_utc":extra[3],"check":"profile_diagnostic_pairing","status":"WARN","detail":"Profile group has no matching diagnostic record."})
    cases=sorted(profiles.case_id.dropna().unique().tolist())
    sites=sorted(profiles.site.dropna().unique().tolist())
    for site in sorted(EXPECTED_SITES-set(sites)):
        integrity.append({"check":"expected_site_coverage","status":"WARN","detail":f"Expected site {site} missing from profile archive."})
    duplicate_diag=diagnostics.duplicated(DIAG_KEY,keep=False)
    if duplicate_diag.any():
        integrity.append({"check":"diagnostic_key_uniqueness","status":"FAIL","detail":f"{int(duplicate_diag.sum())} diagnostic rows have duplicate keys."})
    pd.DataFrame(pflags).to_csv(args.out_dir/"phase1c_profile_flags.csv",index=False)
    pd.DataFrame(dflags).to_csv(args.out_dir/"phase1c_diagnostic_flags.csv",index=False)
    pd.DataFrame(integrity).to_csv(args.out_dir/"phase1c_integrity_findings.csv",index=False)
    pd.DataFrame(missing_value_detail).to_csv(args.out_dir/"phase1c_missing_profile_value_details.csv",index=False)
    flag_summary=pd.DataFrame([{"scope":"profile","flag":k,"count":int(v)} for k,v in pd.Series([x["flag"] for x in pflags]).value_counts().items()]+[{"scope":"diagnostic","flag":k,"count":int(v)} for k,v in pd.Series([x["flag"] for x in dflags]).value_counts().items()])
    flag_summary.to_csv(args.out_dir/"phase1c_flag_summary.csv",index=False)
    counts={"profile_flags":len(pflags),"diagnostic_flags":len(dflags),"integrity_findings":len(integrity),
            "profile_groups":len(pkeys),"diagnostic_groups":len(dkeys),"cases":len(cases),"sites":sites,
            "profile_diagnostic_key_overlap":len(pkeys&dkeys),"profile_only_keys":len(pkeys-dkeys),"diagnostic_only_keys":len(dkeys-pkeys),
            "missing_profile_values":len(missing_value_detail),"negative_cape_flags":sum(x["flag"]=="negative_cape" for x in dflags)}
    status="PASS" if len(pflags)==0 and len(dflags)==0 and not any(x.get("status")=="FAIL" for x in integrity) else "REVIEW"
    report={"phase":"phase1c_physical_plausibility_and_cross_file_audit","overall_status":status,
            "audit_scope":"Broad physical plausibility bounds, detailed missing-value checks, and profile/diagnostic key alignment. This is screening QC, not independent validation.",
            "counts":counts,"profile_pressure_bounds_hpa":PRESSURE_BOUNDS_HPA,"diagnostic_screening_bounds":DIAG_RANGES,
            "flag_summary":flag_summary.to_dict(orient="records"),
            "notes":["Pressure bounds now include ERA5 10 hPa pressure level; prior 50 hPa lower bound caused false positives.",
                      "Missing required profile values are identified by variable and pressure level in the companion detail CSV.",
                      "Negative CAPE values are preserved and flagged once per field; they are not clipped or treated as ordinary numerical noise.",
                      "This audit does not compare ERA5 with independent observations or validate case classification.",
                      "ERA5 profiles and diagnostics remain reanalysis-derived; surface and height approximations remain in effect."]}
    (args.out_dir/"phase1c_audit.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    md=["# Phase 1C — Physical Plausibility & Cross-file Audit","",f"**Status: {status}**","",
        "## Summary","",f"- Profile groups: {len(pkeys)}",f"- Diagnostic groups: {len(dkeys)}",
        f"- Profile groups without diagnostics: {len(pkeys-dkeys)}",f"- Diagnostic groups without profiles: {len(dkeys-pkeys)}",
        f"- Profile flags: {len(pflags)}",f"- Diagnostic flags: {len(dflags)}",f"- Integrity findings: {len(integrity)}",
        f"- Missing profile values detailed: {len(missing_value_detail)}","",
        "## Flag summary","",markdown_table(flag_summary),"",
        "## Scope and caveats","",report["audit_scope"],"",*[f"- {n}" for n in report["notes"]]]
    (args.out_dir/"phase1c_audit.md").write_text("\n".join(md),encoding="utf-8")
    print(json.dumps({"status":status,**counts,"output_dir":str(args.out_dir)},indent=2))
if __name__=="__main__": main()
