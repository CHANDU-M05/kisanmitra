# Changelog

All notable changes to the **KisanMitra** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-05-13

### Added
- **Vector Intelligence:** Integrated `pgvector` for high-performance semantic search within PostgreSQL.
- **Agentic Ingestion:** New `scripts/seed_knowledge.py` using LLM-driven "Atomic Proposition" extraction for RAG.
- **Security Guardrails:**
  - HMAC SHA256 signature verification for Meta WhatsApp Webhooks.
  - Fuzzy matching engine for crop and district entity resolution.
  - Deterministic intent classification to prevent LLM hallucinations.
- **Satellite Monitoring:** Integrated Google Earth Engine (GEE) with Sentinel-1 SAR fallback for cloud-proof crop verification.
- **Real-time Telemetry:** `ChatHistory` engine with automated feedback loops (👍/👎 buttons on WhatsApp).
- **Admin Dashboard:** React/Vite Glassmorphism dashboard for RAG health monitoring and failure hotspot analysis.
- **Cloud Infrastructure:** Nginx reverse proxy, Certbot SSL automation, and GitHub Actions CI/CD workflows.

### Changed
- **Architecture:** Transitioned from a monolithic prototype to a decoupled, async-first FastAPI service.
- **Database:** Migrated from local SQLite to a production-ready PostgreSQL + PostGIS + pgvector cluster.
- **RAG Pipeline:** Shifted from basic chunking to metadata-filtered, crop-specific retrieval.
- **ML Deployment:** Refactored Price Forecasting into a resilient startup service with automatic model reload.

### Removed
- **Legacy Files:** Deleted `kisanmitra.db` (SQLite) and old Python-only price models.
- **Redundant Dependencies:** Removed `langchain-postgres` and unused monolithic libraries to optimize container weight.
- **Synchronous Bottlenecks:** Replaced blocking subprocess calls with FastAPI BackgroundTasks.

---
[2.0.0]: https://github.com/your-username/kisanmitra/releases/tag/v2.0.0
