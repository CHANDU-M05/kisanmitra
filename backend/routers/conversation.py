"""
backend/routers/conversation.py — Channel-agnostic conversation endpoint

POST /api/v1/conversation/message

This is the single shared entry point for ALL channel integrations
(WhatsApp webhook, Telegram bot, future SMS/IVRS channels).

Architecture contract:
  - Receives: { sender_id, text, channel, crop?, district?, area? }
  - Returns:  { type, ... }  — a structured result the channel layer formats.
  - The bot/channel NEVER imports ML or RAG code directly. Only this endpoint does.

This enforces the "channel-independent core" principle: if a channel could import
services directly, shortcuts get taken and channels get coupled to each other.
"""
from __future__ import annotations

import datetime
import logging
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.dates import current_season as _current_season
from backend.core.models import ChatHistory, CropDeclaration, MandiPrice
from backend.services import farmer_service, message_handler as mh, ml_service
from backend.services.message_handler import Intent
from backend.services.rag import get_agronomy_advice

logger = logging.getLogger("kisanmitra.conversation")

router = APIRouter(prefix="/api/v1/conversation", tags=["conversation"])


# ── Request / Response shapes ─────────────────────────────

class ConversationRequest(BaseModel):
    sender_id: str          # phone number for WhatsApp, Telegram user_id as str for Telegram
    text: str               # raw user message
    channel: str = "web"   # "whatsapp" | "telegram" | "web"
    farmer_name: Optional[str] = None # Optional actual display name from Telegram/WhatsApp profile
    # Optional pre-resolved entities from button flows (skip NLP parsing):
    crop: Optional[str] = None
    district: Optional[str] = None
    area: Optional[float] = None
    # Explicit intent override — set by button flows so NLP classification is skipped
    # entirely for queries where the intent is already known from UI context.
    # Values mirror Intent enum names: "PRICE_QUERY" | "DECLARE_CROP" | "SATURATION_CHECK"
    intent: Optional[str] = None


# ── Handler ───────────────────────────────────────────────

@router.post("/message")
async def conversation_message(
    body: ConversationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Shared conversation logic for all channels.
    Returns a structured dict with `type` as the discriminator:
      "forecast"       — price + 60-day prediction
      "saturation"     — district crop saturation %
      "declaration"    — crop sown confirmation
      "advisory"       — RAG agronomy text
      "anomaly_flagged"— high-deviation forecast (>30%) needing human review
      "help"           — unknown intent help message
      "error"          — model/data unavailable
    """
    # If the caller pre-resolved entities (button flows), synthesise a text for NLP
    # so ChatHistory is always human-readable.
    synthetic_text = body.text
    if body.crop and not body.text.strip():
        parts = [body.crop]
        if body.district:
            parts.append(body.district)
        if body.area:
            parts.append(f"{body.area} acres")
        synthetic_text = " ".join(parts)

    # ── Parse intent ─────────────────────────────────────
    # Button flows pass body.intent explicitly — skip NLP classification entirely.
    # Free-text flows leave body.intent=None and go through message_handler.parse().
    if body.intent:
        parsed = mh.parse("price")  # get a ParsedMessage shell with correct typing
        # Override the intent with the caller-declared one.
        try:
            parsed = mh.ParsedMessage(
                intent=Intent[body.intent],
                crop=body.crop or mh.resolve_crop(body.text),
                district=body.district or mh.resolve_district(body.text),
                area=body.area or mh.extract_area(body.text),
                raw_text=body.text,
            )
        except KeyError:
            logger.warning("Unknown explicit intent=%r, falling back to NLP.", body.intent)
            parsed = mh.parse(synthetic_text)
    else:
        parsed = mh.parse(synthetic_text)

    # Allow callers to override NLP-parsed entities with pre-resolved button values.
    # Multi-turn Context Recovery:
    # 1. Scope context to (sender_id, channel) with a 24-hour TTL recency window.
    # 2. If crop or district is omitted in current turn, recover context from previous turns.
    has_explicit_current_entity = bool(body.crop or parsed.crop or body.district or parsed.district)

    crop, district, crop_from_ctx, dist_from_ctx, crop_used_def, dist_used_def = await _resolve_conversation_context(
        sender_id=body.sender_id,
        channel=body.channel,
        body_crop=body.crop,
        parsed_crop=parsed.crop,
        body_district=body.district,
        parsed_district=parsed.district,
        db=db,
    )
    area = body.area or parsed.area or 1.0
    is_fallback_default = crop_used_def or dist_used_def

    # CRITICAL GUARD: Intent carryover ONLY triggers if the user explicitly provided an entity
    # in the CURRENT turn (e.g., "what about Belagavi?") but omitted the intent keyword.
    # Greetings/chitchat ("hello", "thanks") specify NO entity -> intent remains UNKNOWN -> returns help.
    if parsed.intent == Intent.UNKNOWN and has_explicit_current_entity:
        prev_intent = await _get_previous_intent(body.sender_id, body.channel, db)
        if prev_intent:
            parsed = mh.ParsedMessage(
                intent=prev_intent,
                crop=crop,
                district=district,
                area=area,
                raw_text=synthetic_text,
            )

    # ── Log incoming ─────────────────────────────────────
    db.add(ChatHistory(
        phone_number=body.sender_id,
        channel=body.channel,
        role="user",
        message_content=body.text or synthetic_text,
        intent_category=parsed.intent.name,
        crop=crop,
        district=district,
    ))

    result: dict = {}

    try:
        if parsed.intent == Intent.PRICE_QUERY:
            result = await _handle_price(crop, district, db)

        elif parsed.intent == Intent.DECLARE_CROP:
            result = await _handle_declare(
                body.sender_id, crop, district, area, db,
                channel=body.channel, farmer_name=body.farmer_name,
            )

        elif parsed.intent == Intent.SATURATION_CHECK:
            result = await _handle_saturation(crop, district, db)

        elif parsed.intent == Intent.AGRONOMY_ADVICE:
            advice = await get_agronomy_advice(body.text, db, crop=crop)
            result = {"type": "advisory", "text": advice, "crop": crop}

        else:
            result = {"type": "help"}

    except Exception as exc:
        logger.exception("Conversation engine error for sender=%s: %s", body.sender_id, exc)
        result = {"type": "error", "detail": str(exc)}

    if isinstance(result, dict) and is_fallback_default and result.get("type") in ("forecast", "saturation"):
        result["is_fallback_default"] = True

    # ── Log outgoing ─────────────────────────────────────
    db.add(ChatHistory(
        phone_number=body.sender_id,
        channel=body.channel,
        role="assistant",
        message_content=str(result),
        intent_category=parsed.intent.name,
        crop=crop,
        district=district,
    ))
    await db.commit()

    return result


# ── Context Recovery Helpers ──────────────────────────────

_CONTEXT_TTL_HOURS = 24


async def _resolve_conversation_context(
    sender_id: str,
    channel: str,
    body_crop: Optional[str],
    parsed_crop: Optional[str],
    body_district: Optional[str],
    parsed_district: Optional[str],
    db: AsyncSession,
) -> tuple[str, str, bool, bool, bool, bool]:
    """
    Multi-turn Context Recovery (Scoped by sender_id + channel, 24h TTL):
    1. If crop is explicitly provided in request or parsed from text, use it.
       Otherwise, query ChatHistory for the last non-null crop for (sender_id, channel) within 24h.
       Fallback: "Tomato" (crop_used_default=True).
    2. If district is explicitly provided in request or parsed from text, use it.
       Otherwise, query ChatHistory for the last non-null district for (sender_id, channel) within 24h.
       Fallback: "Chikkaballapur" (dist_used_default=True).

    Returns: (crop, district, crop_from_ctx, dist_from_ctx, crop_used_default, dist_used_default)
    """
    resolved_crop = body_crop or parsed_crop
    resolved_district = body_district or parsed_district
    crop_from_context = False
    district_from_context = False
    crop_used_default = False
    district_used_default = False

    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=_CONTEXT_TTL_HOURS)

    if not resolved_crop:
        res = await db.execute(
            select(ChatHistory.crop)
            .where(
                ChatHistory.phone_number == sender_id,
                ChatHistory.channel == channel,
                ChatHistory.crop.isnot(None),
                ChatHistory.created_at >= cutoff,
            )
            .order_by(ChatHistory.created_at.desc())
            .limit(1)
        )
        prev_crop = res.scalar_one_or_none()
        if prev_crop:
            resolved_crop = prev_crop
            crop_from_context = True
        else:
            resolved_crop = "Tomato"
            crop_used_default = True

    if not resolved_district:
        res = await db.execute(
            select(ChatHistory.district)
            .where(
                ChatHistory.phone_number == sender_id,
                ChatHistory.channel == channel,
                ChatHistory.district.isnot(None),
                ChatHistory.created_at >= cutoff,
            )
            .order_by(ChatHistory.created_at.desc())
            .limit(1)
        )
        prev_district = res.scalar_one_or_none()
        if prev_district:
            resolved_district = prev_district
            district_from_context = True
        else:
            resolved_district = "Chikkaballapur"
            district_used_default = True

    return resolved_crop, resolved_district, crop_from_context, district_from_context, crop_used_default, district_used_default


async def _get_previous_intent(sender_id: str, channel: str, db: AsyncSession) -> Optional[Intent]:
    """
    Fetch the most recent non-HELP/UNKNOWN intent for (sender_id, channel) within 24 hours.
    """
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=_CONTEXT_TTL_HOURS)
    res = await db.execute(
        select(ChatHistory.intent_category)
        .where(
            ChatHistory.phone_number == sender_id,
            ChatHistory.channel == channel,
            ChatHistory.intent_category.isnot(None),
            ChatHistory.intent_category != Intent.UNKNOWN.name,
            ChatHistory.created_at >= cutoff,
        )
        .order_by(ChatHistory.created_at.desc())
        .limit(1)
    )
    cat_name = res.scalar_one_or_none()
    if cat_name:
        try:
            return Intent[cat_name]
        except KeyError:
            return None
    return None


# ── Intent sub-handlers ───────────────────────────────────

async def _handle_price(crop: str, district: str, db: AsyncSession) -> dict:
    if ml_service.MODEL is None:
        return {"type": "error", "detail": "Model not loaded. Run scripts/03_train_model.py first."}

    price_row = await db.execute(
        select(MandiPrice.modal_price)
        .where(
            MandiPrice.commodity.ilike(crop),
            MandiPrice.district.ilike(district),
            MandiPrice.modal_price.isnot(None),
        )
        .order_by(MandiPrice.arrival_date.desc())
        .limit(1)
    )
    latest = price_row.scalar_one_or_none()
    if latest is None:
        return {
            "type": "error",
            "detail": f"No spot price found for {crop} in {district}.",
            "crop": crop,
            "district": district,
        }

    current_price = float(latest)

    arr_row = await db.execute(
        select(MandiPrice.arrivals_tonnes)
        .where(
            MandiPrice.commodity.ilike(crop),
            MandiPrice.district.ilike(district),
            MandiPrice.arrivals_tonnes.isnot(None),
        )
        .order_by(MandiPrice.arrival_date.desc())
        .limit(1)
    )
    arrivals = float(arr_row.scalar_one_or_none() or 100.0)

    X = await ml_service.build_features(
        current_price, arrivals, date.today().month, crop, district, db
    )
    pred_res = ml_service.make_prediction(X, current_price)
    pred = pred_res["pred"]
    low  = pred_res["low"]
    high = pred_res["high"]
    signal, signal_kn = ml_service.price_signal(pred, current_price)
    meta = ml_service.crop_prediction_meta(crop, current_price)

    deviation_pct = abs(pred - current_price) / max(current_price, 1) * 100
    is_anomaly    = deviation_pct > 30.0
    anomaly_type  = "SPIKE" if pred > current_price else ("CRASH" if pred < current_price else "NORMAL")

    base = {
        "crop":          crop,
        "district":      district,
        "current_price": round(current_price, 0),
        "forecast":      round(pred, 0),
        "lower":         round(low, 0),
        "upper":         round(high, 0),
        "signal":        signal,
        "signal_kannada":signal_kn,
        "is_anomaly":    is_anomaly,
        "anomaly_type":  anomaly_type,
        "deviation_pct": round(deviation_pct, 1),
        "crop_mape_pct": meta["crop_mape_pct"],
        "msp_floor":     meta["msp_floor"],
    }

    if is_anomaly:
        return {"type": "anomaly_flagged", **base}
    return {"type": "forecast", **base}


async def _handle_declare(
    sender_id: str, crop: str, district: str, area: float, db: AsyncSession,
    channel: str = "web", farmer_name: Optional[str] = None,
) -> dict:
    season = _current_season()
    if farmer_name and farmer_name.strip():
        cleaned = re.sub(r"[\r\n\t\x00-\x1f]", " ", farmer_name.strip())
        farmer_name = cleaned[:255].strip() or "KisanMitra Farmer"
    else:
        _CHANNEL_NAMES = {"whatsapp": "WhatsApp Farmer", "telegram": "Telegram Farmer"}
        farmer_name = _CHANNEL_NAMES.get(channel, "KisanMitra Farmer")

    # ── Single-query: dedup guard + is_update UX signal ─────────────────
    _DEDUP_WINDOW_SECONDS = 60
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=_DEDUP_WINDOW_SECONDS)

    prior_result = await db.execute(
        select(CropDeclaration)
        .where(
            CropDeclaration.phone == sender_id,
            CropDeclaration.crop.ilike(crop),
            CropDeclaration.district.ilike(district),
            CropDeclaration.season == season,
        )
        .order_by(CropDeclaration.declared_at.desc())
        .limit(1)
    )
    prior = prior_result.scalar_one_or_none()

    # Branch 1: within dedup window → this is a retry, not a new declaration.
    if prior is not None and prior.declared_at >= cutoff:
        logger.info(
            "Duplicate declaration suppressed (within %ds window): sender=%s crop=%s district=%s",
            _DEDUP_WINDOW_SECONDS, sender_id, crop, district,
        )
        sat = await farmer_service.calc_saturation(district, crop, season, db)
        return {
            "type":           "declaration",
            "crop":           crop,
            "district":       district,
            "area":           prior.area_acres,
            "saturation_pct": sat["saturation_pct"],
            "risk_level":     sat["risk_level"],
            "risk_kannada":   sat["risk_kannada"],
            "farmer_count":   sat["farmer_count"],
            "is_update":      False,  # dedup suppression, not a genuine update
        }

    # Branch 2: outside dedup window → either first declaration or genuine area update.
    is_update = prior is not None  # prior exists but is old → farmer is updating area

    # ── Upsert — atomically insert or update area on conflict ──────────────
    # ON CONFLICT uses index_elements matching the functional unique index
    # ON CONFLICT (lower(phone), lower(crop), lower(district), season).
    stmt = (
        pg_insert(CropDeclaration)
        .values(
            farmer_name=farmer_name,
            phone=sender_id,
            village="",
            district=district,
            crop=crop,
            area_acres=area,
            season=season,
            trust_score=0.85,
            satellite_status="pending",
        )
        .on_conflict_do_update(
            index_elements=[
                func.lower(CropDeclaration.phone),
                func.lower(CropDeclaration.crop),
                func.lower(CropDeclaration.district),
                CropDeclaration.season,
            ],
            set_={
                "area_acres":  area,
                "farmer_name": farmer_name,
                # declared_at intentionally not updated — the original timestamp
                # is preserved so the 60s SELECT window still works on further retries.
            },
        )
    )
    try:
        await db.execute(stmt)
    except IntegrityError:
        logger.warning(
            "IntegrityError suppressed in _handle_declare: sender=%s crop=%s district=%s",
            sender_id, crop, district,
        )
        await db.rollback()

    sat = await farmer_service.calc_saturation(district, crop, season, db)
    return {
        "type":            "declaration",
        "crop":            crop,
        "district":        district,
        "area":            area,
        "saturation_pct":  sat["saturation_pct"],
        "risk_level":      sat["risk_level"],
        "risk_kannada":    sat["risk_kannada"],
        "farmer_count":    sat["farmer_count"],
        "is_update":       is_update,
    }


async def _handle_saturation(crop: str, district: str, db: AsyncSession) -> dict:
    sat = await farmer_service.calc_saturation(district, crop, _current_season(), db)
    return {
        "type":           "saturation",
        "crop":           crop,
        "district":       district,
        "saturation_pct": sat["saturation_pct"],
        "risk_level":     sat["risk_level"],
        "risk_kannada":   sat["risk_kannada"],
        "farmer_count":   sat["farmer_count"],
        "total_area":     sat["total_area"],
        "emoji":          sat["emoji"],
    }
