# AI Usage Statement

> **Draft — please review together as a group before submission.** Edit anything that does not match what you actually did, and add any other AI tools members used (e.g. ChatGPT, GitHub Copilot).

## Tools used

| Tool | Link | Used by |
|---|---|---|
| Claude (Anthropic) | https://claude.ai | Ma Tianjiao, Deng Shenbojia |
| _add other tools here (e.g. GitHub Copilot, if used)_ | | |

## How we used GenAI

We acknowledge the use of **Claude (Anthropic)** to support **coding, debugging, documentation and checking our analysis**. Specifically, it was used to:

- **Find and access data:** suggest how to download datasets through the data.gov.sg API, how to get block locations from the NUS 3D HDB dataset (including converting SVY21 map coordinates to latitude/longitude), and how to look up the remaining blocks with the OneMap Search API.
- **Write and debug code:** draft the scripts in `src/` (download, geocoding, cleaning, summary tables) and the Streamlit dashboard `app.py`, and fix errors when running them.
- **Extend the analysis after TA feedback:** suggest adding distance to the nearest MRT exit and to the CBD, an interactive map, and a regression that holds other factors equal.
- **Documentation:** draft `README.md`, `data/DATA_SOURCES.md` and this file.
- **Figures and interpretation (Deng Shenbojia):** write `src/make_figures.py` for the static charts in `outputs/figures/`; explain the findings (e.g. why % and S$ rankings differ, why MRT distance and lease length are mixed together) and suggest plainer wording for the *Key findings* and *Limitations* sections of the README.

The types of prompts used included: describing our research question and the proposal feedback, asking how to clean specific columns (e.g. `"61 years 04 months"`), asking for a dashboard layout that tells a clear story, and pasting error messages for debugging.

## How we checked the output

- We ran the full pipeline ourselves (`download_data.py` → `download_mrt.py` → `geocode_blocks.py` → `wrangle.py` → `make_tables.py` → `streamlit run app.py`) on our own computers.
- We checked the cleaned data against the raw data (row counts, date range, example rows) and checked that medians in the dashboard match those computed directly in pandas.
- We checked HDB's official list of mature estates (hdb.gov.sg) against the list in `wrangle.py`.
- We spot-checked block locations on the map, compared the SVY21 conversion with the `pyproj` library and with OneMap for sample blocks, and reviewed the match-quality summary.
- We read the regression output ourselves and wrote the interpretation as associations, not causes.
- _TODO (Shenbojia): describe your own checks, only what you actually did, e.g. "ran `python src/make_figures.py` and `streamlit run app.py` on my own computer, compared the numbers on the figures with `outputs/tables/`, and read and edited the README text so that I can explain every point."_
- _Add any other checks you did._

## Responsibility

The outputs were used as a starting point for our code, analysis and documentation. We reviewed, modified and verified the outputs as appropriate, can explain every part of the code, and remain responsible for the final content, analysis, code and conclusions submitted as part of this project.
