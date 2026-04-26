import pandas as pd
import numpy as np
import joblib
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error, r2_score, mean_absolute_error

BASE_DIR      = Path(__file__).parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
MODELS_DIR    = BASE_DIR / "data" / "models"

FEATURE_COLS = [
    "month", "month_sin", "month_cos",
    "season", "quarter",
    "modal_price",
    "price_7d_avg", "price_30d_avg",
    "price_7d_ago", "price_30d_ago",
    "price_trend_7d", "vs_seasonal",
    "seasonal_avg", "arrivals_tonnes",
    "arrivals_7d_avg",
]

TARGET_COL = "target_price_60d"

def load_data():
    path = PROCESSED_DIR / "tomato_model_data.csv"
    df   = pd.read_csv(path)
    df["arrival_date"] = pd.to_datetime(df["arrival_date"])
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"Loaded {len(df):,} rows")
    print(f"Date range: {df['arrival_date'].min().date()} to {df['arrival_date'].max().date()}")
    return df

def prepare_features(df):
    print("\nPreparing features...")
    available = [f for f in FEATURE_COLS if f in df.columns]
    X = df[available].copy()
    y = df[TARGET_COL].copy()
    dates = df["arrival_date"].copy()
    for col in X.columns:
        X[col] = X[col].fillna(X[col].median())
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
    fig.suptitle("KisanMitra — Price Prediction Results\nTomato, Kolar APMC", fontsize=13)
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

def save_model(model, features, test_mape, test_r2):
    print("\nSaving model...")
    model_path = MODELS_DIR / "price_model.pkl"
    joblib.dump(model, model_path)
    meta = {
        "version":    "1.0.0",
        "commodity":  "Tomato",
        "markets":    ["Kolar", "Chikkaballapur"],
        "horizon":    "60 days",
        "algorithm":  "RandomForestRegressor",
        "features":   features,
        "test_mape":  round(test_mape, 2),
        "test_r2":    round(test_r2, 4),
    }
    with open(MODELS_DIR / "model_metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    size = model_path.stat().st_size / 1024
    print(f"  Model saved: {model_path} ({size:.0f} KB)")
    print(f"  Metadata saved: {MODELS_DIR / 'model_metadata.json'}")

def main():
    print("="*50)
    print("KisanMitra - Model Training")
    print("="*50)
    df = load_data()
    X, y, dates, features = prepare_features(df)
    X_train, X_test, y_train, y_test, dates_test = split_data(X, y, dates)
    model = train(X_train, y_train)
    test_mape, test_r2, y_pred_test = evaluate(model, X_train, X_test, y_train, y_test)
    plot_results(y_test, y_pred_test, dates_test, model, features)
    save_model(model, features, test_mape, test_r2)
    print("\n" + "="*50)
    print("TRAINING COMPLETE")
    print("="*50)
    print(f"\nTest MAPE: {test_mape:.2f}%")
    print(f"Test R²:   {test_r2:.4f}")
    print("\nWhat to tell your guide:")
    print(f"'Our Random Forest model achieves {test_mape:.1f}% MAPE")
    print(f" on held-out test data, trained on {len(X_train):,}")
    print(f" historical price records from AGMARKNET.'")
    print("\nNext step: Phase 7 - FastAPI backend")

if __name__ == "__main__":
    main()
