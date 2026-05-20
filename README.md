# 🌾 KisanMitra v2.0
> **Production-Grade Smart Crop Planning & Market Intelligence Platform for Karnataka Farmers**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI 0.115+](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Status: Production-Ready](https://img.shields.io/badge/Status-Production--Ready-success?style=flat-square)](#)

KisanMitra is an enterprise-grade, vertically integrated agricultural intelligence platform. It empowers farmers in Karnataka with real-time crop market forecasts, AI-driven agronomy advice (RAG), and satellite-verified crop saturation monitoring—all delivered through a low-friction **WhatsApp interface**.

---

## 📖 Table of Contents
- [🌾 KisanMitra v2.0](#-kisanmitra-v20)
  - [📖 Table of Contents](#-table-of-contents)
  - [🏗️ System Architecture](#️-system-architecture)
    - [The 5-Layer Stack](#the-5-layer-stack)
    - [The 4 Security Guardrails](#the-4-security-guardrails)
  - [📂 Directory Structure](#-directory-structure)
  - [🚀 Quick Start (Docker Compose)](#-quick-start-docker-compose)
    - [1. Configure Environment](#1-configure-environment)
    - [2. Launch the Stack](#2-launch-the-stack)
    - [3. Initialize Database \& Seeds](#3-initialize-database--seeds)
    - [4. Seed the Knowledge Base](#4-seed-the-knowledge-base)
  - [💻 Local Development Setup](#-local-development-setup)
    - [Backend (FastAPI) Setup](#backend-fastapi-setup)
    - [Frontend (React + Vite Dashboard) Setup](#frontend-react--vite-dashboard-setup)
  - [📡 External Integration Setup](#-external-integration-setup)
    - [1. Meta WhatsApp Webhook Configuration](#1-meta-whatsapp-webhook-configuration)
    - [2. Google Earth Engine (GEE) Service Account](#2-google-earth-engine-gee-service-account)
  - [⚙️ Core CLI Scripts Walkthrough](#️-core-cli-scripts-walkthrough)
    - [1. Webhook Simulator (`scripts/simulate_whatsapp.py`)](#1-webhook-simulator-scriptssimulate_whatsapppy)
    - [2. Price Model Trainer (`scripts/03_train_model.py`)](#2-price-model-trainer-scripts03_train_modelpy)
    - [3. Satellite Verification (`scripts/04_satellite_verify.py`)](#3-satellite-verification-scripts04_satellite_verifypy)
  - [📊 RAG Health & Telemetry Dashboard](#-rag-health--telemetry-dashboard)
  - [🌐 Production Deployment & Infrastructure](#-production-deployment--infrastructure)

---

## 🏗️ System Architecture

KisanMitra is built with scalability, reliability, and security in mind. Detailed documentation on data flows and logical branching can be found in [docs/ARCHITECTURE.md](file:///home/chandu/kisanmitra/docs/ARCHITECTURE.md).

### The 5-Layer Stack
1. **Ingress & Gateway Layer:** Nginx reverse proxy with automated Let's Encrypt SSL certificates.
2. **Logic & API Engine:** Async-first FastAPI backend with custom routers, strict Pydantic v2 schemas, and dependency injection.
3. **Intelligence Layer:**
   - **RAG Engine:** Cosine similarity search on `pgvector`-stored embeddings of ICAR bulletins using OpenAI's GPT-4o-mini.
   - **Machine Learning Engine:** Scikit-learn Random Forest model predicting 60-day crop prices based on historical Mandi volumes, seasonality, and regions.
4. **Verification Layer:** Google Earth Engine API processing Sentinel-2 (optical) and Sentinel-1 (SAR radar) imagery for remote crop confirmation.
5. **Telemetry & Analytics Loop:** PostgreSQL-backed chat telemetry, recording real-time farmer thumbs-up/down ratings and feeding the admin dashboard.

### The 4 Security Guardrails
*   **G1 (Entity Resolution):** `thefuzz`-based fuzzy matching to map non-standard crop and district names (in Kannada/English) to standard database records.
*   **G2 (Deterministic Intent Router):** Regex classifier routes incoming farmer queries before hitting the LLM, protecting against hallucinated responses for critical market decisions.
*   **G3 (Cloud-Proof Imagery Fallback):** Asynchronous GEE pipeline checks optical cloud coverage. If cloud cover $> 20\%$, it automatically activates Sentinel-1 Synthetic Aperture Radar (SAR) to verify crop presence through rain and clouds.
*   **G4 (HMAC Signature Verification):** Validates the `X-Hub-Signature-256` header on incoming Meta WhatsApp payloads to ensure authenticity.

---

## 📂 Directory Structure

```text
kisanmitra/
├── .github/
│   └── workflows/
│       └── deploy.yml            # CI/CD pipeline for cloud deployment
├── api/
│   ├── core/                     # Database, configuration, and logging setup
│   │   ├── config.py             # Settings configuration using pydantic-settings
│   │   ├── database.py           # SQLAlchemy async database session manager
│   │   ├── logging_config.py     # Application logger configuration
│   │   └── models.py             # SQLAlchemy models (Farmers, ChatHistory, etc.)
│   ├── routers/                  # API endpoint groups
│   │   ├── analytics.py          # Dashboard endpoints (accuracy, hotspots)
│   │   ├── farmers.py            # Farmer onboarding & registration
│   │   ├── prices.py             # Crop price forecasting endpoints
│   │   ├── satellite.py          # Earth Engine verification triggers
│   │   ├── system.py             # Health check & status
│   │   └── webhook.py            # Meta WhatsApp Webhook ingress
│   ├── services/                 # Business logic components
│   │   ├── farmer_service.py     # Farmer registry logic
│   │   ├── message_handler.py    # Main conversation parser & agent coordinator
│   │   ├── ml_service.py         # Price forecasting model wrapper
│   │   ├── rag.py                # pgvector OpenAI retrieval system
│   │   └── whatsapp.py           # Meta Cloud API client
│   ├── main.py                   # FastAPI main entry point
│   └── schemas.py                # Pydantic v2 validation schemas
├── config/
│   └── .env                      # Real environment configurations (ignored by git)
├── credentials/
│   └── gee-sa.json               # Google Earth Engine Service Account key (ignored by git)
├── dashboard/                    # React Admin Telemetry Dashboard
│   ├── src/
│   │   ├── components/
│   │   │   └── RAGHealthDashboard.jsx  # Glassmorphism dashboard component
│   │   ├── services/
│   │   │   └── api.js            # Axios client for backend API
│   │   ├── App.css               # Styling rules
│   │   ├── App.jsx               # Application shell
│   │   └── index.css             # Tailwind/CSS utilities
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── data/
│   ├── bulletins/                # ICAR bulletins (inputs for RAG)
│   └── models/                   # Trained ML models and evaluation plots
├── docs/                         # Additional documentation
│   ├── ARCHITECTURE.md           # Mermaid dataflow diagrams
│   ├── LAUNCH_POST.md            # Release post template
│   └── META_SETUP.md             # Guide for setting up Meta Business API
├── logs/                         # App runtime logs (ignored by git)
├── n8n/                          # n8n Orchestration configuration
│   ├── workflows/                # Backup JSON workflows (Form ingestion, syncs)
│   └── docker-compose.yml        # Self-hosted n8n instance setup
├── nginx/
│   └── nginx.conf                # Ingress reverse proxy configuration
├── scripts/                      # Management and automation utilities
│   ├── 00_init_db.py             # DB structure initializer (Creates tables, pgvector, indices)
│   ├── 03_train_model.py         # Random Forest model training script
│   ├── 04_satellite_verify.py    # Standalone GEE imagery pipeline test
│   ├── provision_server.sh       # Cloud server VM initialization script
│   ├── seed_knowledge.py         # ICAR bulletins RAG parser & vector seeder
│   ├── simulate_whatsapp.py      # HMAC-signed local webhook event generator
│   └── verify_db.py              # DB connection sanity checker
├── .dockerignore
├── .env.example                  # Template configuration keys
├── .gitignore
├── CHANGELOG.md                  # Release version history
├── Dockerfile                    # Multi-stage production container definition
├── docker-compose.yml            # Main Docker Stack specification
└── requirements.txt              # Backend python dependencies
```

---

## 🚀 Quick Start (Docker Compose)

### 1. Configure Environment
Prepare environment settings by copying the template file:
```bash
cp .env.example config/.env
```
Fill out the variables inside `config/.env` (especially `OPENAI_API_KEY`, `WHATSAPP_TOKEN`, and `WHATSAPP_APP_SECRET`).

### 2. Launch the Stack
This boots PostgreSQL, PostGIS, pgvector, Nginx, and the FastAPI backend:
```bash
docker-compose up -d --build
```

### 3. Initialize Database & Seeds
Run database initialization inside the API container:
```bash
docker exec -it kisanmitra_api python scripts/00_init_db.py
```

### 4. Seed the Knowledge Base
Seed the RAG vector engine using the provided ICAR agriculture bulletins:
```bash
docker exec -it kisanmitra_api python scripts/seed_knowledge.py data/bulletins/icar_2024.txt
```

---

## 💻 Local Development Setup

If you prefer to run services individually without Docker:

### Backend (FastAPI) Setup
1. Create a Python 3.11+ virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the database migrations & verify connection:
   ```bash
   python scripts/00_init_db.py
   python scripts/verify_db.py
   ```
4. Start the backend server:
   ```bash
   uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
   ```

### Frontend (React + Vite Dashboard) Setup
1. Navigate to the dashboard directory:
   ```bash
   cd dashboard
   ```
2. Install NodeJS packages:
   ```bash
   npm install
   ```
3. Start the dev server:
   ```bash
   npm run dev
   ```

---

## 📡 External Integration Setup

### 1. Meta WhatsApp Webhook Configuration
See [docs/META_SETUP.md](file:///home/chandu/kisanmitra/docs/META_SETUP.md) for full config details.
* Ensure you configure `WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` in your `.env`.
* Meta expects HTTPS, which is handled via Nginx in production or Ngrok for local testing.

### 2. Google Earth Engine (GEE) Service Account
* Generate a service account key file in your Google Cloud Console.
* Save the key to `credentials/gee-sa.json`. It will be loaded automatically by the backend to perform satellite checks.

---

## ⚙️ Core CLI Scripts Walkthrough

### 1. Webhook Simulator (`scripts/simulate_whatsapp.py`)
Simulate incoming webhook messages locally (generates valid HMAC signatures using `WHATSAPP_APP_SECRET`):
```bash
python scripts/simulate_whatsapp.py
```

### 2. Price Model Trainer (`scripts/03_train_model.py`)
Train and export the scikit-learn Random Forest model used for mandi crop price predictions:
```bash
python scripts/03_train_model.py
```
This saves the model files inside `data/models/` and generates validation metrics.

### 3. Satellite Verification (`scripts/04_satellite_verify.py`)
Verify the Google Earth Engine credentials and test the multi-spectral cloud fallback algorithm stand-alone:
```bash
python scripts/04_satellite_verify.py
```

---

## 📊 RAG Health & Telemetry Dashboard

The dashboard provides admin analytics directly reflecting live farmer feedback:
* **Interactive Rating Tracking:** Evaluates thumbs-up/down ratios on LLM answers.
* **Failure Hotspots:** Identifies weak knowledge chunks based on negative feedback.
* **Geographical Activity:** Real-time visualization of query densities across Karnataka districts.

---

## 🌐 Production Deployment & Infrastructure

Refer to:
- [scripts/provision_server.sh](file:///home/chandu/kisanmitra/scripts/provision_server.sh) for server staging commands.
- [nginx/nginx.conf](file:///home/chandu/kisanmitra/nginx/nginx.conf) for routing setups.
- [.github/workflows/deploy.yml](file:///home/chandu/kisanmitra/.github/workflows/deploy.yml) for GitHub actions automated deployments.

---

## 📜 License
Distributed under the MIT License. See `LICENSE` for details.
