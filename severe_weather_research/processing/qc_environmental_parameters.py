#!/usr/bin/env python3
"""Phase 3 QC summaries and plots for ERA5 environmental diagnostics."""
from pathlib import Path
import argparse, json, math
import numpy as np
import pandas as pd

def json_safe(value):
    """Convert NumPy/Pandas scalars and non-finite floats to strict JSON values."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return value

PARAMS = {
 "sbcape_jkg": ("CAPE", "J/kg", 0, 5000),
 "mlcape_100hpa_jkg": ("MLCAPE", "J/kg", 0, 5000),
 "mucape_300hpa_jkg": ("MUCAPE", "J/kg", 0, 6000),
 "sbcin_jkg": ("SBCIN", "J/kg", -500, 0),
 "mlcin_100hpa_jkg": ("MLCIN", "J/kg", -500, 0),
 "mucin_300hpa_jkg": ("MUCIN", "J/kg", -500, 0),
 "pwat_mm": ("PWAT", "mm", 0, 80),
 "lcl_pressure_hpa": ("LCL pressure", "hPa", 500, 1050),
 "lcl_temperature_c": ("LCL temperature", "C", -50, 40),
 "shear_0_1km_kt": ("0-1 km shear", "kt", 0, 150),
 "shear_0_3km_kt": ("0-3 km shear", "kt", 0, 150),
 "shear_0_6km_kt": ("0-6 km shear", "kt", 0, 200),
 "lapse_0_3km_c_per_km": ("0-3 km lapse rate", "C/km", -10, 15),
 "lapse_700_500_c_per_km": ("700-500 hPa lapse rate", "C/km", -10, 15),
 "freezing_level_agl_m": ("Freezing level AGL proxy", "m", 0, 10000),
 "hail_growth_layer_10_to_30c_depth_m": ("-10 to -30 C layer depth", "m", 0, 10000),
 "profile_top_agl_m": ("Profile top height proxy", "m", 0, 30000),
}

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--input",type=Path,required=True)
 ap.add_argument("--out-dir",type=Path,required=True)
 args=ap.parse_args()
 args.out_dir.mkdir(parents=True,exist_ok=True)
 df=pd.read_csv(args.input)
 required=["case_id","date","site","valid_time_utc"]
 missing=[c for c in required if c not in df.columns]
 if missing: raise SystemExit(f"Missing required key columns: {missing}")
 df["valid_time_utc"]=pd.to_datetime(df["valid_time_utc"],errors="coerce",utc=True)
 duplicate_count=int(df.duplicated(required).sum())
 summary=[]; flags=[]
 for col,(name,unit,low,high) in PARAMS.items():
  if col not in df: 
   summary.append({"parameter":col,"label":name,"unit":unit,"present":False})
   flags.append({"parameter":col,"flag":"column_missing"})
   continue
  vals=pd.to_numeric(df[col],errors="coerce")
  finite=vals[np.isfinite(vals)]
  row={"parameter":col,"label":name,"unit":unit,"present":True,"valid_count":int(finite.size),
       "coverage_pct":round(100*finite.size/len(df),2),"min":float(finite.min()) if len(finite) else None,
       "p05":float(finite.quantile(.05)) if len(finite) else None,"median":float(finite.median()) if len(finite) else None,
       "mean":float(finite.mean()) if len(finite) else None,"p95":float(finite.quantile(.95)) if len(finite) else None,
       "max":float(finite.max()) if len(finite) else None,"unit":unit,
       "outside_sanity_bounds":int(((finite<low)|(finite>high)).sum())}
  summary.append(row)
  bad=vals.notna()&((vals<low)|(vals>high))
  for idx in df.index[bad]:
   flags.append({"parameter":col,"flag":"outside_sanity_bounds","case_id":df.at[idx,"case_id"],"site":df.at[idx,"site"],"time":str(df.at[idx,"valid_time_utc"]),"value":float(vals.at[idx])})
 # Group means by case and parameter
 group_rows=[]
 for case,group in df.groupby("case_id"):
  for col in PARAMS:
   if col in group:
    s=pd.to_numeric(group[col],errors="coerce")
    group_rows.append({"case_id":case,"parameter":col,"n":int(s.notna().sum()),"mean":float(s.mean()) if s.notna().any() else None,"median":float(s.median()) if s.notna().any() else None})
 pd.DataFrame(summary).to_csv(args.out_dir/"parameter_qc_summary.csv",index=False)
 pd.DataFrame(group_rows).to_csv(args.out_dir/"case_parameter_summary.csv",index=False)
 pd.DataFrame(flags).to_csv(args.out_dir/"qc_flags.csv",index=False)
 report={"row_count":len(df),"duplicate_key_rows":duplicate_count,"case_count":int(df.case_id.nunique()),"site_count":int(df.site.nunique()),"timestamp_parse_failures":int(df.valid_time_utc.isna().sum()),"parameter_summary":summary,"flag_count":len(flags),"flag_types":pd.Series([f.get("flag") for f in flags]).value_counts().to_dict()}
 (args.out_dir/"qc_report.json").write_text(json.dumps(json_safe(report),indent=2,allow_nan=False))
 print(json.dumps({"rows":len(df),"duplicates":duplicate_count,"flags":len(flags),"summary_file":"parameter_qc_summary.csv","case_file":"case_parameter_summary.csv"},indent=2))
if __name__=="__main__": main()
