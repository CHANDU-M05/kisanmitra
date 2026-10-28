"""
scripts/experiments/audit_quantile_calibration.py — Audit CatBoost Quantile Calibration

Investigates CatBoost Quantile loss convergence, iterations, learning rate,
and exact empirical coverage math for Q15, Q50, Q85 on test set.

Usage:
    PYTHONPATH=. venv/bin/python scripts/experiments/audit_quantile_calibration.py
"""

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

# Load data
df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
df["arrival_date"] = pd.to_datetime(df["arrival_date"])
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

# Reconstruct D3 features
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

# Weather features
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

df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

valid_mask = df[TARGET_COL].notna()
df_valid = df[valid_mask].copy()

cutoff = int(len(df_valid) * 0.80)
train_df = df_valid.iloc[:cutoff].copy()
test_df = df_valid.iloc[cutoff:].copy()

for c in D3_FEATURES:
    med = train_df[c].median()
    train_df[c] = train_df[c].fillna(med)
    test_df[c] = test_df[c].fillna(med)

X_train, y_train = train_df[D3_FEATURES], train_df[TARGET_COL]
X_test, y_test = test_df[D3_FEATURES], test_df[TARGET_COL]

print("=== AUDITING CATBOOST QUANTILE CALIBRATION & COVERAGE ===")

# Test MAE loss vs Quantile:alpha=0.50 with 1000 iterations and higher learning rate
test_configs = [
    ("RMSE (D3 Control)", "RMSE", 500, 0.05),
    ("MAE (L1 Loss)", "MAE", 500, 0.05),
    ("Quantile Q15 (iter=500, lr=0.05)", "Quantile:alpha=0.15", 500, 0.05),
    ("Quantile Q50 (iter=500, lr=0.05)", "Quantile:alpha=0.50", 500, 0.05),
    ("Quantile Q85 (iter=500, lr=0.05)", "Quantile:alpha=0.85", 500, 0.05),
    ("Quantile Q15 (iter=1000, lr=0.1)", "Quantile:alpha=0.15", 1000, 0.1),
    ("Quantile Q50 (iter=1000, lr=0.1)", "Quantile:alpha=0.50", 1000, 0.1),
    ("Quantile Q85 (iter=1000, lr=0.1)", "Quantile:alpha=0.85", 1000, 0.1),
]

audit_results = []

for name, loss_fn, iter_cnt, lr in test_configs:
    model = cb.CatBoostRegressor(loss_function=loss_fn, iterations=iter_cnt, learning_rate=lr, depth=6, random_state=42, verbose=0)
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    
    # Calculate coverage: proportion of actuals <= prediction (y_test <= preds)
    cov_y_le_pred = np.mean(y_test <= preds) * 100
    # Calculate coverage: proportion of actuals >= prediction (y_test >= preds)
    cov_y_ge_pred = np.mean(y_test >= preds) * 100
    
    # Calculate training set empirical coverage
    train_preds = model.predict(X_train)
    train_cov = np.mean(y_train <= train_preds) * 100
    
    mape = np.mean(np.abs((preds - y_test) / y_test) * 100)
    med_mape = np.median(np.abs((preds - y_test) / y_test) * 100)
    mae = mean_absolute_error(y_test, preds)
    
    # Signed residual: mean(preds - y_test)
    signed_res = np.mean(preds - y_test)
    
    audit_results.append({
        "Configuration": name,
        "Train Cov (y<=q)": round(train_cov, 2),
        "Test Cov (y<=q)": round(cov_y_le_pred, 2),
        "MAPE (%)": round(mape, 2),
        "Med MAPE (%)": round(med_mape, 2),
        "MAE (₹/q)": round(mae, 2),
        "Signed Bias (₹/q)": round(signed_res, 2)
    })

res_df = pd.DataFrame(audit_results)
print("\n" + "=" * 90)
print("=== CATBOOST QUANTILE CALIBRATION AUDIT RESULTS ===")
print("=" * 90)
print(res_df.to_string(index=False))
