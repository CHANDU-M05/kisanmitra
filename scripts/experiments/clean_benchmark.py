"""
scripts/clean_benchmark.py

Clean multi-algorithm comparison using a single chronological 80/20 split.
Replaces the results from 04_model_comparison.py which used a shuffled
stratified split, causing temporal leakage.

All models — including ARIMA — are evaluated on the same protocol:
  - Train: rows 0..80% sorted by arrival_date
  - Test:  rows 80%..100% (genuinely future data the model never saw)

ARIMA is run per crop+market series, then results are pooled.

Usage:
    venv/bin/python scripts/clean_benchmark.py

Output:
    results/clean_benchmark.csv        — full results table
    results/clean_benchmark_chart.png  — MAPE bar chart
    results/arima_per_series.csv       — per crop+market ARIMA detail
"""

import sys
import time
import json
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.svm import SVR
from sklearn.neighbors import KNeighborsRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.tree import DecisionTreeRegressor
from sklearn.metrics import (
    mean_absolute_percentage_error,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE_DIR      = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RAW_DIR       = BASE_DIR / "data" / "raw"
RESULTS_DIR   = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

TARGET_COL   = "target_price_60d"
NUMERIC_COLS = [
    "month", "month_sin", "month_cos",
    "season", "quarter",
    "modal_price",
    "price_7d_avg",  "price_30d_avg",
    "price_7d_ago",  "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "arrivals_tonnes",
    "arrivals_7d_avg",
    # MSP features (non-zero only for Maize and Ragi — MSP-eligible crops;
    # Brinjal, Tomato, Onion, Potato, Marigold are perishables outside the scheme)
    "msp_rs_per_quintal",
    "msp_ratio",
]


# ── Data loading ────────────────────────────────────────────────────────────

def _attach_msp(df: pd.DataFrame) -> pd.DataFrame:
    """
    Join MSP history onto the mandi rows using a backward-fill merge_asof.

    For each row, the MSP assigned is the most recent official announcement
    that is *on or before* arrival_date — i.e., no look-ahead leakage.

    Only Maize and Ragi have official MSPs under India's MSP scheme.
    All other crops (Brinjal, Tomato, Onion, Potato, Marigold) are
    perishable vegetables/flowers outside the scheme; their rows receive
    msp_rs_per_quintal = 0 and msp_ratio = 0, signalling "not applicable"
    to tree models.

    Source: CCEA cabinet announcements 2020-21 → 2024-25, via pib.gov.in.

    NOTE: this implementation preserves original row order by merging on a
    per-crop basis and writing results back by index, avoiding a groupby→concat
    that would permute within-date ties and shift the train/test boundary.
    """
    msp_path = RAW_DIR / "msp_history.csv"
    if not msp_path.exists():
        print("  [MSP] msp_history.csv not found — MSP features will be 0.")
        df["msp_rs_per_quintal"] = 0.0
        df["msp_ratio"]          = 0.0
        return df

    msp = pd.read_csv(msp_path, comment="#", parse_dates=["effective_date"])
    msp = msp.sort_values("effective_date").rename(columns={"crop": "commodity"})

    # Normalise casing
    msp["commodity_norm"] = msp["commodity"].str.strip().str.title()
    df["commodity_norm"]  = df["commodity"].str.strip().str.title()
    msp_crops = msp["commodity_norm"].unique().tolist()

    # Initialise to zero — non-MSP crops keep this value
    df["msp_rs_per_quintal"] = 0.0

    # For each MSP-eligible crop, do a sorted merge_asof and write back by index
    for crop_name in msp_crops:
        crop_mask = df["commodity_norm"] == crop_name
        if not crop_mask.any():
            continue
        crop_idx = df.index[crop_mask]
        # Extract subset sorted by date (merge_asof requires sorted left key)
        sub = df.loc[crop_idx, ["arrival_date"]].sort_values("arrival_date").copy()
        msp_crop = msp[msp["commodity_norm"] == crop_name].sort_values("effective_date")
        merged = pd.merge_asof(
            sub,
            msp_crop[["effective_date", "msp_rs_per_quintal"]],
            left_on="arrival_date",
            right_on="effective_date",
            direction="backward",
        )
        merged["msp_rs_per_quintal"] = merged["msp_rs_per_quintal"].fillna(0.0)
        # Write back to original index positions (preserves original row order)
        df.loc[sub.index, "msp_rs_per_quintal"] = merged["msp_rs_per_quintal"].values

    df.drop(columns=["commodity_norm"], inplace=True)

    # msp_ratio: guarded division — 0.0 for non-MSP rows (denominator = 0)
    df["msp_ratio"] = np.where(
        df["msp_rs_per_quintal"] > 0,
        df["modal_price"] / df["msp_rs_per_quintal"],
        0.0,
    )

    n_msp = (df["msp_rs_per_quintal"] > 0).sum()
    print(f"  [MSP] Joined — {n_msp:,} rows have non-zero MSP (Maize + Ragi); "
          f"{len(df) - n_msp:,} rows are non-MSP crops (set to 0).")
    return df



def load_and_split():
    df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # ── Attach MSP feature (leak-safe, backward-fill) ────────────────────────
    df = _attach_msp(df)

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
        else:
            df[col] = 0.0  # ensure column always exists even if attachment failed

    valid = df[TARGET_COL].notna()
    df = df[valid].reset_index(drop=True)

    cutoff = int(len(df) * 0.80)
    train  = df.iloc[:cutoff].copy()
    test   = df.iloc[cutoff:].copy()

    print(f"  Total rows : {len(df):,}")
    print(f"  Train rows : {len(train):,}  ({train['arrival_date'].min().date()} → {train['arrival_date'].max().date()})")
    print(f"  Test  rows : {len(test):,}  ({test['arrival_date'].min().date()} → {test['arrival_date'].max().date()})")
    return train, test


def encode(train, test):
    """Label-encode commodity and market; one-hot encode for linear models."""
    le_comm = LabelEncoder().fit(train["commodity"])
    le_mkt  = LabelEncoder().fit(train["market"])

    for df in (train, test):
        df["commodity_encoded"] = le_comm.transform(
            df["commodity"].where(df["commodity"].isin(le_comm.classes_), le_comm.classes_[0])
        )
        df["market_encoded"] = le_mkt.transform(
            df["market"].where(df["market"].isin(le_mkt.classes_), le_mkt.classes_[0])
        )

    tree_cols   = NUMERIC_COLS + ["commodity_encoded", "market_encoded"]
    X_tr_tree   = train[tree_cols].copy()
    X_te_tree   = test[tree_cols].copy()
    y_train     = train[TARGET_COL]
    y_test      = test[TARGET_COL]

    # One-hot for linear/distance models — fit only on train to avoid leakage
    all_cols = NUMERIC_COLS + ["commodity", "market"]
    X_tr_lin = pd.get_dummies(train[all_cols], columns=["commodity", "market"])
    X_te_lin = pd.get_dummies(test[all_cols],  columns=["commodity", "market"])
    # Align columns — test may have fewer dummies if some labels only appear in train
    X_te_lin = X_te_lin.reindex(columns=X_tr_lin.columns, fill_value=0)

    return X_tr_tree, X_te_tree, X_tr_lin, X_te_lin, y_train, y_test


def metrics(y_true, y_pred):
    mape = mean_absolute_percentage_error(y_true, y_pred) * 100
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mae  = mean_absolute_error(y_true, y_pred)
    r2   = r2_score(y_true, y_pred)
    return mape, rmse, mae, r2


# ── ARIMA per-series ────────────────────────────────────────────────────────

def run_arima(train_df, test_df):
    """
    Fit ARIMA(5,1,0) per crop+market series.
    Uses only modal_price (the raw series) — ARIMA is a univariate method.
    For each series: train on the train split, forecast h steps ahead
    where h = len(test rows for that series), compare to actual target_price_60d.
    Returns pooled MAPE and per-series detail.
    """
    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError:
        return None, None, "statsmodels not installed — run: pip install statsmodels"

    series_results = []
    all_true, all_pred = [], []

    groups = train_df.groupby(["commodity", "market"])

    for (commodity, market), grp_train in groups:
        grp_test = test_df[
            (test_df["commodity"] == commodity) &
            (test_df["market"]    == market)
        ].copy()

        if len(grp_test) == 0:
            continue

        # Need at least 20 observations to fit a meaningful ARIMA
        price_train = grp_train.sort_values("arrival_date")["modal_price"].dropna()
        if len(price_train) < 20:
            continue

        try:
            model = ARIMA(price_train.values, order=(5, 1, 0))
            fit   = model.fit()

            # Forecast one step per test row — rolling re-fit is expensive,
            # so we forecast h steps from end of training series.
            h      = len(grp_test)
            fc     = fit.forecast(steps=h)
            y_true = grp_test.sort_values("arrival_date")[TARGET_COL].values

            # Align lengths
            min_len = min(len(fc), len(y_true))
            fc      = fc[:min_len]
            y_true  = y_true[:min_len]

            valid = ~np.isnan(y_true)
            if valid.sum() < 3:
                continue

            mape_s = mean_absolute_percentage_error(y_true[valid], fc[valid]) * 100
            series_results.append({
                "commodity": commodity,
                "market":    market,
                "n_train":   len(price_train),
                "n_test":    valid.sum(),
                "mape":      round(mape_s, 2),
            })
            all_true.extend(y_true[valid].tolist())
            all_pred.extend(fc[valid].tolist())

        except Exception as e:
            series_results.append({
                "commodity": commodity, "market": market,
                "n_train": len(price_train), "n_test": 0,
                "mape": float("nan"), "error": str(e)[:80],
            })

    if not all_true:
        return None, pd.DataFrame(series_results), "No series produced valid forecasts"

    pooled_mape = mean_absolute_percentage_error(all_true, all_pred) * 100
    return pooled_mape, pd.DataFrame(series_results), None


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("KisanMitra — Clean Chronological Benchmark")
    print("All models | Chronological 80/20 split | No shuffle")
    print("=" * 60)

    print("\nLoading and splitting data...")
    train, test = load_and_split()
    X_tr_tree, X_te_tree, X_tr_lin, X_te_lin, y_train, y_test = encode(train, test)

    # ── ML Models ────────────────────────────────────────────────────────────
    model_configs = [
        ("Random Forest",
         RandomForestRegressor(
             n_estimators=200, max_depth=12, min_samples_split=10,
             min_samples_leaf=5, random_state=42, n_jobs=-1
         ),
         X_tr_tree, X_te_tree),

        ("Gradient Boosting",
         GradientBoostingRegressor(
             n_estimators=200, learning_rate=0.05, max_depth=5, random_state=42
         ),
         X_tr_tree, X_te_tree),

        ("Decision Tree",
         DecisionTreeRegressor(
             max_depth=5, min_samples_split=10, min_samples_leaf=5, random_state=42
         ),
         X_tr_tree, X_te_tree),

        ("SVR",
         Pipeline([("scaler", StandardScaler()),
                   ("model", SVR(kernel="rbf", C=100, epsilon=1, gamma="scale"))]),
         X_tr_lin, X_te_lin),

        ("KNN Regressor",
         Pipeline([("scaler", StandardScaler()),
                   ("model", KNeighborsRegressor(n_neighbors=10, weights="distance"))]),
         X_tr_lin, X_te_lin),

        ("Ridge Regression",
         Pipeline([("scaler", StandardScaler()),
                   ("model", Ridge(alpha=0.1))]),
         X_tr_lin, X_te_lin),

        ("Linear Regression",
         Pipeline([("scaler", StandardScaler()),
                   ("model", LinearRegression())]),
         X_tr_lin, X_te_lin),
    ]

    results = []
    for name, model, X_tr, X_te in model_configs:
        print(f"\n  Training {name}...", end=" ", flush=True)
        t0 = time.time()
        model.fit(X_tr, y_train)
        preds = model.predict(X_te)
        elapsed = time.time() - t0
        mape, rmse, mae, r2 = metrics(y_test, preds)
        print(f"MAPE={mape:.2f}%  R²={r2:.4f}  ({elapsed:.1f}s)")
        results.append({
            "Model":      name,
            "MAPE (%)":   round(mape, 2),
            "RMSE (Rs)":  round(rmse, 2),
            "MAE (Rs)":   round(mae, 2),
            "R² Score":   round(r2, 4),
            "Time (s)":   round(elapsed, 1),
            "Split":      "Chronological 80/20",
        })

    # ── ARIMA ──────────────────────────────────────────────────────────────
    print(f"\n  Running ARIMA(5,1,0) per crop+market series...", end=" ", flush=True)
    t0 = time.time()
    arima_mape, arima_detail, arima_err = run_arima(train, test)
    elapsed = time.time() - t0

    if arima_mape is not None:
        print(f"MAPE={arima_mape:.2f}%  ({elapsed:.1f}s)")
        results.append({
            "Model":     "ARIMA(5,1,0)",
            "MAPE (%)":  round(arima_mape, 2),
            "RMSE (Rs)": None,
            "MAE (Rs)":  None,
            "R² Score":  None,
            "Time (s)":  round(elapsed, 1),
            "Split":     "Chronological 80/20",
        })
        arima_detail.to_csv(RESULTS_DIR / "arima_per_series.csv", index=False)
        print(f"    ARIMA per-series detail → results/arima_per_series.csv")
    else:
        print(f"ARIMA skipped: {arima_err}")

    # ── Results table ───────────────────────────────────────────────────────
    df_results = pd.DataFrame(results).sort_values("MAPE (%)")
    df_results.to_csv(RESULTS_DIR / "clean_benchmark.csv", index=False)

    print("\n" + "=" * 60)
    print("FINAL RESULTS — Chronological 80/20 split")
    print("=" * 60)
    print(df_results[["Model", "MAPE (%)", "RMSE (Rs)", "R² Score", "Time (s)"]].to_string(index=False))

    # ── Per-crop RF breakdown ───────────────────────────────────────────────
    rf_entry = next(c for c in model_configs if c[0] == "Random Forest")
    rf_model = rf_entry[1]
    preds_rf  = rf_model.predict(X_te_tree)
    print("\nRandom Forest — per-crop MAPE breakdown:")
    df_eval = pd.DataFrame({
        "y": y_test.values,
        "pred": preds_rf,
        "crop": test["commodity"].values,
    })
    crop_rows = []
    print(f"  {'Crop':<18} {'MAPE':>8} {'n':>6}")
    print("  " + "-" * 34)
    for crop, g in df_eval.groupby("crop"):
        cm = mean_absolute_percentage_error(g["y"], g["pred"]) * 100
        crop_rows.append({"crop": crop, "mape": round(cm, 2), "n": len(g)})
        print(f"  {crop:<18} {cm:>7.2f}% {len(g):>6}")
    pool_mape = mean_absolute_percentage_error(df_eval["y"], preds_rf) * 100
    print(f"  {'POOLED':<18} {pool_mape:>7.2f}%")
    pd.DataFrame(crop_rows).to_csv(RESULTS_DIR / "rf_per_crop_mape.csv", index=False)

    # ── Chart ───────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#2D6A4F" if "ARIMA" not in r["Model"] else "#E9C46A"
              for r in df_results.to_dict("records")]
    bars = ax.barh(df_results["Model"], df_results["MAPE (%)"], color=colors)
    ax.set_xlabel("MAPE (%) — lower is better")
    ax.set_title("KisanMitra — Clean Chronological Benchmark\n(all models, same 80/20 temporal split)")
    ax.grid(axis="x", alpha=0.3)
    for bar in bars:
        w = bar.get_width()
        if not np.isnan(w):
            ax.text(w + 0.2, bar.get_y() + bar.get_height() / 2,
                    f"{w:.2f}%", va="center", fontsize=9)
    plt.tight_layout()
    chart_path = RESULTS_DIR / "clean_benchmark_chart.png"
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nChart saved → {chart_path}")

    # ── Significance test (chronological fold-based) ─────────────────────
    print("\n" + "=" * 60)
    print("RF vs best competitor — chronological block significance test")
    print("=" * 60)
    from scipy import stats as scipy_stats

    # Use non-overlapping temporal blocks as pseudo-folds (5 blocks)
    # so the test retains temporal order and avoids KFold shuffle.
    n_blocks = 5
    block_size = len(X_te_tree) // n_blocks
    rf_model_sig = RandomForestRegressor(
        n_estimators=200, max_depth=12, min_samples_split=10,
        min_samples_leaf=5, random_state=42, n_jobs=-1
    )
    rf_model_sig.fit(X_tr_tree, y_train)

    # Find best non-RF result for comparison
    competitors = [r for r in results if r["Model"] not in ("Random Forest", "ARIMA(5,1,0)") and r["MAPE (%)"] is not None]
    best_comp = min(competitors, key=lambda r: r["MAPE (%)"])
    best_comp_name = best_comp["Model"]
    best_comp_model = next(c[1] for c in model_configs if c[0] == best_comp_name)

    rf_block_mapes, comp_block_mapes = [], []
    for i in range(n_blocks):
        start = i * block_size
        end   = start + block_size if i < n_blocks - 1 else len(X_te_tree)
        Xb_tree = X_te_tree.iloc[start:end]
        Xb_lin  = X_te_lin.iloc[start:end]
        yb      = y_test.iloc[start:end]

        Xb_comp = Xb_lin if best_comp_name in ("SVR", "KNN Regressor", "Ridge Regression", "Linear Regression") else Xb_tree

        rf_preds_b   = rf_model_sig.predict(Xb_tree)
        comp_preds_b = best_comp_model.predict(Xb_comp)

        rf_block_mapes.append(mean_absolute_percentage_error(yb, rf_preds_b) * 100)
        comp_block_mapes.append(mean_absolute_percentage_error(yb, comp_preds_b) * 100)

    rf_arr   = np.array(rf_block_mapes)
    comp_arr = np.array(comp_block_mapes)

    t_stat, p_ttest   = scipy_stats.ttest_rel(rf_arr, comp_arr)
    w_stat, p_wilcoxon = scipy_stats.wilcoxon(rf_arr, comp_arr)

    print(f"  RF block MAPEs   : {[round(x,2) for x in rf_arr.tolist()]}")
    print(f"  {best_comp_name} block MAPEs: {[round(x,2) for x in comp_arr.tolist()]}")
    print(f"  Paired t-test  p : {p_ttest:.4f}")
    print(f"  Wilcoxon       p : {p_wilcoxon:.4f}")
    sig = p_ttest < 0.05
    print(f"  {'✅ Significant' if sig else '⚠  Not significant'} at α=0.05 "
          f"({'RF wins' if sig and rf_arr.mean() < comp_arr.mean() else 'inconclusive' if not sig else 'RF loses'})")

    # ── Summary for paper ──────────────────────────────────────────────────
    rf_result = next(r for r in results if r["Model"] == "Random Forest")
    arima_result = next((r for r in results if "ARIMA" in r["Model"]), None)
    print("\n" + "=" * 60)
    print("PAPER-READY NUMBERS (chronological split, no leakage)")
    print("=" * 60)
    print(f"  RF MAPE  : {rf_result['MAPE (%)']:.2f}%")
    print(f"  RF RMSE  : ₹{rf_result['RMSE (Rs)']:.2f}/quintal")
    print(f"  RF R²    : {rf_result['R² Score']:.4f}")
    if arima_result:
        gain = arima_result["MAPE (%)"] - rf_result["MAPE (%)"]
        pct_gain = gain / arima_result["MAPE (%)"] * 100
        print(f"  ARIMA    : {arima_result['MAPE (%)']:.2f}%")
        print(f"  RF vs ARIMA: {gain:+.2f} pp ({pct_gain:.1f}% improvement)")
    print(f"  Best competitor: {best_comp_name} at {best_comp['MAPE (%)']:.2f}%")
    print("")
    print("  Feature notes (for paper):")
    print("    MSP: tested for Maize & Ragi only (2 of 7 crops).")
    print("         Brinjal, Tomato, Onion, Potato, Marigold are perishable")
    print("         vegetables/flowers outside India's MSP scheme; their rows")
    print("         receive msp=0 (not-applicable indicator, not imputed).")
    print("    Fuel price & weather: logged as future work —")
    print("         no verified, dated historical series was available from")
    print("         a programmatically accessible official source within scope.")
    print("         (PPAC RSP bulletins require registration; IMD station data")
    print("         requires institutional access.)")
    print("=" * 60)


if __name__ == "__main__":
    main()
