import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error, mean_squared_error, r2_score
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
MODELS_DIR = Path(__file__).resolve().parents[1] / "data" / "models"
PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

def load_data():
    path = PROCESSED_DIR / "all_model_data.csv"
    df   = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

def main():
    print("="*50)
    print("Reverting Production Model to Random Forest")
    print("="*50)
    
    df = load_data()
    y = df[TARGET_COL].copy()
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    valid = y.notna()
    df, y = df[valid], y[valid]
    
    from sklearn.preprocessing import LabelEncoder
    df_trees = df.copy()
    le_comm = LabelEncoder()
    le_mkt = LabelEncoder()
    df_trees["commodity_encoded"] = le_comm.fit_transform(df_trees["commodity"])
    df_trees["market_encoded"] = le_mkt.fit_transform(df_trees["market"])
    X_trees = df_trees[NUMERIC_COLS + ["commodity_encoded", "market_encoded"]]
    
    indices = np.arange(len(df_trees))
    train_idx, test_idx = train_test_split(indices, test_size=0.20, random_state=42, stratify=df_trees["commodity"])
    
    X_train = X_trees.iloc[train_idx]
    X_test  = X_trees.iloc[test_idx]
    y_train = y.iloc[train_idx]
    y_test  = y.iloc[test_idx]
    
    print("Training Random Forest with best params...")
    best_params = {"n_estimators": 200, "min_samples_split": 10, "min_samples_leaf": 2, "max_features": "sqrt", "max_depth": 20}
    rf_model = RandomForestRegressor(
        **best_params, random_state=42, n_jobs=-1
    )
    
    rf_model.fit(X_train, y_train)
    y_pred = rf_model.predict(X_test)
    
    mape = mean_absolute_percentage_error(y_test, y_pred) * 100
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)
    
    # Calculate per-crop MAPE on the test split
    crop_mapes = {}
    test_df_original = df.iloc[test_idx]
    for crop in test_df_original["commodity"].unique():
        crop_mask = test_df_original["commodity"] == crop
        crop_y_test = y_test[crop_mask]
        crop_X_test = X_test[crop_mask]
        if len(crop_y_test) > 0:
            crop_pred = rf_model.predict(crop_X_test)
            crop_mape = mean_absolute_percentage_error(crop_y_test, crop_pred) * 100
            crop_mapes[crop.strip().title()] = round(float(crop_mape), 2)
            
    print("\n--- PRODUCTION RANDOM FOREST METRICS ---")
    print(f"MAPE: {mape:.2f}%")
    print(f"RMSE: Rs {rmse:.2f}")
    print(f"R²:   {r2:.4f}")
    
    print("\nSaving Random Forest model to production...")
    joblib.dump(rf_model, MODELS_DIR / "price_model.pkl")
    joblib.dump(le_comm, MODELS_DIR / "commodity_encoder.pkl")
    joblib.dump(le_mkt, MODELS_DIR / "market_encoder.pkl")
    
    meta = {
        "version":    "2.1.0",
        "commodity":  "All",
        "markets":    "Pan-Karnataka",
        "horizon":    "60 days",
        "algorithm":  "Random Forest Regressor",
        "features":   list(X_train.columns),
        "test_mape":  round(mape, 2),
        "test_r2":    round(r2, 4),
        "crop_mape":  crop_mapes,
        "crop_msp":   {
            "Maize":    2400.0,
            "Ragi":     4886.0,
            "Brinjal":  None,
            "Potato":   None,
            "Tomato":   None,
            "Onion":    None,
            "Marigold": None
        }
    }
    with open(MODELS_DIR / "model_metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    print("Metadata updated to Random Forest.")

if __name__ == "__main__":
    main()
