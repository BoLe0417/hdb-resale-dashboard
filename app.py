"""HDB Resale Price Dashboard (DS608 Group Project).

Usage (run from the project root folder):
    streamlit run app.py

Needs data/processed/hdb_resale_clean.parquet, created by:
    python src/download_data.py
    python src/download_mrt.py       (optional, adds MRT distances)
    python src/building_coords.py    (optional, block locations, part 1)
    python src/geocode_blocks.py     (optional, block locations, part 2)
    python src/wrangle.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import statsmodels.formula.api as smf
import streamlit as st

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_FILE = PROJECT_ROOT / "data" / "processed" / "hdb_resale_clean.parquet"
MRT_FILE = PROJECT_ROOT / "data" / "raw" / "mrt_station_exits.csv"
SOURCE_URL = "https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view"

# Colour palette (colour-blind-checked categorical order; do not reorder)
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
MAIN_BLUE = "#2a78d6"
LIGHT_BLUE = "#9ec5f4"
# Sequential scale (light = cheaper, dark = more expensive) for the map
PRICE_SCALE = ["#dbe9fb", "#9ec5f4", "#5a9be6", "#2a78d6", "#1a5aa8", "#123d73"]
MAX_TOWNS = len(SERIES_COLORS)

FLAT_TYPE_ORDER = [
    "1 Room", "2 Room", "3 Room", "4 Room", "5 Room", "Executive", "Multi-Generation",
]
DEFAULT_TOWNS = ["Queenstown", "Bukit Merah", "Clementi", "Woodlands", "Sembawang"]

st.set_page_config(page_title="HDB Resale Prices", page_icon="🏠", layout="wide")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
@st.cache_data
def load_data():
    return pd.read_parquet(DATA_FILE)


def money(x):
    """Format a number as a Singapore dollar amount, e.g. 605000 -> $605,000."""
    return f"${x:,.0f}"


def money_md(x):
    """Same as money(), for st.markdown text.

    Streamlit reads two '$' signs in one text as a maths formula, so we escape them.
    """
    return money(x).replace("$", "\\$")


def town_colors(selected_towns):
    """Give each selected town a fixed colour.

    A town keeps its colour while it stays selected, so removing one town
    does not repaint the others.
    """
    saved = st.session_state.setdefault("town_color_map", {})
    for town in list(saved):
        if town not in selected_towns:
            del saved[town]
    for town in selected_towns:
        if town not in saved:
            used = set(saved.values())
            saved[town] = next(c for c in SERIES_COLORS if c not in used)
    return dict(saved)


def style_chart(fig, y_title=None, x_title=None, money_axis=False, height=None):
    """Apply one consistent, quiet style to every chart.

    Same height, legend above the chart (so it does not squeeze the plot),
    light grid lines only on the value axis. Charts that set their own height
    (e.g. long bar lists) keep it.
    """
    if height is None:
        height = fig.layout.height or 380
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(title_text="", orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0),
        hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(title=x_title, showgrid=False)
    fig.update_yaxes(title=y_title, gridcolor="rgba(128,128,128,0.15)")
    if money_axis:
        fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return fig


def show(fig):
    st.plotly_chart(fig, width="stretch", theme="streamlit")


@st.cache_data
def load_mrt_stations():
    """One point per MRT/LRT station (the average position of its exits)."""
    if not MRT_FILE.exists():
        return None
    exits = pd.read_csv(MRT_FILE)
    return exits.groupby("station", as_index=False)[["lat", "lon"]].mean()


@st.cache_data
def fit_price_model(first_year, last_year):
    """Regression: what is linked to a higher price, holding other things equal?

    log(price) = floor area + remaining lease + floor level + MRT distance
                 + CBD distance + flat type + year  (+ error)

    With log(price) on the left, each coefficient b means:
    "one more unit of X goes with about 100 * (exp(b) - 1) % higher price".
    """
    data = load_data()
    data = data[data["year"].between(first_year, last_year)]
    model_df = data.dropna(subset=["mrt_dist_m", "cbd_dist_km"]).copy()
    model_df["log_price"] = np.log(model_df["resale_price"])
    model_df["mrt_100m"] = model_df["mrt_dist_m"] / 100
    model_df["lease_10y"] = model_df["remaining_lease_years"] / 10
    model_df["floor_10"] = model_df["storey_mid"] / 10
    model_df["area_10sqm"] = model_df["floor_area_sqm"] / 10
    result = smf.ols(
        "log_price ~ area_10sqm + lease_10y + floor_10 + mrt_100m + cbd_dist_km"
        " + C(flat_type) + C(year)",
        data=model_df,
    ).fit(cov_type="HC1")  # robust standard errors

    labels = {
        "area_10sqm": "+10 sqm floor area",
        "lease_10y": "+10 years remaining lease",
        "floor_10": "+10 floors higher",
        "mrt_100m": "+100 m further from MRT",
        "cbd_dist_km": "+1 km further from the CBD",
    }
    ci = result.conf_int()
    table = pd.DataFrame({
        "effect": list(labels.values()),
        "pct": [100 * (np.exp(result.params[k]) - 1) for k in labels],
        "low": [100 * (np.exp(ci.loc[k, 0]) - 1) for k in labels],
        "high": [100 * (np.exp(ci.loc[k, 1]) - 1) for k in labels],
    })
    return table, result.rsquared, int(result.nobs)


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
if not DATA_FILE.exists():
    st.error(
        "Processed data not found. Please run these two commands first:\n\n"
        "`python src/download_data.py`\n\n`python src/wrangle.py`"
    )
    st.stop()

df = load_data()
# Location columns exist only after src/download_mrt.py + src/geocode_blocks.py
HAS_LOCATION = "mrt_dist_m" in df.columns and df["mrt_dist_m"].notna().any()
all_towns = sorted(df["town"].unique())
first_year, last_year = int(df["year"].min()), int(df["year"].max())
last_month = df["month"].max()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
# The last year in the data is only partly covered (e.g. Jan-Oct), so
# comparisons between whole years stop at the last FULL year.
FULL_YEAR = last_year if last_month.month == 12 else last_year - 1
FULL_YEARS = [y for y in range(first_year, FULL_YEAR + 1)]
BASE_YEAR = 2019  # last full year before COVID

st.sidebar.header("Settings")
st.sidebar.subheader("Which flats")

flat_types = [t for t in FLAT_TYPE_ORDER if t in df["flat_type"].unique()]
flat_type = st.sidebar.selectbox(
    "Flat type", flat_types, index=flat_types.index("4 Room"),
    help="Comparing the same flat type keeps the comparison fair.",
)

measure = st.sidebar.radio(
    "Price measure", ["Price per sqm", "Total price"], horizontal=True,
    help="Price per square metre removes most of the effect of flat size.",
)
PRICE_COL = "price_per_sqm" if measure == "Price per sqm" else "resale_price"
PRICE_NAME = "median price per sqm" if measure == "Price per sqm" else "median price"

year_range = st.sidebar.slider(
    "Years", first_year, last_year, (first_year, FULL_YEAR),
    help=f"{last_year} only has data up to {last_month:%B}, so it is left out by default.",
)

with st.sidebar.expander("Compare similar flats only"):
    st.caption(
        "Remaining lease and floor level also change prices. Narrow them to compare "
        "more similar flats across towns and years."
    )
    lease_min, lease_max = int(df["remaining_lease_years"].min()), int(np.ceil(df["remaining_lease_years"].max()))
    lease_range = st.slider("Remaining lease (years)", lease_min, lease_max, (lease_min, lease_max))
    floor_max = int(df["storey_mid"].max())
    floor_range = st.slider("Floor level", 1, floor_max, (1, floor_max))

st.sidebar.subheader("Which towns")
towns = st.sidebar.multiselect(
    f"Towns to compare (up to {MAX_TOWNS})", all_towns,
    default=[t for t in DEFAULT_TOWNS if t in all_towns],
    max_selections=MAX_TOWNS,
)

st.sidebar.caption(
    f"Data up to {last_month:%b %Y}. Prices are not adjusted for inflation. "
    "See the About & method tab for how prices are compared."
)
st.sidebar.markdown(f"[Data source: HDB via data.gov.sg]({SOURCE_URL})")

# Flats of the chosen type that pass the lease and floor filters (all years)
similar = df[
    (df["flat_type"] == flat_type)
    & df["remaining_lease_years"].between(lease_range[0], lease_range[1] + 0.99)
    & df["storey_mid"].between(*floor_range)
]
FILTERED = (lease_range != (lease_min, lease_max)) or (floor_range != (1, floor_max))
if FILTERED:
    st.sidebar.info(f"Using {len(similar):,} of {(df['flat_type'] == flat_type).sum():,} "
                    f"{flat_type} sales that match the lease and floor filters.")

# ...and in the chosen years (used by most charts)
ft = similar[similar["year"].between(*year_range)]
# ...and only full years (used for year-to-year comparisons)
ft_full = ft[ft["year"] <= FULL_YEAR]


def change_vs_base(data, base_year, group_col=None):
    """Median of the chosen measure per year, and its change from `base_year`.

    Returns one row per (group,) year with: median, sales, pct_change, sgd_change.
    pct_change = (median in year / median in base year - 1) x 100
    sgd_change = median in year - median in base year
    """
    keys = ([group_col] if group_col else []) + ["year"]
    out = data.groupby(keys, as_index=False).agg(
        median=(PRICE_COL, "median"), sales=(PRICE_COL, "size"))
    base = out[out["year"] == base_year].drop(columns=["year", "sales"])
    base = base.rename(columns={"median": "base_median"})
    if group_col:
        out = out.merge(base, on=group_col)
    else:
        out["base_median"] = base["base_median"].iloc[0] if len(base) else np.nan
    out["pct_change"] = (out["median"] / out["base_median"] - 1) * 100
    out["sgd_change"] = out["median"] - out["base_median"]
    return out


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("HDB resale prices in Singapore")
st.markdown(
    "How much did prices rise after COVID, why do some flats cost more than others, "
    "and which towns fit your budget?"
)
st.caption(
    f"{len(df):,} resale transactions from {df['month'].min():%b %Y} to "
    f"{last_month:%b %Y}, published by HDB. The About & method tab explains how "
    "prices are compared."
)

(tab_overview, tab_growth, tab_drivers, tab_map, tab_budget, tab_data,
 tab_about) = st.tabs([
    "📈 Overview", "🏙️ Town growth", "🔍 Why are some flats pricier?",
    "🗺️ Map", "💰 Help me choose", "📄 Data", "ℹ️ About & method",
])

# ---------------------------------------------------------------------------
# Tab 1: Overview
# ---------------------------------------------------------------------------
with tab_overview:
    # ---- Headline story: fixed comparison, pre-COVID 2019 vs last full year ----
    this_type = df[df["flat_type"] == flat_type]
    med_2019 = this_type.loc[this_type["year"] == BASE_YEAR, "resale_price"].median()
    med_full = this_type.loc[this_type["year"] == FULL_YEAR, "resale_price"].median()

    town_med = (
        this_type[this_type["year"].isin([BASE_YEAR, FULL_YEAR])]
        .groupby(["town", "year"])["resale_price"].agg(["median", "count"])
        .unstack("year")
    )
    town_med = town_med[(town_med["count"] >= 20).all(axis=1)]
    town_pct = (town_med[("median", FULL_YEAR)] / town_med[("median", BASE_YEAR)] - 1) * 100
    town_sgd = town_med[("median", FULL_YEAR)] - town_med[("median", BASE_YEAR)]

    million_2019 = int(df.loc[df["year"] == BASE_YEAR, "is_million"].sum())
    million_full = int(df.loc[df["year"] == FULL_YEAR, "is_million"].sum())

    points = []
    if pd.notna(med_2019) and pd.notna(med_full):
        points.append(
            f"A typical **{flat_type}** flat cost **{money_md(med_2019)}** in {BASE_YEAR} and "
            f"**{money_md(med_full)}** in {FULL_YEAR}: **+{money_md(med_full - med_2019)}** "
            f"(**{(med_full / med_2019 - 1) * 100:+.0f}%**)."
        )
    if len(town_pct):
        points.append(
            f"Growth was uneven: in **%** terms **{town_pct.idxmax()}** rose most "
            f"(**{town_pct.max():+.0f}%**) and **{town_pct.idxmin()}** least "
            f"(**{town_pct.min():+.0f}%**). In **dollar** terms the biggest rise was in "
            f"**{town_sgd.idxmax()}** (**+{money_md(town_sgd.max())}**)."
        )
    if HAS_LOCATION:
        recent_type = this_type[this_type["year"] == FULL_YEAR]
        near = recent_type.loc[recent_type["mrt_dist_m"] < 400, "price_per_sqm"].median()
        far = recent_type.loc[recent_type["mrt_dist_m"] >= 1200, "price_per_sqm"].median()
        if pd.notna(near) and pd.notna(far):
            points.append(
                f"Location matters: flats **within 400 m of an MRT exit** sold for "
                f"**{(near / far - 1) * 100:+.0f}%** more per sqm than flats 1.2 km+ away "
                f"({FULL_YEAR}, before adjusting for lease or floor)."
            )
    points.append(
        f"Million-dollar HDB flats went from **{million_2019:,}** sales in {BASE_YEAR} to "
        f"**{million_full:,}** in {FULL_YEAR} (all flat types)."
    )
    # ---- KPIs for the chosen years (full years only) ----
    start_y = year_range[0]
    end_y = min(year_range[1], FULL_YEAR)
    start_data = ft_full[ft_full["year"] == start_y]
    end_data = ft_full[ft_full["year"] == end_y]

    if start_data.empty or end_data.empty or end_y <= start_y:
        st.info("Pick at least two full years in the sidebar to compare.")
    else:
        start_med = start_data[PRICE_COL].median()
        end_med = end_data[PRICE_COL].median()

        unit = " per sqm" if PRICE_COL == "price_per_sqm" else ""
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Median{unit}, {start_y}", money(start_med), border=True)
        c2.metric(f"Median{unit}, {end_y}", money(end_med), border=True)
        c3.metric("Change in %", f"{(end_med / start_med - 1) * 100:+.0f}%", border=True)
        c4.metric("Change in S$",
                  ("+" if end_med >= start_med else "-") + money(abs(end_med - start_med)),
                  border=True)
        st.caption(
            f"{flat_type} flats in all towns"
            f"{', matching the lease and floor filters' if FILTERED else ''}, "
            f"{len(end_data):,} sales in {end_y}. Median = the middle value. Full years only."
        )

    with st.container(border=True):
        st.markdown("##### Key takeaways")
        st.markdown("\n".join(f"- {p}" for p in points))
        st.caption(
            f"Median total prices, all towns, pre-COVID {BASE_YEAR} vs {FULL_YEAR} "
            f"(the last full year; {last_year} is incomplete). Change the flat type in "
            "the sidebar to update."
        )

    # ---- Year-by-year change from the pre-COVID base year ----
    base = BASE_YEAR if year_range[0] <= BASE_YEAR else year_range[0]
    head, toggle = st.columns([3, 1], vertical_alignment="bottom")
    head.subheader(f"How much higher than in {base}? Year by year")
    show_as = toggle.segmented_control("Show change as", ["%", "S$"], default="%",
                                       key="yearly_unit") or "%"
    yearly_all = change_vs_base(ft_full[ft_full["year"] >= base], base).assign(town="All towns")
    yearly_towns = change_vs_base(
        ft_full[(ft_full["year"] >= base) & ft_full["town"].isin(towns)], base, "town")
    yearly = pd.concat([yearly_all, yearly_towns], ignore_index=True)
    yearly = yearly[yearly["year"] > base]
    if yearly.empty:
        st.info("Pick a year range that covers at least two full years.")
    else:
        line_colors = {"All towns": "#6b7280", **town_colors(towns)}
        y_col = "pct_change" if show_as == "%" else "sgd_change"
        fig = px.line(
            yearly, x="year", y=y_col, color="town", markers=True,
            color_discrete_map=line_colors,
            category_orders={"town": ["All towns"] + towns},
            custom_data=["median", "base_median", "pct_change", "sgd_change", "sales"],
        )
        fig.update_traces(
            line_width=2, marker_size=7,
            hovertemplate=(
                "<b>%{fullData.name}</b><br>%{customdata[2]:+.1f}% / %{customdata[3]:+$,.0f}"
                f"<br>%{{customdata[0]:$,.0f}} vs %{{customdata[1]:$,.0f}} in {base}"
                "<br>%{customdata[4]:,} sales<extra></extra>"
            ),
        )
        fig.update_traces(selector={"name": "All towns"}, line_dash="dot", line_width=3)
        if show_as == "%":
            fig.update_yaxes(ticksuffix="%")
        else:
            fig.update_yaxes(tickprefix="$", tickformat=",.0f")
        fig.add_hline(y=0, line_color="gray", line_width=1)
        fig.update_xaxes(dtick=1)
        show(style_chart(fig, y_title=f"Change in {PRICE_NAME} since {base}"))
        st.caption(
            f"For each year: ({PRICE_NAME} in that year ÷ {PRICE_NAME} in {base} − 1) × 100. "
            f"Full years only, so {last_year} is not shown."
        )

    st.subheader(f"{PRICE_NAME.capitalize()} over time: {flat_type} flats")
    if towns:
        colors = town_colors(towns)
        trend = (
            ft[ft["town"].isin(towns)]
            .groupby(["quarter", "town"], as_index=False)[PRICE_COL].median()
        )
        fig = px.line(
            trend, x="quarter", y=PRICE_COL, color="town",
            color_discrete_map=colors, category_orders={"town": towns},
        )
        fig.update_traces(line_width=2, hovertemplate="%{y:$,.0f}")
        fig.update_layout(hovermode="x unified")
        show(style_chart(fig, y_title=PRICE_NAME.capitalize(), money_axis=True))
        st.caption(
            "Quarterly median, so the latest quarters can be shown even though "
            f"{last_year} is incomplete (move the Years slider to {last_year} to include it)."
        )
    else:
        st.info("Pick at least one town in the sidebar.")

    st.subheader("Million-dollar HDB flats are no longer rare")
    million = (
        df[df["year"].between(*year_range)]
        .groupby("year", as_index=False)["is_million"].sum()
        .rename(columns={"is_million": "flats"})
    )
    million["period"] = np.where(million["year"] <= FULL_YEAR, "Full year",
                                 f"Jan-{last_month:%b} only")
    fig = px.bar(million, x="year", y="flats", color="period",
                 color_discrete_map={"Full year": MAIN_BLUE, f"Jan-{last_month:%b} only": LIGHT_BLUE})
    fig.update_traces(marker_cornerradius=4, hovertemplate="%{x}: %{y:,} flats<extra></extra>")
    fig.update_xaxes(dtick=1)
    fig.update_layout(showlegend=million["period"].nunique() > 1)
    show(style_chart(fig, y_title="Flats sold for $1M+", height=300))
    st.caption("All flat types, total resale price of at least $1,000,000.")

# ---------------------------------------------------------------------------
# Tab 2: Which towns grew the most?
# ---------------------------------------------------------------------------
with tab_growth:
    st.subheader(f"Which towns saw the biggest price increase? ({flat_type})")

    col_a, col_b, col_c = st.container(border=True).columns(3)
    base_year = col_a.selectbox(
        "Compare from", FULL_YEARS[:-1], index=FULL_YEARS.index(BASE_YEAR),
        help=f"{BASE_YEAR} is the last full year before COVID.",
    )
    later_years = [y for y in FULL_YEARS if y > base_year]
    comp_year = col_b.selectbox("to", later_years, index=len(later_years) - 1,
                                help=f"Only full years. {last_year} is incomplete.")
    rank_by = col_c.segmented_control("Rank towns by", ["% change", "S$ change"],
                                      default="% change") or "% change"

    by_town = (
        similar[similar["year"].isin([base_year, comp_year])]
        .groupby(["town", "year"])[PRICE_COL].agg(["median", "count"])
        .unstack("year")
    )
    # Require at least 20 sales in both years so one odd sale does not drive the result
    if by_town.empty or by_town.columns.get_level_values("year").nunique() < 2:
        by_town = by_town.iloc[0:0]
        enough = pd.Series(dtype=bool)
    else:
        enough = (by_town["count"] >= 20).all(axis=1)
    growth = pd.DataFrame() if by_town.empty else pd.DataFrame({
        "town": by_town.index,
        "base_price": by_town[("median", base_year)],
        "comp_price": by_town[("median", comp_year)],
        "base_sales": by_town[("count", base_year)],
        "comp_sales": by_town[("count", comp_year)],
    })[enough.values].dropna()
    if growth.empty:
        growth = pd.DataFrame(columns=["town", "base_price", "comp_price", "base_sales", "comp_sales"])
    growth["change_pct"] = (growth["comp_price"] / growth["base_price"] - 1) * 100
    growth["change_sgd"] = growth["comp_price"] - growth["base_price"]
    rank_col = "change_pct" if rank_by == "% change" else "change_sgd"
    growth = growth.sort_values(rank_col)
    growth["group"] = growth["town"].apply(
        lambda t: "Selected town" if t in towns else "Other town"
    )

    if growth.empty:
        st.info("Not enough transactions to compare these years. Try wider lease/floor filters.")
    else:
        fig = px.bar(
            growth, x=rank_col, y="town", orientation="h", color="group",
            color_discrete_map={"Selected town": MAIN_BLUE, "Other town": LIGHT_BLUE},
            custom_data=["base_price", "comp_price", "change_pct", "change_sgd"],
        )
        fig.update_traces(
            marker_cornerradius=4,
            hovertemplate=(
                "<b>%{y}</b><br>Change: %{customdata[2]:+.0f}% (%{customdata[3]:+$,.0f})<br>"
                f"{base_year}: " + "%{customdata[0]:$,.0f}<br>"
                f"{comp_year}: " + "%{customdata[1]:$,.0f}<extra></extra>"
            ),
        )
        fig.update_layout(height=max(400, 24 * len(growth)),
                          yaxis={"categoryorder": "total ascending"})
        if rank_by == "% change":
            fig.update_xaxes(ticksuffix="%")
        else:
            fig.update_xaxes(tickprefix="$", tickformat=",.0f")
        show(style_chart(
            fig, x_title=f"Change in {PRICE_NAME}, {base_year} to {comp_year} ({rank_by.split()[0]})"))

        top_pct = growth.loc[growth["change_pct"].idxmax()]
        low_pct = growth.loc[growth["change_pct"].idxmin()]
        top_sgd = growth.loc[growth["change_sgd"].idxmax()]
        st.markdown(
            f"In **%** terms, **{top_pct['town']}** grew the most "
            f"(**{top_pct['change_pct']:+.0f}%**) and **{low_pct['town']}** the least "
            f"(**{low_pct['change_pct']:+.0f}%**). In **S\\$** terms, the largest rise was in "
            f"**{top_sgd['town']}** (**+{money_md(top_sgd['change_sgd'])}**"
            f"{' per sqm' if PRICE_COL == 'price_per_sqm' else ''}). "
            "A town that was already expensive can show a big dollar rise with a modest "
            "% rise, so we report both. Towns with fewer than 20 sales in either year are left out."
        )

        with st.expander("Full table: % and S$ change by town"):
            table = growth.sort_values(rank_col, ascending=False)[
                ["town", "base_price", "comp_price", "change_pct", "change_sgd",
                 "base_sales", "comp_sales"]]
            st.dataframe(
                table, hide_index=True, width="stretch",
                column_config={
                    "town": "Town",
                    "base_price": st.column_config.NumberColumn(f"{base_year} median (S$)", format="localized"),
                    "comp_price": st.column_config.NumberColumn(f"{comp_year} median (S$)", format="localized"),
                    "change_pct": st.column_config.NumberColumn("% change", format="%+.1f%%"),
                    "change_sgd": st.column_config.NumberColumn("S$ change", format="localized"),
                    "base_sales": st.column_config.NumberColumn(f"Sales {base_year}"),
                    "comp_sales": st.column_config.NumberColumn(f"Sales {comp_year}"),
                },
            )

        st.subheader("Did cheaper towns catch up?")
        # Label only the 3 fastest- and 3 slowest-growing towns to avoid clutter
        ranked = growth.sort_values("change_pct")
        label_towns = set(ranked["town"].head(3)) | set(ranked["town"].tail(3))
        growth["label"] = growth["town"].where(growth["town"].isin(label_towns), "")
        fig = px.scatter(
            growth, x="base_price", y="change_pct", hover_name="town", text="label",
            color_discrete_sequence=[MAIN_BLUE],
        )
        fig.update_traces(
            marker=dict(size=11, line=dict(width=2, color="white")),
            textposition="top center",
            textfont=dict(size=11),
            hovertemplate=f"<b>%{{hovertext}}</b><br>{base_year} median: " + "%{x:$,.0f}<br>Change: %{y:+.0f}%<extra></extra>",
        )
        fig.update_xaxes(tickprefix="$", tickformat=",.0f")
        fig.update_yaxes(ticksuffix="%")
        show(style_chart(fig, x_title=f"{PRICE_NAME.capitalize()} in {base_year}", y_title="% change"))
        corr = growth["base_price"].corr(growth["change_pct"])
        direction = "cheaper" if corr < 0 else "more expensive"
        st.caption(
            f"Each dot is a town. Correlation = {corr:.2f}: on average, towns that were "
            f"{direction} in {base_year} grew {'a bit ' if abs(corr) < 0.4 else ''}faster."
        )
        st.info(
            "💡 **Careful when reading growth:** a town's median can rise partly because "
            "the *mix* of flats sold changed (e.g. newer flats with long leases start being "
            "resold). Use **Compare similar flats only** in the sidebar to hold lease and "
            "floor level roughly fixed, and see the 'Why are some flats pricier?' tab."
        )

# ---------------------------------------------------------------------------
# Tab 3: What makes a flat more valuable?
# ---------------------------------------------------------------------------
with tab_drivers:
    st.markdown(
        f"Same flat type ({flat_type}), {year_range[0]}-{year_range[1]}, all towns"
        f"{', matching the lease/floor filters' if FILTERED else ''}. "
        "We use **price per square metre** where size could distort the comparison. "
        "The story has three parts: **the flat itself**, **its location**, and "
        "**all factors together**."
    )

    st.markdown("### 1. The flat itself")
    left, right = st.columns(2)

    with left:
        st.subheader("Remaining lease")
        lease = (
            ft.groupby("lease_band", observed=True, as_index=False)["price_per_sqm"].median()
        )
        fig = px.bar(lease, x="lease_band", y="price_per_sqm", color_discrete_sequence=[MAIN_BLUE])
        fig.update_traces(marker_cornerradius=4, hovertemplate="%{x}: %{y:$,.0f} per sqm<extra></extra>")
        show(style_chart(fig, x_title="Remaining lease at sale", y_title="Median price per sqm", money_axis=True))
        st.caption(
            "HDB flats have 99-year leases, so a shorter remaining lease means less time "
            "left to own the flat. The oldest flats (< 60 yrs) are often in central towns, "
            "so a good location can partly make up for a short lease."
        )

    with right:
        st.subheader("Floor level")
        storey = ft.copy()
        storey["floor_band"] = pd.cut(
            storey["storey_mid"], bins=[0, 6, 12, 18, 30, 60],
            labels=["1-6", "7-12", "13-18", "19-30", "31+"],
        )
        storey = storey.groupby("floor_band", observed=True, as_index=False)["price_per_sqm"].median()
        fig = px.bar(storey, x="floor_band", y="price_per_sqm", color_discrete_sequence=[MAIN_BLUE])
        fig.update_traces(marker_cornerradius=4, hovertemplate="Floor %{x}: %{y:$,.0f} per sqm<extra></extra>")
        show(style_chart(fig, x_title="Floor", y_title="Median price per sqm", money_axis=True))
        st.caption("Higher floors usually have better views and less noise.")

    st.markdown("### 2. Its location")
    st.subheader("Mature vs non-mature estates")
    estate = ft_full.groupby(["year", "estate_type"], as_index=False)["resale_price"].median()
    fig = px.line(
        estate, x="year", y="resale_price", color="estate_type", markers=True,
        color_discrete_map={"Mature": SERIES_COLORS[0], "Non-mature": SERIES_COLORS[1]},
    )
    fig.update_traces(line_width=2, marker_size=8, hovertemplate="%{y:$,.0f}")
    fig.update_layout(hovermode="x unified")
    show(style_chart(fig, y_title="Median resale price", money_axis=True))
    st.caption(
        "Mature estates are older towns with more established amenities "
        "(shops, MRT lines, schools). The gap shows what buyers pay for that. "
        "Full years only."
    )

    if not HAS_LOCATION:
        st.info(
            "MRT and CBD distances are not available yet. Run "
            "`python src/download_mrt.py`, `python src/building_coords.py`, "
            "`python src/geocode_blocks.py` and `python src/wrangle.py` to add them."
        )
    else:
        left, right = st.columns(2)

        with left:
            st.subheader("Walking distance to MRT")
            mrt = (
                ft.dropna(subset=["mrt_band"])
                .groupby("mrt_band", observed=True)
                .agg(price_per_sqm=("price_per_sqm", "median"), sales=("price_per_sqm", "size"))
                .reset_index()
            )
            fig = px.bar(mrt, x="mrt_band", y="price_per_sqm", color_discrete_sequence=[MAIN_BLUE],
                         custom_data=["sales"])
            fig.update_traces(
                marker_cornerradius=4,
                hovertemplate="%{x}: %{y:$,.0f} per sqm<br>%{customdata[0]:,} sales<extra></extra>",
            )
            show(style_chart(fig, x_title="Straight-line distance to nearest MRT/LRT exit",
                             y_title="Median price per sqm", money_axis=True))
            st.caption(
                "400 m is roughly a 5-minute walk. Distance is measured to the closest "
                "station exit using today's MRT network."
            )

        with right:
            st.subheader("Distance to the city centre")
            towns_cbd = (
                ft.dropna(subset=["cbd_dist_km"])
                .groupby("town")
                .agg(cbd_km=("cbd_dist_km", "median"), price_per_sqm=("price_per_sqm", "median"),
                     sales=("price_per_sqm", "size"), estate=("estate_type", "first"))
                .reset_index()
            )
            towns_cbd = towns_cbd[towns_cbd["sales"] >= 20]
            fig = px.scatter(
                towns_cbd, x="cbd_km", y="price_per_sqm", color="estate",
                hover_name="town", custom_data=["sales"],
                color_discrete_map={"Mature": SERIES_COLORS[0], "Non-mature": SERIES_COLORS[1]},
            )
            fig.update_traces(
                marker=dict(size=11, line=dict(width=2, color="white")),
                hovertemplate=("<b>%{hovertext}</b><br>%{x:.1f} km from CBD<br>"
                               "%{y:$,.0f} per sqm<br>%{customdata[0]:,} sales<extra></extra>"),
            )
            show(style_chart(fig, x_title="Distance from Raffles Place (km)",
                             y_title="Median price per sqm", money_axis=True))
            corr = towns_cbd["cbd_km"].corr(towns_cbd["price_per_sqm"])
            st.caption(f"Each dot is a town. Correlation = {corr:.2f}.")

        st.markdown("### 3. Putting it all together")
        st.markdown(
            "Each chart above looks at **one** factor at a time, but the factors overlap: "
            "flats near the city are also older, for example. A **regression** compares "
            "flats that are alike in every other factor, so we can see each factor's own link "
            "with price. It uses all flat types in the chosen years."
        )
        effects, r2, n_obs = fit_price_model(*year_range)
        effects = effects.sort_values("pct")
        fig = px.bar(
            effects, x="pct", y="effect", orientation="h",
            color=np.where(effects["pct"] >= 0, "Higher price", "Lower price"),
            color_discrete_map={"Higher price": MAIN_BLUE, "Lower price": SERIES_COLORS[1]},
            error_x=effects["high"] - effects["pct"],
            error_x_minus=effects["pct"] - effects["low"],
        )
        fig.update_traces(marker_cornerradius=4, hovertemplate="%{y}: %{x:+.1f}%<extra></extra>")
        fig.update_xaxes(ticksuffix="%", zeroline=True, zerolinecolor="gray")
        fig.update_layout(showlegend=False, height=320)
        show(style_chart(fig, x_title="Change in price, holding the other factors equal"))

        lookup = effects.set_index("effect")["pct"]
        st.markdown(
            f"For example, being **100 m further from an MRT exit** goes with a "
            f"**{lookup['+100 m further from MRT']:+.1f}%** price, and every **extra 10 years "
            f"of lease** with **{lookup['+10 years remaining lease']:+.1f}%**, for flats that "
            f"are otherwise alike. The model explains **{r2:.0%}** of the variation in "
            f"(log) prices across {n_obs:,} sales."
        )
        with st.expander("How to read this (and what it cannot tell us)"):
            st.markdown(
                "- Model: `log(price) ~ floor area + remaining lease + floor level + MRT "
                "distance + CBD distance + flat type + year`, estimated by OLS with robust "
                "standard errors (statsmodels).\n"
                "- Bars show the % change in price; thin lines are 95% confidence intervals.\n"
                "- These are **associations, not causes**. Things we do not observe (schools, "
                "views, renovation, nearby malls) may be linked to both location and price.\n"
                "- Distances are straight lines, not walking routes, and use today's MRT "
                "network for all years, so new lines (e.g. Thomson-East Coast) are counted "
                "even for sales before they opened."
            )

# ---------------------------------------------------------------------------
# Tab: Map
# ---------------------------------------------------------------------------
with tab_map:
    st.subheader(f"Where are {flat_type} flats most expensive?")
    if not HAS_LOCATION:
        st.info("The map needs block locations. Run `python src/building_coords.py` and "
                "`python src/geocode_blocks.py` first.")
    else:
        map_start = last_month - pd.DateOffset(months=23)
        only_selected = st.checkbox("Only show towns selected in the sidebar", value=False)
        recent_map = df[
            (df["flat_type"] == flat_type) & (df["month"] >= map_start) & df["lat"].notna()
        ]
        if only_selected and towns:
            recent_map = recent_map[recent_map["town"].isin(towns)]

        blocks = (
            recent_map.groupby(["block", "street_name"], as_index=False)
            .agg(town=("town", "first"), lat=("lat", "first"), lon=("lon", "first"),
                 price_per_sqm=("price_per_sqm", "median"), price=("resale_price", "median"),
                 sales=("resale_price", "size"), mrt=("nearest_mrt", "first"),
                 mrt_m=("mrt_dist_m", "first"))
        )
        blocks["address"] = blocks["block"] + " " + blocks["street_name"].str.title()

        if blocks.empty:
            st.info("No sales to show for these settings.")
        else:
            low, high = blocks["price_per_sqm"].quantile([0.05, 0.95])
            fig = px.scatter_map(
                blocks, lat="lat", lon="lon", color="price_per_sqm",
                color_continuous_scale=PRICE_SCALE, range_color=(low, high),
                hover_name="address",
                custom_data=["town", "price", "price_per_sqm", "sales", "mrt", "mrt_m"],
                zoom=10.4, center={"lat": 1.355, "lon": 103.82}, height=620,
                map_style="carto-positron",
            )
            fig.update_traces(
                marker=dict(size=7, opacity=0.85),
                hovertemplate=(
                    "<b>%{hovertext}</b> (%{customdata[0]})<br>"
                    "Median price: %{customdata[1]:$,.0f}<br>"
                    "Per sqm: %{customdata[2]:$,.0f}<br>"
                    "Sales: %{customdata[3]}<br>"
                    "Nearest MRT: %{customdata[4]} (%{customdata[5]:,.0f} m)<extra></extra>"
                ),
            )
            stations = load_mrt_stations()
            if stations is not None:
                station_layer = px.scatter_map(stations, lat="lat", lon="lon", hover_name="station")
                station_layer.update_traces(
                    marker=dict(size=6, color="#eb6834"), name="MRT/LRT station",
                    hovertemplate="<b>%{hovertext}</b> station<extra></extra>",
                )
                fig.add_traces(station_layer.data)
            fig.update_layout(
                margin=dict(l=0, r=0, t=0, b=0),
                coloraxis_colorbar=dict(title="Per sqm", tickprefix="$", tickformat=",.0f"),
                showlegend=False,
            )
            show(fig)
            st.caption(
                f"Each blue dot is an HDB block with {flat_type} sales from "
                f"{map_start:%b %Y} to {last_month:%b %Y}; darker = higher median price per "
                "sqm. Orange dots are MRT/LRT stations. Zoom and hover for details."
            )

# ---------------------------------------------------------------------------
# Tab 4: Budget finder
# ---------------------------------------------------------------------------
with tab_budget:
    st.subheader("Which towns fit my budget and needs?")
    recent_start = last_month - pd.DateOffset(months=11)
    st.markdown(
        f"Based on **{flat_type}** flats sold in the last 12 months of data "
        f"({recent_start:%b %Y} to {last_month:%b %Y})."
    )

    col_a, col_b, col_c = st.container(border=True).columns(3)
    budget = col_a.slider(
        "My budget (S$ thousands)", 200, 1500, 650, step=10, format="$%dk",
    ) * 1000
    min_lease = col_b.slider("Minimum remaining lease (years)", 40, 95, 60)
    mrt_options = {"Any distance": None, "Within 400 m (~5 min walk)": 400,
                   "Within 800 m (~10 min walk)": 800, "Within 1.2 km": 1200}
    mrt_choice = col_c.selectbox(
        "Distance to MRT", list(mrt_options), disabled=not HAS_LOCATION,
        help="Straight-line distance to the nearest MRT/LRT exit.",
    )
    max_mrt = mrt_options[mrt_choice] if HAS_LOCATION else None

    recent = df[
        (df["flat_type"] == flat_type)
        & (df["month"] >= recent_start)
        & (df["remaining_lease_years"] >= min_lease)
    ]
    if max_mrt is not None:
        recent = recent[recent["mrt_dist_m"] < max_mrt]

    if recent.empty:
        st.info("No recent sales match these conditions. Try a lower minimum lease.")
    else:
        summary = (
            recent.assign(within=recent["resale_price"] <= budget)
            .groupby("town")
            .agg(
                sales=("resale_price", "size"),
                median_price=("resale_price", "median"),
                share_within=("within", "mean"),
            )
            .reset_index()
        )
        summary = summary[summary["sales"] >= 10]
        summary["share_within"] *= 100
        summary = summary.sort_values("share_within", ascending=True)

        good = summary[summary["share_within"] >= 50].sort_values("share_within", ascending=False)
        if good.empty:
            st.warning(f"In no town were at least half of recent sales within {money_md(budget)}.")
        else:
            st.success(
                f"In **{len(good)} towns**, at least half of recent {flat_type} sales "
                f"were within {money_md(budget)}: " + ", ".join(good["town"].head(5)) +
                (f" and {len(good) - 5} more." if len(good) > 5 else ".")
            )

        fig = px.bar(
            summary, x="share_within", y="town", orientation="h",
            color_discrete_sequence=[MAIN_BLUE],
            custom_data=["median_price", "sales"],
        )
        fig.update_traces(
            marker_cornerradius=4,
            hovertemplate=(
                "<b>%{y}</b><br>%{x:.0f}% of sales within budget<br>"
                "Median price: %{customdata[0]:$,.0f}<br>Sales: %{customdata[1]:,}<extra></extra>"
            ),
        )
        fig.add_vline(x=50, line_dash="dot", line_color="gray")
        fig.update_layout(height=max(400, 24 * len(summary)))
        fig.update_xaxes(range=[0, 100], ticksuffix="%")
        show(style_chart(fig, x_title="Share of recent sales at or below my budget"))
        st.caption("Towns with fewer than 10 matching sales are hidden. Dotted line = 50%.")

        with st.expander("Show as a table"):
            table = summary.sort_values("share_within", ascending=False).rename(columns={
                "town": "Town", "sales": "Sales", "median_price": "Median price",
                "share_within": "% within budget",
            })
            st.dataframe(
                table, hide_index=True, width="stretch",
                column_config={
                    "Median price": st.column_config.NumberColumn("Median price (S$)", format="localized"),
                    "% within budget": st.column_config.NumberColumn(format="%.0f%%"),
                },
            )

        st.subheader("Shortlist: blocks that sold within my budget")
        pick_towns = st.multiselect(
            "Towns to shortlist", summary["town"].sort_values().tolist(),
            default=good["town"].head(3).tolist(),
        )
        matches = recent[(recent["resale_price"] <= budget) & recent["town"].isin(pick_towns)]
        if matches.empty:
            st.info("No sales within budget in these towns. Try other towns or a higher budget.")
        else:
            agg = dict(
                town=("town", "first"), sales=("resale_price", "size"),
                median_price=("resale_price", "median"),
                lease_left=("remaining_lease_years", "median"),
            )
            if HAS_LOCATION:
                agg.update(nearest_mrt=("nearest_mrt", "first"), mrt_m=("mrt_dist_m", "first"))
            shortlist = (
                matches.groupby(["block", "street_name"], as_index=False).agg(**agg)
                .sort_values(["sales", "median_price"], ascending=[False, True])
            )
            shortlist.insert(0, "address", shortlist["block"] + " " + shortlist["street_name"].str.title())
            shortlist = shortlist.drop(columns=["block", "street_name"])
            st.write(
                f"**{len(shortlist):,} blocks** in the chosen towns had at least one "
                f"{flat_type} sale within {money_md(budget)} in the last 12 months. "
                "Blocks with more sales are listed first: they are easier to find again."
            )
            st.dataframe(
                shortlist, hide_index=True, width="stretch",
                column_config={
                    "address": "Block", "town": "Town", "sales": "Sales within budget",
                    "median_price": st.column_config.NumberColumn("Median price (S$)", format="localized"),
                    "lease_left": st.column_config.NumberColumn("Lease left (yrs)", format="%.0f"),
                    "nearest_mrt": "Nearest MRT",
                    "mrt_m": st.column_config.NumberColumn("MRT distance (m)", format="%.0f"),
                },
            )
            st.caption(
                "Past sales are a guide, not a promise: the same block can sell for more today, "
                "and each flat's condition and floor differ."
            )

# ---------------------------------------------------------------------------
# Tab 5: Data table
# ---------------------------------------------------------------------------
with tab_data:
    st.subheader("Filtered transactions")
    shown = ft[ft["town"].isin(towns)] if towns else ft
    st.write(f"{len(shown):,} rows ({flat_type}, {year_range[0]}-{year_range[1]}"
             + (", selected towns" if towns else ", all towns") + ")")
    cols = [
        "month", "town", "flat_type", "block", "street_name", "storey_range",
        "floor_area_sqm", "remaining_lease_years", "resale_price", "price_per_sqm",
    ]
    if HAS_LOCATION:
        cols += ["nearest_mrt", "mrt_dist_m", "cbd_dist_km"]
    st.dataframe(
        shown[cols].sort_values("month", ascending=False).head(5000),
        hide_index=True, width="stretch",
        column_config={
            "month": st.column_config.DateColumn("Month", format="YYYY-MM"),
            "town": "Town",
            "flat_type": "Flat type",
            "block": "Block",
            "street_name": "Street",
            "storey_range": "Storey",
            "floor_area_sqm": st.column_config.NumberColumn("Area (sqm)"),
            "remaining_lease_years": st.column_config.NumberColumn("Lease left (yrs)", format="%.1f"),
            "resale_price": st.column_config.NumberColumn("Resale price (S$)", format="localized"),
            "price_per_sqm": st.column_config.NumberColumn("Price per sqm (S$)", format="localized"),
            "nearest_mrt": "Nearest MRT",
            "mrt_dist_m": st.column_config.NumberColumn("MRT distance (m)", format="%.0f"),
            "cbd_dist_km": st.column_config.NumberColumn("CBD distance (km)", format="%.1f"),
        },
    )
    st.caption("Showing the latest 5,000 rows. Download for the full filtered data.")
    st.download_button(
        "⬇️ Download filtered data (CSV)",
        shown[cols].to_csv(index=False).encode("utf-8"),
        file_name="hdb_resale_filtered.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------------
# Tab: About & method
# ---------------------------------------------------------------------------
with tab_about:
    st.subheader("What this dashboard is for")
    st.markdown(
        "We study HDB **resale** prices from 2017 to 2026 to answer three questions:\n"
        f"1. **Growth:** which towns saw the biggest price increases after COVID ({BASE_YEAR} "
        "vs later years), in both **%** and **S\\$**?\n"
        "2. **Drivers:** why are some flats and locations more valuable (lease, floor, "
        "mature estate, distance to MRT and to the city centre)?\n"
        "3. **Decision support:** which towns and blocks fit a buyer's budget and needs?"
    )

    st.subheader("How we compare prices across years")
    st.markdown(
        f"- For every **town and year** we take the **median** of the chosen price measure "
        f"(**price per sqm** by default, or total price). The median is the middle value, so "
        "a few very expensive flats do not pull it up.\n"
        f"- **% change** from a base year = (median in year ÷ median in base year − 1) × 100. "
        f"The default base year is **{BASE_YEAR}**, the last full year before COVID.\n"
        "- **S\\$ change** = median in year − median in base year. We show both, because a "
        "town that was already expensive can have a large dollar increase with a small "
        "% increase, and the other way round.\n"
        f"- **Only full years** are compared. {last_year} only has data up to "
        f"{last_month:%B}, so it is left out of every year-to-year comparison; it only "
        "appears in the quarterly trend chart (if you include it with the Years slider), "
        "in the map and in the 'Help me choose' tab (last 12 months).\n"
        "- A town is only ranked if it has **at least 20 sales** in both years compared."
    )

    st.subheader("Making the comparisons fair")
    st.markdown(
        "Comparing medians can mislead when towns sell different kinds of flats. We deal "
        "with this in four ways:\n"
        "- **Same flat type** (chosen in the sidebar), since a 5-room flat costs more than "
        "a 3-room one.\n"
        "- **Price per sqm**, which removes most of the effect of flat size.\n"
        "- **Compare similar flats only** (sidebar): limit the remaining lease and floor "
        "level, which also affect prices.\n"
        "- A **regression** in the 'Why are some flats pricier?' tab estimates the link "
        "between price and each factor (size, lease, floor, MRT distance, CBD distance, "
        "flat type, year) while holding the others fixed.\n\n"
        "Even so, a town's median can change because a different **mix** of flats was "
        "sold in a year (for example, newer flats reaching the 5-year minimum occupation "
        "period), not only because the same flats became more expensive."
    )

    st.subheader("Other limitations")
    st.markdown(
        "- Prices are **nominal** (not adjusted for inflation).\n"
        "- Resale prices are **not rents**, and the data exclude new BTO flats and "
        "private housing.\n"
        "- MRT and CBD distances are **straight-line** distances, using **today's** MRT "
        "network for all years.\n"
        "- The regression shows **associations, not causes**."
    )

    st.subheader("Sources")
    st.markdown(
        f"- Housing & Development Board, [Resale flat prices based on registration date "
        f"from Jan-2017 onwards]({SOURCE_URL}), data.gov.sg, Singapore Open Data Licence.\n"
        "- Land Transport Authority, [LTA MRT Station Exit (GeoJSON)]"
        "(https://data.gov.sg/datasets/d_b39d3a0871985372d7e1637193335da5/view), "
        "data.gov.sg, Singapore Open Data Licence.\n"
        "- Block locations: NUS Urban Analytics Lab, [3D HDB building dataset]"
        "(https://github.com/ualsg/hdb3d-data) (MIT licence; from HDB, OpenStreetMap "
        "contributors and OneMap), plus Singapore Land Authority's [OneMap Search API]"
        "(https://www.onemap.gov.sg/apidocs/) for blocks built after 2019."
    )
    st.caption("DS608 Data Analytics for Economics group project, SMU MSc in Data Science. "
               "Code and documentation are in our GitHub repository.")
