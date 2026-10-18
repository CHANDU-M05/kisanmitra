import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split, RandomizedSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from sklearn.metrics import mean_absolute_percentage_error, mean_absolute_error, mean_squared_error, r2_score
import joblib

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

def prepare_data_splits(df):
    df = df.copy()
    y = df[TARGET_COL].copy()
    dates = df["arrival_date"].copy()
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    valid = y.notna()
    df, y, dates = df[valid], y[valid], dates[valid]
    
    # Feature Set 2: Linear/Distance (One-Hot Encoded)
    df_linear = df.copy()
    X_linear = pd.get_dummies(df_linear[NUMERIC_COLS + CATEGORICAL_COLS], columns=CATEGORICAL_COLS, drop_first=True)
    
    # Stratified Split (80/20)
    indices = np.arange(len(df_linear))
    train_idx, test_idx = train_test_split(indices, test_size=0.20, random_state=42, stratify=df_linear["commodity"])
    
    X_linear_train = X_linear.iloc[train_idx]
    X_linear_test  = X_linear.iloc[test_idx]
    y_train = y.iloc[train_idx]
    y_test  = y.iloc[test_idx]
    
    return None, None, X_linear_train, X_linear_test, y_train, y_test

MODELS_DIR = Path(__file__).resolve().parents[1] / "data" / "models"

def main():
    print("="*50)
    print("Maximizing the Winning Model (SVR)")
    print("="*50)
    
    df = load_data()
    # We only need the linear splits (One-Hot Encoded) because SVR requires it
    _, _, X_train, X_test, y_train, y_test = prepare_data_splits(df)
    
    print("\nRunning Deep Hyperparameter Search for SVR (50 iterations)...")
    pipeline = Pipeline([
        ("scaler", StandardScaler()), 
        ("model", SVR())
    ])
    
    # Wider and deeper parameter grid based on Phase 1
    param_distributions = {
        "model__C": np.logspace(-1, 3, 20),      # 0.1 to 1000
        "model__epsilon": np.logspace(-3, 0, 10), # 0.001 to 1.0
        "model__kernel": ["rbf", "poly", "sigmoid"],
        "model__gamma": ["scale", "auto", 0.1, 0.01, 0.001]
    }
    
    search = RandomizedSearchCV(
        pipeline, 
        param_distributions, 
        n_iter=50, 
        cv=5, 
        scoring='neg_mean_absolute_percentage_error', 
        random_state=42, 
        n_jobs=-1
    )
    
    search.fit(X_train, y_train)
    
    best_model = search.best_estimator_
    print(f"\nBest Parameters Found: {search.best_params_}")
    
    y_pred = best_model.predict(X_test)
    mape = mean_absolute_percentage_error(y_test, y_pred) * 100
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    
    print("\n--- FINAL OPTIMIZED MODEL METRICS ---")
    print(f"MAPE: {mape:.2f}%")
    print(f"RMSE: Rs {rmse:.2f}")
    print(f"R²:   {r2:.4f}")
    
    # Save Model Artifacts
    print("\nSaving new maximized SVR model...")
    joblib.dump(best_model, MODELS_DIR / "price_model.pkl")
    
    meta = {
        "version":    "2.1.0",
        "commodity":  "All",
        "markets":    "Pan-Karnataka",
        "horizon":    "60 days",
        "algorithm":  "Support Vector Regression (SVR)",
        "features":   list(X_train.columns),
        "test_mape":  round(mape, 2),
        "test_r2":    round(r2, 4),
    }
    with open(MODELS_DIR / "model_metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    print("Metadata updated.")

if __name__ == "__main__":
    main()
