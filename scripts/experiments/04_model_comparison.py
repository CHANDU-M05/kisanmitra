import os
import sys
import time
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from sklearn.model_selection import train_test_split, RandomizedSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder, LabelEncoder
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_percentage_error, mean_absolute_error, mean_squared_error, r2_score

from sklearn.linear_model import LinearRegression, Ridge
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.svm import SVR
from sklearn.neighbors import KNeighborsRegressor

TARGET_COL = "target_price_60d"

def load_data():
    path = PROCESSED_DIR / "all_model_data.csv"
    df   = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

BASE_DIR      = Path(__file__).parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RESULTS_DIR   = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# Shared non-categorical features
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

def prepare_data_splits(df):
    print("Preparing features...")
    df = df.copy()
    
    # Target and dates
    y = df[TARGET_COL].copy()
    dates = df["arrival_date"].copy()
    
    # Fill NAs for numeric cols
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
            
    # Valid targets only
    valid = y.notna()
    df, y, dates = df[valid], y[valid], dates[valid]
    
    # --- Feature Set 1: Trees (Ordinal Encoded) ---
    df_trees = df.copy()
    le_comm = LabelEncoder()
    le_mkt = LabelEncoder()
    df_trees["commodity_encoded"] = le_comm.fit_transform(df_trees["commodity"])
    df_trees["market_encoded"] = le_mkt.fit_transform(df_trees["market"])
    X_trees = df_trees[NUMERIC_COLS + ["commodity_encoded", "market_encoded"]]
    
    # --- Feature Set 2: Linear/Distance (One-Hot Encoded) ---
    df_linear = df.copy()
    X_linear = pd.get_dummies(df_linear[NUMERIC_COLS + CATEGORICAL_COLS], columns=CATEGORICAL_COLS, drop_first=True)
    
    # Stratified Split (80/20)
    indices = np.arange(len(df_trees))
    train_idx, test_idx = train_test_split(indices, test_size=0.20, random_state=42, stratify=df_trees["commodity"])
    
    X_trees_train = X_trees.iloc[train_idx]
    X_trees_test  = X_trees.iloc[test_idx]
    
    X_linear_train = X_linear.iloc[train_idx]
    X_linear_test  = X_linear.iloc[test_idx]
    
    y_train = y.iloc[train_idx]
    y_test  = y.iloc[test_idx]
    
    print(f"Train rows: {len(y_train)}, Test rows: {len(y_test)}")
    
    # Verify stratification
    train_crops = df_trees.iloc[train_idx]["commodity"].value_counts()
    test_crops = df_trees.iloc[test_idx]["commodity"].value_counts()
    print("\n--- Stratification Check ---")
    print("Train set crop counts:")
    print(train_crops)
    print("Test set crop counts:")
    print(test_crops)
    print("----------------------------\n")
    
    return X_trees_train, X_trees_test, X_linear_train, X_linear_test, y_train, y_test

def build_models():
    # Model configs: (Estimator, Params, Needs_Linear_Features)
    # Using Pipeline with StandardScaler for linear/distance models to avoid data leakage
    return {
        "Linear Regression": (
            Pipeline([("scaler", StandardScaler()), ("model", LinearRegression())]),
            {}, 
            True
        ),
        "Ridge Regression": (
            Pipeline([("scaler", StandardScaler()), ("model", Ridge(random_state=42))]),
            {"model__alpha": [0.1, 1.0, 10.0, 100.0, 1000.0]},
            True
        ),
        "SVR": (
            Pipeline([("scaler", StandardScaler()), ("model", SVR())]),
            {"model__C": [0.1, 1, 10, 100], "model__epsilon": [0.01, 0.1, 1], "model__kernel": ["rbf", "linear"]},
            True
        ),
        "KNN Regressor": (
            Pipeline([("scaler", StandardScaler()), ("model", KNeighborsRegressor())]),
            {"model__n_neighbors": [3, 5, 10, 20], "model__weights": ["uniform", "distance"]},
            True
        ),
        "Decision Tree": (
            DecisionTreeRegressor(random_state=42),
            {"max_depth": [5, 10, 15, 20, None], "min_samples_split": [2, 5, 10], "min_samples_leaf": [1, 2, 5]},
            False
        ),
        "Random Forest": (
            RandomForestRegressor(random_state=42, n_jobs=-1),
            {"n_estimators": [50, 100, 200], "max_depth": [10, 15, 20, None], "min_samples_split": [2, 5, 10], "min_samples_leaf": [1, 2, 5], "max_features": ["sqrt", "log2", None]},
            False
        ),
        "Gradient Boosting": (
            GradientBoostingRegressor(random_state=42),
            {"n_estimators": [50, 100, 200], "learning_rate": [0.01, 0.05, 0.1], "max_depth": [3, 5, 7, 10]},
            False
        )
    }

def main():
    print("="*50)
    print("KisanMitra - Fair Multi-Algorithm Comparison")
    print("="*50)
    
    df = load_data()
    X_trees_train, X_trees_test, X_linear_train, X_linear_test, y_train, y_test = prepare_data_splits(df)
    
    models = build_models()
    results = []
    
    for name, (estimator, params, is_linear) in models.items():
        print(f"\nTraining {name}...")
        X_tr = X_linear_train if is_linear else X_trees_train
        X_te = X_linear_test if is_linear else X_trees_test
        
        start_time = time.time()
        
        # Grid search logic
        if params:
            search = RandomizedSearchCV(
                estimator, params, n_iter=20, cv=5, 
                scoring='neg_mean_absolute_percentage_error', 
                random_state=42, n_jobs=-1
            )
            search.fit(X_tr, y_train)
            best_model = search.best_estimator_
            best_params = search.best_params_
            cv_std = search.cv_results_['std_test_score'][search.best_index_] * 100  # Convert to % for MAPE
        else:
            best_model = estimator.fit(X_tr, y_train)
            best_params = {}
            cv_std = 0.0
            
        train_time = time.time() - start_time
        
        # Evaluate
        y_pred = best_model.predict(X_te)
        mape = mean_absolute_percentage_error(y_test, y_pred) * 100
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        results.append({
            "Model": name,
            "MAPE (%)": round(mape, 2),
            "RMSE (Rs)": round(rmse, 2),
            "MAE (Rs)": round(mae, 2),
            "R2 Score": round(r2, 4),
            "CV Std (%)": round(cv_std, 2),
            "Time (s)": round(train_time, 1),
            "Best Params": json.dumps(best_params)
        })
        print(f"  --> MAPE: {mape:.2f}% | Time: {train_time:.1f}s")
        
    results_df = pd.DataFrame(results).sort_values("MAPE (%)")
    print("\n" + "="*70)
    print("FINAL COMPARISON RESULTS")
    print("="*70)
    print(results_df[["Model", "MAPE (%)", "RMSE (Rs)", "R2 Score", "CV Std (%)", "Time (s)"]].to_string(index=False))
    
    # Save CSV
    csv_path = RESULTS_DIR / "model_comparison.csv"
    results_df.to_csv(csv_path, index=False)
    print(f"\nSaved CSV to {csv_path}")
    
    # Plot Chart
    plt.figure(figsize=(10, 6))
    bars = plt.barh(results_df["Model"], results_df["MAPE (%)"], color="#2D6A4F")
    plt.xlabel("Test MAPE (%) - Lower is Better")
    plt.title("KisanMitra Model Comparison (MAPE)")
    plt.grid(axis='x', alpha=0.3)
    for bar in bars:
        plt.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2, 
                 f'{bar.get_width():.2f}%', va='center')
    plt.tight_layout()
    chart_path = RESULTS_DIR / "model_comparison_chart.png"
    plt.savefig(chart_path, dpi=150)
    plt.close()
    print(f"Saved Chart to {chart_path}")

if __name__ == "__main__":
    main()
