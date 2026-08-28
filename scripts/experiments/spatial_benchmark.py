"""
scripts/experiments/spatial_benchmark.py — Experiment D: Spatial Feature Benchmark

Tests whether causal, past-only regional spatial signals (regional price mean,
spatial spread, relative market momentum, spatial lags) improve T+60 forecasting.

Ablation Ladder:
  - D0: CatBoost Baseline (Existing Features) -> 35.73% MAPE, MAE ₹707.30
  - D1: CatBoost + Spatial Features
  - D2: LightGBM + Spatial Features
  - RF + Spatial Features (Reference)

Strict Causal Rule:
  All spatial aggregations for date t are calculated strictly using data on or before t.
"""

import time
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import lightgbm as lgb
import catboost as cb

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Load Data ──
print("Loading all_model_data.csv...")
df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
df["arrival_date"] = pd.to_datetime(df["arrival_date"])
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

# ── Construct Causal Spatial Features ──
print("Constructing causal spatial features (strictly <= t)...")

# 1. Daily regional mean per (arrival_date, commodity)
# Compute global daily mean for each commodity across all markets
daily_regional = df.groupby(["arrival_date", "commodity"])["modal_price"].agg(["mean", "count"]).reset_index()
daily_regional.rename(columns={"mean": "daily_regional_mean", "count": "daily_reporting_mandis"}, inplace=True)

# Merge daily regional mean back
df = df.merge(daily_regional, on=["arrival_date", "commodity"], how="left")

# To make 'regional_price_mean' strictly leave-one-out for the target market:
# If daily_reporting_mandis > 1: (total_sum - my_price) / (count - 1)
# If daily_reporting_mandis == 1: fallback to my_price
total_sum = df["daily_reporting_mean"] * df["daily_reporting_mandis"] if "daily_reporting_mean" in df else df["daily_regional_mean"] * df["daily_reporting_mandis"]
df["regional_price_mean"] = np.where(
    df["daily_reporting_mandis"] > 1,
    (total_sum - df["modal_price"]) / (df["daily_reporting_mandis"] - 1),
    df["modal_price"]
)
df.drop(columns=["daily_regional_mean"], inplace=True)

# 2. Spatial Spread and Percentage Spread
df["spatial_spread"] = df["modal_price"] - df["regional_price_mean"]
df["spatial_spread_pct"] = (df["modal_price"] - df["regional_price_mean"]) / (df["regional_price_mean"] + 1e-5)

# 3. Rolling Regional Trends & Lags (per commodity over date)
# Sort by commodity and date to compute causal rolling regional statistics
df.sort_values(["commodity", "arrival_date"], inplace=True)

# Group by commodity and date (daily unique series for regional mean)
commodity_daily = df.groupby(["commodity", "arrival_date"])["regional_price_mean"].first().reset_index()
commodity_daily.sort_values(["commodity", "arrival_date"], inplace=True)

# Rolling 7d and 30d regional averages (strictly past <= t)
commodity_daily["regional_price_7d_avg"] = commodity_daily.groupby("commodity")["regional_price_mean"].transform(
    lambda x: x.rolling(7, min_periods=1).mean()
)
commodity_daily["regional_price_30d_avg"] = commodity_daily.groupby("commodity")["regional_price_mean"].transform(
    lambda x: x.rolling(30, min_periods=1).mean()
)
commodity_daily["regional_price_lag_7d"] = commodity_daily.groupby("commodity")["regional_price_mean"].shift(7)
commodity_daily["regional_price_lag_30d"] = commodity_daily.groupby("commodity")["regional_price_mean"].shift(30)

# Regional momentum
commodity_daily["regional_trend_7d"] = (commodity_daily["regional_price_mean"] / (commodity_daily["regional_price_7d_avg"] + 1e-5)) - 1.0

# Merge rolling regional dynamics back to main dataframe
df = df.merge(
    commodity_daily[["commodity", "arrival_date", "regional_price_7d_avg", "regional_price_30d_avg", "regional_price_lag_7d", "regional_price_lag_30d", "regional_trend_7d"]],
    on=["commodity", "arrival_date"],
    how="left"
)

# Relative market momentum (how target mandi moves vs overall region)
df["relative_market_momentum"] = df["price_trend_7d"] - df["regional_trend_7d"]

# Re-sort by arrival_date to restore strict chronological index order
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

# ── Feature Sets Definition ──
encoders = {}
for col in ["commodity", "market", "season"]:
    le = LabelEncoder()
    df[f"{col}_encoded"] = le.fit_transform(df[col].astype(str))
    encoders[col] = le

BASELINE_FEATURES = [
    "commodity_encoded", "market_encoded",
    "month", "month_sin", "month_cos",
    "season_encoded", "quarter",
    "modal_price",
    "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "days_since_last_report",
]

SPATIAL_FEATURES = [
    "regional_price_mean",
    "spatial_spread",
    "spatial_spread_pct",
    "regional_price_7d_avg",
    "regional_price_30d_avg",
    "regional_price_lag_7d",
    "regional_price_lag_30d",
    "regional_trend_7d",
    "relative_market_momentum"
]

ALL_FEATURES_WITH_SPATIAL = BASELINE_FEATURES + SPATIAL_FEATURES

TARGET_COL = "target_price_60d"

# Filter valid target rows
valid_mask = df[TARGET_COL].notna()
df_valid = df[valid_mask].copy()

# Exact 80/20 Chronological Split
cutoff = int(len(df_valid) * 0.80)
train_df = df_valid.iloc[:cutoff].copy()
test_df = df_valid.iloc[cutoff:].copy()

# Impute missing values with training medians
for c in ALL_FEATURES_WITH_SPATIAL:
    med = train_df[c].median()
    train_df[c] = train_df[c].fillna(med)
    test_df[c] = test_df[c].fillna(med)

print("=== DATASET & SPLIT VERIFICATION ===")
print(f"Total valid target rows: {len(df_valid):,}")
print(f"Train split: {len(train_df):,} rows ({train_df['arrival_date'].min().date()} to {train_df['arrival_date'].max().date()})")
print(f"Test split:  {len(test_df):,} rows ({test_df['arrival_date'].min().date()} to {test_df['arrival_date'].max().date()})")
print(f"Baseline features count: {len(BASELINE_FEATURES)}")
print(f"Spatial features added:  {len(SPATIAL_FEATURES)} -> Total: {len(ALL_FEATURES_WITH_SPATIAL)}")
print("-" * 60)

# Define Controlled Experiments
experiments = [
    {
        "name": "D0: CatBoost Baseline (No Spatial)",
        "model": cb.CatBoostRegressor(iterations=500, learning_rate=0.05, depth=6, random_state=42, verbose=0),
        "features": BASELINE_FEATURES
    },
    {
        "name": "D1: CatBoost + Spatial Features",
        "model": cb.CatBoostRegressor(iterations=500, learning_rate=0.05, depth=6, random_state=42, verbose=0),
        "features": ALL_FEATURES_WITH_SPATIAL
    },
    {
        "name": "D0: LightGBM Baseline (No Spatial)",
        "model": lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31, random_state=42, verbose=-1, n_jobs=-1),
        "features": BASELINE_FEATURES
    },
    {
        "name": "D2: LightGBM + Spatial Features",
        "model": lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31, random_state=42, verbose=-1, n_jobs=-1),
        "features": ALL_FEATURES_WITH_SPATIAL
    },
    {
        "name": "RF Baseline (No Spatial)",
        "model": RandomForestRegressor(n_estimators=100, max_depth=15, random_state=42, n_jobs=-1),
        "features": BASELINE_FEATURES
    },
    {
        "name": "RF + Spatial Features",
        "model": RandomForestRegressor(n_estimators=100, max_depth=15, random_state=42, n_jobs=-1),
        "features": ALL_FEATURES_WITH_SPATIAL
    }
]

results = []
commodity_results = []

for exp in experiments:
    name = exp["name"]
    model = exp["model"]
    feat_cols = exp["features"]
    
    X_train = train_df[feat_cols]
    y_train = train_df[TARGET_COL]
    X_test = test_df[feat_cols]
    y_test = test_df[TARGET_COL]
    
    print(f"Running {name}...")
    t0 = time.time()
    model.fit(X_train, y_train)
    fit_time = time.time() - t0
    
    preds = model.predict(X_test)
    
    # Metrics
    abs_pct_err = np.abs((preds - y_test) / y_test) * 100
    mape = np.mean(abs_pct_err)
    median_mape = np.median(abs_pct_err)
    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    r2 = r2_score(y_test, preds)
    
    # Directional accuracy
    initial_prices = test_df["modal_price"].values
    actual_dir = np.sign(y_test.values - initial_prices)
    pred_dir = np.sign(preds - initial_prices)
    dir_acc = np.mean(actual_dir == pred_dir) * 100
    
    results.append({
        "Experiment": name,
        "MAPE (%)": round(mape, 2),
        "Median MAPE (%)": round(median_mape, 2),
        "MAE (₹/q)": round(mae, 2),
        "RMSE (₹/q)": round(rmse, 2),
        "R2": round(r2, 4),
        "Directional Acc (%)": round(dir_acc, 2),
        "Fit Time (s)": round(fit_time, 2)
    })

    # Per Crop Eval for CatBoost D0 vs D1
    if "CatBoost" in name:
        test_eval = test_df.copy()
        test_eval["pred"] = preds
        test_eval["ape"] = abs_pct_err
        for crop, group in test_eval.groupby("commodity"):
            commodity_results.append({
                "Experiment": name,
                "Commodity": crop,
                "Mean MAPE (%)": round(group["ape"].mean(), 2),
                "Median MAPE (%)": round(group["ape"].median(), 2),
                "MAE (₹/q)": round(mean_absolute_error(group[TARGET_COL], group["pred"]), 2)
            })

# Print Main Results Table
print("\n" + "=" * 90)
print("=== EXPERIMENT D: SPATIAL FEATURE ABLATION BENCHMARK RESULTS (TEST N = 44,572) ===")
print("=" * 90)
res_df = pd.DataFrame(results)
print(res_df.to_string(index=False))

if commodity_results:
    print("\n" + "=" * 90)
    print("=== CATBOOST SPATIAL FEATURE IMPACT PER COMMODITY ===")
    print("=" * 90)
    crop_res_df = pd.DataFrame(commodity_results)
    pivot_df = crop_res_df.pivot(index="Commodity", columns="Experiment", values="Mean MAPE (%)")
    print("Mean MAPE (%) by Crop:")
    print(pivot_df.to_string())

# Save results
res_df.to_csv(RESULTS_DIR / "spatial_feature_benchmark.csv", index=False)
print(f"\nSaved results to {RESULTS_DIR / 'spatial_feature_benchmark.csv'}")
