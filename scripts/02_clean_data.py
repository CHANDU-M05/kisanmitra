import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

COMMODITY_MAP = {
    "tomato": "Tomato", "tamatar": "Tomato",
    "tomato(hybrid)": "Tomato", "tomato(local)": "Tomato",
    "potato": "Potato", "aloo": "Potato",
    "onion": "Onion", "big onion": "Onion",
    "marigold": "Marigold", "capsicum": "Capsicum",
    "brinjal": "Brinjal", "ragi": "Ragi", "maize": "Maize",
}

def load_data():
    df = pd.read_csv(RAW_DIR / "agmarknet_karnataka.csv")
    df["arrival_date"] = pd.to_datetime(df["arrival_date"], errors="coerce")
    df.dropna(subset=["arrival_date"], inplace=True)
    print(f"Loaded {len(df):,} rows")
    return df

def fix_commodity_names(df):
    print("\nStep 1: Fixing commodity names...")
    df["commodity"] = df["commodity"].str.lower().str.strip().map(COMMODITY_MAP)
    df.dropna(subset=["commodity"], inplace=True)
    print(f"  Crops: {sorted(df['commodity'].unique())}")
    return df

def fix_prices(df):
    print("\nStep 2: Fixing prices...")
    before = len(df)
    for col in ["min_price", "max_price", "modal_price"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["modal_price"], inplace=True)
    df = df[(df["modal_price"] >= 50) & (df["modal_price"] <= 50000)].copy()
    df["arrivals_tonnes"] = pd.to_numeric(df["arrivals_tonnes"], errors="coerce")
    df["arrivals_tonnes"] = df["arrivals_tonnes"].fillna(df["arrivals_tonnes"].median())
    print(f"  Removed {before - len(df)} bad rows. Remaining: {len(df):,}")
    return df

def add_features(df):
    print("\nStep 3: Adding features...")
    df.sort_values(["market", "commodity", "arrival_date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    g = df.groupby(["market", "commodity"])
    df["month"] = df["arrival_date"].dt.month
    df["year"] = df["arrival_date"].dt.year
    df["quarter"] = df["arrival_date"].dt.quarter
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    def get_season(m):
        if m in [6,7,8,9,10,11]: return 0
        elif m in [12,1,2,3]: return 1
        else: return 2
    df["season"] = df["month"].apply(get_season)
    df["price_7d_avg"] = g["modal_price"].transform(lambda x: x.shift(1).rolling(7, min_periods=3).mean())
    df["price_30d_avg"] = g["modal_price"].transform(lambda x: x.shift(1).rolling(30, min_periods=10).mean())
    df["price_7d_ago"] = g["modal_price"].transform(lambda x: x.shift(7))
    df["price_30d_ago"] = g["modal_price"].transform(lambda x: x.shift(30))
    df["price_trend_7d"] = (df["modal_price"] - df["price_7d_ago"]) / df["price_7d_ago"].replace(0, np.nan)
    monthly_avg = df.groupby(["market","commodity","month"])["modal_price"].mean().reset_index().rename(columns={"modal_price":"seasonal_avg"})
    df = df.merge(monthly_avg, on=["market","commodity","month"], how="left")
    df["vs_seasonal"] = df["modal_price"] / df["seasonal_avg"].replace(0, np.nan)
    df["arrivals_7d_avg"] = g["arrivals_tonnes"].transform(lambda x: x.shift(1).rolling(7, min_periods=3).mean())
    df["target_price_60d"] = g["modal_price"].transform(lambda x: x.shift(-60))
    print(f"  Total columns: {len(df.columns)}")
    return df

def save_outputs(df):
    print("\nStep 4: Saving...")
    df.to_csv(PROCESSED_DIR / "karnataka_clean.csv", index=False)
    tomato = df[(df["commodity"]=="Tomato") & (df["market"].isin(["Kolar","Chikkaballapur"]))].copy()
    tomato.dropna(subset=["target_price_60d"], inplace=True)
    tomato.to_csv(PROCESSED_DIR / "tomato_model_data.csv", index=False)
    print(f"  Full dataset:   {len(df):,} rows")
    print(f"  Tomato dataset: {len(tomato):,} rows")
    return tomato

def main():
    print("="*50)
    print("KisanMitra - Data Cleaning")
    print("="*50)
    df = load_data()
    df = fix_commodity_names(df)
    df = fix_prices(df)
    df = add_features(df)
    save_outputs(df)
    print("\nDone! Next: python scripts/03_train_model.py")

if __name__ == "__main__":
    main()
