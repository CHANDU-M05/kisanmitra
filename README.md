# 🌾 KisanMitra 
> **Smart Crop Planning & Market Intelligence Platform for Karnataka Farmers**

KisanMitra is an agricultural intelligence platform that empowers farmers in Karnataka with real-time crop market forecasts (60-day mandi price prediction) and AI-driven precision agronomy advice via a simple **Telegram Bot (`@KisanMitraAssistBot`)** & **WhatsApp interface**, while giving administrators a web dashboard to monitor district-level crop saturation and price anomalies.

---

## ✨ Features & Architecture (v3.0)

1. **CatBoost 60-Day Mandi Price Forecasting**: Multi-horizon price forecasts across all 31 Karnataka districts with anomaly classification (`CRASH` / `SPIKE`) and upper/lower bounds.
2. **Deterministic Intent Guardrails (No LLM Hallucinations)**:
   - Market Prices, Sowing Declarations, and District Saturation Risk queries **bypass the LLM completely** and query PostgreSQL directly.
   - Only agronomy disease & pest queries reach the **pgvector + Gemini RAG pipeline**.
3. **Interactive Sowing Confirmation Gate**: Mandatory two-stage declaration flow prevents accidental or fake database registrations.
4. **31-District Canonical Resolution**: 100% normalization of all 31 Karnataka districts across legacy English spellings (`Shimoga`, `Belgaum`, `Gulbarga`), modern official spellings (`Shivamogga`, `Belagavi`), Kannada script locatives (`ಶಿವಮೊಗ್ಗದಲ್ಲಿ`), and Kanglish transliterations (`shimogalli`).
5. **Telegram Bot Integration**: Built with `Aiogram 3`, featuring Redis FSM state persistence, inline keyboards, and automated crop menu registration.
6. **Progressive Web App (PWA) & Admin Dashboard**: React 18 + Vite dashboard with dark mode, live telemetry, and real-time bot transcript streaming (`BotMonitorView.jsx`).
7. **Empirical Benchmarks**: Verified via a 1,000-case procedural stress test and a 25-case live HTTP E2E transcript audit.

---

## 🏗️ Tech Stack

- **Backend:** FastAPI (Python 3.14) + SQLAlchemy + Pydantic v2
- **Database:** PostgreSQL + `pgvector` (SQLite fallback supported)
- **Machine Learning:** CatBoost (`price_model.pkl`) + Scikit-learn + LightGBM
- **Bot Framework:** Aiogram 3 + Redis FSM
- **Frontend:** Vite 8 + React 18 + TailwindCSS + Recharts + Lucide Icons
- **Testing:** Pytest (43 core tests) + 1,000-Case Stress Harness + 25-Case Live HTTP E2E Suite

---

## 📂 Directory Structure

```text
kisanmitra/
├── backend/                    # 🧠 Core Backend REST API
│   ├── core/                   # DB connections, config, and SQLAlchemy ORM models
│   ├── routers/                # API Endpoints (conversation, price, farmers, analytics, audit)
│   ├── services/               # Core Logic (message_handler, ml_service, rag, farmer_service)
│   └── main.py                 # FastAPI Application Entrypoint
├── telegram_bot/               # 🤖 Aiogram 3 Telegram Bot Application
│   ├── handlers/               # Command & message routers (start, price, declare, advisory, mycrops)
│   ├── middleware/             # Rate-limiting & request deduplication
│   └── bot.py                  # Bot entrypoint & polling dispatcher
├── frontend/                   # 📊 Vite + React Admin Dashboard
│   ├── src/pages/              # Admin Views (Insights, Farmers, BotMonitor, Advisory, Weather)
│   └── src/components/         # Reusable UI components & Layout
├── data/                       # 📁 Storage for ML models (price_model.pkl) and datasets
├── docs/                       # 📄 Academic results and system documentation
├── results/                    # 📈 Benchmark CSVs and evaluation charts
├── artifacts/                  # 📄 Audit evidence transcripts (live_backend_e2e_transcript.md)
├── scripts/                    # ⚙️ Training, DB init, RAG seed, and benchmark scripts
├── tests/                      # 🛡️ Pytest suite for core logic & NLU guardrails
└── requirements.txt            # Python dependencies
```

---

## 🚀 How to Run Locally

### 1. Backend (FastAPI) Setup
```bash
# 1. Activate virtual environment
source venv/bin/activate
pip install -r requirements.txt

# 2. Start API Server
venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 2. Telegram Bot Setup
```bash
source venv/bin/activate
venv/bin/python -m telegram_bot.bot
```

### 3. Frontend (Vite Dashboard) Setup
```bash
cd frontend
npm install
npm run dev
```
Dashboard available at **http://localhost:3000**.

---

## 🚀 Deployment

| Target | Stack | Guide |
|---|---|---|
| **Current (free tier)** | Render free Docker web service + Neon Free Postgres + Cloudflare Pages PWA | [`docs/RENDER_NEON_CLOUDFLARE_DEPLOYMENT.md`](docs/RENDER_NEON_CLOUDFLARE_DEPLOYMENT.md) |
| Upgrade path (heavy load) | Oracle Always Free Ampere A1 VM, Docker Compose, Caddy, GitHub Actions | [`docs/DEPLOYMENT_RUNBOOK.md`](docs/DEPLOYMENT_RUNBOOK.md) + [`docs/ORACLE_A1_PROVISIONING_AND_SECRETS.md`](docs/ORACLE_A1_PROVISIONING_AND_SECRETS.md) |

Honest scope: the free stack spins down after 15 min idle (≈1 min cold start),
runs one 512 MB worker, and does **not** host the Telegram bot or heavy load —
it is for demos and evaluation. The Oracle path (kept intact in `deploy/`,
`.github/workflows/cd.yml`) re-arms with `gh variable set DEPLOY_TARGET --body oracle`.
Blueprint: [`render.yaml`](render.yaml) · env template: [`deploy/env/render.env.example`](deploy/env/render.env.example)

---

## 🛡️ Testing & Benchmarks

Run the unit test suite:
```bash
PYTHONPATH=. venv/bin/pytest tests/
```

Run the 1,000-case procedural stress benchmark:
```bash
PYTHONPATH=. venv/bin/python scripts/generate_and_stress_test_1000.py
```

Run the 25-case live HTTP E2E transcript audit:
```bash
PYTHONPATH=. venv/bin/python scripts/test_live_backend_e2e.py
```

---

## 📜 License
Distributed under the MIT License.
