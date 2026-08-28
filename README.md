# 🌾 KisanMitra 
> **Smart Crop Planning & Market Intelligence Platform for Karnataka Farmers**

KisanMitra is a streamlined agricultural intelligence platform. It empowers farmers in Karnataka with real-time crop market forecasts and AI-driven agronomy advice via a simple **WhatsApp interface**, while giving administrators a powerful web dashboard to monitor district-level saturation and price trends.

This repository has been deliberately simplified for maximum stability and developer accessibility. Complex containerization (Docker) and external orchestrators (n8n) have been permanently removed in favor of a standard, test-driven Python + React architecture.

---

## ✨ Latest Updates (v2.0)
The project has reached production readiness with the following features fully implemented:
1. **Progressive Web App (PWA)**: The farmer-facing web dashboard is now fully installable on mobile devices (Android/iOS) with offline caching and manifest support.
2. **i18n Localization**: Seamless Kannada/English toggling across all farmer workspaces using `react-i18next`.
3. **JWT Authentication**: The Admin Dashboard is now fully secured with cryptographic JWT authentication, password hashing (`bcrypt`), and backend route protection.

---

## 🏗️ Tech Stack
- **Backend:** FastAPI (Python 3.11+) for high-performance async routing.
- **Database:** PostgreSQL + `pgvector` for robust relational data and vector similarity search.
- **Frontend (Admin Dashboard):** Rebuilt from scratch using **Vite + React 19** + Tailwind CSS.
- **AI / ML Engine:** Scikit-learn (Random Forest Price Prediction) and Google Gemini (RAG for agronomy).
- **Testing:** Comprehensive `pytest` suite guaranteeing intent routing stability.

---

## 📂 Directory Structure

A quick guide to finding your way around the highly-optimized codebase:

```text
kisanmitra/
├── backend/                    # 🧠 Core Backend Logic
│   ├── core/                   # DB connections, config, and SQLAlchemy ORM models
│   ├── routers/                # API Endpoints (WhatsApp webhook, analytics, etc)
│   ├── services/               # Business Logic (RAG, ML, message handling)
│   └── main.py                 # FastAPI Application Entry Point
├── frontend/                   # 📊 Rebuilt React Admin Dashboard (Vite)
│   ├── src/pages/              # React Views (Terminal, Insights, Farmers, BotMonitor, Settings)
│   └── src/components/         # Reusable UI components (Layout, etc.)
├── data/                       # 📁 Local Storage for ML models and raw data drops
├── scripts/                    # ⚙️ Utility scripts (DB init, ML pipeline, data cleaning)
├── tests/                      # 🛡️ Pytest suite for core logic validation
└── requirements.txt            # Python dependencies
```

---

## 🚀 How to Run Locally

Since this project avoids complex orchestrators, getting started locally is incredibly straightforward.

### 1. Backend (FastAPI) Setup
1. **Create a virtual environment & install dependencies:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure Environment Variables:**
   Ensure you have your Gemini API keys and PostgreSQL credentials configured in the **root `.env`** file.
3. **Initialize the Database:**
   *(Ensure you have a local PostgreSQL instance running with the pgvector extension).*
   ```bash
   # Create tables & import survey records
   python scripts/00_init_db.py
   python scripts/04_sync_surveys.py
   
   # Run the ML pipeline to download data, clean it, and train the model
   python scripts/01_download_data.py
   python scripts/02_clean_data.py
   python scripts/03_train_model.py
   ```
4. **Start the API Server:**
   ```bash
   uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```

### 2. Frontend (Vite Dashboard) Setup
Open a new terminal window:
```bash
cd frontend
npm install
npm run dev
```
The dashboard will be available at **http://localhost:3000**.

---

## 🛡️ Testing the System
We use `pytest` to guarantee that our core logic (specifically, the deterministic message routing and fuzzy Kannada matching) never breaks.
```bash
source venv/bin/activate
PYTHONPATH=. pytest tests/
```

---

## 📡 Webhook Integration
To connect this local instance to Meta's WhatsApp API, use a tunneling service like **Ngrok**:
```bash
ngrok http 8000
```
Update your Meta Developer Console with the generated Ngrok URL (append `/webhook/whatsapp` to the URL).

---
## 📜 License
Distributed under the MIT License.
