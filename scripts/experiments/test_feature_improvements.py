"""
scripts/experiments/test_feature_improvements.py — Controlled Model Improvement Benchmark

Tests step-by-step model enhancements on the EXACT SAME chronological 80/20 temporal split:
1. Target Audit: shift(-60) vs Exact Calendar T+60 Target (arrival_date + 60 days)
2. Robust Luni-Solar Festival Features (days_to_next_festival, days_since_prev, festival_type, etc.)
3. Algorithm Benchmarks: Random Forest vs HistGradientBoosting (GBDT)
4. Model Architecture: Single Pooled Model vs Grouped Models (Storable vs Perishable)

Outputs per-crop MAPE breakdown and exact % improvement relative to baseline.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.preprocessing import LabelEncoder

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Major Karnataka Luni-Solar Festivals (2020 – 2026) ────────────────────────
FESTIVAL_CALENDAR = pd.DataFrame([
    # 2020
    {"date": "2020-01-15", "festival": "Sankranti", "type": 5},
    {"date": "2020-03-25", "festival": "Ugadi",     "type": 1},
    {"date": "2020-08-22", "festival": "Ganesha",   "type": 2},
    {"date": "2020-10-25", "festival": "Dasara",    "type": 3},
    {"date": "2020-11-14", "festival": "Diwali",    "type": 4},
    # 2021
    {"date": "2021-01-14", "festival": "Sankranti", "type": 5},
    {"date": "2021-04-13", "festival": "Ugadi",     "type": 1},
    {"date": "2021-09-10", "festival": "Ganesha",   "type": 2},
    {"date": "2021-10-15", "festival": "Dasara",    "type": 3},
    {"date": "2021-11-04", "festival": "Diwali",    "type": 4},
    # 2022
    {"date": "2022-01-14", "festival": "Sankranti", "type": 5},
    {"date": "2022-04-02", "festival": "Ugadi",     "type": 1},
    {"date": "2022-08-31", "festival": "Ganesha",   "type": 2},
    {"date": "2022-10-05", "festival": "Dasara",    "type": 3},
    {"date": "2022-10-24", "festival": "Diwali",    "type": 4},
    # 2023
    {"date": "2023-01-15", "festival": "Sankranti", "type": 5},
    {"date": "2023-03-22", "festival": "Ugadi",     "type": 1},
    {"date": "2023-09-18", "festival": "Ganesha",   "type": 2},
    {"date": "2023-10-24", "festival": "Dasara",    "type": 3},
    {"date": "2023-11-12", "festival": "Diwali",    "type": 4},
    # 2024
    {"date": "2024-01-15", "festival": "Sankranti", "type": 5},
    {"date": "2024-04-09", "festival": "Ugadi",     "type": 1},
    {"date": "2024-09-07", "festival": "Ganesha",   "type": 2},
    {"date": "2024-10-12", "festival": "Dasara",    "type": 3},
    {"date": "2024-11-01", "festival": "Diwali",    "type": 4},
    # 2025
    {"date": "2025-01-14", "festival": "Sankranti", "type": 5},
    {"date": "2025-03-30", "festival": "Ugadi",     "type": 1},
    {"date": "2025-08-27", "festival": "Ganesha",   "type": 2},
    {"date": "2025-10-02", "festival": "Dasara",    "type": 3},
    {"date": "2025-10-20", "festival": "Diwali",    "type": 4},
    # 2026
    {"date": "2026-01-14", "festival": "Sankranti", "type": 5},
    {"date": "2026-03-19", "festival": "Ugadi",     "type": 1},
    {"date": "2026-09-14", "festival": "Ganesha",   "type": 2},
    {"date": "2026-10-20", "festival": "Dasara",    "type": 3},
    {"date": "2026-11-08", "festival": "Diwali",    "type": 4},
])
FESTIVAL_CALENDAR["date"] = pd.to_datetime(FESTIVAL_CALENDAR["date"])


def load_dataset() -> pd.DataFrame:
    path = PROCESSED_DIR / "karnataka_clean.csv"
    if not path.exists():
        path = PROCESSED_DIR / "all_model_data.csv"
    df = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values(["market", "commodity", "arrival_date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def add_exact_calendar_target(df: pd.DataFrame) -> pd.DataFrame:
    """
    Step 1 Target Audit: Replaces shift(-60) with exact calendar T+60 target.
    Matches the price observed 60 calendar days into the future (nearest within ±5 days).
    """
    df = df.copy()
    targets = []
    
    # Map (market, commodity, date) -> modal_price for fast lookup
    price_map = df.set_index(["market", "commodity", "arrival_date"])["modal_price"].to_dict()
    
    for idx, row in df.iterrows():
        t_date = row["arrival_date"] + pd.Timedelta(days=60)
        key = (row["market"], row["commodity"], t_date)
        
        if key in price_map:
            targets.append(price_map[key])
        else:
            # Nearest match within ±5 days
            found = None
            for offset in range(1, 6):
                for sign in (1, -1):
                    cand_date = t_date + pd.Timedelta(days=sign * offset)
                    cand_key = (row["market"], row["commodity"], cand_date)
                    if cand_key in price_map:
                        found = price_map[cand_key]
                        break
                if found is not None:
                    break
            targets.append(found)
            
    df["calendar_target_60d"] = targets
    return df


def add_robust_festival_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Step 2: Adds days_to_next_festival, days_since_prev_festival,
    is_festival_week, is_festival_month, and next_festival_type.
    """
    df = df.copy()
    f_dates = FESTIVAL_CALENDAR["date"].values
    f_types = FESTIVAL_CALENDAR["type"].values
    
    days_to_next = []
    days_since_prev = []
    next_types = []
    
    for dt in df["arrival_date"]:
        dt_val = np.datetime64(dt)
        future_idx = np.where(f_dates >= dt_val)[0]
        past_idx = np.where(f_dates < dt_val)[0]
        
        if len(future_idx) > 0:
            next_i = future_idx[0]
            days_to_next.append(int((f_dates[next_i] - dt_val) / np.timedelta64(1, 'D')))
            next_types.append(int(f_types[next_i]))
        else:
            days_to_next.append(99)
            next_types.append(0)
            
        if len(past_idx) > 0:
            prev_i = past_idx[-1]
            days_since_prev.append(int((dt_val - f_dates[prev_i]) / np.timedelta64(1, 'D')))
        else:
            days_since_prev.append(99)
            
    df["days_to_next_festival"] = days_to_next
    df["days_since_prev_festival"] = days_since_prev
    df["is_festival_week"] = (df["days_to_next_festival"] <= 7).astype(int)
    df["is_festival_month"] = (df["days_to_next_festival"] <= 30).astype(int)
    df["next_festival_type"] = next_types
    
    return df


def prepare_experiment_data(df: pd.DataFrame, feature_cols: list[str], target_col: str):
    df_clean = df.copy()
    
    # Encoders
    c_enc = LabelEncoder()
    m_enc = LabelEncoder()
    df_clean["commodity_encoded"] = c_enc.fit_transform(df_clean["commodity"])
    df_clean["market_encoded"] = m_enc.fit_transform(df_clean["market"])
    
    valid = df_clean[target_col].notna()
    df_clean = df_clean[valid].sort_values("arrival_date").reset_index(drop=True)
    
    X = df_clean[feature_cols]
    y = df_clean[target_col]
    crops = df_clean["commodity"]
    
    # Chronological 80/20 split
    cutoff = int(len(X) * 0.80)
    X_train, X_test = X.iloc[:cutoff], X.iloc[cutoff:]
    y_train, y_test = y.iloc[:cutoff], y.iloc[cutoff:]
    crops_test = crops.iloc[cutoff:]
    
    return X_train, X_test, y_train, y_test, crops_test


def evaluate_predictions(y_test, y_pred, crops_test):
    overall_mape = mean_absolute_percentage_error(y_test, y_pred) * 100
    overall_mae = mean_absolute_error(y_test, y_pred)
    overall_r2 = r2_score(y_test, y_pred)
    
    eval_df = pd.DataFrame({"actual": y_test, "pred": y_pred, "crop": crops_test})
    crop_mapes = {}
    for crop_name, group in eval_df.groupby("crop"):
        c_mape = mean_absolute_percentage_error(group["actual"], group["pred"]) * 100
        crop_mapes[crop_name] = round(c_mape, 2)
        
    return {
        "overall_mape": round(overall_mape, 2),
        "overall_mae": round(overall_mae, 1),
        "overall_r2": round(overall_r2, 4),
        "crop_mapes": crop_mapes,
    }


def run_benchmark_experiments():
    print("=" * 65)
    print("KisanMitra — Controlled Feature & Model Benchmark Experiments")
    print("=" * 65)

    raw_df = load_dataset()
    print(f"Loaded dataset: {len(raw_df):,} rows")

    # Step 1: Add Calendar T+60 Target & Festival Features
    df_aug = add_exact_calendar_target(raw_df)
    df_aug = add_robust_festival_features(df_aug)

    base_features = [
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

    fest_features = base_features + [
        "days_to_next_festival", "days_since_prev_festival",
        "is_festival_week", "is_festival_month", "next_festival_type"
    ]

    experiments = {}

    # ── Exp A: Baseline RF (Original Shift Target + Base Features) ──
    X_tr, X_te, y_tr, y_te, c_te = prepare_experiment_data(df_aug, base_features, "target_price_60d")
    rf_base = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf_base.fit(X_tr, y_tr)
    experiments["Exp A: Baseline RF (Shift Target)"] = evaluate_predictions(y_te, rf_base.predict(X_te), c_te)

    # ── Exp B: RF + Exact Calendar T+60 Target ─────────────────────────
    X_tr, X_te, y_tr, y_te, c_te = prepare_experiment_data(df_aug, base_features, "calendar_target_60d")
    rf_cal = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf_cal.fit(X_tr, y_tr)
    experiments["Exp B: RF + Exact Calendar T+60"] = evaluate_predictions(y_te, rf_cal.predict(X_te), c_te)

    # ── Exp C: RF + Calendar T+60 + Festival Features ────────────────
    X_tr, X_te, y_tr, y_te, c_te = prepare_experiment_data(df_aug, fest_features, "calendar_target_60d")
    rf_fest = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf_fest.fit(X_tr, y_tr)
    experiments["Exp C: RF + Calendar T+60 + Festivals"] = evaluate_predictions(y_te, rf_fest.predict(X_te), c_te)

    # ── Exp D: HistGradientBoosting (GBDT) + Calendar T+60 + Festivals ─
    X_tr, X_te, y_tr, y_te, c_te = prepare_experiment_data(df_aug, fest_features, "calendar_target_60d")
    hgbd = HistGradientBoostingRegressor(max_iter=200, max_depth=8, min_samples_leaf=10, random_state=42)
    hgbd.fit(X_tr, y_tr)
    experiments["Exp D: HistGBDT + Calendar T+60 + Festivals"] = evaluate_predictions(y_te, hgbd.predict(X_te), c_te)

    # ── Exp E: Grouped Models (Storable vs Perishable Regressors) ─────
    # Train separate models for Storable (Maize, Ragi, Potato) and Perishable (Tomato, Onion, Marigold, Brinjal)
    storable_crops = ["Maize", "Ragi", "Potato"]
    df_storable = df_aug[df_aug["commodity"].isin(storable_crops)]
    df_perishable = df_aug[~df_aug["commodity"].isin(storable_crops)]

    # Storable
    X_tr_s, X_te_s, y_tr_s, y_te_s, c_te_s = prepare_experiment_data(df_storable, fest_features, "calendar_target_60d")
    hgb_s = HistGradientBoostingRegressor(max_iter=200, max_depth=6, min_samples_leaf=10, random_state=42)
    hgb_s.fit(X_tr_s, y_tr_s)
    pred_s = hgb_s.predict(X_te_s)

    # Perishable
    X_tr_p, X_te_p, y_tr_p, y_te_p, c_te_p = prepare_experiment_data(df_perishable, fest_features, "calendar_target_60d")
    hgb_p = HistGradientBoostingRegressor(max_iter=200, max_depth=10, min_samples_leaf=5, random_state=42)
    hgb_p.fit(X_tr_p, y_tr_p)
    pred_p = hgb_p.predict(X_te_p)

    # Combine predictions
    y_combined_actual = pd.concat([y_te_s, y_te_p])
    y_combined_pred = np.concatenate([pred_s, pred_p])
    c_combined = pd.concat([c_te_s, c_te_p])
    experiments["Exp E: Grouped GBDT (Storable vs Perishable)"] = evaluate_predictions(y_combined_actual, y_combined_pred, c_combined)

    # ── PRINT COMPARATIVE EXPERIMENT REPORT ───────────────────────────
    all_crops = sorted(list(experiments["Exp A: Baseline RF (Shift Target)"]["crop_mapes"].keys()))

    print("\n" + "═"*90)
    print(f"{'Experiment Name':<42} | {'Overall MAPE':<12} | {'MAE (Rs)':<9} | {'R²':<7}")
    print("═"*90)

    base_mape = experiments["Exp A: Baseline RF (Shift Target)"]["overall_mape"]

    for exp_name, res in experiments.items():
        imp = ((base_mape - res['overall_mape']) / base_mape) * 100.0
        imp_str = f"({imp:+.1f}%)" if exp_name != "Exp A: Baseline RF (Shift Target)" else ""
        print(f"{exp_name:<42} | {res['overall_mape']:>6.2f}% {imp_str:<5} | Rs {res['overall_mae']:>5.0f} | {res['overall_r2']:>6.4f}")

    print("\n" + "─"*90)
    print("PER-CROP MAPE BREAKDOWN (%):")
    print("─"*90)

    header = f"{'Crop':<12} | " + " | ".join([f"{name[:12]:<12}" for name in experiments.keys()])
    print(header)
    print("─"*len(header))

    for crop in all_crops:
        row_vals = [f"{experiments[exp]['crop_mapes'].get(crop, 0.0):>12.2f}" for exp in experiments.keys()]
        print(f"{crop:<12} | " + " | ".join(row_vals))

    print("═"*90)

    # Save summary CSV
    records = []
    for exp_name, res in experiments.items():
        rec = {
            "Experiment": exp_name,
            "Overall MAPE (%)": res["overall_mape"],
            "MAE (Rs)": res["overall_mae"],
            "R2 Score": res["overall_r2"],
        }
        rec.update(res["crop_mapes"])
        records.append(rec)

    exp_df = pd.DataFrame(records)
    out_csv = RESULTS_DIR / "feature_improvement_experiments.csv"
    exp_df.to_csv(out_csv, index=False)
    print(f"\nSaved experiment results CSV: {out_csv}")


if __name__ == "__main__":
    run_benchmark_experiments()
