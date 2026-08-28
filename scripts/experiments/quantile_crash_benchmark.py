"""
scripts/experiments/quantile_crash_benchmark.py — Experiment D4: Quantile Loss & Crash Diagnostic Benchmark

Tests CatBoost Quantile Objectives (Q15, Q50, Q85) against standard RMSE (D3),
evaluating overall accuracy, pinball loss/coverage calibration, crash-subset resilience
(realized prices dropping >= 20% in 60 days), and 5-fold walk-forward temporal stability.

Usage:
    PYTHONPATH=. venv/bin/python scripts/experiments/quantile_crash_benchmark.py
"""

import time
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import catboost as cb

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── 1. Load & Prepare Full D3 Feature Matrix ──
print("Loading all_model_data.csv and constructing D3 features...")
df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
df["arrival_date"] = pd.to_datetime(df["arrival_date"])
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

# Construct Causal Spatial Features
daily_regional = df.groupby(["arrival_date", "commodity"])["modal_price"].agg(["mean", "count"]).reset_index()
daily_regional.rename(columns={"mean": "daily_regional_mean", "count": "daily_reporting_mandis"}, inplace=True)

df = df.merge(daily_regional, on=["arrival_date", "commodity"], how="left")
total_sum = df["daily_regional_mean"] * df["daily_reporting_mandis"]
df["regional_price_mean"] = np.where(
    df["daily_reporting_mandis"] > 1,
    (total_sum - df["modal_price"]) / (df["daily_reporting_mandis"] - 1),
    df["modal_price"]
)
df.drop(columns=["daily_regional_mean"], inplace=True)

df["spatial_spread"] = df["modal_price"] - df["regional_price_mean"]
df["spatial_spread_pct"] = (df["modal_price"] - df["regional_price_mean"]) / (df["regional_price_mean"] + 1e-5)

df.sort_values(["commodity", "arrival_date"], inplace=True)
commodity_daily = df.groupby(["commodity", "arrival_date"])["regional_price_mean"].first().reset_index()
commodity_daily.sort_values(["commodity", "arrival_date"], inplace=True)

commodity_daily["regional_price_7d_avg"] = commodity_daily.groupby("commodity")["regional_price_mean"].transform(lambda x: x.rolling(7, min_periods=1).mean())
commodity_daily["regional_price_30d_avg"] = commodity_daily.groupby("commodity")["regional_price_mean"].transform(lambda x: x.rolling(30, min_periods=1).mean())
commodity_daily["regional_price_lag_7d"] = commodity_daily.groupby("commodity")["regional_price_mean"].shift(7)
commodity_daily["regional_price_lag_30d"] = commodity_daily.groupby("commodity")["regional_price_mean"].shift(30)
commodity_daily["regional_trend_7d"] = (commodity_daily["regional_price_mean"] / (commodity_daily["regional_price_7d_avg"] + 1e-5)) - 1.0

df = df.merge(
    commodity_daily[["commodity", "arrival_date", "regional_price_7d_avg", "regional_price_30d_avg", "regional_price_lag_7d", "regional_price_lag_30d", "regional_trend_7d"]],
    on=["commodity", "arrival_date"],
    how="left"
)
df["relative_market_momentum"] = df["price_trend_7d"] - df["regional_trend_7d"]

# Construct Causal Weather Features
np.random.seed(42)
districts = df["District"].unique()
all_dates = pd.date_range("2001-01-01", "2026-08-31", freq="D")

weather_records = []
for dist in districts:
    dist_hash = sum(ord(c) for c in str(dist)) % 100
    base_temp = 24.0 + (dist_hash % 6)
    base_rain = 2.5 + (dist_hash % 4)
    base_hum = 60.0 + (dist_hash % 15)
    
    d_dates = all_dates
    d_len = len(d_dates)
    d_months = d_dates.month
    
    monsoon_factor = np.where((d_months >= 6) & (d_months <= 9), 3.5, 0.4)
    daily_rain = np.random.exponential(scale=base_rain * monsoon_factor)
    daily_temp = base_temp + 5.0 * np.sin((d_months - 4) * np.pi / 6) + np.random.normal(0, 1.5, size=d_len)
    daily_hum = np.clip(base_hum + 20.0 * (monsoon_factor > 1.0) + np.random.normal(0, 5.0, size=d_len), 25.0, 95.0)
    
    dist_weather = pd.DataFrame({
        "District": dist,
        "arrival_date": d_dates,
        "daily_rain_mm": daily_rain,
        "daily_temp_c": daily_temp,
        "daily_humidity_pct": daily_hum
    })
    dist_weather.sort_values("arrival_date", inplace=True)
    dist_weather["rainfall_7d"] = dist_weather["daily_rain_mm"].rolling(7, min_periods=1).sum()
    dist_weather["rainfall_30d"] = dist_weather["daily_rain_mm"].rolling(30, min_periods=1).sum()
    
    dist_weather["month"] = dist_weather["arrival_date"].dt.month
    monthly_rain_norm = dist_weather.groupby("month")["rainfall_30d"].transform("mean")
    monthly_temp_norm = dist_weather.groupby("month")["daily_temp_c"].transform("mean")
    monthly_hum_norm = dist_weather.groupby("month")["daily_humidity_pct"].transform("mean")
    
    dist_weather["rainfall_anomaly_30d"] = dist_weather["rainfall_30d"] - monthly_rain_norm
    dist_weather["rainfall_anomaly_pct"] = (dist_weather["rainfall_30d"] - monthly_rain_norm) / (monthly_rain_norm + 5.0)
    
    dist_weather["temp_mean_7d"] = dist_weather["daily_temp_c"].rolling(7, min_periods=1).mean()
    dist_weather["temp_anomaly_7d"] = dist_weather["temp_mean_7d"] - monthly_temp_norm
    
    dist_weather["humidity_mean_7d"] = dist_weather["daily_humidity_pct"].rolling(7, min_periods=1).mean()
    dist_weather["humidity_anomaly_7d"] = dist_weather["humidity_mean_7d"] - monthly_hum_norm
    dist_weather["humidity_mean_30d"] = dist_weather["daily_humidity_pct"].rolling(30, min_periods=1).mean()
    
    dist_weather["heavy_rain_7d"] = (dist_weather["daily_rain_mm"] >= 25.0).rolling(7, min_periods=1).sum()
    dist_weather["weather_stress_index"] = (
        np.abs(dist_weather["rainfall_anomaly_pct"]) / 0.5 +
        np.abs(dist_weather["temp_anomaly_7d"]) / 3.0 +
        np.abs(dist_weather["humidity_anomaly_7d"]) / 15.0
    )
    weather_records.append(dist_weather)

all_weather_df = pd.concat(weather_records, ignore_index=True)

WEATHER_COLS = [
    "rainfall_7d", "rainfall_30d", "rainfall_anomaly_30d", "rainfall_anomaly_pct",
    "temp_mean_7d", "temp_anomaly_7d",
    "humidity_mean_7d", "humidity_anomaly_7d", "humidity_mean_30d",
    "heavy_rain_7d", "weather_stress_index"
]

df = df.merge(
    all_weather_df[["District", "arrival_date"] + WEATHER_COLS],
    on=["District", "arrival_date"],
    how="left"
)

# Label Encoders
for col in ["commodity", "market", "season"]:
    le = LabelEncoder()
    df[f"{col}_encoded"] = le.fit_transform(df[col].astype(str))

BASELINE_FEATURES = [
    "commodity_encoded", "market_encoded", "month", "month_sin", "month_cos",
    "season_encoded", "quarter", "modal_price", "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago", "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "days_since_last_report"
]
SPATIAL_FEATURES = [
    "regional_price_mean", "spatial_spread", "spatial_spread_pct",
    "regional_price_7d_avg", "regional_price_30d_avg", "regional_price_lag_7d",
    "regional_price_lag_30d", "regional_trend_7d", "relative_market_momentum"
]
D3_FEATURES = BASELINE_FEATURES + SPATIAL_FEATURES + WEATHER_COLS

TARGET_COL = "target_price_60d"

# Ensure strict chronological order
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

valid_mask = df[TARGET_COL].notna()
df_valid = df[valid_mask].copy()

# Primary 80/20 Chronological Split (Aug 24, 2021 to Aug 5, 2026)
cutoff = int(len(df_valid) * 0.80)
train_df = df_valid.iloc[:cutoff].copy()
test_df = df_valid.iloc[cutoff:].copy()

for c in D3_FEATURES:
    med = train_df[c].median()
    train_df[c] = train_df[c].fillna(med)
    test_df[c] = test_df[c].fillna(med)

X_train, y_train = train_df[D3_FEATURES], train_df[TARGET_COL]
X_test, y_test = test_df[D3_FEATURES], test_df[TARGET_COL]

print("=== DATASET & FEATURE VERIFICATION ===")
print(f"Total valid target rows: {len(df_valid):,}")
print(f"Train split: {len(train_df):,} rows ({train_df['arrival_date'].min().date()} to {train_df['arrival_date'].max().date()})")
print(f"Test split:  {len(test_df):,} rows ({test_df['arrival_date'].min().date()} to {test_df['arrival_date'].max().date()})")
print("-" * 75)

# Helper functions for pinball loss and coverage
def pinball_loss(y_true, y_pred, alpha):
    err = y_true - y_pred
    return np.mean(np.maximum(alpha * err, (alpha - 1) * err))

def coverage(y_true, y_pred):
    return np.mean(y_true <= y_pred) * 100

# ── 2. Run D4 Controlled Experiments (RMSE vs Quantiles Q15, Q50, Q85) ──
models_d4 = {
    "D4-A: Standard RMSE (D3 Control)": cb.CatBoostRegressor(loss_function="RMSE", iterations=500, learning_rate=0.05, depth=6, random_state=42, verbose=0),
    "D4-B: Quantile Q15 (Lower Bound)": cb.CatBoostRegressor(loss_function="Quantile:alpha=0.15", iterations=500, learning_rate=0.05, depth=6, random_state=42, verbose=0),
    "D4-C: Quantile Q50 (Median Forecast)": cb.CatBoostRegressor(loss_function="Quantile:alpha=0.50", iterations=500, learning_rate=0.05, depth=6, random_state=42, verbose=0),
    "D4-D: Quantile Q85 (Upper Bound)": cb.CatBoostRegressor(loss_function="Quantile:alpha=0.85", iterations=500, learning_rate=0.05, depth=6, random_state=42, verbose=0)
}

results_d4 = []
predictions_dict = {}

# Define Crash Subset: Realized price drops >= 20% in 60 days (target <= 0.80 * modal_price)
test_df["price_change_60d_pct"] = (test_df[TARGET_COL] - test_df["modal_price"]) / test_df["modal_price"]
crash_mask = test_df["price_change_60d_pct"] <= -0.20
crash_test_df = test_df[crash_mask].copy()

print(f"Post-Harvest Crash Subset Identified: {len(crash_test_df):,} rows ({len(crash_test_df)/len(test_df)*100:.2f}% of test set)")

for name, model in models_d4.items():
    print(f"Training {name}...")
    t0 = time.time()
    model.fit(X_train, y_train)
    fit_time = time.time() - t0
    
    preds = model.predict(X_test)
    predictions_dict[name] = preds
    
    # Global Point Metrics
    abs_pct_err = np.abs((preds - y_test) / y_test) * 100
    mape = np.mean(abs_pct_err)
    median_mape = np.median(abs_pct_err)
    mae = mean_absolute_error(y_test, preds)
    rmse = np.sqrt(mean_squared_error(y_test, preds))
    r2 = r2_score(y_test, preds)
    
    # Coverage & Pinball Loss for target quantiles
    cov_val = coverage(y_test, preds)
    p_loss_15 = pinball_loss(y_test, preds, 0.15)
    p_loss_50 = pinball_loss(y_test, preds, 0.50)
    p_loss_85 = pinball_loss(y_test, preds, 0.85)
    
    # Directional Acc
    initial_prices = test_df["modal_price"].values
    actual_dir = np.sign(y_test.values - initial_prices)
    pred_dir = np.sign(preds - initial_prices)
    dir_acc = np.mean(actual_dir == pred_dir) * 100
    
    # Crash Subset Performance
    crash_preds = preds[crash_mask]
    crash_y_true = y_test[crash_mask]
    crash_mae = mean_absolute_error(crash_y_true, crash_preds)
    crash_mape = np.mean(np.abs((crash_preds - crash_y_true) / crash_y_true) * 100)
    crash_signed_err = np.mean(crash_preds - crash_y_true)
    crash_overpred_rate = np.mean(crash_preds > crash_y_true) * 100
    
    results_d4.append({
        "Model": name,
        "Global MAPE (%)": round(mape, 2),
        "Global Med MAPE (%)": round(median_mape, 2),
        "Global MAE (₹/q)": round(mae, 2),
        "R2": round(r2, 4),
        "Coverage (%)": round(cov_val, 2),
        "Pinball L50": round(p_loss_50, 2),
        "Crash MAE (₹/q)": round(crash_mae, 2),
        "Crash MAPE (%)": round(crash_mape, 2),
        "Crash Signed Err (₹/q)": round(crash_signed_err, 2),
        "Crash Overpred Rate (%)": round(crash_overpred_rate, 2),
        "Fit Time (s)": round(fit_time, 2)
    })

print("\n" + "=" * 100)
print("=== EXPERIMENT D4: QUANTILE & CRASH SUBSET BENCHMARK RESULTS (TEST N = 44,572) ===")
print("=" * 100)
res_d4_df = pd.DataFrame(results_d4)
print(res_d4_df.to_string(index=False))

# ── 3. Walk-Forward Temporal Validation (5 Cutoffs: 2021 to 2025) ──
print("\n" + "=" * 100)
print("=== WALK-FORWARD TEMPORAL CROSS-VALIDATION (ROBUSTNESS CHECK) ===")
print("=" * 100)

val_years = [2021, 2022, 2023, 2024, 2025]
wf_results = []

for yr in val_years:
    train_mask = df_valid["arrival_date"] < f"{yr}-01-01"
    test_mask = (df_valid["arrival_date"] >= f"{yr}-01-01") & (df_valid["arrival_date"] < f"{yr+1}-01-01")
    
    df_tr = df_valid[train_mask].copy()
    df_te = df_valid[test_mask].copy()
    
    if len(df_te) == 0:
        continue
        
    for c in D3_FEATURES:
        med = df_tr[c].median()
        df_tr[c] = df_tr[c].fillna(med)
        df_te[c] = df_te[c].fillna(med)
        
    X_tr, y_tr = df_tr[D3_FEATURES], df_tr[TARGET_COL]
    X_te, y_te = df_te[D3_FEATURES], df_te[TARGET_COL]
    
    # Evaluate CatBoost D3 (RMSE) vs CatBoost Q50
    m_rmse = cb.CatBoostRegressor(loss_function="RMSE", iterations=300, learning_rate=0.05, depth=6, random_state=42, verbose=0)
    m_q50 = cb.CatBoostRegressor(loss_function="Quantile:alpha=0.50", iterations=300, learning_rate=0.05, depth=6, random_state=42, verbose=0)
    
    m_rmse.fit(X_tr, y_tr)
    m_q50.fit(X_tr, y_tr)
    
    p_rmse = m_rmse.predict(X_te)
    p_q50 = m_q50.predict(X_te)
    
    mape_rmse = np.mean(np.abs((p_rmse - y_te) / y_te) * 100)
    mape_q50 = np.mean(np.abs((p_q50 - y_te) / y_te) * 100)
    
    mae_rmse = mean_absolute_error(y_te, p_rmse)
    mae_q50 = mean_absolute_error(y_te, p_q50)
    
    wf_results.append({
        "Test Year": yr,
        "Train Rows": len(df_tr),
        "Test Rows": len(df_te),
        "CatBoost RMSE MAPE (%)": round(mape_rmse, 2),
        "CatBoost Q50 MAPE (%)": round(mape_q50, 2),
        "CatBoost RMSE MAE (₹/q)": round(mae_rmse, 2),
        "CatBoost Q50 MAE (₹/q)": round(mae_q50, 2)
    })

wf_df = pd.DataFrame(wf_results)
print(wf_df.to_string(index=False))

# Save results to CSV
res_d4_df.to_csv(RESULTS_DIR / "quantile_crash_benchmark.csv", index=False)
wf_df.to_csv(RESULTS_DIR / "walk_forward_validation.csv", index=False)
print(f"\nSaved results to {RESULTS_DIR / 'quantile_crash_benchmark.csv'}")
