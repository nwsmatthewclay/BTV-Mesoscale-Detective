from __future__ import annotations
import csv
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / "btv_cwa.xml"
CSV = ROOT / "btv_cwa.csv"

def main():
    root = ET.parse(XML).getroot()
    sources = {node.attrib["name"]: node for node in root.findall("datasource")}
    expected = {"BTV CWA RRFS", "BTV CWA GFS", "BTV CWA RAP", "BTV CWA HRRR"}
    assert set(sources) == expected, sources.keys()
    with CSV.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) >= 20, len(rows)
    assert len({row["srcid"] for row in rows}) == len(rows)
    assert all(row["lat"] and row["lon"] and row["srcid"] for row in rows)
    for name, node in sources.items():
        outlet = node.find("outlet")
        assert outlet is not None and outlet.attrib["format"] == "bufkit"
        assert "{srcid}" in outlet.attrib["url"]
        assert node.find("outlet/points").attrib["csv"] == "btv_cwa.csv"
    # Verify SHARPpy itself can load the source XML and station CSV.
    from sharppy.datasources.data_source import loadDataSources
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp)
        (target / "btv_cwa.xml").write_bytes(XML.read_bytes())
        (target / "btv_cwa.csv").write_bytes(CSV.read_bytes())
        loaded = loadDataSources(ds_dir=str(target))
        assert expected.issubset(loaded.keys()), loaded.keys()
    print(f"PASS: native SHARPpy loaded {len(rows)} BTV CWA station entries and {len(expected)} model data sources")

if __name__ == "__main__":
    main()
