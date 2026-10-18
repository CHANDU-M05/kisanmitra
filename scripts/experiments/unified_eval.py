"""
unified_eval.py — single source of truth for old vs. new model comparison.
Run this top to bottom. Old and new models are trained on the SAME loaded
dataframe in the SAME run, so the baseline cannot drift between comparisons.
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.preprocessing import LabelEncoder

DATA_PATH = "data/processed/karnataka_clean.csv"

MSP = {
    "Maize": 2400.0,
    "Ragi":  4886.0,
}

# ---------------------------------------------------------------------
# 1. Load once. Print shape immediately so nothing drifts silently.
# ---------------------------------------------------------------------
df = pd.read_csv(DATA_PATH)
df["arrival_date"] = pd.to_datetime(df["arrival_date"])
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

print(f"Loaded rows: {len(df):,}")
print(f"Date range:  {df['arrival_date'].min().date()} -> {df['arrival_date'].max().date()}")
print(f"Markets:     {sorted(df['market'].unique())}")
print(f"Commodities: {sorted(df['commodity'].unique())}")
print()

# ---------------------------------------------------------------------
# 2. Feature engineering — ONE pass, both old and new features built here
#    from the same sort order, so no divergence between runs.
# ---------------------------------------------------------------------
df.sort_values(["market", "commodity", "arrival_date"], inplace=True)
df.reset_index(drop=True, inplace=True)
g = df.groupby(["market", "commodity"])["modal_price"]

df["price_7d_avg"]  = g.transform(lambda x: x.shift(1).rolling(7,  min_periods=3).mean())
df["price_30d_avg"] = g.transform(lambda x: x.shift(1).rolling(30, min_periods=10).mean())
df["price_7d_ago"]  = g.transform(lambda x: x.shift(7))
df["price_30d_ago"] = g.transform(lambda x: x.shift(30))
df["price_trend_7d"] = (df["modal_price"] - df["price_7d_ago"]) / df["price_7d_ago"].replace(0, np.nan)

df["price_14d_ago"] = g.transform(lambda x: x.shift(14))
df["price_45d_ago"] = g.transform(lambda x: x.shift(45))
df["price_60d_ago"] = g.transform(lambda x: x.shift(60))
df["price_30d_std"] = g.transform(lambda x: x.shift(1).rolling(30, min_periods=7).std())
df["price_yoy"]     = g.transform(lambda x: x.shift(364))

# month/year/quarter/season
df["month"] = df["arrival_date"].dt.month
df["year"] = df["arrival_date"].dt.year
df["quarter"] = df["arrival_date"].dt.quarter
df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

def get_season(m):
    if m in [6,7,8,9,10,11]: return 0
    elif m in [12,1,2,3]: return 1
    else: return 2
df["season"] = df["month"].apply(get_season)

monthly_means = df.groupby(["market", "commodity", "year", "month"])["modal_price"].mean().reset_index()
monthly_means.sort_values("year", inplace=True)
monthly_means["seasonal_avg"] = monthly_means.groupby(["market", "commodity", "month"])["modal_price"].transform(
    lambda x: x.shift(1).expanding().mean()
)
if "seasonal_avg" in df.columns:
    df.drop(columns=["seasonal_avg"], inplace=True)
df = df.merge(monthly_means[["market", "commodity", "year", "month", "seasonal_avg"]],
              on=["market", "commodity", "year", "month"], how="left")
df["seasonal_avg"] = df["seasonal_avg"].fillna(df["price_30d_avg"]).fillna(df["modal_price"])
df["vs_seasonal"]  = df["modal_price"] / df["seasonal_avg"].replace(0, np.nan)
df["arrivals_7d_avg"] = df.groupby(["market","commodity"])["arrivals_tonnes"].transform(
    lambda x: x.shift(1).rolling(7, min_periods=3).mean()
)

df["msp_ratio"] = df.apply(
    lambda r: (r["modal_price"] - MSP[r["commodity"]]) / MSP[r["commodity"]] if r["commodity"] in MSP else np.nan,
    axis=1
)

df["commodity_encoded"] = LabelEncoder().fit_transform(df["commodity"])
df["market_encoded"] = LabelEncoder().fit_transform(df["market"])

# Target: production definition (positional shift, NOT calendar-date lookup)
df["target_price_60d"] = df.groupby(["market", "commodity"])["modal_price"].transform(lambda x: x.shift(-60))

# Re-sort chronologically for the split (critical — do this LAST)
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

print(f"Rows after feature engineering (before dropna on target): {len(df):,}")

# ---------------------------------------------------------------------
# 3. Feature sets
# ---------------------------------------------------------------------
OLD_FEATURES = [
    "commodity_encoded", "market_encoded", "month", "month_sin", "month_cos",
    "season", "quarter", "modal_price",
    "price_7d_avg", "price_30d_avg", "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal", "seasonal_avg",
    "arrivals_tonnes", "arrivals_7d_avg",
]
NEW_FEATURES = OLD_FEATURES + [
    "price_14d_ago", "price_45d_ago", "price_60d_ago",
    "price_30d_std", "price_yoy", "msp_ratio",
]

TARGET = "target_price_60d"
valid = df[TARGET].notna()
df_valid = df[valid].copy()
print(f"Rows with valid target: {len(df_valid):,}\n")

# ---------------------------------------------------------------------
# 4. Single chronological 80/20 split, used for BOTH models
# ---------------------------------------------------------------------
cutoff = int(len(df_valid) * 0.80)
train_df = df_valid.iloc[:cutoff]
test_df  = df_valid.iloc[cutoff:]
print(f"Train: {train_df['arrival_date'].min().date()} -> {train_df['arrival_date'].max().date()} ({len(train_df):,} rows)")
print(f"Test:  {test_df['arrival_date'].min().date()} -> {test_df['arrival_date'].max().date()} ({len(test_df):,} rows)\n")

def impute(train, test, cols):
    train, test = train.copy(), test.copy()
    for c in cols:
        med = train[c].median()
        train[c] = train[c].fillna(med)
        test[c] = test[c].fillna(med)
    return train, test

# ---------------------------------------------------------------------
# 5. Train + evaluate BOTH models, overall and per crop
# ---------------------------------------------------------------------
results = []
for crop in sorted(df_valid["commodity"].unique()):
    tr = train_df[train_df["commodity"] == crop]
    te = test_df[test_df["commodity"] == crop]
    if len(tr) < 30 or len(te) < 10:
        print(f"Skipping {crop}: insufficient rows (train={len(tr)}, test={len(te)})")
        continue

    tr_old, te_old = impute(tr, te, OLD_FEATURES)
    m_old = HistGradientBoostingRegressor(random_state=42).fit(tr_old[OLD_FEATURES], tr_old[TARGET])
    pred_old = m_old.predict(te_old[OLD_FEATURES])
    mape_old = mean_absolute_percentage_error(te_old[TARGET], pred_old) * 100

    tr_new, te_new = impute(tr, te, NEW_FEATURES)
    m_new = HistGradientBoostingRegressor(random_state=42).fit(tr_new[NEW_FEATURES], tr_new[TARGET])
    pred_new = m_new.predict(te_new[NEW_FEATURES])
    mape_new = mean_absolute_percentage_error(te_new[TARGET], pred_new) * 100

    results.append((crop, len(tr), len(te), mape_old, mape_new, mape_old - mape_new))

print(f"{'Crop':<12}{'Train N':>9}{'Test N':>8}{'Old MAPE':>11}{'New MAPE':>11}{'Improve':>10}")
print("-" * 61)
for crop, ntr, nte, mo, mn, imp in results:
    print(f"{crop:<12}{ntr:>9}{nte:>8}{mo:>10.2f}%{mn:>10.2f}%{imp:>+9.2f}%")

# Compute overall MAPE across all crops
all_te_old = impute(train_df, test_df, OLD_FEATURES)[1]
all_te_new = impute(train_df, test_df, NEW_FEATURES)[1]
m_old_all = HistGradientBoostingRegressor(random_state=42).fit(impute(train_df, test_df, OLD_FEATURES)[0][OLD_FEATURES], train_df[TARGET])
m_new_all = HistGradientBoostingRegressor(random_state=42).fit(impute(train_df, test_df, NEW_FEATURES)[0][NEW_FEATURES], train_df[TARGET])
ov_old = mean_absolute_percentage_error(test_df[TARGET], m_old_all.predict(all_te_old[OLD_FEATURES])) * 100
ov_new = mean_absolute_percentage_error(test_df[TARGET], m_new_all.predict(all_te_new[NEW_FEATURES])) * 100
print("-" * 61)
print(f"{'OVERALL':<12}{len(train_df):>9}{len(test_df):>8}{ov_old:>10.2f}%{ov_new:>10.2f}%{ov_old - ov_new:>+9.2f}%")
