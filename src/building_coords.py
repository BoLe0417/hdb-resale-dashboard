"""Get the location of HDB blocks from the NUS 3D HDB building dataset.

Source: NUS Urban Analytics Lab, "3D city model of Singapore public housing
        (HDB) buildings" (hdb3d-data, MIT licence), built from HDB, OpenStreetMap
        and OneMap data. https://github.com/ualsg/hdb3d-data
        Dataset version 2019-08-25, so blocks finished after mid-2019 are missing;
        src/geocode_blocks.py looks those up with OneMap.

Input : downloads hdb.json (about 90 MB) to data/raw/ (not tracked by Git)
Output: data/external/hdb3d_block_centroids.csv
        (block, street_name, lat, lon, year_completed)

Usage (run from the project root folder):
    python src/building_coords.py
"""

import json
import math
from pathlib import Path

import pandas as pd
import requests

URL = "https://raw.githubusercontent.com/ualsg/hdb3d-data/master/hdb.json"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = PROJECT_ROOT / "data" / "raw" / "hdb3d.json"
OUT_FILE = PROJECT_ROOT / "data" / "external" / "hdb3d_block_centroids.csv"

# SVY21 (EPSG:3414) is Singapore's map grid, in metres. These are its official
# Transverse Mercator settings on the WGS84 ellipsoid.
A = 6378137.0
F = 1 / 298.257223563
LAT0 = math.radians(1 + 22 / 60)            # 1 deg 22' N
LON0 = math.radians(103 + 50 / 60)          # 103 deg 50' E
FALSE_E = 28001.642
FALSE_N = 38744.572
K0 = 1.0


def meridian_arc(lat):
    """Distance along the meridian from the equator to latitude `lat` (radians)."""
    e2 = 2 * F - F * F
    e4, e6 = e2 * e2, e2 ** 3
    return A * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lat)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
        - (35 * e6 / 3072) * math.sin(6 * lat)
    )


def svy21_to_wgs84(x, y):
    """Convert SVY21 easting/northing (metres) to latitude/longitude (degrees).

    Standard inverse Transverse Mercator formulas (Snyder 1987, p. 63).
    """
    e2 = 2 * F - F * F
    ep2 = e2 / (1 - e2)
    m = meridian_arc(LAT0) + (y - FALSE_N) / K0
    mu = m / (A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    lat1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(lat1) ** 2
    t1 = math.tan(lat1) ** 2
    n1 = A / math.sqrt(1 - e2 * math.sin(lat1) ** 2)
    r1 = A * (1 - e2) / (1 - e2 * math.sin(lat1) ** 2) ** 1.5
    d = (x - FALSE_E) / (n1 * K0)
    lat = lat1 - (n1 * math.tan(lat1) / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720
    )
    lon = LON0 + (
        d - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120
    ) / math.cos(lat1)
    return math.degrees(lat), math.degrees(lon)


def vertex_ids(boundaries, out):
    """CityJSON nests vertex numbers in lists of lists; collect them all."""
    if isinstance(boundaries, int):
        out.append(boundaries)
    else:
        for part in boundaries:
            vertex_ids(part, out)
    return out


def main():
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not RAW_FILE.exists():
        print("Downloading hdb.json from GitHub (about 90 MB) ...")
        resp = requests.get(URL, timeout=600)
        resp.raise_for_status()
        RAW_FILE.write_bytes(resp.content)

    city = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    vertices = city["vertices"]

    rows = []
    for building in city["CityObjects"].values():
        attr = building["attributes"]
        if not attr.get("hdb_blk_no"):
            continue
        ids = []
        for geometry in building["geometry"]:
            vertex_ids(geometry["boundaries"], ids)
        # Centre of the building = average of its corner points
        x = sum(vertices[i][0] for i in ids) / len(ids)
        y = sum(vertices[i][1] for i in ids) / len(ids)
        lat, lon = svy21_to_wgs84(x, y)
        rows.append({
            "block": str(attr["hdb_blk_no"]).strip(),
            "street_name": str(attr["hdb_street"]).strip(),
            "lat": lat, "lon": lon,
            "year_completed": attr.get("hdb_year_completed"),
        })

    blocks = (
        pd.DataFrame(rows)
        .groupby(["block", "street_name"], as_index=False)
        .agg(lat=("lat", "mean"), lon=("lon", "mean"), year_completed=("year_completed", "first"))
    )
    blocks["lat"] = blocks["lat"].round(6)
    blocks["lon"] = blocks["lon"].round(6)
    blocks.to_csv(OUT_FILE, index=False)
    print(f"Saved {len(blocks):,} block locations to: {OUT_FILE}")


if __name__ == "__main__":
    main()
