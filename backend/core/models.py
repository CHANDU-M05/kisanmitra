"""
api/core/models.py — ORM models for KisanMitra

Extension detection is performed at import time by checking an
environment variable DB_HAS_PGVECTOR / DB_HAS_POSTGIS. The 00_init_db.py
script sets these after probing the live database. For fresh setups
without extensions, fallback column types (Text, Float) are used.
"""
from __future__ import annotations

import os
import logging
import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
import uuid

from backend.core.database import Base

logger = logging.getLogger("kisanmitra.models")

# ── Extension availability flags ─────────────────────────
# Set by 00_init_db.py or docker-compose environment.
# Default to False so the app always boots.
_HAS_PGVECTOR = os.getenv("DB_HAS_PGVECTOR", "").lower() in ("1", "true", "yes")
_HAS_POSTGIS  = os.getenv("DB_HAS_POSTGIS",  "").lower() in ("1", "true", "yes")

if _HAS_PGVECTOR:
    from pgvector.sqlalchemy import Vector
if _HAS_POSTGIS:
    from geoalchemy2 import Geometry


class MandiPrice(Base):
    """Daily AGMARKNET mandi arrival prices."""

    __tablename__ = "mandi_prices"

    id              = Column(Integer, primary_key=True)
    state           = Column(String(100), nullable=False)
    district        = Column(String(100), nullable=False, index=True)
    market          = Column(String(150), nullable=False, index=True)
    commodity       = Column(String(150), nullable=False, index=True)
    variety         = Column(String(150))
    arrival_date    = Column(DateTime(timezone=True), nullable=False, index=True)
    min_price       = Column(Float)
    max_price       = Column(Float)
    modal_price     = Column(Float)
    arrivals_tonnes = Column(Float)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "commodity", "market", "arrival_date",
            name="uq_mandi_commodity_market_date",
        ),
        Index("ix_mandi_cmm_date", "commodity", "market", "arrival_date"),
    )


class Farmer(Base):
    """Registered farmer profile."""

    __tablename__ = "farmers"

    id         = Column(Integer, primary_key=True)
    name       = Column(String(255), nullable=False)
    phone      = Column(String(20), unique=True, nullable=False, index=True)
    village    = Column(String(255))
    district   = Column(String(100), index=True)
    taluk      = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CropDeclaration(Base):
    """
    Single-season crop declaration by a farmer.
    Uses PostGIS POINT when available, otherwise lat/lon floats.
    """

    __tablename__ = "crop_declarations"

    id               = Column(Integer, primary_key=True)
    farmer_name      = Column(String(255), nullable=False)
    phone            = Column(String(20), nullable=False, index=True)
    village          = Column(String(255))
    district         = Column(String(100), nullable=False, index=True)
    taluk            = Column(String(100), index=True)
    crop             = Column(String(100), nullable=False, index=True)
    area_acres       = Column(Float, nullable=False)
    season           = Column(String(50), nullable=False)
    trust_score      = Column(Float)
    satellite_status = Column(String(50))
    latitude         = Column(Float, nullable=True)
    longitude        = Column(Float, nullable=True)
    declared_at      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_decl_district_crop_season", "district", "crop", "season"),
        # Unique per farmer per crop/district/season — enforced atomically by Postgres.
        # Uses lower() on all text fields for case-insensitive uniqueness so that
        # "Tomato" and "tomato" from different channels are treated as the same declaration.
        # This is the correct domain semantic: one declaration row per farmer per season;
        # a changed area should be an UPDATE, not a second INSERT.
        # The unique index makes Layer 2's SELECT-before-INSERT race-condition-proof:
        # concurrent retries that both pass the SELECT still can't both INSERT —
        # Postgres rejects the second one and Python catches IntegrityError.
        Index(
            "uq_decl_phone_crop_district_season",
            func.lower(Column("phone")),
            func.lower(Column("crop")),
            func.lower(Column("district")),
            Column("season"),
            unique=True,
        ),
    )


class KnowledgeChunk(Base):
    """
    RAG knowledge base for the Kannada advisory bot.
    Uses pgvector Vector(768) when available, otherwise Text.
    """

    __tablename__ = "knowledge_chunks"

    id         = Column(Integer, primary_key=True)
    crop       = Column(String(100), index=True)
    category   = Column(String(100), index=True)
    districts  = Column(JSONB)  # List of districts
    content    = Column(Text, nullable=False)
    keywords   = Column(JSONB)  # List of keywords
    source     = Column(String(255))
    language   = Column(String(10), default="kn")
    meta       = Column("metadata", JSONB, default=dict)
    embedding  = Column(Vector(768)) if _HAS_PGVECTOR else Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    if _HAS_PGVECTOR:
        __table_args__ = (
            Index(
                "ix_knowledge_embedding_hnsw",
                "embedding",
                postgresql_using="hnsw",
                postgresql_with={"m": 16, "ef_construction": 64},
                postgresql_ops={"embedding": "vector_cosine_ops"},
            ),
        )
    else:
        __table_args__ = ()


class ChatHistory(Base):
    """
    Conversation persistence, entity context tracking, and LLM telemetry.
    """
    __tablename__ = "chat_history"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number    = Column(String(20), index=True, nullable=False)
    channel         = Column(String(20), nullable=False, default="web", index=True)
    role            = Column(String(20), nullable=False)  # user | assistant
    message_content = Column(Text, nullable=False)
    intent_category = Column(String(50))
    crop            = Column(String(100), nullable=True, index=True)
    district        = Column(String(100), nullable=True, index=True)
    feedback_score  = Column(Integer)  # 1 (positive) | -1 (negative) | null
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class AdminUser(Base):
    """
    Admin user credentials for the dashboard.
    """
    __tablename__ = "admin_users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class RevokedToken(Base):
    """
    Blacklisted JWTs.
    """
    __tablename__ = "revoked_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    jti        = Column(String, unique=True, index=True, nullable=False)
    revoked_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """
    DPDP Act Compliance & System Governance Audit Log.
    Tracks PII reveals, data exports, admin actions, and credential events.
    """
    __tablename__ = "audit_logs"

    id             = Column(Integer, primary_key=True, index=True)
    admin_username = Column(String, index=True, nullable=False)
    action         = Column(String, index=True, nullable=False)
    target         = Column(String, nullable=False)
    ip_address     = Column(String, nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class DataRefreshRun(Base):
    """
    One row per AGMARKNET refresh attempt — the operational record that lets an
    operator tell apart three very different situations:

      status='success'      new market rows landed; forecasts are current
      status='no_new_data'  the fetch worked but the upstream has published
                            nothing newer than what we already hold
      status='failed'       fetch/parse/write error — data age is NOT evidence
                            of an idle market

    Without this distinction a stalled pipeline looks identical to a closed
    mandi, and the freshness gate would silently blame the farmer's crop.
    """
    __tablename__ = "data_refresh_runs"

    id            = Column(Integer, primary_key=True, index=True)
    started_at    = Column(DateTime(timezone=True), nullable=False, index=True)
    finished_at   = Column(DateTime(timezone=True))
    status        = Column(String(20), nullable=False, index=True)
    trigger       = Column(String(20), nullable=False, default="manual")

    rows_fetched   = Column(Integer, default=0)
    rows_validated = Column(Integer, default=0)
    rows_rejected  = Column(Integer, default=0)
    rows_duplicate = Column(Integer, default=0)
    rows_inserted  = Column(Integer, default=0)

    # Newest market date known to the DB before and after this run.
    prev_newest_date = Column(DateTime(timezone=True))
    new_newest_date  = Column(DateTime(timezone=True))

    error          = Column(Text)
    details        = Column(JSONB)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
