import hmac
import hashlib
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.models import CropDeclaration, ChatHistory
from api.services.whatsapp import send_message as wa_send, send_feedback_buttons
from sqlalchemy import desc, select

from api.services import message_handler as mh
from api.services.message_handler import Intent
from api.services import ml_service, farmer_service
from api.services.rag import get_agronomy_advice

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
    if not settings.whatsapp_app_secret or not signature_header:
        return True if not settings.whatsapp_app_secret else False
    expected_hash = hmac.new(
        settings.whatsapp_app_secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected_hash}", signature_header)

@router.post("/whatsapp")
async def whatsapp_message(
    request: Request,
    x_hub_signature_256: str = Header(None),
    db: AsyncSession = Depends(get_db),
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
    except (KeyError, IndexError, json.JSONDecodeError):
        return {"status": "ok"}

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
            wa_send(phone, "ಧನ್ಯವಾದಗಳು! (Thank you for the feedback!)")
        return {"status": "ok"}

    # ── Standard Text Message ──
    text = msg_data.get("text", {}).get("body", "").strip()
    if not text:
        return {"status": "ok"}

    parsed = mh.parse(text)
    
    # Log Incoming (Directive 2)
    db.add(ChatHistory(
        phone_number=phone,
        role="user",
        message_content=text,
        intent_category=parsed.intent.value
    ))

    is_agronomy = False
    if parsed.intent == Intent.PRICE_QUERY:
        crop     = parsed.crop or "Tomato"
        district = parsed.district or "Chikkaballapur"
        if ml_service.MODEL is not None:
            X     = await ml_service.build_features(2000, 100, date.today().month, crop, district, db)
            pred  = float(ml_service.MODEL.predict(X)[0])
            _, sk = ml_service.price_signal(pred, 2000)
            reply = (
                f"🌾 KisanMitra ಬೆಲೆ ಮಾಹಿತಿ\n\n"
                f"{crop} — {district}\n"
                f"60-ದಿನ ಮುನ್ಸೂಚನೆ: ₹{pred:.0f}/ಕ್ವಿಂಟಾಲ್\n\n"
                f"{sk}\n\n— KisanMitra 🌾"
            )
        else:
            reply = "ಮಾಡೆಲ್ ಲೋಡ್ ಆಗಿಲ್ಲ. ದಯವಿಟ್ಟು ನಂತರ ಪ್ರಯತ್ನಿಸಿ. — KisanMitra 🌾"

    elif parsed.intent == Intent.DECLARE_CROP:
        crop     = parsed.crop or "Tomato"
        district = parsed.district or "Chikkaballapur"
        area     = parsed.area or 1.0
        decl = CropDeclaration(
            farmer_name="WhatsApp Farmer",
            phone=phone,
            village="",
            district=district,
            crop=crop,
            area_acres=area,
            season="kharif_2025",
        )
        db.add(decl)
        sat   = await farmer_service.calc_saturation(district, crop, "kharif_2025", db)
        reply = (
            f"✅ ನಿಮ್ಮ {crop} ({area} ಎಕರೆ) ದಾಖಲಾಗಿದೆ.\n\n"
            f"📍 {district}:\n"
            f"{sat['emoji']} {crop} saturation: {sat['saturation_pct']:.0f}% "
            f"({sat['risk_level']} RISK)\n{sat['risk_kannada']}\n\n— KisanMitra 🌾"
        )

    elif parsed.intent == Intent.SATURATION_CHECK:
        crop     = parsed.crop or "Tomato"
        district = parsed.district or "Chikkaballapur"
        sat   = await farmer_service.calc_saturation(district, crop, "kharif_2025", db)
        reply = (
            f"📍 {district} — {crop}\n"
            f"{sat['emoji']} Saturation: {sat['saturation_pct']:.0f}%\n"
            f"Risk: {sat['risk_level']} — {sat['risk_kannada']}\n"
            f"ರೈತರು: {sat['farmer_count']} · {sat['total_area']:.1f} ಎಕರೆ\n\n— KisanMitra 🌾"
        )

    elif parsed.intent == Intent.AGRONOMY_ADVICE:
        reply = await get_agronomy_advice(text, db, crop=parsed.crop)
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
        intent_category=parsed.intent.value
    ))
    
    await db.commit()

    # Dispatch (Directive 3)
    if is_agronomy:
        send_feedback_buttons(phone, reply)
    else:
        wa_send(phone, reply)
        
    return {"status": "ok"}
