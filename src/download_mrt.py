"""Download the locations of all MRT/LRT station exits from data.gov.sg.

Source: Land Transport Authority (LTA), "LTA MRT Station Exit (GEOJSON)",
        via data.gov.sg, Singapore Open Data Licence.
Output: data/raw/mrt_station_exits.csv  (one row per exit: station, exit, lat, lon)

Usage (run from the project root folder):
    python src/download_mrt.py
"""

import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

DATASET_ID = "d_b39d3a0871985372d7e1637193335da5"
BASE_URL = "https://api-open.data.gov.sg/v1/public/api/datasets"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
GEOJSON_FILE = RAW_DIR / "mrt_station_exits.geojson"
OUTPUT_FILE = RAW_DIR / "mrt_station_exits.csv"

# Some exits are labelled with a station code instead of a name
# (checked against LTA's MRT system map, Oct 2026)
CODE_NAMES = {
    "Cc9": "Paya Lebar", "Cc30": "Keppel", "Cc31": "Cantonment",
    "Cc32": "Prince Edward Road", "Dt4": "Hume", "Dt18": "Telok Ayer",
    "Ne18": "Punggol Coast",
}


def get_download_url(dataset_id, max_tries=10):
    """Ask data.gov.sg to prepare the file, then wait until the link is ready."""
    start = requests.get(f"{BASE_URL}/{dataset_id}/initiate-download", timeout=30)
    start.raise_for_status()
    for attempt in range(max_tries):
        resp = requests.get(f"{BASE_URL}/{dataset_id}/poll-download", timeout=30)
        resp.raise_for_status()
        data = resp.json()["data"]
        if data.get("url"):
            return data["url"]
        print(f"  Link not ready yet (try {attempt + 1}/{max_tries}), waiting...")
        time.sleep(3)
    raise RuntimeError("Download link was not ready. Please try again later.")


def read_field(props, field):
    """Read a field such as STATION_NA from one GeoJSON feature.

    Depending on the version of the file, the value is either a normal
    property, or hidden inside an HTML table in the 'Description' property.
    """
    if field in props:
        return props[field]
    html = props.get("Description", "")
    match = re.search(rf"<th>{field}</th>\s*<td>(.*?)</td>", html)
    return match.group(1) if match else None


def geojson_to_table(geojson):
    rows = []
    for feature in geojson["features"]:
        props = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"][:2]
        rows.append({
            "station": read_field(props, "STATION_NA"),
            "exit_code": read_field(props, "EXIT_CODE"),
            "lat": lat,
            "lon": lon,
        })
    table = pd.DataFrame(rows).dropna(subset=["station"])
    # 'ADMIRALTY MRT STATION' -> 'Admiralty'
    table["station"] = (
        table["station"].str.strip()
        .str.replace(r"(?i)\s+(MRT|LRT)\s+STATION$", "", regex=True)
        .str.title()
        .replace(CODE_NAMES)
    )
    # Exits with no name yet ('Pending') get the name of the closest named station
    named = table[table["station"] != "Pending"]
    for i, row in table[table["station"] == "Pending"].iterrows():
        dist = (named["lat"] - row["lat"]) ** 2 + (named["lon"] - row["lon"]) ** 2
        table.loc[i, "station"] = named.loc[dist.idxmin(), "station"]
    return table


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if not GEOJSON_FILE.exists():
        print("Requesting download link from data.gov.sg ...")
        url = get_download_url(DATASET_ID)
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        GEOJSON_FILE.write_bytes(resp.content)
        print(f"Saved raw GeoJSON to: {GEOJSON_FILE}")
    else:
        print(f"GeoJSON already exists, skipping download: {GEOJSON_FILE}")

    geojson = json.loads(GEOJSON_FILE.read_text(encoding="utf-8"))
    exits = geojson_to_table(geojson)
    exits.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(exits):,} exits from {exits['station'].nunique()} stations to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
