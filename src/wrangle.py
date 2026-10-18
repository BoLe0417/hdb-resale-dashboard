"""Clean the raw HDB resale data and save an analysis-ready file.

Input : data/raw/hdb_resale_2017_onwards.csv   (from src/download_data.py)
        data/raw/mrt_station_exits.csv          (from src/download_mrt.py, optional)
        data/external/block_coordinates.csv     (from src/building_coords.py +
                                                 src/geocode_blocks.py, optional)
Output: data/processed/hdb_resale_clean.parquet

If the two optional files exist, location columns are added:
lat, lon, nearest_mrt, mrt_dist_m, mrt_band, cbd_dist_km.

Usage (run from the project root folder):
    python src/wrangle.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = PROJECT_ROOT / "data" / "raw" / "hdb_resale_2017_onwards.csv"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_FILE = PROCESSED_DIR / "hdb_resale_clean.parquet"
MRT_FILE = PROJECT_ROOT / "data" / "raw" / "mrt_station_exits.csv"
COORDS_FILE = PROJECT_ROOT / "data" / "external" / "block_coordinates.csv"

# Raffles Place MRT station, used as the centre of the CBD
CBD_LAT, CBD_LON = 1.28393, 103.85144

MRT_BINS = [0, 400, 800, 1200, 100_000]
MRT_LABELS = ["< 400 m", "400-799 m", "800-1,199 m", "1,200 m +"]

# HDB groups towns into "mature" (older, well-established) and
# "non-mature" (newer) estates. Checked on 12 Oct 2026 against HDB's own list
# (hdb.gov.sg, Annex A1, Aug 2023: 15 mature estates). Towns not listed here,
# e.g. Tengah or Punggol, are non-mature.
MATURE_TOWNS = {
    "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT MERAH", "BUKIT TIMAH",
    "CENTRAL AREA", "CLEMENTI", "GEYLANG", "KALLANG/WHAMPOA",
    "MARINE PARADE", "PASIR RIS", "QUEENSTOWN", "SERANGOON",
    "TAMPINES", "TOA PAYOH",
}

LEASE_BINS = [0, 60, 70, 80, 90, 100]
LEASE_LABELS = ["< 60 yrs", "60-69 yrs", "70-79 yrs", "80-89 yrs", "90+ yrs"]


def lease_to_years(text):
    """Convert text like '61 years 04 months' or '91 years' to 61.33 / 91.0."""
    parts = str(text).split()
    years = int(parts[0])
    months = int(parts[2]) if len(parts) >= 4 else 0
    return round(years + months / 12, 2)


def storey_to_mid(text):
    """Convert '10 TO 12' to its middle floor, 11."""
    low, high = text.split(" TO ")
    return (int(low) + int(high)) / 2


def distance_m(lat1, lon1, lat2, lon2):
    """Straight-line (great-circle) distance in metres. Works on arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6_371_000 * 2 * np.arcsin(np.sqrt(a))


def location_features():
    """One row per block: coordinates, nearest MRT station and distances.

    Returns None if the location files have not been created yet.
    """
    if not (MRT_FILE.exists() and COORDS_FILE.exists()):
        print("  Location files not found, skipping MRT / CBD distances.")
        print("  (Run src/download_mrt.py, src/building_coords.py and "
              "src/geocode_blocks.py to add them.)")
        return None

    exits = pd.read_csv(MRT_FILE)
    blocks = pd.read_csv(COORDS_FILE, dtype={"block": str, "street_name": str})
    blocks = blocks.dropna(subset=["lat", "lon"]).copy()

    # Distance from every block (rows) to every MRT exit (columns)
    dist = distance_m(
        blocks["lat"].to_numpy()[:, None], blocks["lon"].to_numpy()[:, None],
        exits["lat"].to_numpy()[None, :], exits["lon"].to_numpy()[None, :],
    )
    nearest = dist.argmin(axis=1)
    blocks["nearest_mrt"] = exits["station"].to_numpy()[nearest]
    blocks["mrt_dist_m"] = dist.min(axis=1).round(0)
    blocks["mrt_band"] = pd.cut(
        blocks["mrt_dist_m"], bins=MRT_BINS, labels=MRT_LABELS, right=False
    )
    blocks["cbd_dist_km"] = (
        distance_m(blocks["lat"], blocks["lon"], CBD_LAT, CBD_LON) / 1000
    ).round(2)
    print(f"  Location found for {len(blocks):,} blocks "
          f"(nearest of {exits['station'].nunique()} MRT/LRT stations)")
    return blocks[["block", "street_name", "lat", "lon", "nearest_mrt",
                   "mrt_dist_m", "mrt_band", "cbd_dist_km"]]


def clean(df):
    df = df.copy()

    # 1. Dates: '2017-01' -> a real date, plus year and quarter helpers
    df["month"] = pd.to_datetime(df["month"], format="%Y-%m")
    df["year"] = df["month"].dt.year
    df["quarter"] = df["month"].dt.to_period("Q").dt.start_time

    # 2. Text columns that are really numbers
    df["remaining_lease_years"] = df["remaining_lease"].apply(lease_to_years)
    df["storey_mid"] = df["storey_range"].apply(storey_to_mid)

    # 3. Make sure numeric columns are numeric (API values can arrive as text)
    for col in ["floor_area_sqm", "resale_price", "lease_commence_date"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 4. New variables for the analysis
    df["price_per_sqm"] = (df["resale_price"] / df["floor_area_sqm"]).round(0)
    df["flat_age"] = df["year"] - df["lease_commence_date"]
    df["estate_type"] = df["town"].apply(
        lambda t: "Mature" if t in MATURE_TOWNS else "Non-mature"
    )
    df["lease_band"] = pd.cut(
        df["remaining_lease_years"], bins=LEASE_BINS, labels=LEASE_LABELS, right=False
    )
    df["is_million"] = df["resale_price"] >= 1_000_000

    # 5. Location: join coordinates and distances on block + street
    locations = location_features()
    if locations is not None:
        df["block"] = df["block"].astype(str)
        df = df.merge(locations, on=["block", "street_name"], how="left")
        missing = df["mrt_dist_m"].isna().mean() * 100
        print(f"  {missing:.1f}% of transactions have no location (block not geocoded)")

    # 6. Nicer labels for charts: 'ANG MO KIO' -> 'Ang Mo Kio'
    df["town"] = df["town"].str.title().str.replace("/", " / ")
    df["flat_type"] = df["flat_type"].str.title()

    # 7. Drop rows we cannot use (none expected, but check anyway)
    before = len(df)
    df = df.dropna(subset=["resale_price", "floor_area_sqm", "remaining_lease_years"])
    print(f"  Dropped {before - len(df)} rows with missing key values")

    keep = [
        "month", "year", "quarter", "town", "estate_type", "flat_type",
        "flat_model", "block", "street_name", "storey_range", "storey_mid",
        "floor_area_sqm", "lease_commence_date", "remaining_lease_years",
        "lease_band", "flat_age", "resale_price", "price_per_sqm", "is_million",
    ]
    if locations is not None:
        keep += ["lat", "lon", "nearest_mrt", "mrt_dist_m", "mrt_band", "cbd_dist_km"]
    return df[keep]


def main():
    if not RAW_FILE.exists():
        raise FileNotFoundError(
            f"{RAW_FILE} not found. Run 'python src/download_data.py' first."
        )

    print(f"Reading {RAW_FILE.name} ...")
    raw = pd.read_csv(RAW_FILE, dtype={"block": str})
    print(f"  {len(raw):,} rows, {raw.shape[1]} columns")

    print("Cleaning ...")
    clean_df = clean(raw)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    clean_df.to_parquet(PROCESSED_FILE, index=False)
    print(f"Saved {len(clean_df):,} rows to {PROCESSED_FILE}")
    print(f"Date range: {clean_df['month'].min():%Y-%m} to {clean_df['month'].max():%Y-%m}")


if __name__ == "__main__":
    main()
