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
from backend.core.dates import current_season as _current_season
from fastapi import APIRouter, Depends, HTTPException, Request, Header, BackgroundTasks
from backend.services.whatsapp import mark_message_as_read, send_typing_indicator_workaround
from backend.core.database import AsyncSessionLocal
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.models import CropDeclaration, ChatHistory, MandiPrice
from backend.services.whatsapp import send_message as wa_send, send_feedback_buttons
from sqlalchemy import desc, select

from backend.services import message_handler as mh
from backend.services.message_handler import Intent
from backend.services import ml_service, farmer_service
from backend.services.rag import get_agronomy_advice

router = APIRouter(prefix="/webhook", tags=["webhook"])

@router.get("/whatsapp")
async def whatsapp_verify(request: Request) -> PlainTextResponse:
    mode      = request.query_params.get("hub.mode")
    token     = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
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
            elif ml_service.MODEL is not None:
                # Fetch the latest recorded modal price for this crop+district.
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
                latest_price_row = price_row.scalar_one_or_none()
                if latest_price_row is None:
                    reply = f"ಕ್ಷಮಿಸಿ, {crop} ಬೆಳೆಗೆ {district} ಜಿಲ್ಲೆಯ ಇತ್ತೀಚಿನ ಬೆಲೆ ಮಾಹಿತಿ ನಮ್ಮ ಡೇಟಾಬೇಸ್‌ನಲ್ಲಿ ಲಭ್ಯವಿಲ್ಲ. — KisanMitra 🌾"
                else:
                    current_price = float(latest_price_row)

                    # Fetch latest arrivals_tonnes for this crop+district.
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
                    latest_arr = arr_row.scalar_one_or_none()
                    arrivals   = float(latest_arr) if latest_arr else 100.0

                    X = await ml_service.build_features(current_price, arrivals, date.today().month, crop, district, db)
                    try:
                        pred_res = ml_service.make_prediction(X, current_price)
                        pred = pred_res["pred"]
                        _, sk = ml_service.price_signal(pred, current_price)
                        reply = (
                            f"🌾 KisanMitra ಬೆಲೆ ಮಾಹಿತಿ\n\n"
                            f"{crop} — {district}\n"
                            f"ಇಂದಿನ ಬೆಲೆ: ₹{current_price:.0f}/ಕ್ವಿಂಟಾಲ್\n"
                            f"60-ದಿನ ಮುನ್ಸೂಚನೆ: ₹{pred:.0f}/ಕ್ವಿಂಟಾಲ್\n\n"
                            f"{sk}\n\n— KisanMitra 🌾"
                        )
                    except Exception as err:
                        reply = f"ಕ್ಷಮಿಸಿ, {crop} ಬೆಲೆ ಮುನ್ಸೂಚನೆ ಲಭ್ಯವಿಲ್ಲ. — KisanMitra 🌾"
            else:
                reply = "ಮಾಡೆಲ್ ಲೋಡ್ ಆಗಿಲ್ಲ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ. — KisanMitra 🌾"

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
        

