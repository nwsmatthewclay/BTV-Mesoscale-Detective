#!/usr/bin/env python3
"""Decode pilot ERA5 GRIBs and export hourly nearest-grid profiles plus Skew-T plots."""
from __future__ import annotations
import argparse, csv, json, traceback, sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "acquisition" / "case_manifest.csv"
SITES = {"KBTV":(44.4719,-73.1533),"KPBG":(44.6500,-73.4681),"KMSS":(44.9358,-74.8458),"KSLK":(44.3853,-74.2062),"KMPV":(44.2036,-72.5623),"KRUT":(43.5294,-72.9494)}
PLOT_HOURS = (12,15,18,21)

def load_pressure_data(path):
    import cfgrib, xarray as xr
    datasets=cfgrib.open_datasets(str(path),backend_kwargs={"indexpath":""})
    groups=[ds for ds in datasets if "isobaricInhPa" in ds.coords]
    if not groups: raise RuntimeError("No pressure-level GRIB groups decoded")
    ds=xr.merge(groups,compat="override",join="outer")
    missing={"t","r","u","v"}-set(ds.data_vars)
    if missing: raise RuntimeError(f"Missing required profile fields: {sorted(missing)}")
    return ds

def nearest_grid(ds,lat,lon):
    latname="latitude" if "latitude" in ds.coords else "lat"
    lonname="longitude" if "longitude" in ds.coords else "lon"
    lats,lons=ds[latname].values,ds[lonname].values
    if lats.ndim!=1 or lons.ndim!=1: raise ValueError("Unexpected non-1D ERA5 coordinate grid")
    targetlon=lon%360 if np.nanmax(lons)>180 else lon
    iy=int(np.abs(lats-lat).argmin()); ix=int(np.abs(lons-targetlon).argmin())
    return {latname:iy,lonname:ix},float(lats[iy]),float(lons[ix])

def make_skewt(p,t,td,u,v,path,title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from metpy.plots import SkewT
    from metpy.units import units
    fig=plt.figure(figsize=(8,8)); skew=SkewT(fig,rotation=45)
    skew.plot(p*units.hPa,t*units.degC,"r",linewidth=2)
    skew.plot(p*units.hPa,td*units.degC,"g",linewidth=2)
    # Thin wind barbs manually; MetPy plot_barbs does not accept a skip kwarg.
    idx=np.arange(0,len(p),3)
    skew.plot_barbs(p[idx]*units.hPa,u[idx]*units("m/s"),v[idx]*units("m/s"),barbcolor="black")
    skew.ax.set_ylim(1000,100); skew.ax.set_xlim(-40,45)
    skew.plot_dry_adiabats(alpha=.25); skew.plot_moist_adiabats(alpha=.25); skew.plot_mixing_lines(alpha=.25)
    skew.ax.set_title(title); fig.savefig(path,dpi=140,bbox_inches="tight"); plt.close(fig)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--raw-dir",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,default=Path("profile_output"))
    args=parser.parse_args()
    import pandas as pd
    from metpy.calc import dewpoint_from_relative_humidity
    from metpy.units import units
    cases=list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    args.output_dir.mkdir(parents=True,exist_ok=True)
    plotdir=args.output_dir/"skewt"; plotdir.mkdir(exist_ok=True)
    rows=[]; statuses=[]
    for case in cases:
        cid,date=case["case_id"],case["event_date_utc"]
        file=args.raw_dir/cid/date/"pressure_levels_full.grib"
        record={"case_id":cid,"date":date,"file_exists":file.exists(),"status":"missing"}
        if not file.exists():
            record["error"]="pressure-level GRIB not found"; statuses.append(record); continue
        try:
            ds=load_pressure_data(file)
            p=np.asarray(ds.isobaricInhPa.values,dtype=float)
            times=ds.time.values
            record.update(decoded=True,variables=sorted(ds.data_vars),pressure_levels_hpa=sorted(p.tolist(),reverse=True),time_count=len(times))
            for site,(lat,lon) in SITES.items():
                idx,glat,glon=nearest_grid(ds,lat,lon)
                point=ds.isel(idx)
                for ti,stamp in enumerate(times):
                    frame=point.isel(time=ti) if "time" in point.dims else point
                    temp=np.asarray(frame["t"].values).squeeze().astype(float)-273.15
                    rh=np.clip(np.asarray(frame["r"].values).squeeze().astype(float)/100,0,1)
                    u=np.asarray(frame["u"].values).squeeze().astype(float); v=np.asarray(frame["v"].values).squeeze().astype(float)
                    dew=dewpoint_from_relative_humidity(temp*units.degC,rh*units.dimensionless).to("degC").magnitude
                    order=np.argsort(p)[::-1]; hour=int(pd.Timestamp(stamp).hour)
                    for k in order:
                        rows.append({"case_id":cid,"date":date,"site":site,"valid_time_utc":pd.Timestamp(stamp).isoformat(),"pressure_hpa":float(p[k]),"temperature_c":float(temp[k]),"dewpoint_c":float(dew[k]),"u_ms":float(u[k]),"v_ms":float(v[k]),"grid_lat":glat,"grid_lon":glon})
                    if site in ("KBTV","KPBG") and hour in PLOT_HOURS:
                        make_skewt(p,temp,dew,u,v,plotdir/f"{cid}_{site}_{hour:02d}Z.png",f"{cid} {site} {pd.Timestamp(stamp):%Y-%m-%d %H:%M UTC}")
            ds.close(); record["status"]="ok"
        except Exception as exc:
            record["status"]="processing_error"; record["error"]=repr(exc)
            print(f"ERROR processing {cid} ({date}): {exc!r}", file=sys.stderr, flush=True)
            traceback.print_exc()
        statuses.append(record)
    if rows: pd.DataFrame(rows).to_csv(args.output_dir/"hourly_profiles.csv",index=False)
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"cases":statuses,"rows_written":len(rows),"sites":list(SITES),"skewt_sites":["KBTV","KPBG"],"skewt_hours_utc":list(PLOT_HOURS)}
    (args.output_dir/"decode_profile_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"case_status":[(r["case_id"],r["status"]) for r in statuses],"rows_written":len(rows)},indent=2))
    return 0 if all(r["status"]=="ok" for r in statuses) else 1

if __name__=="__main__": raise SystemExit(main())
