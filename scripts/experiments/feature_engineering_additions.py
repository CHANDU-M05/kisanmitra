"""
scripts/feature_engineering_additions.py

Adds three low-effort, high-signal features to the existing pipeline:
  1. Price momentum: % change vs 7 days ago (direction, not just level)
  2. Rolling price volatility: 30-day trailing std per crop+market
  3. Log-transformed target with inverse-transform at prediction time

Note on cyclical month encoding (month_sin, month_cos):
  These columns already exist in all_model_data.csv and FEATURE_COLS.
  No changes needed for that — it was already done correctly.

Note on ordinal 'month' column:
  'month' is kept in FEATURE_COLS because the model was trained with it.
  After retraining with the new features you can drop it from FEATURE_COLS
  since month_sin/cos fully capture the cyclical signal. This script adds
  momentum and volatility but does NOT drop 'month' to keep a clean diff.

Usage:
    venv/bin/python scripts/feature_engineering_additions.py

Output: Overwrites data/models/price_model.pkl and model_metadata.json
        with the retrained model using the new features.
"""

import sys
import json
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error, r2_score, mean_absolute_error
from sklearn.preprocessing import LabelEncoder

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
MODELS_DIR    = Path(__file__).parent.parent / "data" / "models"
DATA_PATH     = PROCESSED_DIR / "all_model_data.csv"

# Original features from 03_train_model.py, plus two new ones appended
FEATURE_COLS = [
    "commodity_encoded", "market_encoded",
    "month", "month_sin", "month_cos",
    "season", "quarter",
    "modal_price",
    "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "arrivals_tonnes",
    "arrivals_7d_avg",
    # --- New features added by this script ---
    "price_momentum_7d",
    "price_volatility_30d",
]
TARGET_COL = "target_price_60d"


def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds price_momentum_7d and price_volatility_30d.
    Expects df sorted by arrival_date ascending (already done in load_data).
    Groups by commodity+market so rolling windows don't bleed across series.
    """
    df = df.copy()

    # 1. Price momentum: % change vs 7 days ago within same crop+market series
    #    price_7d_ago already exists in the CSV — reuse it directly.
    #    Guard against division by zero with replace(0, NaN).
    df["price_momentum_7d"] = (
        (df["modal_price"] - df["price_7d_ago"])
        / df["price_7d_ago"].replace(0, np.nan)
    ).fillna(0.0)

    # 2. Rolling 30-day price volatility (std) per crop+market
    #    min_periods=5 avoids NaN on the first few rows of each series.
    df["price_volatility_30d"] = (
        df.groupby(["commodity", "market"])["modal_price"]
        .transform(lambda s: s.rolling(window=30, min_periods=5).std())
        .fillna(0.0)
    )

    return df


def load_and_prepare():
    df = pd.read_csv(DATA_PATH)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"Loaded {len(df):,} rows | {df['arrival_date'].min().date()} → {df['arrival_date'].max().date()}")

    # Add new features
    df = add_engineered_features(df)

    # Encode categoricals (same as 03_train_model.py)
    le_commodity = LabelEncoder()
    le_market    = LabelEncoder()
    df["commodity_encoded"] = le_commodity.fit_transform(df["commodity"])
    df["market_encoded"]    = le_market.fit_transform(df["market"])
    joblib.dump({"commodity": le_commodity, "market": le_market}, MODELS_DIR / "encoders.pkl")

    available = [f for f in FEATURE_COLS if f in df.columns]
    missing   = [f for f in FEATURE_COLS if f not in df.columns]
    if missing:
        print(f"  ⚠  Missing columns (will be skipped): {missing}")

    X = df[available].copy()
    y = df[TARGET_COL].copy()
    # Retain commodity label for per-crop breakdown
    commodity_label = df["commodity"].copy()

    valid = y.notna()
    return X[valid], y[valid], df["arrival_date"][valid], commodity_label[valid], available


def fit_log_target(model, X_train, y_train):
    """Fit on log1p(price) — handles right-skew in agricultural price distributions."""
    model.fit(X_train, np.log1p(y_train))
    return model


def predict_log_target(model, X):
    """Inverse-transform back to Rs/quintal scale."""
    return np.expm1(model.predict(X))


def per_crop_mape(y_true, y_pred, commodity_labels):
    print(f"\n{'Crop':<18} {'MAPE':>8} {'MAE':>10} {'R²':>8} {'n':>6}")
    print("-" * 54)
    results = []
    df_eval = pd.DataFrame({"y": y_true.values, "pred": y_pred, "crop": commodity_labels.values})
    for crop, g in df_eval.groupby("crop"):
        mape = mean_absolute_percentage_error(g["y"], g["pred"]) * 100
        mae  = mean_absolute_error(g["y"], g["pred"])
        r2   = r2_score(g["y"], g["pred"]) if len(g) > 1 else float("nan")
        results.append((crop, mape, mae, r2, len(g)))
        print(f"{crop:<18} {mape:>7.2f}% {mae:>10.2f} {r2:>8.4f} {len(g):>6}")

    pooled = mean_absolute_percentage_error(df_eval["y"], df_eval["pred"]) * 100
    print("-" * 54)
    print(f"{'POOLED':<18} {pooled:>7.2f}%")

    mapes  = [r[1] for r in results]
    spread = max(mapes) - min(mapes)
    print(f"\nSpread across crops: {spread:.2f} pp")
    if spread > 5.0:
        worst = max(results, key=lambda r: r[1])
        best  = min(results, key=lambda r: r[1])
        print(
            f"Meaningful variance: worst={worst[0]} ({worst[1]:.2f}%), "
            f"best={best[0]} ({best[1]:.2f}%). "
            f"Consider reporting per-crop MAPE in the paper."
        )
    return pooled


def main():
    print("=" * 55)
    print("KisanMitra — Feature Engineering Additions")
    print("=" * 55)

    X, y, dates, commodity_labels, features = load_and_prepare()
    print(f"Training with {len(features)} features: {features}\n")

    cutoff  = int(len(X) * 0.80)
    X_train = X.iloc[:cutoff].copy()
    X_test  = X.iloc[cutoff:].copy()
    y_train = y.iloc[:cutoff]
    y_test  = y.iloc[cutoff:]
    commodity_test  = commodity_labels.iloc[cutoff:]
    dates_test      = dates.iloc[cutoff:]

    # Impute missing values using train split medians only (no look-ahead leak)
    for col in X_train.columns:
        train_median = X_train[col].median()
        X_train[col] = X_train[col].fillna(train_median)
        X_test[col]  = X_test[col].fillna(train_median)

    # --- Train with log-transformed target ---

    print("Training with log-transformed target...")
    model = RandomForestRegressor(
        n_estimators=200, max_depth=12, min_samples_split=10,
        min_samples_leaf=5, random_state=42, n_jobs=-1, oob_score=True,
    )
    fit_log_target(model, X_train, y_train)
    print(f"  OOB Score: {model.oob_score_:.4f}")

    y_pred_test  = predict_log_target(model, X_test)
    y_pred_train = predict_log_target(model, X_train)

    test_mape  = mean_absolute_percentage_error(y_test, y_pred_test) * 100
    train_mape = mean_absolute_percentage_error(y_train, y_pred_train) * 100
    test_r2    = r2_score(y_test, y_pred_test)
    test_mae   = mean_absolute_error(y_test, y_pred_test)

    print(f"\n  Train MAPE : {train_mape:.2f}%")
    print(f"  Test  MAPE : {test_mape:.2f}%  (previous: check model_metadata.json)")
    print(f"  Test  R²   : {test_r2:.4f}")
    print(f"  Test  MAE  : ₹{test_mae:.0f}/quintal")

    # --- Per-crop breakdown ---
    print("\nPer-crop MAPE breakdown:")
    per_crop_mape(y_test, y_pred_test, commodity_test)

    # --- Save if improved ---
    meta_path = MODELS_DIR / "model_metadata.json"
    prev_mape = None
    if meta_path.exists():
        with open(meta_path) as f:
            prev_mape = json.load(f).get("test_mape")

    if prev_mape is None or test_mape < prev_mape:
        model_path = MODELS_DIR / "price_model.pkl"
        
        # Backup existing model if both model and metadata exist
        if model_path.exists() and meta_path.exists():
            try:
                with open(meta_path) as f:
                    old_meta = json.load(f)
                    old_ver  = old_meta.get("version", "unknown")
                backup_path = MODELS_DIR / f"price_model_v{old_ver}.pkl"
                import shutil
                shutil.copyfile(model_path, backup_path)
                print(f"  Backup created: {backup_path}")
            except Exception as e:
                print(f"  Backup warning: {e}")

        joblib.dump(model, model_path)
        meta = {
            "version":   "3.0.0",
            "commodity": "All",
            "markets":   "Pan-Karnataka",
            "horizon":   "60 days",
            "algorithm": "RandomForestRegressor + log1p target",
            "features":  features,
            "test_mape": round(test_mape, 2),
            "test_r2":   round(test_r2, 4),
            "notes":     "Added price_momentum_7d, price_volatility_30d; log1p target transform.",
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        delta = f"({prev_mape:.2f}% → {test_mape:.2f}%)" if prev_mape else ""
        print(f"\n✅ Model improved {delta} — saved to data/models/price_model.pkl")
    else:
        print(f"\n⚠  New model ({test_mape:.2f}%) did not beat previous ({prev_mape:.2f}%) — original kept.")



if __name__ == "__main__":
    main()
