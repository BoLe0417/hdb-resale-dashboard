"""Create the summary tables quoted in the README and the presentation.

Input : data/processed/hdb_resale_clean.parquet   (from src/wrangle.py)
Output: outputs/tables/*.csv

Usage (run from the project root folder):
    python src/make_tables.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "processed" / "hdb_resale_clean.parquet"
TABLE_DIR = PROJECT_ROOT / "outputs" / "tables"

BASE_YEAR = 2019        # last full year before COVID
FLAT_TYPE = "4 Room"    # most common flat type, used for fair comparisons


def save(table, name):
    path = TABLE_DIR / name
    table.to_csv(path, index=False)
    print(f"\n=== {name} ===")
    print(table.to_string(index=False))


def main():
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(DATA_FILE)
    last = df["month"].max()
    end_year = last.year if last.month == 12 else last.year - 1   # last full year
    four = df[df["flat_type"] == FLAT_TYPE]

    # 1. Town growth, 4-room, 2019 vs last full year (the partial last year is excluded).
    #    For both total price and price per sqm: medians, % change and S$ change.
    pieces = []
    for col, name in [("resale_price", "price"), ("price_per_sqm", "psm")]:
        by_town = (
            four[four["year"].isin([BASE_YEAR, end_year])]
            .groupby(["town", "year"])[col].agg(["median", "count"])
            .unstack("year")
        )
        by_town = by_town[(by_town["count"] >= 20).all(axis=1)]
        part = pd.DataFrame({
            f"{name}_{BASE_YEAR}": by_town[("median", BASE_YEAR)],
            f"{name}_{end_year}": by_town[("median", end_year)],
        })
        part[f"{name}_pct_change"] = (
            part[f"{name}_{end_year}"] / part[f"{name}_{BASE_YEAR}"] - 1).mul(100).round(1)
        part[f"{name}_sgd_change"] = (part[f"{name}_{end_year}"] - part[f"{name}_{BASE_YEAR}"]).round(0)
        pieces.append(part)
    growth = pd.concat(pieces, axis=1).reset_index()
    growth["rank_pct"] = growth["price_pct_change"].rank(ascending=False).astype(int)
    growth["rank_sgd"] = growth["price_sgd_change"].rank(ascending=False, method="min").astype(int)
    save(growth.sort_values("price_pct_change", ascending=False), "town_growth_4room.csv")

    # 1b. Year-by-year % change from 2019 (all towns, 4-room, full years only)
    yearly = (
        four[four["year"].between(BASE_YEAR, end_year)]
        .groupby("year")[["resale_price", "price_per_sqm"]].median()
    )
    yearly["price_pct_vs_2019"] = (yearly["resale_price"] / yearly.loc[BASE_YEAR, "resale_price"] - 1).mul(100).round(1)
    yearly["psm_pct_vs_2019"] = (yearly["price_per_sqm"] / yearly.loc[BASE_YEAR, "price_per_sqm"] - 1).mul(100).round(1)
    save(yearly.reset_index(), "yearly_change_vs_2019_4room.csv")

    # 2. Million-dollar flats per year (all flat types)
    million = df.groupby("year", as_index=False)["is_million"].sum()
    million["full_year"] = million["year"] <= end_year
    save(million.rename(columns={"is_million": "flats_sold_1m_plus"}), "million_dollar_flats.csv")

    if "mrt_dist_m" not in df.columns:
        print("\nNo location columns, skipping MRT tables.")
        return

    # 3. Price per sqm by distance to MRT (4-room, last full year)
    recent = four[four["year"] == end_year]
    mrt = (
        recent.dropna(subset=["mrt_band"])
        .groupby("mrt_band", observed=True)
        .agg(median_price_per_sqm=("price_per_sqm", "median"),
             median_price=("resale_price", "median"),
             median_lease_left=("remaining_lease_years", "median"),
             sales=("resale_price", "size"))
        .reset_index()
    )
    save(mrt, f"mrt_band_4room_{end_year}.csv")

    # 4. Regression: all flat types, all years
    m = df.dropna(subset=["mrt_dist_m", "cbd_dist_km"]).copy()
    m["log_price"] = np.log(m["resale_price"])
    m["mrt_100m"] = m["mrt_dist_m"] / 100
    m["lease_10y"] = m["remaining_lease_years"] / 10
    m["floor_10"] = m["storey_mid"] / 10
    m["area_10sqm"] = m["floor_area_sqm"] / 10
    result = smf.ols(
        "log_price ~ area_10sqm + lease_10y + floor_10 + mrt_100m + cbd_dist_km"
        " + C(flat_type) + C(year)",
        data=m,
    ).fit(cov_type="HC1")
    names = ["area_10sqm", "lease_10y", "floor_10", "mrt_100m", "cbd_dist_km"]
    ci = result.conf_int()
    effects = pd.DataFrame({
        "variable": names,
        "coef": result.params[names].round(4).values,
        "pct_effect": (100 * (np.exp(result.params[names]) - 1)).round(2).values,
        "ci_low_pct": (100 * (np.exp(ci.loc[names, 0]) - 1)).round(2).values,
        "ci_high_pct": (100 * (np.exp(ci.loc[names, 1]) - 1)).round(2).values,
    })
    save(effects, "regression_effects.csv")
    print(f"\nR-squared: {result.rsquared:.3f}, observations: {int(result.nobs):,}")


if __name__ == "__main__":
    main()
