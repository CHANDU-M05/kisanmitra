"""
KisanMitra - Feature Engineering Pipeline
Input: data/processed/clean_agmarknet_prices.csv (227,538 clean rows)
Output: data/processed/all_model_data.csv
Calculates lag features, seasonal metrics, and 60-day future target price per market-commodity group.
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
INPUT_PATH = PROCESSED_DIR / "clean_agmarknet_prices.csv"
OUTPUT_PATH = PROCESSED_DIR / "all_model_data.csv"

def get_season(month):
    if month in [12, 1, 2]:
        return "Winter"
    elif month in [3, 4, 5]:
        return "Summer"
    elif month in [6, 7, 8, 9]:
        return "Monsoon"
    else:
        return "Post-Monsoon"

def build_features():
    print("=" * 60)
    print("KisanMitra — Feature Engineering Pipeline")
    print(f"Loading preprocessed clean prices from {INPUT_PATH.name}...")
    print("=" * 60)

    if not INPUT_PATH.exists():
        print(f"[ERROR] Clean data file not found at {INPUT_PATH}")
        return

    df = pd.read_csv(INPUT_PATH)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values(["Commodity", "Market_Clean", "arrival_date"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Standardize column naming for model consumption
    df.rename(columns={
        "Commodity": "commodity",
        "Market_Clean": "market",
        "Modal_Price": "modal_price"
    }, inplace=True)

    # Calendar features
    df["month"] = df["arrival_date"].dt.month
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["quarter"] = df["arrival_date"].dt.quarter
    df["season"] = df["month"].apply(get_season)

    print("Computing per-series lag and seasonal features...")
    
    # Calculate 7d and 30d rolling lag features per market-commodity series
    # Using window rolling on dates where applicable, or shift-based rolling
    grouped = df.groupby(["commodity", "market"])

    df["price_7d_avg"] = grouped["modal_price"].transform(lambda x: x.rolling(7, min_periods=1).mean())
    df["price_30d_avg"] = grouped["modal_price"].transform(lambda x: x.rolling(30, min_periods=1).mean())
    df["price_7d_ago"] = grouped["modal_price"].shift(7)
    df["price_30d_ago"] = grouped["modal_price"].shift(30)
    
    df["price_trend_7d"] = (df["modal_price"] - df["price_7d_ago"]) / (df["price_7d_ago"] + 1e-5)
    
    # Calculate monthly seasonal benchmark average per commodity
    seasonal_avg = df.groupby(["commodity", "month"])["modal_price"].transform("mean")
    df["seasonal_avg"] = seasonal_avg
    df["vs_seasonal"] = (df["modal_price"] - df["seasonal_avg"]) / (df["seasonal_avg"] + 1e-5)

    # Calculate target price (60-day future horizon price) strictly within each market-commodity group
    df["target_price_60d"] = grouped["modal_price"].shift(-60)

    # Filter out rows where target_price_60d is NaN (the last 60 entries of each group)
    df_model = df.dropna(subset=["target_price_60d"]).copy()

    print(f"Total model features created: {len(df_model.columns)} columns.")
    print(f"Valid feature-target rows for training: {len(df_model):,}")

    df_model.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved feature dataset -> {OUTPUT_PATH}")

if __name__ == "__main__":
    build_features()
