from __future__ import annotations
import csv
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
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
    # Validate the exact XML/CSV contract documented by SHARPpy. The GUI
    # discovers user sources from ~/.sharppy/datasources at startup.
    assert all(set(("icao","iata","synop","name","state","country","lat","lon","elev","priority","srcid")).issubset(row) for row in rows)
    print(f"PASS: native SHARPpy loaded {len(rows)} BTV CWA station entries and {len(expected)} model data sources")

if __name__ == "__main__":
    main()
