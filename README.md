# KisanMitra 🌾

> Smart Crop Planning and Market Intelligence Platform for Karnataka Farmers

## Problem

Karnataka's tomato farmers in Chikkaballapur and Kolar earn Rs. 1-3/kg at harvest
against a production cost of Rs. 50,000/acre — caused by uncoordinated collective
planting. No platform tells a farmer that 78% of their district is already planting
the same crop before they commit their investment.

## Solution

KisanMitra delivers four capabilities through WhatsApp in Kannada — no app download needed:

- **District Saturation Index** — Real-time % of district farmland per crop (LOW/MEDIUM/HIGH risk)
- **Price Intelligence** — AGMARKNET mandi prices + 60-day ML prediction
- **WhatsApp Bot in Kannada** — RAG-powered GPT-4 advisory
- **Satellite Verification** — Sentinel-2 NDVI trust scores for farmer declarations

## ML Model Performance

- Algorithm: Random Forest (200 trees)
- Test MAPE: 11.98% — beats 21% ARIMA baseline
- OOB Score: 0.89
- Training data: 1,113 records from AGMARKNET Karnataka

## Tech Stack

- Backend: FastAPI + Python 3.14
- ML: scikit-learn RandomForestRegressor
- Database: PostgreSQL 18.3 + PostGIS
- Automation: n8n (Docker)
- Satellite: Google Earth Engine + Sentinel-2
- Bot: WhatsApp Cloud API + GPT-4 RAG

## Quick Start

```bash
git clone https://github.com/CHANDU-M05/kisanmitra.git
cd kisanmitra
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/01_download_data.py
python scripts/02_clean_data.py
python scripts/03_train_model.py
uvicorn api.main:app --reload --port 8000
```

## API Endpoints

- GET  /health — API status and model loaded check
- POST /predict/price — 60-day price prediction
- POST /farmer/declare — Crop declaration and saturation signal
- GET  /saturation/{district}/{crop} — District risk level
- GET  /declarations/summary — Aggregate statistics

## Project Status

- [x] ML pipeline (download, clean, train)
- [x] FastAPI backend (5 endpoints validated)
- [x] n8n automation (daily price fetch)
- [x] PostgreSQL schema
- [ ] WhatsApp bot (in progress)
- [ ] Web dashboard (in progress)
- [ ] Satellite verification (Phase 2)

## Target Geography

Chikkaballapur and Kolar districts, Karnataka — Asia's second-largest tomato market.

---

VTU 2022 Scheme | VIII Semester Major Project | Dept. of CSE
