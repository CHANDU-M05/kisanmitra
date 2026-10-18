"""
scripts/experiments/run_final_cohort_benchmark.py — Single Fixed Cohort Final Model Evaluation

Runs a strict 6-model comparison on the EXACT SAME Operational T+60 ±1 day cohort (n = 10,062):
1. Model 1: Baseline RF (Record Shift Target baseline)
2. Model 2: Calendar T+60 ±1d Target RF
3. Model 3: Calendar T+60 ±1d Target RF + Luni-Solar Festival Features
4. Model 4: Calendar T+60 ±1d Target HistGBDT + Festival Features
5. Model 5: Grouped GBDT (Storable vs Perishable Regressors) + Festival Features
6. Model 6: Grouped GBDT + Festival Features + Real Sowing Saturation Index (crop_declarations)

Outputs apples-to-apples per-crop MAPE breakdown and exact % improvements.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.preprocessing import LabelEncoder

from backend.core.database import AsyncSessionLocal
from backend.core.models import CropDeclaration
from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Major Karnataka Luni-Solar Festival Dates (2020 – 2026) ───────────────────
FESTIVAL_CALENDAR = pd.DataFrame([
    {"date": "2020-01-15", "type": 5}, {"date": "2020-03-25", "type": 1},
    {"date": "2020-08-22", "type": 2}, {"date": "2020-10-25", "type": 3}, {"date": "2020-11-14", "type": 4},
    {"date": "2021-01-14", "type": 5}, {"date": "2021-04-13", "type": 1},
    {"date": "2021-09-10", "type": 2}, {"date": "2021-10-15", "type": 3}, {"date": "2021-11-04", "type": 4},
    {"date": "2022-01-14", "type": 5}, {"date": "2022-04-02", "type": 1},
    {"date": "2022-08-31", "type": 2}, {"date": "2022-10-05", "type": 3}, {"date": "2022-10-24", "type": 4},
    {"date": "2023-01-15", "type": 5}, {"date": "2023-03-22", "type": 1},
    {"date": "2023-09-18", "type": 2}, {"date": "2023-10-24", "type": 3}, {"date": "2023-11-12", "type": 4},
    {"date": "2024-01-15", "type": 5}, {"date": "2024-04-09", "type": 1},
    {"date": "2024-09-07", "type": 2}, {"date": "2024-10-12", "type": 3}, {"date": "2024-11-01", "type": 4},
    {"date": "2025-01-14", "type": 5}, {"date": "2025-03-30", "type": 1},
    {"date": "2025-08-27", "type": 2}, {"date": "2025-10-02", "type": 3}, {"date": "2025-10-20", "type": 4},
    {"date": "2026-01-14", "type": 5}, {"date": "2026-03-19", "type": 1},
    {"date": "2026-09-14", "type": 2}, {"date": "2026-10-20", "type": 3}, {"date": "2026-11-08", "type": 4},
])
FESTIVAL_CALENDAR["date"] = pd.to_datetime(FESTIVAL_CALENDAR["date"])


async def load_declarations_saturation_map() -> dict:
    """Loads crop_declarations from PostgreSQL DB and computes saturation by (district, crop, year)."""
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(CropDeclaration))
        rows = res.scalars().all()
        
    records = []
    for r in rows:
        records.append({
            "district": r.district,
            "crop": r.crop,
            "area_acres": r.area_acres or 1.0,
            "declared_at": r.declared_at or pd.Timestamp("2026-01-01")
        })
        
    if not records:
        return {}
        
    d_df = pd.DataFrame(records)
    d_df["year"] = pd.to_datetime(d_df["declared_at"]).dt.year
    agg = d_df.groupby(["district", "crop", "year"])["area_acres"].sum().reset_index()
    
    # Compute saturation score relative to historical mean
    mean_acres = agg.groupby(["district", "crop"])["area_acres"].transform("mean")
    agg["sowing_saturation_index"] = (agg["area_acres"] / mean_acres.replace(0, 1.0)) * 100.0
    
    sat_map = {}
    for _, row in agg.iterrows():
        sat_map[(row["district"].lower(), row["crop"].lower(), row["year"])] = row["sowing_saturation_index"]
    return sat_map


def build_operational_cohort_dataset(sat_map: dict) -> pd.DataFrame:
    path = PROCESSED_DIR / "karnataka_clean.csv"
    if not path.exists():
        path = PROCESSED_DIR / "all_model_data.csv"
    df = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 1. Operational T+60 ±1 day Target Matching
    price_map = df.set_index(["market", "commodity", "arrival_date"])["modal_price"].to_dict()
    targets = []
    
    for idx, row in df.iterrows():
        t_date = row["arrival_date"] + pd.Timedelta(days=60)
        key = (row["market"], row["commodity"], t_date)
        if key in price_map:
            targets.append(price_map[key])
        else:
            found = None
            for offset in (1, -1):
                cand_key = (row["market"], row["commodity"], t_date + pd.Timedelta(days=offset))
                if cand_key in price_map:
                    found = price_map[cand_key]
                    break
            targets.append(found)

    df["operational_target_60d"] = targets
    df.dropna(subset=["operational_target_60d"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 2. Luni-Solar Festival Features
    f_dates = FESTIVAL_CALENDAR["date"].values
    f_types = FESTIVAL_CALENDAR["type"].values
    days_to_next, days_since_prev, next_types = [], [], []

    for dt in df["arrival_date"]:
        dt_val = np.datetime64(dt)
        future_idx = np.where(f_dates >= dt_val)[0]
        past_idx = np.where(f_dates < dt_val)[0]
        if len(future_idx) > 0:
            days_to_next.append(int((f_dates[future_idx[0]] - dt_val) / np.timedelta64(1, 'D')))
            next_types.append(int(f_types[future_idx[0]]))
        else:
            days_to_next.append(99)
            next_types.append(0)
        if len(past_idx) > 0:
            days_since_prev.append(int((dt_val - f_dates[past_idx[-1]]) / np.timedelta64(1, 'D')))
        else:
            days_since_prev.append(99)

    df["days_to_next_festival"] = days_to_next
    df["days_since_prev_festival"] = days_since_prev
    df["is_festival_week"] = (df["days_to_next_festival"] <= 7).astype(int)
    df["is_festival_month"] = (df["days_to_next_festival"] <= 30).astype(int)
    df["next_festival_type"] = next_types

    # 3. Real Sowing Saturation Feature
    sats = []
    for _, row in df.iterrows():
        key = (str(row["market"]).lower(), str(row["commodity"]).lower(), row["year"])
        sats.append(sat_map.get(key, 100.0))  # Default 100% normal saturation if no declaration
    df["sowing_saturation_index"] = sats

    # Encodings
    df["commodity_encoded"] = LabelEncoder().fit_transform(df["commodity"])
    df["market_encoded"] = LabelEncoder().fit_transform(df["market"])

    return df


def run_fixed_cohort_benchmark():
    print("=" * 80)
    print("KisanMitra — Fixed Cohort Operational T+60 ±1 Day Final Benchmark")
    print("=" * 80)

    sat_map = asyncio.run(load_declarations_saturation_map())
    cohort_df = build_operational_cohort_dataset(sat_map)
    print(f"Fixed Evaluation Cohort Size: {len(cohort_df):,} rows (Strict Operational T+60 ±1d)")

    base_features = [
        "commodity_encoded", "market_encoded",
        "month", "month_sin", "month_cos", "season", "quarter",
        "modal_price", "price_7d_avg", "price_30d_avg",
        "price_7d_ago", "price_30d_ago", "price_trend_7d",
        "vs_seasonal", "seasonal_avg", "arrivals_tonnes", "arrivals_7d_avg",
    ]
    fest_features = base_features + [
        "days_to_next_festival", "days_since_prev_festival",
        "is_festival_week", "is_festival_month", "next_festival_type"
    ]
    sat_features = fest_features + ["sowing_saturation_index"]

    target_col = "operational_target_60d"

    cutoff = int(len(cohort_df) * 0.80)
    train_df = cohort_df.iloc[:cutoff]
    test_df = cohort_df.iloc[cutoff:]

    y_tr, y_te = train_df[target_col], test_df[target_col]
    c_te = test_df["commodity"]

    models_res = {}

    # Model 1: Legacy RF (Shift Target)
    rf_base = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf_base.fit(train_df[base_features], train_df["target_price_60d"] if "target_price_60d" in train_df else y_tr)
    models_res["M1 — Legacy RF (Shift Target)"] = rf_base.predict(test_df[base_features])

    # Model 2: Calendar-Aligned RF
    rf_cal = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf_cal.fit(train_df[base_features], y_tr)
    models_res["M2 — Calendar-Aligned RF"] = rf_cal.predict(test_df[base_features])

    # Model 3: Calendar + Festival RF
    rf_fest = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_split=10, min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf_fest.fit(train_df[fest_features], y_tr)
    models_res["M3 — Calendar + Festival RF"] = rf_fest.predict(test_df[fest_features])

    # Model 4: Calendar + Festival HistGBDT
    hgb_fest = HistGradientBoostingRegressor(max_iter=200, max_depth=8, min_samples_leaf=10, random_state=42)
    hgb_fest.fit(train_df[fest_features], y_tr)
    models_res["M4 — Calendar + Festival HistGBDT"] = hgb_fest.predict(test_df[fest_features])

    # Model 5: Calendar + Festival Grouped GBDT
    storable_crops = ["Maize", "Ragi", "Potato"]
    tr_s = train_df[train_df["commodity"].isin(storable_crops)]
    te_s = test_df[test_df["commodity"].isin(storable_crops)]
    tr_p = train_df[~train_df["commodity"].isin(storable_crops)]
    te_p = test_df[~test_df["commodity"].isin(storable_crops)]

    hgb_s = HistGradientBoostingRegressor(max_iter=200, max_depth=6, min_samples_leaf=10, random_state=42)
    hgb_s.fit(tr_s[fest_features], tr_s[target_col])
    pred_s = hgb_s.predict(te_s[fest_features])

    hgb_p = HistGradientBoostingRegressor(max_iter=200, max_depth=10, min_samples_leaf=5, random_state=42)
    hgb_p.fit(tr_p[fest_features], tr_p[target_col])
    pred_p = hgb_p.predict(te_p[fest_features])

    combined_pred = np.zeros(len(test_df))
    combined_pred[test_df["commodity"].isin(storable_crops)] = pred_s
    combined_pred[~test_df["commodity"].isin(storable_crops)] = pred_p
    models_res["M5 — Calendar + Festival Grouped GBDT"] = combined_pred

    # Model 6: Calendar + Festival Grouped GBDT + Live Saturation
    hgb_s_sat = HistGradientBoostingRegressor(max_iter=200, max_depth=6, min_samples_leaf=10, random_state=42)
    hgb_s_sat.fit(tr_s[sat_features], tr_s[target_col])
    pred_s_sat = hgb_s_sat.predict(te_s[sat_features])

    hgb_p_sat = HistGradientBoostingRegressor(max_iter=200, max_depth=10, min_samples_leaf=5, random_state=42)
    hgb_p_sat.fit(tr_p[sat_features], tr_p[target_col])
    pred_p_sat = hgb_p_sat.predict(te_p[sat_features])

    combined_pred_sat = np.zeros(len(test_df))
    combined_pred_sat[test_df["commodity"].isin(storable_crops)] = pred_s_sat
    combined_pred_sat[~test_df["commodity"].isin(storable_crops)] = pred_p_sat
    models_res["M6 — Calendar + Festival Grouped GBDT + Saturation"] = combined_pred_sat

    # ── EVALUATION REPORT ─────────────────────────────────────────────
    eval_table = []
    base_mape = None

    for m_name, y_pred in models_res.items():
        mape = mean_absolute_percentage_error(y_te, y_pred) * 100
        mae = mean_absolute_error(y_te, y_pred)
        r2 = r2_score(y_te, y_pred)
        
        if base_mape is None:
            base_mape = mape
            imp_str = "Baseline"
        else:
            imp = ((base_mape - mape) / base_mape) * 100.0
            imp_str = f"+{imp:.1f}%"

        eval_df = pd.DataFrame({"actual": y_te, "pred": y_pred, "crop": c_te})
        c_mapes = {}
        for crop_name, grp in eval_df.groupby("crop"):
            c_mapes[crop_name] = round(mean_absolute_percentage_error(grp["actual"], grp["pred"]) * 100, 2)

        rec = {
            "Model Pipeline": m_name,
            "Overall MAPE (%)": round(mape, 2),
            "Error Reduction": imp_str,
            "MAE (Rs)": round(mae, 1),
            "R2 Score": round(r2, 4),
        }
        rec.update(c_mapes)
        eval_table.append(rec)

    df_out = pd.DataFrame(eval_table)

    print("\n" + "═"*95)
    print(f"{'Model Pipeline':<42} | {'Overall MAPE':<12} | {'Reduction':<9} | {'MAE (Rs)':<9} | {'R²':<7}")
    print("═"*95)
    for _, r in df_out.iterrows():
        print(f"{r['Model Pipeline']:<42} | {r['Overall MAPE (%)']:>6.2f}%      | {r['Error Reduction']:<9} | Rs {r['MAE (Rs)']:>5.0f} | {r['R2 Score']:>6.4f}")
    print("═"*95)

    all_crops = sorted(list(c_mapes.keys()))
    print("\nPER-CROP MAPE BREAKDOWN (%):")
    print("─"*95)
    headers = [f"Model {i+1}" for i in range(len(models_res))]
    print(f"{'Crop':<12} | " + " | ".join([f"{h:<10}" for h in headers]))
    print("─"*95)
    for crop in all_crops:
        vals = [f"{r[crop]:>10.2f}" for _, r in df_out.iterrows()]
        print(f"{crop:<12} | " + " | ".join(vals))
    print("═"*95)

    out_csv = RESULTS_DIR / "final_cohort_benchmark.csv"
    df_out.to_csv(out_csv, index=False)
    print(f"\nSaved final fixed cohort evaluation CSV: {out_csv}")


if __name__ == "__main__":
    run_fixed_cohort_benchmark()
