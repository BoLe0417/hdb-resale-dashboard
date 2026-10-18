"""Quick look at the downloaded HDB resale data.

Usage (run from the project root folder):
    python src/check_data.py
"""

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "raw" / "hdb_resale_2017_onwards.csv"

df = pd.read_csv(DATA_FILE)

print("Shape (rows, columns):", df.shape)
print("\nFirst 5 rows:")
print(df.head())
print("\nColumn types:")
print(df.dtypes)
print("\nMissing values per column:")
print(df.isna().sum())
print("\nResale price summary:")
print(df["resale_price"].describe())
