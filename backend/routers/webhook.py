"""
api/routers/webhook.py - WhatsApp Webhook Integration

This module handles the core communication flow with Meta's WhatsApp Cloud API.
The flow is as follows:
1. Meta sends an HTTPS request (GET for verification, POST for message delivery).
2. For POST, we verify the HMAC signature (Guardrail 4) to ensure authenticity.
3. The message is passed to `message_handler.py` to determine the user's intent.
4. The system delegates logic based on the intent (e.g., getting ML price, RAG agronomy advice).
5. The response is sent back via the WhatsApp API and logged to the ChatHistory database.
"""
from datetime import date
import hmac
import hashlib
import logging
import secrets
from backend.core.dates import current_season as _current_season
from fastapi import APIRouter, Depends, HTTPException, Request, Header, BackgroundTasks
from backend.services.whatsapp import mark_message_as_read, send_typing_indicator_workaround
from backend.core.database import AsyncSessionLocal
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import is_known_compromised_secret, settings
from backend.core.database import get_db
from backend.core.models import CropDeclaration, ChatHistory, MandiPrice
from backend.services.whatsapp import send_message as wa_send, send_feedback_buttons
from sqlalchemy import desc, select

from backend.services import message_handler as mh
from backend.services.price_service import get_price_forecast
from backend.services.message_handler import Intent
from backend.services import ml_service, farmer_service
from backend.services.rag import get_agronomy_advice

router = APIRouter(prefix="/webhook", tags=["webhook"])

@router.get("/whatsapp")
async def whatsapp_verify(request: Request) -> PlainTextResponse:
    mode      = request.query_params.get("hub.mode")
    token     = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    expected  = settings.whatsapp_verify_token
    # An unconfigured verify token must refuse, not match: with the old `==`
    # comparison a caller could pass an empty hub.verify_token and be handed a
    # 200 whenever WHATSAPP_VERIFY_TOKEN was simply unset.
    if not expected:
        logging.getLogger("kisanmitra.webhook").error(
            "webhook verification refused: WHATSAPP_VERIFY_TOKEN is not configured"
        )
        raise HTTPException(503, "Webhook verification is not configured.")
    if is_known_compromised_secret(expected):
        # Not a refusal: development hosts legitimately run with the documented
        # example value. Production startup already rejects it (config
        # .validate_production_settings), so this only leaves an audit trail of
        # a handshake secured by a publicly known token.
        logging.getLogger("kisanmitra.webhook").warning(
            "WHATSAPP_VERIFY_TOKEN is a value published in this repository's "
            "history; rotate it before exposing this endpoint.")
    if (mode == "subscribe" and token is not None
            and secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))):
        return PlainTextResponse(content=challenge, status_code=200)
    raise HTTPException(403, "Verification failed")

def verify_signature(payload: bytes, signature_header: str) -> bool:
    if not settings.whatsapp_app_secret:
        if settings.app_env == "development":
            return True
        return False
        
    if not signature_header:
        return False

    expected_hash = hmac.new(
        settings.whatsapp_app_secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected_hash}", signature_header)


def _stale_reason_kn(result: dict) -> str:
    """
    Why no current price exists, in the farmer's language. A feed-wide outage
    and a missing crop record are different facts; saying so stops the farmer
    treating a pipeline delay as a market signal.
    """
    feed = result.get("feed_newest_date") or "ಕೊನೆಯ ದಾಖಲಿತ ಸেশನ್"
    reason = result.get("stale_reason")
    if reason == "upstream_not_published":
        return (f"ಕರ್ನಾಟಕದ ಯಾವುದೇ ಮಾರುಕಟ್ಟೆಗೂ {feed} ನಂತರ ಹೊಸ ದತ್ತಾಂಶ "
                f"ಪ್ರಕಟವಾಗಿಲ್ಲ — ಇದು ದತ್ತಾಂಶ ವಿಳಂಬ, ನಿಮ್ಮ ಬೆಳೆಯ ಸಮಸ್ಯೆಯಲ್ಲ.")
    if reason == "crop_gap":
        return (f"{feed} ವರೆಗೆ ಮಾರುಕಟ್ಟೆ ದತ್ತಾಂಶ ದಾಖಲಾಗಿದೆ, ಆದರೆ "
                f"{result.get('crop', 'ಈ ಬೆಳೆ')} ಇನ್ನೂ ವರದಿಯಾಗಿಲ್ಲ.")
    if reason == "upstream_stalled_with_crop_gap":
        return (f"ಕರ್ನಾಟಕದ ಮಾರುಕಟ್ಟೆ ದತ್ತಾಂಶ {feed} ({result.get('feed_age_days', '?')} "
                f"ದಿನಗಳ ಹಿಂದೆ) ನಲ್ಲಿ ನಿಂತಿದೆ; ಈ ಬೆಳೆಯ ಕೊನೆಯ ದಾಖಲೆ ಇನ್ನೂ ಹಳೆಯದಾಗಿದೆ. "
                f"ಇದು ದತ್ತಾಂಶ ವಿಳಂಬ ಹೊರತು ಮಾರುಕಟ್ಟೆ ಸೂಚನೆಯಲ್ಲ.")
    return "ಹೊಸ ಮಾರುಕಟ್ಟೆ ದಾಖಲೆ ಇನ್ನೂ ತಲುಪಿಲ್ಲ."


@router.post("/whatsapp")
async def whatsapp_message(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(None),
) -> dict:
    # ── Security: HMAC Signature Verification ──
    raw_body = await request.body()
    if not verify_signature(raw_body, x_hub_signature_256):
        raise HTTPException(403, "Invalid webhook signature")

    import json
    try:
        body = json.loads(raw_body)
        msg_data = body["entry"][0]["changes"][0]["value"]["messages"][0]
        phone    = msg_data["from"]
        msg_type = msg_data["type"]
        msg_id   = msg_data.get("id")
    except (KeyError, IndexError, json.JSONDecodeError):
        return {"status": "ok"}
        
    background_tasks.add_task(process_whatsapp_message_bg, phone, msg_type, msg_data, msg_id)
    return {"status": "ok"}

async def process_whatsapp_message_bg(phone: str, msg_type: str, msg_data: dict, msg_id: str):
    if msg_id:
        await mark_message_as_read(msg_id)
        await send_typing_indicator_workaround(phone)
        
    async with AsyncSessionLocal() as db:

    # ── Handle Interactive Feedback (Directive 4) ──
        if msg_type == "interactive":
            reply_id = msg_data["interactive"]["button_reply"]["id"]
            score = 1 if reply_id == "feedback_positive" else -1
        
            # Update last assistant message score
            stmt = (
                select(ChatHistory)
                .where(ChatHistory.phone_number == phone, ChatHistory.role == "assistant")
                .order_by(desc(ChatHistory.created_at))
                .limit(1)
            )
            res = await db.execute(stmt)
            last_msg = res.scalar_one_or_none()
            if last_msg:
                last_msg.feedback_score = score
                await db.commit()
                await wa_send(phone, "ಧನ್ಯವಾದಗಳು! (Thank you for the feedback!)")
            return {"status": "ok"}

        text = msg_data.get("text", {}).get("body", "").strip()
        if not text:
            return {"status": "ok"}

        parsed = mh.parse(text)
        
        # Session Memory Entity Resolution
        from backend.services import context_service
        active_crop, active_district = await context_service.resolve_session_entities(phone, db)
        
        crop = parsed.crop or active_crop
        district = parsed.district or active_district
    
        # Log Incoming (Directive 2)
        db.add(ChatHistory(
            phone_number=phone,
            role="user",
            message_content=text,
            intent_category=parsed.intent.name,
            crop=crop,
            district=district
        ))

        is_agronomy = False
        if parsed.intent == Intent.PRICE_QUERY:
            if not crop or not district:
                reply = (
                    "🌾 KisanMitra ಬೆಲೆ ಮಾಹಿತಿ\n\n"
                    "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಬೆಳೆ ಮತ್ತು ಜಿಲ್ಲೆಯ ಹೆಸರು ತಿಳಿಸಿ.\n"
                    "ಉದಾಹರಣೆಗೆ: 'ಕೋಲಾರ ಟೊಮ್ಯಾಟೊ ಬೆಲೆ' ಎಂದು ಟೈಪ್ ಮಾಡಿ. — KisanMitra 🌾"
                )
            else:
                # Reuse the canonical price handler so WhatsApp cannot invent a
                # spot price or diverge from the web/Telegram forecast logic.
                try:
                    result = await get_price_forecast(crop, district, db)
                    result_type = result.get("type")

                    if result_type == "no_data":
                        reply = (
                            f"🌾 KisanMitra ಬೆಲೆ ಮಾಹಿತಿ\n\n"
                            f"{crop} ಬೆಳೆಗಾಗಿ {district} ಜಿಲ್ಲೆಯಲ್ಲಿ ಇತ್ತೀಚಿನ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಲಭ್ಯವಿಲ್ಲ.\n"
                            "ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ ಅಥವಾ ಲಭ್ಯವಿರುವ ಮತ್ತೊಂದು ಮಾರುಕಟ್ಟೆಯ ಮಾಹಿತಿ ಪರಿಶೀಲಿಸಿ."
                            " — KisanMitra 🌾"
                        )
                    elif result_type == "stale_data":
                        # Freshness SLA breach — tell the farmer WHY there is no
                        # forecast instead of the generic processing-failure text.
                        reply = (
                            f"🌾 KisanMitra ಬೆಲೆ ಮಾಹಿತಿ\n\n"
                            f"{crop} — {district}\n"
                            f"ಕೊನೆಯ ದಾಖಲೆ: {result.get('price_as_of') or 'ದಿನಾಂಕ ತಿಳಿದಿಲ್ಲ'} "
                            f"({result.get('days_old', '?')} ದಿನಗಳ ಹಿಂದೆ) — "
                            f"{result.get('max_age_days', 3)} ದಿನಗಳ ಮಿತಿ ಮೀರಿದೆ.\n"
                            f"ಕೊನೆಯ ದಾಖಲಿತ ಬೆಲೆ: ₹{result.get('current_price', 0):.0f}/ಕ್ವಿಂಟಾಲ್ "
                            f"({result.get('source_market') or 'ಮಾರುಕಟ್ಟೆ ತಿಳಿದಿಲ್ಲ'})\n"
                            f"{_stale_reason_kn(result)}\n"
                            "ಹಳೆಯ ಬೆಲೆಯಿಂದ ಮುನ್ಸೂಚನೆ ನೀಡುವುದಿಲ್ಲ. ಮುಂದಿನ ಮಾರುಕಟ್ಟೆ "
                            "ದಿನದ ನಂತರ ಪುನಃ ಕೇಳಿ. — KisanMitra 🌾"
                        )
                    elif result_type == "error":
                        reply = "ಕ್ಷಮಿಸಿ, ಈಗ ಬೆಲೆ ಮುನ್ಸೂಚನೆ ಲಭ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ. — KisanMitra 🌾"
                    elif result_type in {"forecast", "anomaly_flagged"}:
                        source_note = ""
                        if result.get("data_source") == "state_fallback":
                            source_note = (
                                f"\nಗಮನಿಸಿ: {district} ಜಿಲ್ಲೆಯ ನೇರ ಬೆಲೆ ಲಭ್ಯವಿಲ್ಲ. "
                                f"ರಾಜ್ಯ ಮಟ್ಟದ ಪರ್ಯಾಯ ಮಾಹಿತಿ: {result.get('source_market') or 'ಮಾರುಕಟ್ಟೆ ತಿಳಿದಿಲ್ಲ'}."
                            )
                        as_of = result.get("price_as_of") or "ದಿನಾಂಕ ಲಭ್ಯವಿಲ್ಲ"
                        degraded = set(result.get("data_quality") or []) & {
                            "arrivals_unknown", "arrivals_imputed", "history_sparse",
                            "arrivals_other_market", "arrivals_date_mismatch",
                            "other_market_price", "arrival_date_missing",
                        }
                        quality_note = (
                            "\nಗಮನಿಸಿ: ಕೆಲ ಮಾಹಿತಿ ಅಪೂರ್ಣ — ಮುನ್ಸೂಚನೆ ಅಂದಾಜು."
                            if degraded else ""
                        )
                        reply = (
                            f"🌾 KisanMitra ಬೆಲೆ ಮಾಹಿತಿ\n\n"
                            f"{crop} — {district}\n"
                            f"ದಾಖಲಾದ ಬೆಲೆ: ₹{result['current_price']:.0f}/ಕ್ವಿಂಟಾಲ್\n"
                            f"ಬೆಲೆ ದಿನಾಂಕ: {as_of}\n"
                            f"60-ದಿನ ಮುನ್ಸೂಚನೆ: ₹{result['forecast']:.0f}/ಕ್ವಿಂಟಾಲ್\n"
                            f"{result.get('signal_kannada', 'ಸಿಗ್ನಲ್ ಲಭ್ಯವಿಲ್ಲ')}"
                            f"{source_note}{quality_note}\n\n— KisanMitra 🌾"
                        )
                    else:
                        reply = "ಕ್ಷಮಿಸಿ, ಬೆಲೆ ಮಾಹಿತಿ ಪ್ರಕ್ರಿಯೆಗೊಳಿಸಲಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ. — KisanMitra 🌾"
                except Exception:
                    # Do not expose internal exception details to the farmer.
                    import logging
                    logging.getLogger("kisanmitra.webhook").exception("WhatsApp price query failed")
                    reply = "ಕ್ಷಮಿಸಿ, ಈಗ ಬೆಲೆ ಮುನ್ಸೂಚನೆ ಲಭ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ. — KisanMitra 🌾"

        elif parsed.intent == Intent.DECLARE_CROP:
            if not crop or not district:
                reply = (
                    "🌱 KisanMitra ಬೆಳೆ ದಾಖಲಾತಿ\n\n"
                    "ದಯವಿಟ್ಟು ಬೆಳೆ ಮತ್ತು ಜಿಲ್ಲೆಯ ಹೆಸರು ತಿಳಿಸಿ.\n"
                    "ಉದಾಹರಣೆಗೆ: '2 ಎಕರೆ ಕೋಲಾರ ಟೊಮ್ಯಾಟೊ' ಎಂದು ಟೈಪ್ ಮಾಡಿ. — KisanMitra 🌾"
                )
            else:
                area     = parsed.area or 1.0
                season   = _current_season()
                decl = CropDeclaration(
                    farmer_name="WhatsApp Farmer",
                    phone=phone,
                    village="",
                    district=district,
                    crop=crop,
                    area_acres=area,
                    season=season,
                    trust_score=0.85,
                    satellite_status="pending",
                )
                db.add(decl)
                sat   = await farmer_service.calc_saturation(district, crop, season, db)
                reply = (
                    f"✅ ನಿಮ್ಮ {crop} ({area} ಎಕರೆ) ದಾಖಲಾಗಿದೆ.\n\n"
                    f"📍 {district}:\n"
                    f"{sat['emoji']} {crop} saturation: {sat['saturation_pct']:.0f}% "
                    f"({sat['risk_level']} RISK)\n{sat['risk_kannada']}\n\n— KisanMitra 🌾"
                )

        elif parsed.intent == Intent.SATURATION_CHECK:
            if not crop or not district:
                reply = (
                    "📍 KisanMitra ಸ್ಯಾಚುರೇಷನ್ ಮಾಹಿತಿ\n\n"
                    "ದಯವಿಟ್ಟು ಬೆಳೆ ಮತ್ತು ಜಿಲ್ಲೆಯ ಹೆಸರು ತಿಳಿಸಿ.\n"
                    "ಉದಾಹರಣೆಗೆ: 'ಕೋಲಾರ ಟೊಮ್ಯಾಟೊ ಸ್ಯಾಚುರೇಷನ್' ಎಂದು ಟೈಪ್ ಮಾಡಿ. — KisanMitra 🌾"
                )
            else:
                sat   = await farmer_service.calc_saturation(district, crop, _current_season(), db)
                reply = (
                    f"📍 {district} — {crop}\n"
                    f"{sat['emoji']} Saturation: {sat['saturation_pct']:.0f}%\n"
                    f"Risk: {sat['risk_level']} — {sat['risk_kannada']}\n"
                )

        elif parsed.intent == Intent.AGRONOMY_ADVICE:
            reply = await get_agronomy_advice(text, db, crop=crop, phone_number=phone)
            is_agronomy = True

        else:
            reply = (
                "ನಮಸ್ಕಾರ! \n"
                "• ಬೆಲೆ ತಿಳಿಯಲು: 'ಟೊಮ್ಯಾಟೊ ಬೆಲೆ' ಎಂದು ಟೈಪ್ ಮಾಡಿ\n"
                "• ಬೆಳೆ ದಾಖಲಿಸಲು: '2 ಎಕರೆ ಟೊಮ್ಯಾಟೊ' ಎಂದು ಟೈಪ್ ಮಾಡಿ\n"
                "• ಅಪಾಯ ತಿಳಿಯಲು: 'ಸ್ಯಾಚುರೇಷನ್' ಎಂದು ಟೈಪ್ ಮಾಡಿ\n"
                "— KisanMitra 🌾"
            )

        # Log Outgoing (Directive 2)
        db.add(ChatHistory(
            phone_number=phone,
            role="assistant",
            message_content=reply,
            intent_category=parsed.intent.name,
            crop=crop,
            district=district
        ))
    
        await db.commit()

    # Dispatch (Directive 3)
        if is_agronomy:
            await send_feedback_buttons(phone, reply)
        else:
            await wa_send(phone, reply)
        

