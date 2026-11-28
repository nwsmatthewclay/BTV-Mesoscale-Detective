#!/usr/bin/env python3
"""Phase 1 foundation audit for the BTV severe-weather research case set.

This audit checks metadata and acquired ERA5 file integrity without making
meteorological judgments. Missing files and questionable metadata are reported
separately from fatal structural errors.
"""
from __future__ import annotations
import argparse, csv, json, hashlib
from pathlib import Path
from datetime import datetime, timezone

EXPECTED_FILES = ("pressure_levels_full.grib", "single_levels.grib")
EXPECTED_SITES = ("KBTV", "KPBG", "KMSS", "KSLK", "KMPV", "KRUT")
EXPECTED_HOURS = 24

def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def audit_manifest(manifest_path):
    cases = read_csv(manifest_path)
    findings = []
    seen_ids, seen_dates = set(), set()
    for i, case in enumerate(cases, start=2):
        cid, date = case.get("case_id", "").strip(), case.get("event_date_utc", "").strip()
        status = []
        if not cid: status.append("missing_case_id")
        if cid in seen_ids: status.append("duplicate_case_id")
        if date:
            try: datetime.strptime(date, "%Y-%m-%d")
            except ValueError: status.append("invalid_date_format")
        else: status.append("missing_event_date")
        if date in seen_dates: status.append("duplicate_event_date_review")
        seen_ids.add(cid); seen_dates.add(date)
        findings.append({"manifest_row":i,"case_id":cid,"event_date_utc":date,
                        "description":case.get("description",""),"status":";".join(status) or "ok"})
    return cases, findings

def audit_raw(raw_dir, cases):
    rows=[]
    missing=[]
    for case in cases:
        cid,date=case.get("case_id",""),case.get("event_date_utc","")
        folder=raw_dir/cid/date
        for filename in EXPECTED_FILES:
            p=folder/filename
            exists=p.is_file()
            size=p.stat().st_size if exists else 0
            sig=False
            if exists and size>=4:
                with p.open("rb") as f: sig=f.read(4)==b"GRIB"
            status="ok" if exists and size>0 and sig else ("missing" if not exists else "invalid")
            if status!="ok": missing.append({"case_id":cid,"date":date,"file":filename,"status":status})
            rows.append({"case_id":cid,"date":date,"file":filename,"path":str(p),
                         "exists":exists,"bytes":size,"grib_signature_ok":sig,"status":status})
    return rows, missing

def audit_profiles(profile_csv):
    if not profile_csv or not profile_csv.exists():
        return {"available":False,"reason":"profile CSV not supplied or not found"}, []
    rows=read_csv(profile_csv)
    required=("case_id","date","site","valid_time_utc","pressure_hpa","temperature_c","dewpoint_c","u_ms","v_ms")
    missing_cols=[c for c in required if rows and c not in rows[0]]
    flags=[]
    if missing_cols: return {"available":True,"row_count":len(rows),"missing_columns":missing_cols}, flags
    keys=set(); counts={}
    for row in rows:
        key=(row["case_id"],row["site"],row["valid_time_utc"],row["pressure_hpa"])
        if key in keys: flags.append({"flag":"duplicate_profile_key","case_id":row["case_id"],"site":row["site"],"time":row["valid_time_utc"],"pressure_hpa":row["pressure_hpa"]})
        keys.add(key)
        counts[(row["case_id"],row["site"])]=counts.get((row["case_id"],row["site"]),0)+1
    case_ids=sorted({r["case_id"] for r in rows})
    sites=sorted({r["site"] for r in rows})
    expected_per_case_site=EXPECTED_HOURS*30
    coverage=[{"case_id":c,"site":s,"rows":counts.get((c,s),0),
               "expected_rows":expected_per_case_site,"coverage_pct":round(100*counts.get((c,s),0)/expected_per_case_site,1)}
              for c in case_ids for s in sites]
    return {"available":True,"row_count":len(rows),"case_count":len(case_ids),"cases":case_ids,
            "site_count":len(sites),"sites":sites,"expected_sites":list(EXPECTED_SITES),
            "missing_cases":sorted(set(c["case_id"] for c in cases)-set(case_ids)),
            "missing_sites":sorted(set(EXPECTED_SITES)-set(sites)),
            "duplicate_profile_keys":len(flags),"coverage_records":len(coverage)}, flags, coverage

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest",type=Path,default=Path("severe_weather_research/acquisition/case_manifest.csv"))
    ap.add_argument("--raw-dir",type=Path,default=None)
    ap.add_argument("--profiles",type=Path,default=None)
    ap.add_argument("--diagnostics",type=Path,default=None)
    ap.add_argument("--out-dir",type=Path,required=True)
    args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    cases,manifest_rows=audit_manifest(args.manifest)
    raw_rows,raw_missing=audit_raw(args.raw_dir,cases) if args.raw_dir else ([],[])
    profile_audit={"available":False,"reason":"profile CSV not supplied"}
    profile_flags=[]; coverage=[]
    if args.profiles:
        result=audit_profiles(args.profiles)
        if len(result)==3: profile_audit,profile_flags,coverage=result
        else: profile_audit,profile_flags=result
    diag_audit={"available":False,"reason":"diagnostics CSV not supplied"}
    if args.diagnostics and args.diagnostics.exists():
        rows=read_csv(args.diagnostics)
        diag_audit={"available":True,"rows":len(rows),"columns":list(rows[0]) if rows else [],
          "cases":sorted({r.get("case_id","") for r in rows}),
          "sites":sorted({r.get("site","") for r in rows}),
          "duplicate_keys":0}
        keycols=[c for c in ("case_id","date","site","valid_time_utc") if rows and c in rows[0]]
        if keycols:
            seen=set(); dups=0
            for r in rows:
                k=tuple(r.get(c) for c in keycols)
                if k in seen: dups+=1
                seen.add(k)
            diag_audit["duplicate_keys"]=dups
    manifest_bad=[r for r in manifest_rows if r["status"]!="ok"]
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"phase":"1_foundation_audit",
      "manifest":{"case_count":len(cases),"unique_case_ids":len({r.get("case_id") for r in cases}),
                 "date_count":len({r.get("event_date_utc") for r in cases}),"findings":manifest_rows,
                 "issues":manifest_bad},
      "raw_files":{"checked":len(raw_rows),"valid":sum(r["status"]=="ok" for r in raw_rows),
                  "invalid_or_missing":raw_missing},
      "profiles":profile_audit,"profile_flags":profile_flags,"profile_coverage":coverage,
      "diagnostics":diag_audit,
      "scientific_notes":["This audit checks data structure and completeness only; it does not validate storm-report timing, event classification, or meteorological interpretation.",
       "ERA5 nearest-grid profiles are reanalysis data and are not observed soundings.",
       "Event labels and case locations remain provisional until report-level verification."]}
    (args.out_dir/"phase1_foundation_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    write_csv(args.out_dir/"manifest_audit.csv",manifest_rows)
    write_csv(args.out_dir/"raw_file_audit.csv",raw_rows)
    write_csv(args.out_dir/"profile_coverage.csv",coverage)
    write_csv(args.out_dir/"profile_flags.csv",profile_flags)
    print(json.dumps({"cases":len(cases),"manifest_issues":len(manifest_bad),
      "raw_files_checked":len(raw_rows),"raw_files_valid":sum(r["status"]=="ok" for r in raw_rows),
      "profile_audit_available":profile_audit.get("available",False),"output":str(args.out_dir)},indent=2))
    # Structural manifest errors are fatal; missing acquired files are reported for review.
    return 1 if manifest_bad else 0

if __name__=="__main__":
    raise SystemExit(main())
