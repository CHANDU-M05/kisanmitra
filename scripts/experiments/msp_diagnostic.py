"""
scripts/msp_diagnostic.py

Three targeted checks before the MSP feature result goes into the paper:

  CHECK 1: msp_ratio zero-fill — does np.where produce any inf/NaN for
            the non-MSP crop rows where msp_rs_per_quintal == 0?

  CHECK 2: ARIMA train/test row identity — does _attach_msp() change
            row count, date range, or 80/20 split boundary compared to
            the baseline (no MSP) pipeline? If it does, the 0.52pp
            ARIMA delta is a pipeline artifact, not a finding.

  CHECK 3: Per-crop (Maize/Ragi) MSP delta significance — apply the
            same chronological block test used in the main benchmark
            to measure whether the Ragi improvement (-0.44pp) is
            statistically distinguishable from noise.

Usage:
    venv/bin/python scripts/msp_diagnostic.py
"""

import sys
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error
from scipy import stats as scipy_stats

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE_DIR      = Path(__file__).parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RAW_DIR       = BASE_DIR / "data" / "raw"

TARGET_COL = "target_price_60d"
NUMERIC_COLS_BASE = [
    "month", "month_sin", "month_cos",
    "season", "quarter",
    "modal_price",
    "price_7d_avg",  "price_30d_avg",
    "price_7d_ago",  "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "arrivals_tonnes",
    "arrivals_7d_avg",
]
NUMERIC_COLS_MSP = NUMERIC_COLS_BASE + ["msp_rs_per_quintal", "msp_ratio"]


def _attach_msp(df: pd.DataFrame) -> pd.DataFrame:
    """Exact copy of the implementation in clean_benchmark.py."""
    msp_path = RAW_DIR / "msp_history.csv"
    msp = pd.read_csv(msp_path, comment="#", parse_dates=["effective_date"])
    msp = msp.sort_values("effective_date").rename(columns={"crop": "commodity"})

    df["commodity_lower"]  = df["commodity"].str.strip().str.title()
    msp["commodity_lower"] = msp["commodity"].str.strip().str.title()
    msp_crops = msp["commodity_lower"].unique().tolist()

    merged_parts = []
    for crop_name, grp in df.groupby("commodity_lower"):
        grp = grp.sort_values("arrival_date").copy()
        if crop_name in msp_crops:
            msp_crop = msp[msp["commodity_lower"] == crop_name].sort_values("effective_date")
            merged = pd.merge_asof(
                grp,
                msp_crop[["effective_date", "msp_rs_per_quintal"]],
                left_on="arrival_date",
                right_on="effective_date",
                direction="backward",
            )
            merged["msp_rs_per_quintal"] = merged["msp_rs_per_quintal"].fillna(0.0)
        else:
            grp["msp_rs_per_quintal"] = 0.0
            merged = grp
        merged_parts.append(merged)

    df = pd.concat(merged_parts).sort_values("arrival_date").reset_index(drop=True)

    df["msp_ratio"] = np.where(
        df["msp_rs_per_quintal"] > 0,
        df["modal_price"] / df["msp_rs_per_quintal"],
        0.0,
    )

    df.drop(columns=["commodity_lower"], inplace=True)
    return df


def load_base():
    """Load data WITHOUT MSP — replicates original baseline pipeline."""
    df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    for col in NUMERIC_COLS_BASE:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    df = df[df[TARGET_COL].notna()].reset_index(drop=True)
    cutoff = int(len(df) * 0.80)
    return df.iloc[:cutoff].copy(), df.iloc[cutoff:].copy()


def load_with_msp():
    """Load data WITH MSP attached — replicates current benchmark pipeline."""
    df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df = _attach_msp(df)
    for col in NUMERIC_COLS_MSP:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
        else:
            df[col] = 0.0
    df = df[df[TARGET_COL].notna()].reset_index(drop=True)
    cutoff = int(len(df) * 0.80)
    return df.iloc[:cutoff].copy(), df.iloc[cutoff:].copy()


def rf_fit_predict(train, test, feature_cols):
    from sklearn.preprocessing import LabelEncoder
    le_comm = LabelEncoder().fit(train["commodity"])
    le_mkt  = LabelEncoder().fit(train["market"])
    for df in (train, test):
        df["commodity_encoded"] = le_comm.transform(
            df["commodity"].where(df["commodity"].isin(le_comm.classes_), le_comm.classes_[0])
        )
        df["market_encoded"] = le_mkt.transform(
            df["market"].where(df["market"].isin(le_mkt.classes_), le_mkt.classes_[0])
        )
    cols = feature_cols + ["commodity_encoded", "market_encoded"]
    rf = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_split=10,
                               min_samples_leaf=5, random_state=42, n_jobs=-1)
    rf.fit(train[cols], train[TARGET_COL])
    return rf.predict(test[cols])


def sep():
    print("=" * 60)


# ── CHECK 1: msp_ratio inf/NaN audit ────────────────────────────────────────
def check1_msp_ratio_integrity():
    sep()
    print("CHECK 1: msp_ratio column integrity (inf / NaN audit)")
    sep()

    df = pd.read_csv(PROCESSED_DIR / "all_model_data.csv")
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df = _attach_msp(df)

    n_inf  = np.isinf(df["msp_ratio"]).sum()
    n_nan  = df["msp_ratio"].isna().sum()
    n_inf_msp  = np.isinf(df["msp_rs_per_quintal"]).sum()
    n_nan_msp  = df["msp_rs_per_quintal"].isna().sum()
    n_zero_msp = (df["msp_rs_per_quintal"] == 0).sum()
    n_pos_msp  = (df["msp_rs_per_quintal"] > 0).sum()

    print(f"  msp_rs_per_quintal — NaN: {n_nan_msp}, inf: {n_inf_msp}, "
          f"zero: {n_zero_msp:,}, positive: {n_pos_msp:,}")
    print(f"  msp_ratio          — NaN: {n_nan}, inf: {n_inf}")

    # Spot-check: non-MSP crops should have exactly msp_ratio == 0.0
    non_msp_crops = ["Brinjal", "Tomato", "Onion", "Potato", "Marigold"]
    for crop in non_msp_crops:
        mask = df["commodity"].str.title() == crop.title()
        ratio_vals = df.loc[mask, "msp_ratio"]
        non_zero = (ratio_vals != 0.0).sum()
        has_inf   = np.isinf(ratio_vals).sum()
        has_nan   = ratio_vals.isna().sum()
        print(f"    {crop:<12} rows={mask.sum():,}  non-zero ratio={non_zero}  "
              f"inf={has_inf}  nan={has_nan}")

    # Spot-check: MSP crops should have positive ratios in expected range
    for crop in ["Maize", "Ragi"]:
        mask = df["commodity"].str.title() == crop.title()
        ratios = df.loc[mask, "msp_ratio"]
        print(f"    {crop:<12} ratio min={ratios.min():.3f}  max={ratios.max():.3f}  "
              f"mean={ratios.mean():.3f}  NaN={ratios.isna().sum()}  inf={np.isinf(ratios).sum()}")

    if n_inf == 0 and n_nan == 0:
        print("\n  ✅ CLEAN — no inf or NaN in msp_ratio. np.where guard works correctly.")
    else:
        print(f"\n  ❌ PROBLEM — {n_inf} inf values and {n_nan} NaN values found in msp_ratio.")


# ── CHECK 2: ARIMA row identity ──────────────────────────────────────────────
def check2_arima_row_identity():
    sep()
    print("CHECK 2: ARIMA train/test row identity (base vs MSP pipeline)")
    sep()

    train_base, test_base = load_base()
    train_msp,  test_msp  = load_with_msp()

    # ARIMA only uses commodity, market, arrival_date, modal_price, target
    arima_cols = ["commodity", "market", "arrival_date", "modal_price", TARGET_COL]

    for split_name, base_df, msp_df in [
        ("train", train_base, train_msp),
        ("test",  test_base,  test_msp),
    ]:
        same_len   = len(base_df) == len(msp_df)
        same_start = base_df["arrival_date"].min() == msp_df["arrival_date"].min()
        same_end   = base_df["arrival_date"].max() == msp_df["arrival_date"].max()

        if same_len and same_start and same_end:
            # Deep check: are the modal_price series identical?
            price_identical = (base_df["modal_price"].values == msp_df["modal_price"].values).all()
            date_identical  = (base_df["arrival_date"].values == msp_df["arrival_date"].values).all()
            crop_identical  = (base_df["commodity"].values == msp_df["commodity"].values).all()
            all_ok = price_identical and date_identical and crop_identical
        else:
            price_identical = date_identical = crop_identical = all_ok = False

        print(f"  {split_name}: rows base={len(base_df):,} msp={len(msp_df):,}  "
              f"same_len={same_len}  "
              f"dates ({base_df['arrival_date'].min().date()}→{base_df['arrival_date'].max().date()})")
        print(f"    modal_price identical: {price_identical}")
        print(f"    arrival_date identical: {date_identical}")
        print(f"    commodity order identical: {crop_identical}")
        print(f"    → {'✅ IDENTICAL — ARIMA delta is a real pipeline change, not a data shift.'  if all_ok else '❌ ROWS DIFFER — ARIMA delta is a pipeline artifact.'}")


# ── CHECK 3: Per-crop significance (Maize + Ragi MSP delta) ─────────────────
def check3_per_crop_significance():
    sep()
    print("CHECK 3: Chronological block significance — RF MSP delta for Maize & Ragi")
    sep()

    train_base, test_base = load_base()
    train_msp,  test_msp  = load_with_msp()

    preds_base = rf_fit_predict(train_base.copy(), test_base.copy(), NUMERIC_COLS_BASE)
    preds_msp  = rf_fit_predict(train_msp.copy(),  test_msp.copy(),  NUMERIC_COLS_MSP)

    n_blocks   = 5
    block_size = len(test_base) // n_blocks

    for crop in ["Maize", "Ragi", "POOLED"]:
        if crop == "POOLED":
            mask_base = np.ones(len(test_base), dtype=bool)
            mask_msp  = np.ones(len(test_msp),  dtype=bool)
        else:
            mask_base = test_base["commodity"].str.title() == crop
            mask_msp  = test_msp["commodity"].str.title()  == crop

        y_base = test_base.loc[mask_base, TARGET_COL].values
        y_msp  = test_msp.loc[mask_msp,   TARGET_COL].values
        p_base = preds_base[mask_base if isinstance(mask_base, np.ndarray) else mask_base.values]
        p_msp  = preds_msp[mask_msp   if isinstance(mask_msp,  np.ndarray) else mask_msp.values]

        overall_base = mean_absolute_percentage_error(y_base, p_base) * 100
        overall_msp  = mean_absolute_percentage_error(y_msp,  p_msp)  * 100
        delta = overall_msp - overall_base

        # Chronological block test within this crop's test rows
        # Use 5 even-sized temporal blocks of the crop's test rows
        n = min(len(y_base), len(y_msp))
        bsz = n // n_blocks
        if bsz < 3:
            print(f"  {crop:<8}: base={overall_base:.2f}% → msp={overall_msp:.2f}%  "
                  f"Δ={delta:+.2f}pp  (too few rows for block test: n={n})")
            continue

        block_base, block_msp = [], []
        for i in range(n_blocks):
            s = i * bsz
            e = s + bsz if i < n_blocks - 1 else n
            block_base.append(mean_absolute_percentage_error(y_base[s:e], p_base[s:e]) * 100)
            block_msp.append(mean_absolute_percentage_error(y_msp[s:e],  p_msp[s:e])  * 100)

        ba = np.array(block_base)
        bm = np.array(block_msp)
        _, p_t = scipy_stats.ttest_rel(bm, ba)
        try:
            _, p_w = scipy_stats.wilcoxon(bm, ba)
        except Exception:
            p_w = float("nan")

        sig = p_t < 0.05
        print(f"  {crop:<8}: base={overall_base:.2f}% → msp={overall_msp:.2f}%  "
              f"Δ={delta:+.2f}pp  t-p={p_t:.4f}  W-p={p_w:.4f}  "
              f"{'⚠  NOT significant' if not sig else '✅ Significant'} at α=0.05")
        print(f"    blocks base={[round(x,2) for x in ba.tolist()]}")
        print(f"    blocks msp ={[round(x,2) for x in bm.tolist()]}")


# ── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    check1_msp_ratio_integrity()
    print()
    check2_arima_row_identity()
    print()
    check3_per_crop_significance()
    print()
