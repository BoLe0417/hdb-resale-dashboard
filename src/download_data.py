"""Download HDB resale flat prices (Jan 2017 onwards) from data.gov.sg.

Source: Housing & Development Board (HDB), via data.gov.sg
Licence: Singapore Open Data Licence
Usage (run from the project root folder):
    python src/download_data.py
"""

import time
from pathlib import Path

import requests

# Dataset ID shown in the data.gov.sg URL for this dataset
DATASET_ID = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"
BASE_URL = "https://api-open.data.gov.sg/v1/public/api/datasets"

# Relative paths: this file lives in src/, so the project root is one level up
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_FILE = RAW_DIR / "hdb_resale_2017_onwards.csv"


def get_download_url(dataset_id, max_tries=10):
    """Ask data.gov.sg to prepare the file, then wait until the link is ready."""
    start = requests.get(f"{BASE_URL}/{dataset_id}/initiate-download", timeout=30)
    start.raise_for_status()

    for attempt in range(max_tries):
        resp = requests.get(f"{BASE_URL}/{dataset_id}/poll-download", timeout=30)
        resp.raise_for_status()
        data = resp.json()["data"]
        if data.get("status") == "DOWNLOAD_SUCCESS":
            return data["url"]
        print(f"  Link not ready yet (try {attempt + 1}/{max_tries}), waiting...")
        time.sleep(3)

    raise RuntimeError("Download link was not ready. Please try again later.")


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if OUTPUT_FILE.exists():
        print(f"File already exists, skipping download: {OUTPUT_FILE}")
        return

    print("Requesting download link from data.gov.sg ...")
    url = get_download_url(DATASET_ID)

    print("Downloading CSV (about 23 MB) ...")
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    OUTPUT_FILE.write_bytes(resp.content)

    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
