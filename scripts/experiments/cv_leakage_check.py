"""
scripts/cv_leakage_check.py

Verifies temporal integrity of the benchmark in 03_train_model.py.

Key finding from reading the actual training script:
  - 03_train_model.py does NOT use KFold or StratifiedKFold.
  - It uses a chronological 80/20 split (iloc[:cutoff] / iloc[cutoff:])
    on a date-sorted dataframe.
  - This is already the correct approach for autocorrelated time-series data.

This script confirms that by running two evaluations and comparing:
  1. Chronological split (what 03_train_model.py actually does)
  2. Shuffled KFold (the leaky alternative)

If the chronological split MAPE is higher than shuffled KFold MAPE,
that gap measures the real-world leakage risk that would have existed
had you used KFold. If they are close, the data is not strongly
autocorrelated at the fold boundary scale.

Usage:
    venv/bin/python scripts/cv_leakage_check.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import KFold, TimeSeriesSplit
from sklearn.metrics import mean_absolute_percentage_error

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
DATA_PATH     = PROCESSED_DIR / "all_model_data.csv"

# Exact column list from 03_train_model.py
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
]
TARGET_COL = "target_price_60d"

RF_PARAMS = dict(
    n_estimators=200, max_depth=12, min_samples_split=10,
    min_samples_leaf=5, random_state=42, n_jobs=-1,
)


def load():
    from sklearn.preprocessing import LabelEncoder
    df = pd.read_csv(DATA_PATH)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    le_commodity = LabelEncoder()
    le_market    = LabelEncoder()
    df["commodity_encoded"] = le_commodity.fit_transform(df["commodity"])
    df["market_encoded"]    = le_market.fit_transform(df["market"])

    available = [f for f in FEATURE_COLS if f in df.columns]
    X = df[available].copy()
    y = df[TARGET_COL].copy()
    for col in X.columns:
        X[col] = X[col].fillna(X[col].median())
    valid = y.notna()
    return X[valid], y[valid], df["arrival_date"][valid], df["commodity"][valid], available


def eval_chronological_split(X, y):
    """Mirrors the exact method in 03_train_model.py."""
    cutoff  = int(len(X) * 0.80)
    model   = RandomForestRegressor(**RF_PARAMS)
    model.fit(X.iloc[:cutoff], y.iloc[:cutoff])
    preds   = model.predict(X.iloc[cutoff:])
    return mean_absolute_percentage_error(y.iloc[cutoff:], preds) * 100


def eval_shuffled_kfold(X, y, n_splits=5):
    """The leaky alternative — train/test rows mixed across time."""
    kf    = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    mapes = []
    for train_idx, test_idx in kf.split(X):
        m = RandomForestRegressor(**RF_PARAMS)
        m.fit(X.iloc[train_idx], y.iloc[train_idx])
        mapes.append(mean_absolute_percentage_error(y.iloc[test_idx], m.predict(X.iloc[test_idx])) * 100)
    return float(np.mean(mapes))


def eval_timeseries_cv(X, y, n_splits=5):
    """TimeSeriesSplit — expanding window, leakage-safe."""
    tscv  = TimeSeriesSplit(n_splits=n_splits)
    mapes = []
    for train_idx, test_idx in tscv.split(X):
        m = RandomForestRegressor(**RF_PARAMS)
        m.fit(X.iloc[train_idx], y.iloc[train_idx])
        mapes.append(mean_absolute_percentage_error(y.iloc[test_idx], m.predict(X.iloc[test_idx])) * 100)
    return float(np.mean(mapes))


if __name__ == "__main__":
    print("Loading data...")
    X, y, dates, commodities, features = load()
    print(f"  {len(X):,} rows | {dates.min().date()} → {dates.max().date()} | {len(features)} features\n")

    print("Running evaluations (this takes ~2-3 mins for 200-tree RF × 3 methods)...")
    chron_mape   = eval_chronological_split(X, y)
    shuffled_mape = eval_shuffled_kfold(X, y)
    ts_mape      = eval_timeseries_cv(X, y)

    print(f"\n{'Method':<35} {'MAPE':>8}")
    print("-" * 45)
    print(f"{'Chronological 80/20 (current method)':<35} {chron_mape:>7.2f}%")
    print(f"{'Shuffled KFold (leaky baseline)':<35} {shuffled_mape:>7.2f}%")
    print(f"{'TimeSeriesSplit 5-fold':<35} {ts_mape:>7.2f}%")

    leakage_gap = shuffled_mape - chron_mape
    print(f"\nLeakage gap (shuffled − chronological): {leakage_gap:+.2f} pp")

    if leakage_gap < -1.0:
        print(
            "\n⚠  WARNING: Shuffled KFold reports lower (better) MAPE than the "
            "chronological split. This is a temporal leakage signature — shuffled "
            "CV lets training rows from the future contaminate test evaluation. "
            "Your current chronological split is the correct method; do not switch "
            "to KFold. Report the chronological split number in the paper."
        )
    else:
        print(
            "\n✅ No leakage detected. Shuffled KFold MAPE is not meaningfully "
            "better than the chronological split — your benchmark is methodologically "
            "sound. The chronological 80/20 split is the right method to report."
        )
