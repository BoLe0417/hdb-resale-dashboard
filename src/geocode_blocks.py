"""Find the latitude/longitude of every HDB block in the resale data.

Step 1: use block centres from the NUS 3D HDB dataset (src/building_coords.py).
        This covers about 90% of addresses (blocks finished up to mid-2019).
Step 2: look up the remaining (newer) blocks with the OneMap Search API
        (Singapore Land Authority). OneMap limits how fast you may search
        without an account, so this step goes slowly and pauses when asked to.
        If you have a free OneMap API token, put it in a file called .env as
            ONEMAP_TOKEN=your_token_here
        (.env is in .gitignore, so the token is never uploaded).

Only addresses that are not yet in the output file are looked up, so you can
stop the script at any time and run it again later to continue.

Input : data/raw/hdb_resale_2017_onwards.csv
        data/external/hdb3d_block_centroids.csv
Output: data/external/block_coordinates.csv
        (block, street_name, lat, lon, source, matched_address, match)

Usage (run from the project root folder):
    python src/building_coords.py
    python src/geocode_blocks.py
"""

import os
import re
import time

import numpy as np
from pathlib import Path

import pandas as pd
import requests

SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
SECONDS_BETWEEN_CALLS = 1.0    # go slowly: OneMap limits searches without an account
PAUSE_WHEN_LIMITED = 60        # seconds to wait when OneMap says "too many requests"
SAVE_EVERY = 25                # write progress to disk every 25 addresses

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = PROJECT_ROOT / "data" / "raw" / "hdb_resale_2017_onwards.csv"
OUT_DIR = PROJECT_ROOT / "data" / "external"
HDB3D_FILE = OUT_DIR / "hdb3d_block_centroids.csv"
OUT_FILE = OUT_DIR / "block_coordinates.csv"
ENV_FILE = PROJECT_ROOT / ".env"

COLUMNS = ["block", "street_name", "lat", "lon", "source", "matched_address", "match"]

# HDB shortens street names ('BT PANJANG RING RD'). If a search finds
# nothing, we try again with the words written out in full.
ABBREVIATIONS = {
    "AVE": "AVENUE", "BT": "BUKIT", "C'WEALTH": "COMMONWEALTH", "CL": "CLOSE",
    "CRES": "CRESCENT", "CTRL": "CENTRAL", "CTR": "CENTRE", "DR": "DRIVE",
    "GDNS": "GARDENS", "HTS": "HEIGHTS", "JLN": "JALAN", "KG": "KAMPONG",
    "LOR": "LORONG", "MKT": "MARKET", "NTH": "NORTH", "PK": "PARK", "PL": "PLACE",
    "RD": "ROAD", "SQ": "SQUARE", "ST": "STREET", "STH": "SOUTH", "TER": "TERRACE",
    "TG": "TANJONG", "UPP": "UPPER", "ST.": "SAINT",
}
OUTLIER_KM = 2.0   # a block this far from every other block in its town is suspicious


def expand(street):
    return " ".join(ABBREVIATIONS.get(word, word) for word in street.split())


def same_road(street, address):
    """True if a OneMap address is on the same road as the HDB street name."""
    def letters(text):
        return re.sub(r"[^A-Z0-9]", "", str(text).upper())
    return letters(expand(street)) in letters(address)


def read_token():
    """Read ONEMAP_TOKEN from the environment or from the .env file, if there is one."""
    token = os.environ.get("ONEMAP_TOKEN")
    if not token and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ONEMAP_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"')
    return token


session = requests.Session()   # reuses the connection, which is faster
TOKEN = read_token()
if TOKEN:
    session.headers["Authorization"] = TOKEN


def search(text):
    """Return the list of OneMap results for a search text (may be empty)."""
    params = {"searchVal": text, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1}
    for attempt in range(6):
        time.sleep(SECONDS_BETWEEN_CALLS)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=15)
            if resp.status_code == 429:
                print(f"  OneMap says too many requests, pausing {PAUSE_WHEN_LIMITED} s ...")
                time.sleep(PAUSE_WHEN_LIMITED)
                continue
            resp.raise_for_status()
            return resp.json().get("results", [])
        except (requests.RequestException, ValueError) as err:
            print(f"  Problem with '{text}': {err}. Retrying ...")
            time.sleep(5)
    raise RuntimeError("OneMap is not answering. Please run this script again later.")


def geocode(block, street):
    """Look up one HDB block. Only accept a result with the same block AND road."""
    for text, how in [(f"{block} {street}", "exact"), (f"{block} {expand(street)}", "expanded")]:
        for r in search(text):
            if r.get("BLK_NO", "").upper() == block.upper() and same_road(street, r.get("ADDRESS")):
                return {
                    "lat": float(r["LATITUDE"]),
                    "lon": float(r["LONGITUDE"]),
                    "source": "onemap",
                    "matched_address": r.get("ADDRESS"),
                    "match": how,
                }
    return {"lat": None, "lon": None, "source": "onemap", "matched_address": None,
            "match": "not_found"}


def find_outliers(coords, addresses):
    """Blocks that are more than OUTLIER_KM from every other block in the same town.

    HDB towns are compact, so such a block was almost surely put in the wrong place
    (e.g. a different road with a similar name).
    """
    data = coords.merge(addresses, on=["block", "street_name"]).dropna(subset=["lat", "lon"])
    flagged = []
    for _, town in data.groupby("town"):
        lat = town["lat"].to_numpy()[:, None]
        lon = town["lon"].to_numpy()[:, None]
        km = np.hypot((lat - lat.T) * 111.3, (lon - lon.T) * 111.3)
        np.fill_diagonal(km, np.inf)
        far = km.min(axis=1) > OUTLIER_KM
        flagged += list(zip(town["block"][far], town["street_name"][far]))
    return flagged


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    addresses = (
        pd.read_csv(RAW_FILE, usecols=["town", "block", "street_name"], dtype=str)
        .drop_duplicates(["block", "street_name"])
        .sort_values(["street_name", "block"])
    )

    if OUT_FILE.exists():
        done = pd.read_csv(OUT_FILE, dtype={"block": str, "street_name": str})
        # Re-check OneMap results saved by older versions of this script
        bad = (done["source"] == "onemap") & done["lat"].notna() & ~pd.Series(
            [same_road(s, a) for s, a in zip(done["street_name"], done["matched_address"])],
            index=done.index)
        if bad.any():
            print(f"Removing {bad.sum()} saved OneMap results on a different road; "
                  "they will be looked up again.")
            done = done[~bad]
    else:
        done = pd.DataFrame(columns=COLUMNS)

    # Step 1: blocks that are in the NUS 3D HDB dataset
    if HDB3D_FILE.exists():
        hdb3d = pd.read_csv(HDB3D_FILE, dtype={"block": str, "street_name": str})
        new = addresses.drop(columns="town").merge(hdb3d, on=["block", "street_name"], how="inner")
        new = new.merge(done[["block", "street_name"]], how="left", indicator=True)
        new = new[new["_merge"] == "left_only"].drop(columns="_merge")
        new = new.assign(source="hdb3d", matched_address=None, match="exact")[COLUMNS]
        done = pd.concat([done, new], ignore_index=True)
        done.to_csv(OUT_FILE, index=False)
        print(f"Step 1: {len(new):,} addresses found in the NUS 3D HDB dataset.")
    else:
        print("Step 1 skipped: run 'python src/building_coords.py' first to save time.")

    # Step 2: the rest with OneMap
    done_keys = set(zip(done["block"], done["street_name"]))
    todo = [(b, s) for b, s in zip(addresses["block"], addresses["street_name"])
            if (b, s) not in done_keys]
    print(f"Step 2: {len(todo):,} addresses left to look up with OneMap "
          f"({'with' if TOKEN else 'without'} an API token).")

    new_rows = []
    start = time.time()
    for i, (block, street) in enumerate(todo, start=1):
        new_rows.append({"block": block, "street_name": street, **geocode(block, street)})
        if i % SAVE_EVERY == 0 or i == len(todo):
            done = pd.concat([done, pd.DataFrame(new_rows)], ignore_index=True)
            done.to_csv(OUT_FILE, index=False)
            new_rows = []
            minutes_left = (time.time() - start) / i * (len(todo) - i) / 60
            print(f"  {i:,}/{len(todo):,} done, about {minutes_left:.0f} min left")

    # Step 3: check for blocks that are far away from the rest of their town
    outliers = find_outliers(done, addresses)
    print(f"\nStep 3: {len(outliers)} block(s) far from the rest of their town; checking with OneMap.")
    for block, street in outliers:
        row = done[(done["block"] == block) & (done["street_name"] == street)].iloc[0]
        if row["source"] == "onemap" and str(row["match"]).endswith("_checked"):
            continue                       # already checked in an earlier run
        result = geocode(block, street)
        result["match"] = result["match"] + "_checked"
        if result["lat"] is None:
            result["match"] = "rejected_outlier"
        print(f"  {block} {street}: {result['match']} {result['matched_address'] or ''}")
        done = done[~((done["block"] == block) & (done["street_name"] == street))]
        done = pd.concat([done, pd.DataFrame([{"block": block, "street_name": street, **result}])],
                         ignore_index=True)
    done.to_csv(OUT_FILE, index=False)

    print("\nWhere the locations came from:")
    print(done.groupby(["source", "match"]).size().to_string())
    print(f"\nSaved to: {OUT_FILE}")


if __name__ == "__main__":
    main()
