import sys
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import KFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from sklearn.ensemble import RandomForestRegressor
from scipy import stats

TARGET_COL = "target_price_60d"
NUMERIC_COLS = [
    "month", "month_sin", "month_cos",
    "season", "quarter",
    "modal_price",
    "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "arrivals_tonnes",
    "arrivals_7d_avg",
]
CATEGORICAL_COLS = ["commodity", "market"]

def load_data():
    PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
    path = PROCESSED_DIR / "all_model_data.csv"
    df   = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

def get_splits(df):
    df = df.copy()
    y = df[TARGET_COL].copy()
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    valid = y.notna()
    df, y = df[valid], y[valid]
    
    # Linear features (SVR)
    df_linear = df.copy()
    X_linear = pd.get_dummies(df_linear[NUMERIC_COLS + CATEGORICAL_COLS], columns=CATEGORICAL_COLS, drop_first=True)
    
    # Tree features (RF)
    from sklearn.preprocessing import LabelEncoder
    df_trees = df.copy()
    le_comm = LabelEncoder()
    le_mkt = LabelEncoder()
    df_trees["commodity_encoded"] = le_comm.fit_transform(df_trees["commodity"])
    df_trees["market_encoded"] = le_mkt.fit_transform(df_trees["market"])
    X_trees = df_trees[NUMERIC_COLS + ["commodity_encoded", "market_encoded"]]
    
    return X_linear, X_trees, y

def main():
    print("Loading data...")
    df = load_data()
    X_linear, X_trees, y = get_splits(df)
    
    # Use the same KFold for both
    cv = KFold(n_splits=5, shuffle=True, random_state=42)
    
    svr_model = Pipeline([
        ("scaler", StandardScaler()), 
        ("model", SVR(kernel='rbf', gamma='scale', epsilon=0.01, C=1000.0)) # max tuned params
    ])
    
    rf_model = RandomForestRegressor(
        n_estimators=200, min_samples_split=10, min_samples_leaf=2, 
        max_features="sqrt", max_depth=20, random_state=42, n_jobs=-1
    )
    
    print("Evaluating SVR...")
    svr_scores = cross_val_score(svr_model, X_linear, y, cv=cv, scoring='neg_mean_absolute_percentage_error', n_jobs=-1)
    svr_mape = -svr_scores * 100
    
    print("Evaluating Random Forest...")
    rf_scores = cross_val_score(rf_model, X_trees, y, cv=cv, scoring='neg_mean_absolute_percentage_error', n_jobs=-1)
    rf_mape = -rf_scores * 100
    
    print(f"SVR fold MAPEs: {svr_mape}")
    print(f"RF fold MAPEs:  {rf_mape}")
    
    # Paired t-test
    t_stat, p_val_ttest = stats.ttest_rel(svr_mape, rf_mape)
    # Wilcoxon signed-rank test
    w_stat, p_val_wilcoxon = stats.wilcoxon(svr_mape, rf_mape)
    
    print("\n--- Significance Test Results ---")
    print(f"Paired t-test p-value: {p_val_ttest:.4f}")
    print(f"Wilcoxon p-value:      {p_val_wilcoxon:.4f}")
    
if __name__ == "__main__":
    main()
