"""
per_crop_eval.py — selects the best feature set per crop, using a proper
train/validation/test split so feature selection doesn't leak into the
reported test score. Builds on the same feature engineering as unified_eval.py.
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.preprocessing import LabelEncoder

DATA_PATH = "data/processed/clean_agmarknet_prices.csv"

MSP = {
    "Maize": 2400.0,
    "Ragi":  4886.0,
}

# ---------------------------------------------------------------------
# 1. Load + feature engineering (identical to unified_eval.py)
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
if "arrivals_tonnes" not in df.columns:
    df["arrivals_tonnes"] = 0.0

df["arrivals_7d_avg"] = df.groupby(["market","commodity"])["arrivals_tonnes"].transform(
    lambda x: x.shift(1).rolling(7, min_periods=3).mean()
)
df["msp_ratio"] = df.apply(
    lambda r: (r["modal_price"] - MSP[r["commodity"]]) / MSP[r["commodity"]] if r["commodity"] in MSP else np.nan,
    axis=1
)
df["commodity_encoded"] = LabelEncoder().fit_transform(df["commodity"])
df["market_encoded"] = LabelEncoder().fit_transform(df["market"])
df["target_price_60d"] = df.groupby(["market", "commodity"])["modal_price"].transform(lambda x: x.shift(-60))

df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

OLD_FEATURES = [
    "commodity_encoded", "market_encoded", "month", "month_sin", "month_cos",
    "season", "quarter", "modal_price",
    "price_7d_avg", "price_30d_avg", "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal", "seasonal_avg",
    "arrivals_tonnes", "arrivals_7d_avg",
]
EXTRA_FEATURES = ["price_14d_ago", "price_45d_ago", "price_60d_ago",
                   "price_30d_std", "price_yoy", "msp_ratio"]
NEW_FEATURES = OLD_FEATURES + EXTRA_FEATURES

TARGET = "target_price_60d"
df_valid = df[df[TARGET].notna()].copy()
print(f"Rows with valid target: {len(df_valid):,}")

# ---------------------------------------------------------------------
# 2. THREE-WAY chronological split: 60% train / 20% validation / 20% test.
#    Validation picks the feature set; test reports the final, honest score.
# ---------------------------------------------------------------------
n = len(df_valid)
c1, c2 = int(n * 0.60), int(n * 0.80)
train_df = df_valid.iloc[:c1]
val_df   = df_valid.iloc[c1:c2]
test_df  = df_valid.iloc[c2:]

print(f"Train: {train_df['arrival_date'].min().date()} -> {train_df['arrival_date'].max().date()} ({len(train_df):,})")
print(f"Val:   {val_df['arrival_date'].min().date()} -> {val_df['arrival_date'].max().date()} ({len(val_df):,})")
print(f"Test:  {test_df['arrival_date'].min().date()} -> {test_df['arrival_date'].max().date()} ({len(test_df):,})\n")

def impute(train, other, cols):
    train, other = train.copy(), other.copy()
    for c in cols:
        med = train[c].median()
        train[c] = train[c].fillna(med)
        other[c] = other[c].fillna(med)
    return train, other

def score(train, evalset, features):
    tr, ev = impute(train, evalset, features)
    m = HistGradientBoostingRegressor(random_state=42).fit(tr[features], tr[TARGET])
    pred = m.predict(ev[features])
    return mean_absolute_percentage_error(ev[TARGET], pred) * 100, m

# ---------------------------------------------------------------------
# 3. Per crop: pick OLD or NEW features using validation MAPE only,
#    then report the honest score on the untouched test set.
# ---------------------------------------------------------------------
results = []
for crop in sorted(df_valid["commodity"].unique()):
    tr = train_df[train_df["commodity"] == crop]
    va = val_df[val_df["commodity"] == crop]
    te = test_df[test_df["commodity"] == crop]
    if len(tr) < 30 or len(va) < 10 or len(te) < 10:
        print(f"Skipping {crop}: insufficient rows")
        continue

    val_mape_old, _ = score(tr, va, OLD_FEATURES)
    val_mape_new, _ = score(tr, va, NEW_FEATURES)
    chosen = NEW_FEATURES if val_mape_new < val_mape_old else OLD_FEATURES
    chosen_name = "NEW" if chosen is NEW_FEATURES else "OLD"

    # Retrain on train+val combined with the chosen feature set, report on test
    trainval = pd.concat([tr, va])
    test_mape_chosen, _ = score(trainval, te, chosen)
    test_mape_old, _ = score(trainval, te, OLD_FEATURES)  # always-old baseline for comparison

    results.append((crop, chosen_name, len(tr)+len(va), len(te), test_mape_old, test_mape_chosen))

print(f"{'Crop':<12}{'Picked':<8}{'TrainN':>8}{'TestN':>7}{'OldMAPE':>10}{'ChosenMAPE':>12}{'Improve':>10}")
print("-" * 67)
for crop, chosen_name, ntr, nte, mo, mc in results:
    print(f"{crop:<12}{chosen_name:<8}{ntr:>8}{nte:>7}{mo:>9.2f}%{mc:>11.2f}%{mo-mc:>+9.2f}%")

# Compute overall MAPE across all crops
all_trval = pd.concat([train_df, val_df])
all_old_test_mape, _ = score(all_trval, test_df, OLD_FEATURES)

# Score chosen predictions across all crops
chosen_preds = []
test_targets = []
for crop, chosen_name, ntr, nte, mo, mc in results:
    tr = all_trval[all_trval["commodity"] == crop]
    te = test_df[test_df["commodity"] == crop]
    feats = NEW_FEATURES if chosen_name == "NEW" else OLD_FEATURES
    tr_imp, te_imp = impute(tr, te, feats)
    m = HistGradientBoostingRegressor(random_state=42).fit(tr_imp[feats], tr_imp[TARGET])
    p = m.predict(te_imp[feats])
    chosen_preds.extend(p)
    test_targets.extend(te[TARGET].values)

overall_chosen_mape = mean_absolute_percentage_error(test_targets, chosen_preds) * 100
print("-" * 67)
print(f"{'OVERALL':<12}{'HYBRID':<8}{len(all_trval):>8}{len(test_df):>7}{all_old_test_mape:>9.2f}%{overall_chosen_mape:>11.2f}%{all_old_test_mape - overall_chosen_mape:>+9.2f}%")
