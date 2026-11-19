import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from archive_bufkit import parse_cycle

def test_screenshot_station_catalog_has_all_32_exact_ids():
    config=json.loads((Path(__file__).resolve().parents[1]/"bufkit_sites.json").read_text())
    ids=[station["id"] for station in config["stations"]]
    assert len(ids)==32
    assert len(set(ids))==32
    assert ids==["KBTV","KPBG","KMPV","KEFK","RUT","KMSS","KSLK","KMVL","VSF","OGS","MALO","1V4","ALBU","CLCR","GTB","JAYV","KALB","KBGR","KBHB","KCAR","KFVE","KGFL","KHUL","KLEB","KLGN","KPOU","KPQI","KPSF","LO1","MCGL","NUND","RIPT"]

def test_parse_cycle_extracts_model_cycle_and_forecast_hours():
    sample="""STID = KBTV    TIME = 261119/1200
STIM = 0.0
PRES TMPC DWPC HGHT
1000 10.0 5.0 100
STID = KBTV    TIME = 261119/1500
STIM = 3.0
PRES TMPC DWPC HGHT
1000 12.0 6.0 100
"""
    cycle,station,records=parse_cycle(sample)
    assert station=="KBTV"
    assert cycle=="2026-11-19T12:00:00Z"
    assert [r["forecast_hour"] for r in records]==[0.0,3.0]
