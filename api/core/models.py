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

from api.core.database import Base

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
    )


class KnowledgeChunk(Base):
    """
    RAG knowledge base for the Kannada advisory bot.
    Uses pgvector Vector(1536) when available, otherwise Text.
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
    embedding  = Column(Vector(1536)) if _HAS_PGVECTOR else Column(Text, nullable=True)
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
    Conversation persistence and LLM telemetry.
    """
    __tablename__ = "chat_history"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number    = Column(String(20), index=True, nullable=False)
    role            = Column(String(20), nullable=False)  # user | assistant
    message_content = Column(Text, nullable=False)
    intent_category = Column(String(50))
    feedback_score  = Column(Integer)  # 1 (positive) | -1 (negative) | null
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
