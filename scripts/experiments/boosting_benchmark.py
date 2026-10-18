"""
scripts/experiments/boosting_benchmark.py — Controlled Model Architecture Benchmark

Compares Random Forest baseline against LightGBM, CatBoost, and Gradient Boosting
on the exact same chronological train/test split (Aug 24, 2021 to Aug 5, 2026, N = 44,572 test rows).

Usage:
    PYTHONPATH=. venv/bin/python scripts/experiments/boosting_benchmark.py
"""

import time
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Load Data ──
df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
df["arrival_date"] = pd.to_datetime(df["arrival_date"])
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

# Encode categorical variables
encoders = {}
for col in ["commodity", "market", "season"]:
    le = LabelEncoder()
    df[f"{col}_encoded"] = le.fit_transform(df[col].astype(str))
    encoders[col] = le

FEATURE_COLS = [
    "commodity_encoded", "market_encoded",
    "month", "month_sin", "month_cos",
    "season_encoded", "quarter",
    "modal_price",
    "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "days_since_last_report",
]
TARGET_COL = "target_price_60d"

# Filter valid target rows
valid_mask = df[TARGET_COL].notna()
df_valid = df[valid_mask].copy()

# Exact 80/20 Chronological Split
cutoff = int(len(df_valid) * 0.80)
train_df = df_valid.iloc[:cutoff].copy()
test_df = df_valid.iloc[cutoff:].copy()

# Fill missing values with training medians
for c in FEATURE_COLS:
    med = train_df[c].median()
    train_df[c] = train_df[c].fillna(med)
    test_df[c] = test_df[c].fillna(med)

X_train, y_train = train_df[FEATURE_COLS], train_df[TARGET_COL]
X_test, y_test = test_df[FEATURE_COLS], test_df[TARGET_COL]

print("=== DATASET & SPLIT VERIFICATION ===")
print(f"Total valid target rows: {len(df_valid):,}")
print(f"Train split: {len(train_df):,} rows ({train_df['arrival_date'].min().date()} to {train_df['arrival_date'].max().date()})")
print(f"Test split:  {len(test_df):,} rows ({test_df['arrival_date'].min().date()} to {test_df['arrival_date'].max().date()})")
print("-" * 60)

# Import LightGBM and CatBoost
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    print("Warning: LightGBM not installed")

try:
    import catboost as cb
    HAS_CAT = True
except ImportError:
    HAS_CAT = False
    print("Warning: CatBoost not installed")

models = {
    "Random Forest (M5 Baseline)": RandomForestRegressor(n_estimators=100, max_depth=15, random_state=42, n_jobs=-1),
    "HistGradientBoosting": HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, random_state=42),
}

if HAS_LGB:
    models["LightGBM"] = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31, random_state=42, verbose=-1, n_jobs=-1)

if HAS_CAT:
    models["CatBoost"] = cb.CatBoostRegressor(iterations=500, learning_rate=0.05, depth=6, random_state=42, verbose=0)

results = []
commodity_results = []

for name, model in models.items():
    print(f"Training {name}...")
    t0 = time.time()
    model.fit(X_train, y_train)
    fit_time = time.time() - t0
    
    preds = model.predict(X_test)
    
    # Calculate Overall Metrics
    abs_pct_err = np.abs((preds - y_test) / y_test) * 100
    mape = np.mean(abs_pct_err)
    median_mape = np.median(abs_pct_err)
    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    r2 = r2_score(y_test, preds)
    
    # Directional Accuracy (vs initial price)
    initial_prices = test_df["modal_price"].values
    actual_dir = np.sign(y_test.values - initial_prices)
    pred_dir = np.sign(preds - initial_prices)
    dir_acc = np.mean(actual_dir == pred_dir) * 100
    
    results.append({
        "Model": name,
        "MAPE (%)": round(mape, 2),
        "Median MAPE (%)": round(median_mape, 2),
        "MAE (₹/q)": round(mae, 2),
        "RMSE (₹/q)": round(rmse, 2),
        "R2": round(r2, 4),
        "Directional Acc (%)": round(dir_acc, 2),
        "Fit Time (s)": round(fit_time, 2)
    })
    
    # Per-Commodity Breakdown
    test_eval = test_df.copy()
    test_eval["pred"] = preds
    test_eval["ape"] = abs_pct_err
    
    for crop, group in test_eval.groupby("commodity"):
        commodity_results.append({
            "Model": name,
            "Commodity": crop,
            "Rows": len(group),
            "Mean MAPE (%)": round(group["ape"].mean(), 2),
            "Median MAPE (%)": round(group["ape"].median(), 2),
            "MAE (₹/q)": round(mean_absolute_error(group[TARGET_COL], group["pred"]), 2)
        })

# Print Overall Comparison
print("\n" + "=" * 80)
print("=== CONTROLLED MODEL ARCHITECTURE BENCHMARK RESULTS (TEST N = 44,572) ===")
print("=" * 80)
res_df = pd.DataFrame(results)
print(res_df.to_string(index=False))

# Print Per-Commodity Breakdown Table
print("\n" + "=" * 80)
print("=== PER-COMMODITY MEAN / MEDIAN MAPE BREAKDOWN ===")
print("=" * 80)
crop_res_df = pd.DataFrame(commodity_results)
pivot_df = crop_res_df.pivot(index="Commodity", columns="Model", values="Mean MAPE (%)")
print("Mean MAPE (%) by Crop:")
print(pivot_df.to_string())

pivot_med_df = crop_res_df.pivot(index="Commodity", columns="Model", values="Median MAPE (%)")
print("\nMedian MAPE (%) by Crop:")
print(pivot_med_df.to_string())

# Save to CSV
res_df.to_csv(RESULTS_DIR / "boosting_architecture_benchmark.csv", index=False)
crop_res_df.to_csv(RESULTS_DIR / "boosting_per_crop_benchmark.csv", index=False)
print(f"\nSaved results to {RESULTS_DIR / 'boosting_architecture_benchmark.csv'}")
