import pandas as pd
import numpy as np
import joblib
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error, r2_score, mean_absolute_error
from sklearn.preprocessing import LabelEncoder
import asyncio
import sys

# Allow importing api modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete
from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.core.models import MandiPrice

BASE_DIR      = Path(__file__).parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
MODELS_DIR    = BASE_DIR / "data" / "models"

FEATURE_COLS = [
    "commodity_encoded", "market_encoded",
    "month", "month_sin", "month_cos",
    "season_encoded", "quarter",
    "modal_price",
    "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "days_since_last_report",
]

TARGET_COL = "target_price_60d"

def load_data():
    path = PROCESSED_DIR / "all_model_data.csv"
    df   = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"Loaded {len(df):,} rows")
    print(f"Date range: {df['arrival_date'].min().date()} to {df['arrival_date'].max().date()}")
    return df

def prepare_features(df):
    print("\nPreparing features...")
    
    # Encode categorical features
    commodity_encoder = LabelEncoder()
    market_encoder = LabelEncoder()
    season_encoder = LabelEncoder()
    
    df["commodity_encoded"] = commodity_encoder.fit_transform(df["commodity"])
    df["market_encoded"] = market_encoder.fit_transform(df["market"])
    df["season_encoded"] = season_encoder.fit_transform(df["season"].astype(str))
    
    # Save encoders for ml_service.py
    joblib.dump({
        "commodity": commodity_encoder,
        "market": market_encoder,
        "season": season_encoder,
    }, MODELS_DIR / "encoders.pkl")
    
    available = [f for f in FEATURE_COLS if f in df.columns]
    X = df[available].copy()
    y = df[TARGET_COL].copy()
    dates = df["arrival_date"].copy()
    valid = y.notna()
    X, y, dates = X[valid], y[valid], dates[valid]
    print(f"  Features: {len(available)}")
    print(f"  Rows: {len(X):,}")
    return X, y, dates, available

def split_data(X, y, dates):
    print("\nSplitting data...")
    cutoff = int(len(X) * 0.80)
    X_train = X.iloc[:cutoff]
    X_test  = X.iloc[cutoff:]
    y_train = y.iloc[:cutoff]
    y_test  = y.iloc[cutoff:]
    dates_test = dates.iloc[cutoff:]
    print(f"  Train: {len(X_train):,} rows")
    print(f"  Test:  {len(X_test):,} rows")
    return X_train, X_test, y_train, y_test, dates_test

def train(X_train, y_train):
    print("\nTraining Random Forest...")
    print("  200 trees being built — please wait...")
    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=12,
        min_samples_split=10,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1,
        oob_score=True,
    )
    model.fit(X_train, y_train)
    print(f"  Training done!")
    print(f"  OOB Score: {model.oob_score_:.4f}")
    return model

def evaluate(model, X_train, X_test, y_train, y_test):
    print("\nEvaluating model...")
    y_pred_train = model.predict(X_train)
    y_pred_test  = model.predict(X_test)
    train_mape = mean_absolute_percentage_error(y_train, y_pred_train) * 100
    test_mape  = mean_absolute_percentage_error(y_test,  y_pred_test)  * 100
    train_r2   = r2_score(y_train, y_pred_train)
    test_r2    = r2_score(y_test,  y_pred_test)
    test_mae   = mean_absolute_error(y_test, y_pred_test)
    print("\n  ┌─────────────────────────────────┐")
    print("  │      MODEL RESULTS              │")
    print("  ├──────────────────┬──────────────┤")
    print(f"  │ Train MAPE       │ {train_mape:>8.2f}%   │")
    print(f"  │ Test  MAPE       │ {test_mape:>8.2f}%   │")
    print(f"  │ Train R²         │ {train_r2:>10.4f} │")
    print(f"  │ Test  R²         │ {test_r2:>10.4f} │")
    print(f"  │ Test  MAE        │ Rs {test_mae:>7.0f}   │")
    print("  └──────────────────┴──────────────┘")
    if test_mape < 15:
        print("\n  Grade: EXCELLENT")
    elif test_mape < 21:
        print("\n  Grade: GOOD — beats ARIMA baseline of 21%")
    else:
        print("\n  Grade: NEEDS MORE DATA")
    return test_mape, test_r2, y_pred_test

def plot_results(y_test, y_pred_test, dates_test, model, features):
    print("\nSaving evaluation chart...")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("KisanMitra — Pan-Karnataka Price Prediction Results", fontsize=13)
    ax = axes[0]
    ax.plot(dates_test.values, y_test.values,
            label="Actual", color="#40916C", linewidth=2)
    ax.plot(dates_test.values, y_pred_test,
            label="Predicted", color="#E9C46A", linewidth=2, linestyle="--")
    ax.set_title("Actual vs Predicted Price (60-day horizon)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price (Rs/quintal)")
    ax.legend()
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, alpha=0.3)
    ax = axes[1]
    importance = pd.Series(model.feature_importances_, index=features)
    importance.nlargest(10).sort_values().plot(
        kind="barh", ax=ax, color="#2D6A4F"
    )
    ax.set_title("Top 10 Important Features")
    ax.set_xlabel("Importance Score")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    path = MODELS_DIR / "model_evaluation.png"
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved to {path}")

def save_model(model, features, test_mape, test_r2, crop_mapes):
    print("\nSaving model...")
    model_path = MODELS_DIR / "price_model.pkl"
    meta_path  = MODELS_DIR / "model_metadata.json"

    # Backup existing model if both model and metadata exist
    if model_path.exists() and meta_path.exists():
        try:
            with open(meta_path) as f:
                old_meta = json.load(f)
                old_ver  = old_meta.get("version", "unknown")
            backup_path = MODELS_DIR / f"price_model_v{old_ver}.pkl"
            import shutil
            shutil.copyfile(model_path, backup_path)
            print(f"  Backup created: {backup_path}")
        except Exception as e:
            print(f"  Backup warning: {e}")

    joblib.dump(model, model_path)
    meta = {
        "version":    "2.0.0",
        "commodity":  "All",
        "markets":    "Pan-Karnataka",
        "horizon":    "60 days",
        "algorithm":  "RandomForestRegressor",
        "features":   features,
        "test_mape":  round(test_mape, 2),
        "test_r2":    round(test_r2, 4),
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
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    size = model_path.stat().st_size / 1024
    print(f"  Model saved: {model_path} ({size:.0f} KB)")
    print(f"  Metadata saved: {meta_path}")


async def async_save_prices(df):
    print("\nClearing old prices from PostgreSQL database...")
    count = 0
    async with AsyncSessionLocal() as session:
        await session.execute(delete(MandiPrice))
        await session.commit()
        
        print("Saving new prices to PostgreSQL database...")
        for _, row in df.iterrows():
            price = MandiPrice(
                state="Karnataka",
                district=row.get("district", row.get("market", "")),
                market=row.get("market", ""),
                commodity=row.get("commodity", "Tomato"),
                arrival_date=row["arrival_date"].to_pydatetime(),
                min_price=row.get("min_price"),
                max_price=row.get("max_price"),
                modal_price=row.get("modal_price"),
                arrivals_tonnes=row.get("arrivals_tonnes"),
            )
            session.add(price)
            count += 1
        
        await session.commit()
    print(f"  Inserted {count:,} records into mandi_prices table")

def save_prices_to_db():
    """Upsert cleaned CSV data into the mandi_prices table."""
    csv_path = PROCESSED_DIR / "all_model_data.csv"
    df = pd.read_csv(csv_path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    
    asyncio.run(async_save_prices(df))

def main():
    print("="*50)
    print("KisanMitra - Model Training")
    print("="*50)
    df = load_data()
    X, y, dates, features = prepare_features(df)
    X_train, X_test, y_train, y_test, dates_test = split_data(X, y, dates)
    
    # Impute missing values using train split medians only (no look-ahead leak)
    for col in X_train.columns:
        if pd.api.types.is_numeric_dtype(X_train[col]):
            train_median = X_train[col].median()
            X_train[col] = X_train[col].fillna(train_median)
            X_test[col]  = X_test[col].fillna(train_median)

    model = train(X_train, y_train)
    test_mape, test_r2, y_pred_test = evaluate(model, X_train, X_test, y_train, y_test)
    
    # Calculate per-crop MAPE on the test split
    crop_mapes = {}
    test_df_original = df.loc[X_test.index]
    for crop in test_df_original["commodity"].unique():
        crop_mask = test_df_original["commodity"] == crop
        crop_y_test = y_test[crop_mask]
        crop_X_test = X_test[crop_mask]
        if len(crop_y_test) > 0:
            crop_pred = model.predict(crop_X_test)
            crop_mape = mean_absolute_percentage_error(crop_y_test, crop_pred) * 100
            crop_mapes[crop.strip().title()] = round(float(crop_mape), 2)
            
    plot_results(y_test, y_pred_test, dates_test, model, features)
    save_model(model, features, test_mape, test_r2, crop_mapes)
    try:
        save_prices_to_db()
    except Exception as e:
        print(f"\n[NOTE] Database save skipped: {e}")

    print("\n" + "="*50)
    print("TRAINING COMPLETE")
    print("="*50)
    print(f"\nTest MAPE: {test_mape:.2f}%")
    print(f"Test R²:   {test_r2:.4f}")

if __name__ == "__main__":
    main()

