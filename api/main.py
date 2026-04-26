import sys
import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date, datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

BASE_DIR   = Path(__file__).parent.parent
MODELS_DIR = BASE_DIR / "data" / "models"

# ── Load model at startup ─────────────────────────────────
MODEL    = None
FEATURES = []

def load_model():
    global MODEL, FEATURES
    try:
        MODEL = joblib.load(MODELS_DIR / "price_model.pkl")
        with open(MODELS_DIR / "model_metadata.json") as f:
            meta     = json.load(f)
            FEATURES = meta["features"]
        print(f"Model loaded. Features: {len(FEATURES)}")
    except Exception as e:
        print(f"Model not loaded: {e}")

load_model()

# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="KisanMitra API",
    description="Smart Crop Planning for Karnataka Farmers",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In memory store for declarations ─────────────────────
# Replace with database in production
DECLARATIONS = []

# ── Historical averages from NHB data ────────────────────
HISTORICAL_AREA = {
    "chikkaballapur": {
        "tomato":   15000,
        "marigold": 8000,
        "capsicum": 5000,
    },
    "kolar": {
        "tomato":  12000,
        "potato":  6000,
        "onion":   4000,
    },
}

# ── Schemas ───────────────────────────────────────────────
class PriceRequest(BaseModel):
    commodity:       str
    market:          str
    current_price:   float
    arrivals_tonnes: Optional[float] = 100.0

class DeclareRequest(BaseModel):
    farmer_name:  str
    phone:        str
    village:      str
    district:     str
    crop:         str
    area_acres:   float
    season:       str = "kharif_2025"

# ── Helper: build feature vector ─────────────────────────
def build_features(current_price, arrivals, month):
    season = 0 if month in [6,7,8,9,10,11] else (1 if month in [12,1,2,3] else 2)
    values = {
        "month":           month,
        "month_sin":       np.sin(2 * np.pi * month / 12),
        "month_cos":       np.cos(2 * np.pi * month / 12),
        "season":          season,
        "quarter":         (month - 1) // 3 + 1,
        "modal_price":     current_price,
        "price_7d_avg":    current_price * 0.97,
        "price_30d_avg":   current_price * 0.95,
        "price_7d_ago":    current_price * 0.96,
        "price_30d_ago":   current_price * 0.91,
        "price_trend_7d":  0.03,
        "vs_seasonal":     1.0,
        "seasonal_avg":    current_price * 0.95,
        "arrivals_tonnes": arrivals,
        "arrivals_7d_avg": arrivals * 1.05,
    }
    row = {f: values.get(f, 0) for f in FEATURES}
    return pd.DataFrame([row])[FEATURES]

# ── Helper: saturation calculation ───────────────────────
def calc_saturation(district, crop, season):
    dist  = district.lower()
    cr    = crop.lower()
    decls = [
        d for d in DECLARATIONS
        if d["district"].lower() == dist
        and d["crop"].lower() == cr
        and d["season"] == season
    ]
    total_area   = sum(d["area_acres"] for d in decls)
    farmer_count = len(decls)
    avg_area     = HISTORICAL_AREA.get(dist, {}).get(cr, 5000)
    sat_pct      = (total_area / avg_area) * 100 if avg_area else 0
    if sat_pct >= 70:
        risk = "HIGH"
        risk_kn = "ಅಧಿಕ ಅಪಾಯ"
        emoji = "🔴"
    elif sat_pct >= 40:
        risk = "MEDIUM"
        risk_kn = "ಮಧ್ಯಮ ಅಪಾಯ"
        emoji = "🟡"
    else:
        risk = "LOW"
        risk_kn = "ಕಡಿಮೆ ಅಪಾಯ"
        emoji = "🟢"
    return {
        "district":      district,
        "crop":          crop,
        "saturation_pct": round(sat_pct, 1),
        "risk_level":    risk,
        "risk_kannada":  risk_kn,
        "emoji":         emoji,
        "farmer_count":  farmer_count,
        "total_area":    total_area,
        "season":        season,
    }

# ═══════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "name":         "KisanMitra API",
        "version":      "1.0.0",
        "model_loaded": MODEL is not None,
        "endpoints": [
            "GET  /health",
            "POST /predict/price",
            "POST /farmer/declare",
            "GET  /saturation/{district}/{crop}",
            "GET  /declarations/summary",
        ]
    }

@app.get("/health")
def health():
    return {
        "status":        "healthy",
        "model_loaded":  MODEL is not None,
        "features":      len(FEATURES),
        "declarations":  len(DECLARATIONS),
        "time":          datetime.now().isoformat(),
    }

@app.post("/predict/price")
def predict_price(req: PriceRequest):
    if MODEL is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Run scripts/03_train_model.py first."
        )
    today = date.today()
    X     = build_features(req.current_price, req.arrivals_tonnes, today.month)
    pred  = float(MODEL.predict(X)[0])
    trees = np.array([t.predict(X)[0] for t in MODEL.estimators_])
    low   = float(np.percentile(trees, 15))
    high  = float(np.percentile(trees, 85))
    pct   = (pred - req.current_price) / req.current_price * 100
    if pct > 10:
        signal    = "WAIT — Price likely rising"
        signal_kn = "ಬೆಲೆ ಏರಲಿದೆ — ಕಾಯಿರಿ ⬆"
    elif pct < -10:
        signal    = "SELL NOW — Price likely falling"
        signal_kn = "ಈಗಲೇ ಮಾರಿ — ಬೆಲೆ ಇಳಿಯಲಿದೆ ⬇"
    else:
        signal    = "NEUTRAL — Monitor weekly"
        signal_kn = "ಸ್ಥಿರ ಬೆಲೆ — ವಾರ ವಾರ ಗಮನಿಸಿ ➡"
    return {
        "commodity":       req.commodity,
        "market":          req.market,
        "current_price":   req.current_price,
        "predicted_price": round(pred, 0),
        "confidence_low":  round(low, 0),
        "confidence_high": round(high, 0),
        "signal":          signal,
        "signal_kannada":  signal_kn,
        "model_mape":      "11.98%",
    }

@app.post("/farmer/declare")
def declare_crop(req: DeclareRequest):
    declaration = {
        "id":          len(DECLARATIONS) + 1,
        "farmer_name": req.farmer_name,
        "phone":       req.phone,
        "village":     req.village,
        "district":    req.district,
        "crop":        req.crop,
        "area_acres":  req.area_acres,
        "season":      req.season,
        "declared_at": datetime.now().isoformat(),
    }
    DECLARATIONS.append(declaration)
    sat = calc_saturation(req.district, req.crop, req.season)
    reply = (
        f"ನಮಸ್ಕಾರ {req.farmer_name}! ✅\n\n"
        f"ನಿಮ್ಮ {req.crop} ({req.area_acres} ಎಕರೆ) "
        f"ದಾಖಲಾಗಿದೆ.\n\n"
        f"📍 {req.district}:\n"
        f"{sat['emoji']} {req.crop} saturation: "
        f"{sat['saturation_pct']:.0f}% "
        f"({sat['risk_level']} RISK)\n\n"
        f"— KisanMitra 🌾"
    )
    return {
        "success":       True,
        "declaration_id": declaration["id"],
        "saturation":    sat,
        "whatsapp_reply": reply,
    }

@app.get("/saturation/{district}/{crop}")
def get_saturation(district: str, crop: str, season: str = "kharif_2025"):
    return calc_saturation(district, crop, season)

@app.get("/declarations/summary")
def summary():
    if not DECLARATIONS:
        return {
            "message": "No declarations yet.",
            "tip":     "Collect data during Ugadi!",
        }
    df = pd.DataFrame(DECLARATIONS)
    return {
        "total_declarations": len(df),
        "total_farmers":      df["phone"].nunique(),
        "districts":          df["district"].unique().tolist(),
        "crops":              df["crop"].value_counts().to_dict(),
        "latest":             df.iloc[-1]["declared_at"],
    }

@app.post("/internal/fetch-prices")
def fetch_prices():
    """
    Called by n8n every morning at 6 AM.
    Runs the price download script and returns status.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["python", "scripts/01_download_data.py"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return {
                "status":  "success",
                "message": "Prices updated successfully",
                "output":  result.stdout[-500:],
            }
        else:
            return {
                "status":  "error",
                "message": result.stderr[-500:],
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/internal/clean-data")
def clean_data():
    """
    Called by n8n after price fetch.
    Runs the cleaning script.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["python", "scripts/02_clean_data.py"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return {
                "status":  "success",
                "message": "Data cleaned successfully",
                "output":  result.stdout[-500:],
            }
        else:
            return {
                "status": "error",
                "message": result.stderr[-500:],
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}
