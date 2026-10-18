# Data Sources

## HDB Resale Flat Prices (Jan 2017 onwards)

| Item | Details |
|---|---|
| Dataset name | Resale flat prices based on registration date from Jan-2017 onwards |
| Publisher | Housing & Development Board (HDB) |
| Platform | data.gov.sg (Singapore Government open data portal) |
| Dataset page | https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view |
| Dataset ID | `d_8b84c4ee58e3cfc0ece0d773c8ca6abc` |
| Collection | Resale Flat Prices (Collection ID 189, 5 datasets covering 1990 to present) |
| Coverage | Jan 2017 to Oct 2026 in our download (updated regularly) |
| Size | 242,454 rows, 11 columns, CSV, about 24 MB |
| Licence | Singapore Open Data Licence (use and redistribution permitted with attribution) |
| Accessed | 12 October 2026 (version used for all results) |

### Columns

`month`, `town`, `flat_type`, `block`, `street_name`, `storey_range`, `floor_area_sqm`, `flat_model`, `lease_commence_date`, `remaining_lease`, `resale_price`

### How to obtain the data

Run from the project root:

```
python src/download_data.py
```

The script uses the data.gov.sg API:

- `https://api-open.data.gov.sg/v1/public/api/datasets/{DATASET_ID}/initiate-download`
- `https://api-open.data.gov.sg/v1/public/api/datasets/{DATASET_ID}/poll-download`

The file is saved to `data/raw/hdb_resale_2017_onwards.csv`. Raw CSV files are excluded from Git via `.gitignore`.

### Known limitations

- Excludes resale transactions that may not reflect full market prices (for example, transfers between relatives), according to the dataset notes.
- Approximate floor area includes recess areas purchased and space-adding items under HDB upgrading programmes.
- Data from March 2012 onwards are based on registration date; earlier data are based on approval date.

### Citation

Housing & Development Board (2026). *Resale flat prices based on registration date from Jan-2017 onwards* [Dataset]. data.gov.sg. Retrieved October 12, 2026, from https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view. Licensed under the Singapore Open Data Licence.

## LTA MRT Station Exits

| Item | Details |
|---|---|
| Dataset name | LTA MRT Station Exit (GEOJSON) |
| Publisher | Land Transport Authority (LTA) |
| Platform | data.gov.sg |
| Dataset page | https://data.gov.sg/datasets/d_b39d3a0871985372d7e1637193335da5/view |
| Dataset ID | `d_b39d3a0871985372d7e1637193335da5` |
| Content | One point per MRT/LRT station exit, with station name and exit code |
| Licence | Singapore Open Data Licence |
| Accessed | 12 October 2026 |

Run `python src/download_mrt.py`. The raw GeoJSON is saved to `data/raw/mrt_station_exits.geojson` (not tracked) and a simple table (`station`, `exit_code`, `lat`, `lon`) to `data/raw/mrt_station_exits.csv` (tracked, small).

Limitation: the file shows **today's** network. Stations that opened between 2017 and 2026 are used for all years.

## Block coordinates, step 1: NUS 3D HDB dataset

| Item | Details |
|---|---|
| Dataset | 3D city model of Singapore public housing (HDB) buildings, version 2019-08-25 |
| Publisher | NUS Urban Analytics Lab (built from HDB, OpenStreetMap and OneMap data) |
| Link | https://github.com/ualsg/hdb3d-data |
| Licence | MIT. Terms of use ask to mention: NUS Urban Analytics Lab, HDB Singapore, OpenStreetMap contributors, and OneMap |
| Citation | Biljecki F (2020). Exploration of open data in Southeast Asia to generate 3D building models. ISPRS Annals VI-4/W1-2020: 37-44. doi:10.5194/isprs-annals-vi-4-w1-2020-37-2020 |
| Output | `data/external/hdb3d_block_centroids.csv` (tracked): one row per block with the centre of the building, converted from SVY21 (EPSG:3414) to latitude/longitude |

Run `python src/building_coords.py` (downloads `hdb.json`, about 90 MB, to `data/raw/`, not tracked). It matches about 90% of the addresses in the resale data (8,818 of 9,760). Blocks completed after mid-2019 are missing and are handled in step 2.

We checked the coordinate conversion against the `pyproj` library (difference under 0.1 m) and against OneMap for sample blocks (difference under 1 m).

## Block coordinates, step 2: OneMap

| Item | Details |
|---|---|
| Service | OneMap Search API, Singapore Land Authority |
| Documentation | https://www.onemap.gov.sg/apidocs/ |
| Endpoint | `https://www.onemap.gov.sg/api/common/elastic/search` (no API key needed) |
| Input | Addresses not found in step 1 (942 newer blocks) |
| Output | `data/external/block_coordinates.csv` (tracked) |

Run `python src/geocode_blocks.py`. It first copies the step-1 locations, then searches OneMap for the rest. OneMap limits searches without an account, so the script waits about one second between searches, pauses when OneMap answers "too many requests", and saves progress every 25 addresses, so it can be stopped and restarted. An optional free API token can be put in `.env` as `ONEMAP_TOKEN=...` (never uploaded). If a search finds nothing, it retries with abbreviations written out (e.g. `BT` → `BUKIT`). The `source` column says where each location came from (`hdb3d` or `onemap`), and the `match` column records how each OneMap address was found:

- `exact` / `expanded`: a result with the same block number was found
- `*_other_block`: only a nearby address on the same street was found (location is approximate)
- `not_found`: no result; these sales have no location

## Derived variables (`src/wrangle.py`)

| Variable | Meaning |
|---|---|
| `remaining_lease_years` | Remaining lease as a number, e.g. "61 years 04 months" → 61.33 |
| `storey_mid` | Middle of the storey range, e.g. "10 TO 12" → 11 |
| `price_per_sqm` | Resale price ÷ floor area |
| `flat_age` | Sale year − lease commencement year |
| `estate_type` | Mature / Non-mature (HDB list of 15 mature estates, checked 12 Oct 2026) |
| `lease_band` | Remaining lease grouped: < 60, 60–69, 70–79, 80–89, 90+ years |
| `is_million` | Sold for at least $1,000,000 |
| `nearest_mrt`, `mrt_dist_m` | Nearest MRT/LRT station and straight-line distance to its closest exit (metres) |
| `mrt_band` | < 400 m, 400–799 m, 800–1,199 m, 1,200 m + |
| `cbd_dist_km` | Straight-line distance to Raffles Place MRT (km) |
