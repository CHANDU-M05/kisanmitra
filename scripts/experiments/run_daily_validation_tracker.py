"""
scripts/experiments/run_daily_validation_tracker.py

Unified evaluation on production target (target_price_60d):

Fixes implemented:
1. Target unification: Uses `target_price_60d` directly from `karnataka_clean.csv`
   eliminating the discrepancy between calendar lookup and row-based shift.
2. MSP ratio feature: Replaced raw subtraction with relative MSP floor gap:
      (modal_price - MSP) / MSP   for Maize & Ragi
      np.nan                      for non-MSP crops (HistGBDT handles natively)
3. Aligned rolling std: `price_30d_std` uses `shift(1).rolling(30)` to strictly
   match the shift convention of `price_7d_avg` and `price_30d_avg`.
"""
from __future__ import annotations

from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.preprocessing import LabelEncoder

BASE_DIR      = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
ARTIFACTS_DIR = Path(
    "/home/chandu/.gemini/antigravity-ide/brain/"
    "405adf4b-ec6a-46d0-86d3-78507e97e0bc"
)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.sans-serif"] = "DejaVu Sans"
plt.rcParams["axes.edgecolor"] = "#aaaaaa"
plt.rcParams["axes.linewidth"] = 0.8

# Official Kharif MSP (₹/quintal)
MSP = {"Maize": 2400.0, "Ragi": 4886.0}


# ── helpers ──────────────────────────────────────────────────────────────────

def build_dataset() -> pd.DataFrame:
    path = PROCESSED_DIR / "karnataka_clean.csv"
    if not path.exists():
        path = PROCESSED_DIR / "all_model_data.csv"
    df = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Use production target directly (eliminates calendar vs row shift discrepancy)
    df.dropna(subset=["target_price_60d"], inplace=True)

    # ── Feature Engineering ───────────────────────────────────────────────────
    df = df.sort_values(["market", "commodity", "arrival_date"])
    grp = df.groupby(["market", "commodity"])["modal_price"]

    df["price_14d_ago"] = grp.shift(14)
    df["price_45d_ago"] = grp.shift(45)
    df["price_60d_ago"] = grp.shift(60)
    # Shift(1) before rolling to align convention with price_30d_avg
    df["price_30d_std"] = grp.transform(
        lambda s: s.shift(1).rolling(30, min_periods=7).std()
    )
    df["price_yoy"]     = grp.shift(364)

    # Relative MSP ratio: (price - msp) / msp for MSP crops, NaN for non-MSP
    df["msp_ratio"] = df.apply(
        lambda r: (r["modal_price"] - MSP[r["commodity"]]) / MSP[r["commodity"]]
        if r["commodity"] in MSP else np.nan,
        axis=1
    )

    df["commodity_encoded"] = LabelEncoder().fit_transform(df["commodity"])
    df["market_encoded"]    = LabelEncoder().fit_transform(df["market"])

    df = df.sort_values("arrival_date").reset_index(drop=True)
    return df


OLD_FEATURES = [
    "commodity_encoded", "market_encoded",
    "month", "month_sin", "month_cos", "season", "quarter",
    "modal_price", "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago", "price_trend_7d",
    "vs_seasonal", "seasonal_avg", "arrivals_tonnes", "arrivals_7d_avg",
]

NEW_FEATURES = OLD_FEATURES + [
    "price_14d_ago", "price_45d_ago", "price_60d_ago",
    "price_30d_std", "price_yoy", "msp_ratio",
]


# ── model factories ───────────────────────────────────────────────────────────

def train_old(train_df):
    """Old model: binary storable/perishable split, base features."""
    storable = ["Maize", "Ragi", "Potato"]
    tr_s = train_df[train_df["commodity"].isin(storable)]
    tr_p = train_df[~train_df["commodity"].isin(storable)]

    m_s = HistGradientBoostingRegressor(
        max_iter=200, max_depth=6, min_samples_leaf=10, random_state=42
    )
    m_s.fit(tr_s[OLD_FEATURES], tr_s["target_price_60d"])

    m_p = HistGradientBoostingRegressor(
        max_iter=200, max_depth=10, min_samples_leaf=5, random_state=42
    )
    m_p.fit(tr_p[OLD_FEATURES], tr_p["target_price_60d"])

    def predict(te_df):
        p  = np.zeros(len(te_df))
        s  = te_df["commodity"].isin(storable).values
        p[s]  = m_s.predict(te_df[OLD_FEATURES].iloc[np.where(s)[0]])
        p[~s] = m_p.predict(te_df[OLD_FEATURES].iloc[np.where(~s)[0]])
        return p

    return predict


def train_new(train_df):
    """New model: same binary split, ALL new features."""
    storable = ["Maize", "Ragi", "Potato"]
    tr_s = train_df[train_df["commodity"].isin(storable)]
    tr_p = train_df[~train_df["commodity"].isin(storable)]

    m_s = HistGradientBoostingRegressor(
        max_iter=400, max_depth=7, min_samples_leaf=8,
        learning_rate=0.04, random_state=42
    )
    m_s.fit(tr_s[NEW_FEATURES], tr_s["target_price_60d"])

    m_p = HistGradientBoostingRegressor(
        max_iter=400, max_depth=7, min_samples_leaf=8,
        learning_rate=0.04, random_state=42
    )
    m_p.fit(tr_p[NEW_FEATURES], tr_p["target_price_60d"])

    def predict(te_df):
        p  = np.zeros(len(te_df))
        s  = te_df["commodity"].isin(storable).values
        p[s]  = m_s.predict(te_df[NEW_FEATURES].iloc[np.where(s)[0]])
        p[~s] = m_p.predict(te_df[NEW_FEATURES].iloc[np.where(~s)[0]])
        return p

    return predict


# ── walk-forward cross-validation ─────────────────────────────────────────────

def walk_forward_cv(df, n_folds=5):
    """Returns (old_mape, new_mape) averaged across folds."""
    fold_size = len(df) // (n_folds + 1)
    old_mapes, new_mapes = [], []

    for fold in range(n_folds):
        train_end = fold_size * (fold + 1)
        test_end  = train_end + fold_size
        if test_end > len(df):
            break
        tr = df.iloc[:train_end].copy()
        te = df.iloc[train_end:test_end].copy()
        if len(tr) < 200 or len(te) < 20:
            continue

        old_p = train_old(tr)(te)
        new_p = train_new(tr)(te)

        om = mean_absolute_percentage_error(te["target_price_60d"], old_p) * 100
        nm = mean_absolute_percentage_error(te["target_price_60d"], new_p) * 100
        old_mapes.append(om)
        new_mapes.append(nm)
        print(f"  Fold {fold+1}: old={om:.2f}%  new={nm:.2f}%")

    return float(np.mean(old_mapes)), float(np.mean(new_mapes))


# ── main ──────────────────────────────────────────────────────────────────────

def run():
    print("Building dataset with unified production target...")
    df = build_dataset()
    crops = sorted(df["commodity"].unique())
    print(f"Dataset: {len(df):,} rows | {df['arrival_date'].min().date()} → "
          f"{df['arrival_date'].max().date()}\n")

    # ── Walk-forward CV ───────────────────────────────────────────────────────
    print("Running 5-fold walk-forward cross-validation...")
    old_cv, new_cv = walk_forward_cv(df, n_folds=5)
    print(f"\nWalk-forward CV result:")
    print(f"  Old model (base features): {old_cv:.2f}% MAPE")
    print(f"  New model (all features):  {new_cv:.2f}% MAPE")
    print(f"  Improvement: {old_cv - new_cv:+.2f}%\n")

    # ── Final 80/20 holdout ───────────────────────────────────────────────────
    cutoff   = int(len(df) * 0.80)
    train_df = df.iloc[:cutoff].copy()
    test_df  = df.iloc[cutoff:].copy()

    print("Training final models on 80% holdout split...")
    old_predict = train_old(train_df)
    new_predict = train_new(train_df)

    test_df = test_df.copy()
    test_df["old_pred"] = old_predict(test_df)
    test_df["new_pred"] = new_predict(test_df)
    test_df["actual"]   = test_df["target_price_60d"]

    print()
    print("=" * 68)
    print(f"{'Crop':<14} {'Old MAPE':>10} {'New MAPE':>10} {'Δ Improvement':>14}")
    print("=" * 68)
    o_list, n_list = [], []
    for crop in crops:
        og = test_df[test_df["commodity"] == crop]
        if len(og) == 0:
            continue
        om = mean_absolute_percentage_error(og["actual"], og["old_pred"]) * 100
        nm = mean_absolute_percentage_error(og["actual"], og["new_pred"]) * 100
        delta = om - nm
        o_list.append(om); n_list.append(nm)
        flag = "✅" if delta > 0 else ("⚠️ " if delta < 0 else "→")
        print(f"{crop:<14} {om:>9.2f}% {nm:>9.2f}% {delta:>+12.2f}%  {flag}")
    print("-" * 68)
    print(f"{'OVERALL':<14} {np.mean(o_list):>9.2f}% {np.mean(n_list):>9.2f}% "
          f"{np.mean(o_list)-np.mean(n_list):>+12.2f}%")
    print("=" * 68)

    # Pick the better model for charts
    best_col = "new_pred" if np.mean(n_list) < np.mean(o_list) else "old_pred"
    print(f"\nUsing '{best_col}' for charts.")

    # ── Chart 1: Tomato across all mandis — weekly average ───────────────────
    tomato_markets = ["Kolar", "Belagavi", "Chikkaballapur"]
    tom = test_df[
        (test_df["commodity"] == "Tomato") &
        (test_df["market"].isin(tomato_markets))
    ].sort_values("arrival_date")

    weekly = (
        tom.set_index("arrival_date")[["actual", best_col]]
        .resample("W").mean().dropna().reset_index()
    )

    fig, ax = plt.subplots(figsize=(12, 5), dpi=300)
    ax.plot(weekly["arrival_date"], weekly["actual"],
            color="#0f172a", linewidth=2.8, linestyle="-",
            label="Actual Mandi Price (Real AGMARKNET data)")
    ax.plot(weekly["arrival_date"], weekly[best_col],
            color="#ea580c", linewidth=2.4, linestyle="--",
            label="Predicted Price (60-Day Model)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=25, ha="right")
    ax.set_title(
        "Tomato Price: Actual vs. Predicted Across All Karnataka Mandis\n"
        "(Kolar + Belagavi + Chikkaballapur  |  Feb 2024 – Apr 2025)",
        fontsize=13, fontweight="bold", pad=14, color="#0f172a"
    )
    ax.set_xlabel("Month", fontsize=11, fontweight="bold", labelpad=8, color="#334155")
    ax.set_ylabel("Weekly Avg Price  (₹ per Quintal)", fontsize=11,
                  fontweight="bold", labelpad=8, color="#334155")
    ax.legend(loc="upper right", frameon=True, facecolor="#ffffff",
              edgecolor="#94a3b8", fontsize=11)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5, color="#cbd5e1")
    plt.tight_layout()
    plt.savefig(ARTIFACTS_DIR / "actual_vs_predicted_all_mandis_overall.png")
    plt.close()

    # ── Chart 2: 4-panel multi-mandi ─────────────────────────────────────────
    panels = [
        ("Kolar",    "Tomato",  "Kolar Mandi — Tomato",    "Perishable · Most Volatile"),
        ("Dharwad",  "Onion",   "Dharwad Mandi — Onion",   "Price-Shock Prone"),
        ("Belagavi", "Brinjal", "Belagavi Mandi — Brinjal","Perishable Vegetable"),
        ("Tumakuru", "Ragi",    "Tumakuru Mandi — Ragi",   "Staple Cereal · Most Stable"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), dpi=300)
    axes = axes.flatten()
    for idx, (market, crop, title, subtitle) in enumerate(panels):
        ax = axes[idx]
        sub = test_df[
            (test_df["market"] == market) & (test_df["commodity"] == crop)
        ].sort_values("arrival_date")

        ax.plot(sub["arrival_date"], sub["actual"],
                color="#0f172a", linewidth=2.0, linestyle="-",
                label="Actual Mandi Price")
        ax.plot(sub["arrival_date"], sub[best_col],
                color="#ea580c", linewidth=1.8, linestyle="--",
                label="Predicted (60-Day)")
        ax.set_title(f"{title}\n{subtitle}", fontsize=11,
                     fontweight="bold", color="#0f172a", pad=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=25, ha="right", fontsize=8)
        ax.tick_params(axis="y", labelsize=8)
        ax.set_ylabel("Price (₹/q)", fontsize=9, color="#334155")
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.5, color="#cbd5e1")
        if idx == 0:
            ax.legend(loc="upper right", frameon=True, facecolor="#ffffff",
                      edgecolor="#94a3b8", fontsize=9)

    fig.suptitle(
        "Actual vs. Predicted — 4 Karnataka Mandi Hubs  (Feb 2024 – Apr 2025)",
        fontsize=13, fontweight="bold", y=1.01, color="#0f172a"
    )
    plt.tight_layout()
    plt.savefig(ARTIFACTS_DIR / "actual_vs_predicted_multi_mandi.png", bbox_inches="tight")
    plt.close()

    print(f"\nCharts saved to:\n  {ARTIFACTS_DIR / 'actual_vs_predicted_all_mandis_overall.png'}"
          f"\n  {ARTIFACTS_DIR / 'actual_vs_predicted_multi_mandi.png'}")


if __name__ == "__main__":
    run()
