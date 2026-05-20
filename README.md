# 🌾 KisanMitra v2.0
> **Smart Crop Planning & Market Intelligence for Karnataka Farmers**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/Status-Production--Ready-success?style=for-the-badge)

KisanMitra is an enterprise-grade, vertically integrated agricultural intelligence platform. It empowers farmers in Karnataka with real-time crop market forecasts, AI-driven agronomy advice (RAG), and satellite-verified saturation monitoring—all delivered through a low-friction **WhatsApp interface**.

---

## 🏗️ The 5-Layer Stack
1.  **Ingress Layer:** Nginx Reverse Proxy with Let's Encrypt SSL.
2.  **Logic Engine:** FastAPI (Async-first) with Pydantic v2 validation.
3.  **Intelligence Layer:** 
    *   **RAG:** GPT-4o-mini + `pgvector` for hyper-local agronomy advice.
    *   **ML:** Scikit-learn Random Forest for 60-day price forecasting.
4.  **Verification Layer:** Google Earth Engine (GEE) script (NDVI/SAR fallback) for satellite crop health verification.
5.  **Telemetry & Analytics:** PostgreSQL `chat_history` engine feeding a Glassmorphism React Dashboard.

## 🛡️ The 4 Security Guardrails
*   **G1 (Fuzzy Engine):** Thefuzz-powered matching for non-standard crop and district names.
*   **G2 (Deterministic Routing):** Regex-intent classification to prevent "LLM hallucination" in critical market decisions.
*   **G3 (Satellite Fallback):** Sentinel-1 SAR (Radar) path activates automatically if Sentinel-2 (Optical) is cloud-blocked.
*   **G4 (HMAC Verification):** Strict `X-Hub-Signature-256` validation for all Meta WhatsApp webhooks.

---

## 🚀 Quick Start (Docker Deployment)

### 1. Configure Environment
Create a `.env` file from the template:
```bash
cp .env.example .env
# Essential Keys: OPENAI_API_KEY, WHATSAPP_TOKEN, WHATSAPP_APP_SECRET
```

### 2. Launch the Stack
```bash
docker-compose up -d --build
```

### 3. Initialize Intelligence
```bash
docker exec -it kisanmitra_api python scripts/seed_knowledge.py data/bulletins/icar_2024.txt
```

---

## 📊 RAG Health Dashboard
KisanMitra includes a real-time monitoring dashboard built with Vite/React. It visualizes:
*   **Accuracy Score:** Ground-truth 👍/👎 ratings from live farmer interactions.
*   **Engagement Rate:** Percentage of conversations providing active feedback.
*   **Failure Hotspots:** Automatic identification of weak points in the knowledge base.

---

## 📜 License
Distributed under the MIT License. See `LICENSE` for more information.
