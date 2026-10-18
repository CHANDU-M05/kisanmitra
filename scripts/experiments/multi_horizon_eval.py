"""
multi_horizon_eval.py -- answers: "how accurate is the prediction at 1, 7,
14, 21, 30, 45, and 60 days ahead, for each crop?"

Features are computed ONCE (they don't depend on horizon). Only the target
column changes per horizon (shift(-h)). Each horizon is evaluated against:
  1. Model MAPE          -- the actual model's error
  2. Naive MAPE           -- "tomorrow/next-period price = today's price",
                             the bar the model must beat to be worth using
  3. Direction accuracy   -- did the model get up/down right
  4. Avg rupee error      -- absolute error in real currency, easier to
                             communicate than a percentage

This reuses the same leak-free feature engineering verified earlier: every
feature is built with shift(1) or later, so on any given day we only use
information available by end of that day.
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.preprocessing import LabelEncoder

DATA_PATH = "data/processed/clean_agmarknet_prices.csv"

MSP = {"Maize": 2400.0, "Ragi": 4886.0}
HORIZONS = [1, 7, 14, 21, 30, 45, 60]

# ---------------------------------------------------------------------
# 1. Load + feature engineering -- computed ONCE, independent of horizon.
# ---------------------------------------------------------------------
df = pd.read_csv(DATA_PATH)
df["arrival_date"] = pd.to_datetime(df["arrival_date"])
df.rename(columns={
    "Commodity": "commodity",
    "Market_Clean": "market",
    "Modal_Price": "modal_price"
}, inplace=True)
df.sort_values(["market", "commodity", "arrival_date"], inplace=True)
df.reset_index(drop=True, inplace=True)
g = df.groupby(["market", "commodity"])["modal_price"]

df["price_1d_ago"]  = g.transform(lambda x: x.shift(1))
df["price_7d_ago"]  = g.transform(lambda x: x.shift(7))
df["price_14d_ago"] = g.transform(lambda x: x.shift(14))
df["price_30d_ago"] = g.transform(lambda x: x.shift(30))
df["price_45d_ago"] = g.transform(lambda x: x.shift(45))
df["price_60d_ago"] = g.transform(lambda x: x.shift(60))
df["price_yoy"]     = g.transform(lambda x: x.shift(364))

df["price_7d_avg"]  = g.transform(lambda x: x.shift(1).rolling(7,  min_periods=3).mean())
df["price_30d_avg"] = g.transform(lambda x: x.shift(1).rolling(30, min_periods=10).mean())
df["price_3d_std"]  = g.transform(lambda x: x.shift(1).rolling(3,  min_periods=2).std())
df["price_7d_std"]  = g.transform(lambda x: x.shift(1).rolling(7,  min_periods=3).std())
df["price_30d_std"] = g.transform(lambda x: x.shift(1).rolling(30, min_periods=7).std())
df["price_trend_7d"] = (df["price_1d_ago"] - df["price_7d_ago"]) / df["price_7d_ago"].replace(0, np.nan)

df["month"] = df["arrival_date"].dt.month
df["year"] = df["arrival_date"].dt.year
df["quarter"] = df["arrival_date"].dt.quarter
df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

if "arrivals_tonnes" not in df.columns:
    df["arrivals_tonnes"] = 0.0

df["arrivals_1d_ago"] = df.groupby(["market","commodity"])["arrivals_tonnes"].transform(lambda x: x.shift(1))
df["arrivals_7d_avg"] = df.groupby(["market","commodity"])["arrivals_tonnes"].transform(
    lambda x: x.shift(1).rolling(7, min_periods=3).mean()
)

monthly_means = df.groupby(["market", "commodity", "year", "month"])["modal_price"].mean().reset_index()
monthly_means.sort_values("year", inplace=True)
monthly_means["seasonal_avg"] = monthly_means.groupby(["market", "commodity", "month"])["modal_price"].transform(
    lambda x: x.shift(1).expanding().mean()
)
if "seasonal_avg" in df.columns:
    df.drop(columns=["seasonal_avg"], inplace=True)
df = df.merge(monthly_means[["market", "commodity", "year", "month", "seasonal_avg"]],
              on=["market", "commodity", "year", "month"], how="left")
df["seasonal_avg"] = df["seasonal_avg"].fillna(df["price_30d_avg"]).fillna(df["price_1d_ago"])
df["vs_seasonal"] = df["price_1d_ago"] / df["seasonal_avg"].replace(0, np.nan)

df["msp_ratio"] = df.apply(
    lambda r: (r["price_1d_ago"] - MSP[r["commodity"]]) / MSP[r["commodity"]]
    if r["commodity"] in MSP and pd.notna(r["price_1d_ago"]) else np.nan,
    axis=1
)
df["commodity_encoded"] = LabelEncoder().fit_transform(df["commodity"])
df["market_encoded"] = LabelEncoder().fit_transform(df["market"])

FEATURES = [
    "commodity_encoded", "market_encoded", "month", "month_sin", "month_cos", "quarter",
    "price_1d_ago", "price_7d_ago", "price_14d_ago", "price_30d_ago", "price_45d_ago",
    "price_60d_ago", "price_yoy",
    "price_7d_avg", "price_30d_avg", "price_3d_std", "price_7d_std", "price_30d_std",
    "price_trend_7d", "vs_seasonal", "seasonal_avg",
    "arrivals_1d_ago", "arrivals_7d_avg", "msp_ratio",
]

df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

print(f"Total rows loaded: {len(df):,}")
print(f"Date range: {df['arrival_date'].min().date()} -> {df['arrival_date'].max().date()}\n")


def impute(train, test, cols):
    train, test = train.copy(), test.copy()
    for c in cols:
        med = train[c].median()
        train[c] = train[c].fillna(med)
        test[c] = test[c].fillna(med)
    return train, test


def evaluate_horizon(h):
    """Build target for horizon h, split chronologically, train+eval per crop."""
    dfh = df.copy()
    dfh["target"] = dfh.groupby(["market", "commodity"])["modal_price"].transform(lambda x: x.shift(-h))
    valid = dfh["target"].notna() & dfh["price_1d_ago"].notna()
    dfh = dfh[valid].copy()

    n = len(dfh)
    cutoff = int(n * 0.80)
    train_df = dfh.iloc[:cutoff]
    test_df  = dfh.iloc[cutoff:]

    rows = []
    for crop in sorted(dfh["commodity"].unique()):
        tr = train_df[train_df["commodity"] == crop]
        te = test_df[test_df["commodity"] == crop]
        if len(tr) < 30 or len(te) < 10:
            continue

        tr_i, te_i = impute(tr, te, FEATURES)
        model = HistGradientBoostingRegressor(random_state=42, max_iter=300)
        model.fit(tr_i[FEATURES], tr_i["target"])
        pred = model.predict(te_i[FEATURES])

        mape_model = mean_absolute_percentage_error(te_i["target"], pred) * 100

        # naive baseline: horizon-ahead price = most recent known price
        naive_pred = te_i["price_1d_ago"].values
        mape_naive = mean_absolute_percentage_error(te_i["target"], naive_pred) * 100

        actual_dir = np.sign(te_i["target"].values - te_i["price_1d_ago"].values)
        pred_dir = np.sign(pred - te_i["price_1d_ago"].values)
        dir_acc = np.mean(actual_dir == pred_dir) * 100

        avg_rs_err = np.mean(np.abs(pred - te_i["target"].values))

        rows.append({
            "crop": crop, "horizon": h, "train_n": len(tr), "test_n": len(te),
            "model_mape": mape_model, "naive_mape": mape_naive,
            "dir_acc": dir_acc, "avg_rs_err": avg_rs_err,
        })
    return rows


# ---------------------------------------------------------------------
# 2. Run all horizons, print a full table, then a per-crop summary
#    showing how MAPE degrades as horizon grows.
# ---------------------------------------------------------------------
all_rows = []
for h in HORIZONS:
    print(f"Running horizon = {h} day(s)...")
    all_rows.extend(evaluate_horizon(h))

results = pd.DataFrame(all_rows)

print("\n" + "=" * 90)
print("FULL RESULTS: MODEL MAPE vs NAIVE BASELINE, BY CROP AND HORIZON")
print("=" * 90)
print(f"{'Crop':<10}{'Horizon':>8}{'TrainN':>8}{'TestN':>7}{'ModelMAPE':>11}{'NaiveMAPE':>11}{'DirAcc':>9}{'AvgRsErr':>10}")
print("-" * 90)
for _, r in results.iterrows():
    print(f"{r['crop']:<10}{int(r['horizon']):>7}d{int(r['train_n']):>8}{int(r['test_n']):>7}"
          f"{r['model_mape']:>10.2f}%{r['naive_mape']:>10.2f}%{r['dir_acc']:>8.1f}%{r['avg_rs_err']:>9.1f}")

print("\n" + "=" * 90)
print("SUMMARY: MODEL MAPE BY CROP ACROSS ALL HORIZONS (pivot table)")
print("=" * 90)
pivot = results.pivot(index="crop", columns="horizon", values="model_mape")
pivot = pivot.reindex(columns=HORIZONS)
print(pivot.round(2).to_string())

print("\n" + "=" * 90)
print("OVERALL MAPE PER HORIZON (averaged across crops, weighted by test_n)")
print("=" * 90)
for h in HORIZONS:
    sub = results[results["horizon"] == h]
    weighted_mape = np.average(sub["model_mape"], weights=sub["test_n"])
    weighted_naive = np.average(sub["naive_mape"], weights=sub["test_n"])
    weighted_dir = np.average(sub["dir_acc"], weights=sub["test_n"])
    print(f"Horizon {h:>3}d: Model MAPE = {weighted_mape:.2f}%  |  "
          f"Naive MAPE = {weighted_naive:.2f}%  |  Direction Acc = {weighted_dir:.1f}%")

results.to_csv("multi_horizon_results.csv", index=False)
print("\nSaved full results to multi_horizon_results.csv")
