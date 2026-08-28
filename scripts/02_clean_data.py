"""
KisanMitra - Data Cleaning & Preprocessing Pipeline
Input: data/raw/real_karnataka_agmarknet_full.csv (490,240 rows)
Output: data/processed/clean_agmarknet_prices.csv
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_PATH = BASE_DIR / "data" / "raw" / "real_karnataka_agmarknet_full.csv"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

def clean_market_name(m):
    """Normalize APMC market string variants and standardize spellings."""
    if pd.isna(m):
        return m
    m = str(m).strip()
    if m.endswith(" APMC") or m.endswith(" apmc"):
        m = m[:-5].strip()
    
    mapping = {
        "Bengaluru": "Bangalore",
        "Binny Mill (F&V), Bangalore": "Bangalore",
        "Chikkamagalore": "Chikkamagaluru",
        "Chickkaballapura": "Chikkaballapur",
        "Belgaum": "Belagavi",
        "Mysore (Bandipalya)": "Mysuru",
        "Davangere": "Davanagere",
        "Hubli (Amaragol)": "Hubballi",
        "Shimoga": "Shivamogga",
        "Tumkur": "Tumakuru",
    }
    return mapping.get(m, m)

def main():
    print("=" * 60)
    print("KisanMitra — Data Preprocessing Pipeline")
    print(f"Loading raw dataset from {RAW_PATH.name}...")
    print("=" * 60)

    if not RAW_PATH.exists():
        print(f"[ERROR] Raw data file not found at {RAW_PATH}")
        return

    df = pd.read_csv(RAW_PATH, low_memory=False)
    print(f"Raw record count: {len(df):,}")

    # Standardize column names
    date_col = "arrival_date" if "arrival_date" in df.columns else "Arrival_Date"
    df["arrival_date"] = pd.to_datetime(df[date_col], errors="coerce")
    df.dropna(subset=["arrival_date"], inplace=True)

    # Standardize numeric price columns
    price_cols = ["Min_Price", "Max_Price", "Modal_Price"]
    for col in price_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df.dropna(subset=["Modal_Price"], inplace=True)
    df = df[df["Modal_Price"] > 0]

    # Apply market string normalization
    df["Market_Clean"] = df["Market"].apply(clean_market_name)
    print(f"Market string normalization: {df['Market'].nunique()} raw markets -> {df['Market_Clean'].nunique()} clean mandis.")

    # Sort chronologically
    df.sort_values(["Commodity", "Market_Clean", "arrival_date"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Compute per-market, per-commodity gap days
    df["prev_date"] = df.groupby(["Commodity", "Market_Clean"])["arrival_date"].shift(1)
    df["days_since_last_report"] = (df["arrival_date"] - df["prev_date"]).dt.days.fillna(0).astype(int)

    # Calculate market-commodity inclusion metrics
    # Rationale: count >= 500 AND max gap <= 365 days (no full 12-month calendar silence)
    group_stats = df.groupby(["Commodity", "Market_Clean"]).agg(
        total_rows=("arrival_date", "count"),
        max_gap=("days_since_last_report", "max"),
        min_date=("arrival_date", "min"),
        max_date=("arrival_date", "max")
    ).reset_index()

    valid_groups = group_stats[
        (group_stats["total_rows"] >= 500) & (group_stats["max_gap"] <= 365)
    ]

    print(f"\nInclusion Filter: Total series = {len(group_stats)}, Qualified series = {len(valid_groups)}")
    
    # Filter dataset to qualified market-commodity series
    qualified_keys = set(zip(valid_groups["Commodity"], valid_groups["Market_Clean"]))
    df["is_qualified"] = df.apply(lambda r: (r["Commodity"], r["Market_Clean"]) in qualified_keys, axis=1)
    
    df_clean = df[df["is_qualified"]].copy()
    df_clean.drop(columns=["is_qualified", "prev_date"], inplace=True)

    print("\nQualified High-Volume / Low-Gap Series Distribution:")
    print(valid_groups.sort_values("total_rows", ascending=False).to_string(index=False))

    print(f"\nClean Preprocessed Rows: {len(df_clean):,} (from {len(df):,})")
    
    output_path = PROCESSED_DIR / "clean_agmarknet_prices.csv"
    df_clean.to_csv(output_path, index=False)
    print(f"Saved preprocessed dataset -> {output_path}")

if __name__ == "__main__":
    main()
