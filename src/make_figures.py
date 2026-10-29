"""Create the static figures used in the presentation deck and the README.

Input : data/processed/hdb_resale_clean.parquet   (from src/wrangle.py)
        data/raw/mrt_station_exits.csv            (from src/download_mrt.py)
Output: outputs/figures/*.png

The figures use the same definitions as src/make_tables.py (4-room flats,
medians, 2019 as the base year, full years only) and the same colours as the
dashboard (app.py), so numbers and colours match across README, slides and app.

Figures 01-07 are drawn with Matplotlib. Figures 08-11 use Seaborn to show
distributions (histogram + KDE, box plot, side-by-side comparison) and a
regression line with its correlation, which the interactive dashboard does
not show.

Usage (run from the project root folder):
    python src/make_figures.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")                      # draw to files only, no window
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
import seaborn as sns

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "processed" / "hdb_resale_clean.parquet"
MRT_FILE = PROJECT_ROOT / "data" / "raw" / "mrt_station_exits.csv"
FIG_DIR = PROJECT_ROOT / "outputs" / "figures"

BASE_YEAR = 2019        # last full year before COVID
FLAT_TYPE = "4 Room"    # most common flat type, used for fair comparisons
MIN_SALES = 20          # towns with fewer sales in a year are left out of rankings
MRT_ORDER = ["< 400 m", "400-799 m", "800-1,199 m", "1,200 m +"]

# Same colours as app.py, so slides and dashboard look the same
BLUE = "#2a78d6"
LIGHT_BLUE = "#9ec5f4"
ORANGE = "#eb6834"
INK = "#17283b"          # main text
MUTED = "#5b6b7d"        # secondary text, axis labels
GRID = "#e3e8ee"
PRICE_SCALE = ["#dbe9fb", "#9ec5f4", "#5a9be6", "#2a78d6", "#1a5aa8", "#123d73"]

plt.rcParams.update({
    "figure.figsize": (10, 5.625),        # 16:9, fits a full slide
    "figure.dpi": 100,
    "savefig.dpi": 200,
    "font.size": 13,
    "axes.titlesize": 17,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 30,                   # room for the subtitle under the title
    "axes.labelcolor": MUTED,
    "axes.edgecolor": GRID,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,              # gridlines behind the bars
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": INK,
})


def money(x, _=None):
    """$630k style labels for axes."""
    return f"${x / 1000:,.0f}k"


def subtitle(ax, text):
    """Grey line under the title saying what is plotted."""
    ax.text(0, 1.02, text, transform=ax.transAxes, fontsize=12, color=MUTED, va="bottom")


def source(fig, text="Source: HDB resale flat prices (data.gov.sg), Jan 2017 – Oct 2026"):
    fig.text(0.01, -0.03, text, fontsize=9, color=MUTED, va="top")


def save(fig, name):
    path = FIG_DIR / name
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"saved {path.relative_to(PROJECT_ROOT)}")


def last_full_year(df):
    last = df["month"].max()
    return last.year if last.month == 12 else last.year - 1


# ---------------------------------------------------------------------------
# 1. Price trend
# ---------------------------------------------------------------------------
def fig_price_trend(four, end_year):
    """Quarterly median 4-room price, with the 2019 level marked."""
    q = four.groupby("quarter")["resale_price"].median()
    # Drop the last quarter if it is not complete (e.g. only October)
    months_in_last_q = four.loc[four["quarter"] == q.index.max(), "month"].nunique()
    if months_in_last_q < 3:
        q = q.iloc[:-1]

    base = four.loc[four["year"] == BASE_YEAR, "resale_price"].median()
    end = four.loc[four["year"] == end_year, "resale_price"].median()

    fig, ax = plt.subplots()
    ax.plot(q.index, q.values, color=BLUE, linewidth=2.5)
    ax.axhline(base, color=MUTED, linewidth=1, linestyle="--")
    ax.text(pd.Timestamp("2023-01-01"), base - 6000, f"{BASE_YEAR} median: {money(base)}",
            color=MUTED, fontsize=11, va="top")
    ax.axvspan(pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01"), color=GRID, alpha=0.6, zorder=0)
    ax.text(pd.Timestamp("2020-07-01"), q.max(), "COVID-19\n(2020)",
            ha="center", va="top", fontsize=10, color=MUTED)
    ax.annotate(f"{end_year} median: {money(end)}\n+{(end / base - 1) * 100:.0f}% vs {BASE_YEAR}",
                xy=(q.index[-1], q.values[-1]), xytext=(-10, 10), textcoords="offset points",
                ha="right", va="bottom", fontsize=12, color=INK, fontweight="bold")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(money))
    ax.set_title(f"4-room prices rose {(end / base - 1) * 100:.0f}% from {BASE_YEAR} to {end_year}, then levelled off")
    subtitle(ax, "Median resale price per quarter, 4-room flats, all towns")
    source(fig)
    save(fig, "01_price_trend_4room.png")


# ---------------------------------------------------------------------------
# 2. Town growth: % change ranking, with S$ change as a label
# ---------------------------------------------------------------------------
def town_growth(four, end_year):
    by_town = (
        four[four["year"].isin([BASE_YEAR, end_year])]
        .groupby(["town", "year"])["resale_price"].agg(["median", "count"])
        .unstack("year")
    )
    by_town = by_town[(by_town["count"] >= MIN_SALES).all(axis=1)]
    g = pd.DataFrame({
        "p0": by_town[("median", BASE_YEAR)],
        "p1": by_town[("median", end_year)],
    })
    g["pct"] = (g["p1"] / g["p0"] - 1) * 100
    g["sgd"] = g["p1"] - g["p0"]
    g["rank_pct"] = g["pct"].rank(ascending=False).astype(int)
    g["rank_sgd"] = g["sgd"].rank(ascending=False, method="min").astype(int)
    return g


def fig_town_ranking(g, end_year):
    g = g.sort_values("pct")
    fig, ax = plt.subplots(figsize=(10, 9))
    ax.barh(g.index, g["pct"], color=BLUE, height=0.7)
    for town, row in g.iterrows():
        ax.text(row["pct"] + 1, town, f"+{row['pct']:.0f}%   (+{money(row['sgd'])})",
                va="center", fontsize=10.5, color=INK)
    ax.set_xlim(0, g["pct"].max() * 1.35)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0, labelsize=11, labelcolor=INK)
    ax.set_title(f"Which towns' prices grew most, {BASE_YEAR} → {end_year}?")
    subtitle(ax, f"Change in median 4-room resale price: % (bar) and S$ (in brackets). "
                 f"Towns with < {MIN_SALES} sales left out")
    source(fig)
    save(fig, "02_town_growth_ranking.png")


def fig_pct_vs_sgd(g, end_year):
    """Ranking by % and by S$ give different answers."""
    highlight = ["Central Area", "Sembawang", "Clementi", "Toa Payoh",
                 "Queenstown", "Bukit Merah", "Yishun", "Marine Parade"]
    highlight = [t for t in highlight if t in g.index]
    other = g.drop(index=highlight)
    hi = g.loc[highlight]

    fig, ax = plt.subplots()
    ax.scatter(other["pct"], other["sgd"], s=70, color=LIGHT_BLUE,
               edgecolor="white", linewidth=1.5, zorder=2)
    ax.scatter(hi["pct"], hi["sgd"], s=90, color=BLUE,
               edgecolor="white", linewidth=1.5, zorder=3)
    offsets = {"Central Area": (-8, -4, "right"), "Queenstown": (6, 16, "left"),
               "Bukit Merah": (8, -16, "left"), "Marine Parade": (8, 14, "left"),
               "Yishun": (8, -10, "left"), "Sembawang": (0, 22, "right"),
               "Clementi": (8, 0, "left"), "Toa Payoh": (8, 0, "left")}
    for town, row in hi.iterrows():
        dx, dy, ha = offsets.get(town, (8, 0, "left"))
        ax.annotate(f"{town}\n#{int(row['rank_pct'])} by %, #{int(row['rank_sgd'])} by S$",
                    xy=(row["pct"], row["sgd"]), xytext=(dx, dy), textcoords="offset points",
                    ha=ha, va="center", fontsize=9.5, color=INK)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(money))
    ax.set_xlabel(f"% change in median price, {BASE_YEAR} → {end_year}")
    ax.set_ylabel("S$ change in median price")
    ax.set_title("Ranking towns by % and by S$ gives different answers")
    subtitle(ax, f"Each dot is a town (4-room flats). Rank out of {len(g)} towns")
    source(fig)
    save(fig, "03_pct_vs_sgd_change.png")


# ---------------------------------------------------------------------------
# 3. Million-dollar flats
# ---------------------------------------------------------------------------
def fig_million(df, end_year):
    m = df.groupby("year")["is_million"].sum().astype(int)
    last = df["month"].max()
    colors = [BLUE if y <= end_year else LIGHT_BLUE for y in m.index]

    fig, ax = plt.subplots()
    ax.bar(m.index, m.values, color=colors, width=0.7)
    for year in [BASE_YEAR, 2021, end_year - 1, end_year] + ([last.year] if last.year > end_year else []):
        if year in m.index:
            ax.text(year, m[year] + 25, f"{m[year]:,}", ha="center", va="bottom", fontsize=11, color=INK)
    if last.year > end_year:
        ax.text(last.year, m[last.year] / 2, f"Jan–{last:%b}\nonly", ha="center", va="center",
                fontsize=10, color=INK)
    ax.set_xticks(m.index)
    ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("{x:,.0f}"))
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, m.max() * 1.15)
    ax.set_title("Million-dollar HDB flats are no longer rare")
    subtitle(ax, "Number of resale flats sold for S$1 million or more per year, all flat types")
    source(fig)
    save(fig, "04_million_dollar_flats.png")


# ---------------------------------------------------------------------------
# 4. Distance to MRT (one factor at a time)
# ---------------------------------------------------------------------------
def fig_mrt(four, end_year):
    recent = four[(four["year"] == end_year) & four["mrt_band"].notna()]
    t = (recent.groupby("mrt_band")
         .agg(psm=("price_per_sqm", "median"),
              lease=("remaining_lease_years", "median"),
              sales=("resale_price", "size"))
         .reindex(MRT_ORDER))

    fig, ax = plt.subplots()
    colors = [BLUE, BLUE, BLUE, LIGHT_BLUE]
    x = np.arange(len(t))
    ax.bar(x, t["psm"], color=colors, width=0.6)
    for i, (band, row) in enumerate(t.iterrows()):
        ax.text(i, row["psm"] + 60, f"${row['psm']:,.0f}", ha="center", va="bottom",
                fontsize=12, fontweight="bold", color=INK)
        ax.text(i, 250, f"{row['lease']:.0f} yrs\nlease left\n\n{int(row['sales']):,} sales",
                ha="center", va="bottom", fontsize=10, color="white" if i < 3 else INK)
    ax.set_xticks(x, t.index)
    ax.tick_params(axis="x", labelsize=12, labelcolor=INK, length=0)
    ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, t["psm"].max() * 1.15)
    ax.set_xlabel("Straight-line distance to the nearest MRT/LRT exit")
    ax.set_title("Flats near an MRT exit cost more per sqm")
    subtitle(ax, f"Median price per sqm, 4-room flats sold in {end_year}. "
                 "The far group has much newer flats (longer lease), which pushes its price up")
    source(fig)
    save(fig, f"05_mrt_distance_4room_{end_year}.png")


# ---------------------------------------------------------------------------
# 5. Regression effects (read from the table made by make_tables.py)
# ---------------------------------------------------------------------------
def fig_regression():
    path = PROJECT_ROOT / "outputs" / "tables" / "regression_effects.csv"
    if not path.exists():
        print("regression_effects.csv not found: run src/make_tables.py first. Skipping.")
        return
    eff = pd.read_csv(path).set_index("variable")
    labels = {
        "area_10sqm": "+10 sqm floor area",
        "lease_10y": "+10 years remaining lease",
        "floor_10": "+10 floors higher",
        "cbd_dist_km": "+1 km further from the CBD",
        "mrt_100m": "+100 m further from MRT",
    }
    eff = eff.loc[list(labels)].iloc[::-1]

    fig, ax = plt.subplots()
    y = np.arange(len(eff))
    colors = [BLUE if v >= 0 else ORANGE for v in eff["pct_effect"]]
    ax.barh(y, eff["pct_effect"], color=colors, height=0.6)
    ax.errorbar(eff["pct_effect"], y,
                xerr=[eff["pct_effect"] - eff["ci_low_pct"], eff["ci_high_pct"] - eff["pct_effect"]],
                fmt="none", ecolor=INK, elinewidth=1, capsize=3)
    for i, v in enumerate(eff["pct_effect"]):
        ax.text(v + (0.3 if v >= 0 else -0.3), i, f"{v:+.1f}%", va="center",
                ha="left" if v >= 0 else "right", fontsize=12, fontweight="bold", color=INK)
    ax.axvline(0, color=MUTED, linewidth=1)
    ax.set_yticks(y, [labels[v] for v in eff.index])
    ax.tick_params(axis="y", length=0, labelsize=12, labelcolor=INK)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax.set_xlim(-5, 12.5)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Change in resale price, holding the other factors equal")
    ax.set_title("What makes a flat more valuable?")
    subtitle(ax, "Regression of log price on flat and location features, flat type and year "
                 "(all sales, 2017–2026). Lines = 95% CI")
    source(fig)
    save(fig, "06_regression_effects.png")


# ---------------------------------------------------------------------------
# 6. Map of price per sqm by block
# ---------------------------------------------------------------------------
def fig_map(four):
    last = four["month"].max()
    recent = four[four["month"] > last - pd.DateOffset(months=12)].dropna(subset=["lat", "lon"])
    blocks = (recent.groupby(["block", "street_name"])
              .agg(lat=("lat", "first"), lon=("lon", "first"), psm=("price_per_sqm", "median"))
              .sort_values("psm"))           # expensive blocks drawn last, on top
    low, high = blocks["psm"].quantile([0.05, 0.95])
    cmap = LinearSegmentedColormap.from_list("price", PRICE_SCALE[1:])

    fig, ax = plt.subplots(figsize=(10, 4.9))
    pts = ax.scatter(blocks["lon"], blocks["lat"], c=blocks["psm"], cmap=cmap,
                     vmin=low, vmax=high, s=9, linewidth=0)
    if MRT_FILE.exists():
        stations = pd.read_csv(MRT_FILE).groupby("station")[["lat", "lon"]].mean()
        ax.scatter(stations["lon"], stations["lat"], s=10, marker="s", color=ORANGE,
                   linewidth=0, label="MRT/LRT station")
        ax.legend(loc="lower right", frameon=False, fontsize=10)
    cbar = fig.colorbar(pts, ax=ax, shrink=0.75, pad=0.01)
    cbar.ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
    cbar.outline.set_visible(False)
    cbar.set_label("Median price per sqm", color=MUTED)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Price per sqm is highest near the city centre, and in some newer estates")
    subtitle(ax, f"Each dot is an HDB block with a 4-room sale in the 12 months to {last:%b %Y} "
                 "(colour capped at 5th–95th percentile)")
    source(fig, "Source: HDB resale prices and LTA MRT exits (data.gov.sg); "
                "block locations: NUS 3D HDB dataset and OneMap")
    save(fig, "07_map_price_per_sqm.png")


# ---------------------------------------------------------------------------
# 7. Distributions with Seaborn (figures 08-11)
# ---------------------------------------------------------------------------
def fig_hist_kde(four, end_year):
    """Density histogram + KDE of price per sqm for one year (Lecture 8, sns.histplot)."""
    data = four[four["year"] == end_year]
    median = data["price_per_sqm"].median()
    share = data["price_per_sqm"].between(5000, 8000).mean() * 100

    fig, ax = plt.subplots()

    sns.histplot(
        data=data,
        x="price_per_sqm",
        bins="auto",
        stat="density",
        kde=True,
        color=BLUE,
        ax=ax,
    )

    # Mark the median with a dashed vertical line.
    ax.axvline(median, color=INK, linewidth=1.2, linestyle="--")
    ax.text(median + 150, ax.get_ylim()[1] * 0.92, f"Median: ${median:,.0f}",
            color=INK, fontsize=12, fontweight="bold")

    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
    ax.set_xlabel("Price per sqm (S$)")
    ax.set_ylabel("Density")
    # A backslash before "$" stops Matplotlib from reading text between two "$" signs as a formula.
    ax.set_title(f"{share:.0f}% of 4-room flats sold for \\$5,000-\\$8,000 per sqm in {end_year}")
    subtitle(ax, f"Distribution of price per sqm, 4-room flats sold in {end_year} "
                 f"({len(data):,} sales). Bars = density histogram, line = KDE")
    source(fig)
    save(fig, f"08_hist_kde_psm_4room_{end_year}.png")


def fig_box_by_town(four, end_year):
    """Box plots of price per sqm by town, sorted by median (Lecture 8, sns.boxplot)."""
    data = four[four["year"] == end_year]

    # Keep towns with enough sales, then sort towns by their median price per sqm.
    counts = data["town"].value_counts()
    data = data[data["town"].isin(counts[counts >= MIN_SALES].index)]
    order = (
        data.groupby("town")["price_per_sqm"].median()
        .sort_values(ascending=False)
        .index
    )

    fig, ax = plt.subplots(figsize=(10, 9))

    sns.boxplot(
        data=data,
        x="price_per_sqm",
        y="town",
        order=order,
        color=LIGHT_BLUE,
        fliersize=1.5,
        ax=ax,
    )

    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
    ax.set_xlabel("Price per sqm (S$)")
    ax.set_ylabel("Town")
    ax.set_title(f"Central towns cost more per sqm, and prices within them vary more ({end_year})")
    subtitle(ax, f"4-room flats sold in {end_year}, towns sorted by median. "
                 "Box = middle 50% of sales, line = median, dots = potential outliers")
    ax.grid(axis="y", visible=False)
    source(fig)
    save(fig, f"09_box_psm_by_town_{end_year}.png")


def fig_dist_compare(four, end_year):
    """Base year vs last full year, side by side (Lecture 8, plt.subplots with two Axes)."""
    fig, axs = plt.subplots(nrows=1, ncols=2, figsize=(14, 5), sharex=True, sharey=True)

    for i, (year, color) in enumerate([(BASE_YEAR, LIGHT_BLUE), (end_year, BLUE)]):
        data = four[four["year"] == year]
        median = data["price_per_sqm"].median()

        sns.histplot(
            data=data,
            x="price_per_sqm",
            bins="auto",
            stat="density",
            kde=True,
            color=color,
            ax=axs[i],
        )

        axs[i].axvline(median, color=INK, linewidth=1.2, linestyle="--")
        axs[i].text(median + 150, axs[i].get_ylim()[1] * 0.92, f"Median ${median:,.0f}",
                    color=INK, fontsize=11, fontweight="bold")
        axs[i].xaxis.set_major_locator(mtick.MultipleLocator(2000))
        axs[i].xaxis.set_major_formatter(mtick.FuncFormatter(money))
        axs[i].set_xlabel("Price per sqm (S$)")
        axs[i].set_ylabel("Density")
        axs[i].set_title(f"{year} ({len(data):,} sales)", pad=10, fontsize=14)

    base = four.loc[four["year"] == BASE_YEAR, "price_per_sqm"].median()
    end = four.loc[four["year"] == end_year, "price_per_sqm"].median()
    fig.suptitle(f"4-room price per sqm moved right: median +{(end / base - 1) * 100:.0f}% "
                 f"from {BASE_YEAR} to {end_year} (same axes on both sides)",
                 fontsize=16, fontweight="bold", color=INK)
    fig.tight_layout()
    source(fig)
    save(fig, f"10_dist_{BASE_YEAR}_vs_{end_year}.png")


def fig_town_mrt_regplot(four, end_year):
    """Town medians: distance to MRT vs price per sqm (Lecture 8, sns.regplot + correlation)."""
    data = four[(four["year"] == end_year) & four["mrt_dist_m"].notna()]

    # One row per town: median distance to the MRT and median price per sqm.
    towns = data.groupby("town").agg(
        mrt=("mrt_dist_m", "median"),
        psm=("price_per_sqm", "median"),
        sales=("price_per_sqm", "size"),
    )
    towns = towns[towns["sales"] >= MIN_SALES]

    fig, ax = plt.subplots()

    sns.regplot(
        data=towns,
        x="mrt",
        y="psm",
        ci=None,
        scatter_kws={"color": BLUE, "s": 70, "alpha": 0.9},
        line_kws={"color": ORANGE, "linewidth": 2},
        ax=ax,
    )

    # Label a few towns so the dots can be read.
    labels = {"Central Area": (7, 0, "left"), "Toa Payoh": (7, 0, "left"),
              "Queenstown": (7, 0, "left"), "Marine Parade": (7, 0, "left"),
              "Bukit Panjang": (7, 0, "left"), "Choa Chu Kang": (7, 0, "left"),
              "Yishun": (0, 14, "center")}
    for town, (dx, dy, ha) in labels.items():
        if town in towns.index:
            ax.annotate(town, (towns.loc[town, "mrt"], towns.loc[town, "psm"]),
                        xytext=(dx, dy), textcoords="offset points", ha=ha, va="center",
                        fontsize=10, color=INK)

    # Calculate the Pearson sample correlation coefficient.
    r = towns["mrt"].corr(towns["psm"])

    # Display the sample correlation coefficient.
    ax.text(0.65, 0.85, f"Sample correlation = {r:.2f}", transform=ax.transAxes,
            fontsize=13, fontweight="bold", color=INK)

    ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
    ax.xaxis.set_major_formatter(mtick.StrMethodFormatter("{x:,.0f} m"))
    ax.set_xlabel("Median straight-line distance to the nearest MRT/LRT exit")
    ax.set_ylabel("Median price per sqm (S$)")
    ax.set_title(f"Towns further from the MRT tend to be cheaper per sqm (r = {r:.2f})")
    subtitle(ax, f"Each dot is a town ({len(towns)} towns with {MIN_SALES}+ sales of 4-room "
                 f"flats in {end_year}). Line = OLS regression line")
    source(fig)
    save(fig, f"11_town_mrt_vs_psm_{end_year}.png")


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(DATA_FILE)
    end_year = last_full_year(df)
    four = df[df["flat_type"] == FLAT_TYPE]

    fig_price_trend(four, end_year)
    g = town_growth(four, end_year)
    fig_town_ranking(g, end_year)
    fig_pct_vs_sgd(g, end_year)
    fig_million(df, end_year)
    if "mrt_dist_m" in df.columns:
        fig_mrt(four, end_year)
        fig_map(four)
    fig_regression()
    fig_hist_kde(four, end_year)
    fig_box_by_town(four, end_year)
    fig_dist_compare(four, end_year)
    if "mrt_dist_m" in df.columns:
        fig_town_mrt_regplot(four, end_year)


if __name__ == "__main__":
    main()
