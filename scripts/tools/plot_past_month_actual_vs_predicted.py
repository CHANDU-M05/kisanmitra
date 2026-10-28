import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from pathlib import Path
from catboost import CatBoostRegressor
from sklearn.preprocessing import LabelEncoder

# Save location
ARTIFACTS_DIR = Path("/home/chandu/.gemini/antigravity-ide/brain/405adf4b-ec6a-46d0-86d3-78507e97e0bc")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]

# Load Data
df = pd.read_csv("data/processed/all_model_data.csv")
df["arrival_date"] = pd.to_datetime(df["arrival_date"])
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

# Encode Categoricals
le_c = LabelEncoder()
le_m = LabelEncoder()
le_s = LabelEncoder()
df["commodity_encoded"] = le_c.fit_transform(df["commodity"])
df["market_encoded"] = le_m.fit_transform(df["market"])
df["season_encoded"] = le_s.fit_transform(df["season"].astype(str))

FEATURE_COLS = [
    "commodity_encoded", "market_encoded", "month", "month_sin", "month_cos",
    "season_encoded", "quarter", "modal_price", "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago", "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "days_since_last_report"
]

valid = df["target_price_60d"].notna()
df = df[valid].copy()
for c in FEATURE_COLS:
    df[c] = df[c].fillna(df[c].median())

cutoff = int(len(df) * 0.80)
train_df = df.iloc[:cutoff]
test_df = df.iloc[cutoff:].copy()

print(f"Training CatBoost on {len(train_df):,} rows...")
model = CatBoostRegressor(iterations=300, depth=6, verbose=0, random_seed=42)
model.fit(train_df[FEATURE_COLS], train_df["target_price_60d"])

# Predict on full test set
test_df["predicted_price"] = model.predict(test_df[FEATURE_COLS])
test_df["abs_error"] = np.abs(test_df["predicted_price"] - test_df["target_price_60d"])
test_df["pct_error"] = test_df["abs_error"] / test_df["target_price_60d"] * 100

crops = sorted(test_df["commodity"].unique())
print(f"Test crops: {crops}")

# ── 1. Create a 6-Panel Subplot (1 Panel per Commodity for the Past 30 Days) ────
fig, axes = plt.subplots(3, 2, figsize=(15, 12), dpi=300)
axes = axes.flatten()

crop_summaries = []

for idx, crop in enumerate(crops):
    ax = axes[idx]
    crop_df = test_df[test_df["commodity"] == crop].copy()
    
    # Get the last 35 days of test observations for this specific crop
    max_crop_date = crop_df["arrival_date"].max()
    min_crop_date = max_crop_date - pd.Timedelta(days=35)
    
    recent_crop = crop_df[crop_df["arrival_date"] >= min_crop_date].sort_values("arrival_date")
    
    # Aggregate daily mean actual vs predicted price across markets
    daily = recent_crop.groupby("arrival_date").agg({
        "target_price_60d": "mean",
        "predicted_price": "mean",
        "abs_error": "mean",
        "pct_error": "mean"
    }).reset_index()
    
    mean_actual = daily["target_price_60d"].mean()
    mean_pred = daily["predicted_price"].mean()
    mae_val = daily["abs_error"].mean()
    mape_val = daily["pct_error"].mean()
    
    crop_summaries.append({
        "Crop": crop,
        "Date Window": f"{daily['arrival_date'].min().date()} to {daily['arrival_date'].max().date()}",
        "Actual Mean (₹/q)": round(mean_actual, 2),
        "Predicted Mean (₹/q)": round(mean_pred, 2),
        "MAE (₹/q)": round(mae_val, 2),
        "MAPE (%)": round(mape_val, 2)
    })
    
    # Plot Actual vs Predicted Line Chart
    ax.plot(daily["arrival_date"], daily["target_price_60d"], label="Actual Market Price", color="#1E3A8A", linewidth=2.5, marker="o", markersize=4)
    ax.plot(daily["arrival_date"], daily["predicted_price"], label="CatBoost Forecast (T+60)", color="#DC2626", linewidth=2.2, linestyle="--", marker="s", markersize=4)
    
    ax.set_title(f"{crop} — Past 1 Month Window (MAE: ₹{mae_val:.1f}/q | MAPE: {mape_val:.1f}%)", fontsize=11, fontweight="bold", pad=8)
    ax.set_ylabel("Price (₹ / quintal)", fontsize=9, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=8.5)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)

fig.suptitle("Actual vs. Predicted Commodity Prices (Past 1 Month Window per Commodity)", fontsize=14, fontweight="bold", y=0.99)
plt.tight_layout()

chart_path = ARTIFACTS_DIR / "actual_vs_predicted_past_1month.png"
fig.savefig(chart_path, dpi=300, bbox_inches="tight")
plt.close(fig)

print(f"\nSaved graph to {chart_path}")

# Print summary table
summary_df = pd.DataFrame(crop_summaries)
print("\n" + "="*80)
print("PAST 1 MONTH ACTUAL VS PREDICTED PRICE SUMMARY (PER COMMODITY)")
print("="*80)
print(summary_df.to_string(index=False))
