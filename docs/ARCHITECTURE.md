# 📐 KisanMitra System Architecture

This document details the data flow and logical branching of the KisanMitra v2.0 intelligence engine.

```mermaid
graph TD
    %% Entry Layer
    User[Farmer via WhatsApp] -->|HTTPS POST| Nginx[Nginx Reverse Proxy]
    Nginx -->|Proxy Pass| API[FastAPI Logic Engine]

    %% Security Guardrails
    subgraph Guardrails [4 Security Guardrails]
        HMAC[G4: HMAC SHA256 Verification]
        Fuzzy[G1: Fuzzy Crop/District Matching]
        Router[G2: Intent Router]
    end

    API --> HMAC
    HMAC --> Fuzzy
    Fuzzy --> Router

    %% Intelligence Branching
    Router -->|Intent: Price Query| ML[Market ML: Random Forest]
    Router -->|Intent: Agronomy Advice| RAG[RAG: OpenAI + pgvector]
    Router -->|Intent: Crop Declaration| SAT[Satellite Guardrail: GEE NDVI/SAR]

    %% Data Sinks
    ML --> DB[(PostgreSQL + PostGIS)]
    RAG --> DB
    SAT --> DB

    %% Telemetry & Response
    DB --> Telemetry[Chat History & Feedback Scoring]
    Telemetry --> Dash[Glassmorphism React Dashboard]
    
    API -->|Async Response| Meta[Meta Cloud API]
    Meta -->|WhatsApp Message| User
```

## Data Flow Breakdown

### 1. Ingress & Security
The system uses **Nginx** for SSL termination. The FastAPI backend immediately executes **Guardrail 4 (HMAC)** to ensure the message originated from Meta's verified servers. **Guardrail 2** then classifies the intent using deterministic logic.

### 2. Multi-Modal Intelligence
*   **Market Intelligence:** Queries historical Mandi price data and runs a 15-feature Scikit-learn model.
*   **Agronomic Intelligence (RAG):** Performs a cosine-similarity search on `pgvector` stored knowledge chunks. The "Atomic Agronomy" propositions are then synthesized by GPT-4o-mini into a self-contained Kannada response.
*   **Satellite Verification:** Triggers an asynchronous **Google Earth Engine** task. It prioritizes Sentinel-2 (Optical) but falls back to **Sentinel-1 (SAR)** if cloud coverage exceeds 20%.

### 3. Telemetry Loop
Every interaction logs a `ChatHistory` record. When the assistant sends a RAG-based response, it appends **Interactive Buttons**. When a farmer clicks 👍/👎, a secondary webhook updates the `feedback_score`, which is instantly reflected in the **Glassmorphism Dashboard**.
