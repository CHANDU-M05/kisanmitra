"""
telegram_bot/formatters.py — One result object → one formatted Telegram message.

The backend returns a structured dict with `type` as the discriminator.
Telegram-specific formatting (Markdown, emoji, line length) lives here only.
The backend_client and handlers are format-agnostic.

All text is bilingual: English + key Kannada terms so the message is useful
even if the farmer doesn't read English.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("kisanmitra.telegram.formatters")

# ── Reliability label lookup ─────────────────────────────────────────────────

def _reliability(mape: float | None) -> str:
    if mape is None:
        return "Unknown"
    if mape <= 12:
        return "✅ High"
    if mape <= 22:
        return "⚠️ Moderate"
    return "🔴 Low"


# ── Per-result formatters ────────────────────────────────────────────────────

def format_forecast(r: dict) -> str:
    direction = "📈" if r["forecast"] > r["current_price"] else "📉"
    msp_line  = f"\nMSP Floor: ₹{r['msp_floor']:,.0f}/q" if r.get("msp_floor") else ""
    fallback_note = (
        "\n\n_💡 Note: Showing Tomato in Chikkaballapur by default. "
        "Specify your crop and district for custom results!_"
        if r.get("is_fallback_default") else ""
    )
    return (
        f"*{r['crop']} — 60-Day Forecast* {direction}\n"
        f"District: {r['district']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Today's Price: ₹{r['current_price']:,.0f}/quintal\n"
        f"Forecast: *₹{r['forecast']:,.0f}* (₹{r['lower']:,.0f}–₹{r['upper']:,.0f})\n"
        f"Signal: {r['signal']}\n"
        f"{r.get('signal_kannada', '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Model Reliability: {_reliability(r.get('crop_mape_pct'))}"
        f"{msp_line}{fallback_note}\n\n"
        f"_Forecasts are estimates; actual mandi prices may vary. — KisanMitra 🌾_"
    )


def format_anomaly(r: dict) -> str:
    a_type = r.get("anomaly_type", "SPIKE")
    icon   = "🚀" if a_type == "SPIKE" else "💥"
    direction = "📈" if r.get("forecast", 0) > r.get("current_price", 0) else "📉"
    msp_line  = f"\nMSP Floor: ₹{r['msp_floor']:,.0f}/q" if r.get("msp_floor") else ""
    return (
        f"*{r['crop']} — 60-Day Forecast* {direction}\n"
        f"District: {r['district']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Today's Price: ₹{r['current_price']:,.0f}/quintal\n"
        f"Forecast: *₹{r['forecast']:,.0f}* (₹{r.get('lower', r['forecast']*0.85):,.0f}–₹{r.get('upper', r['forecast']*1.15):,.0f})\n"
        f"Signal: {r.get('signal', 'NEUTRAL')}\n"
        f"{r.get('signal_kannada', '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Model Reliability: {_reliability(r.get('crop_mape_pct'))}{msp_line}\n\n"
        f"⚠️ *Anomaly Alert — {a_type}* {icon}\n"
        f"Deviation: *{r['deviation_pct']:.1f}%* (threshold: 30%)\n"
        f"This forecast shows a large price movement. "
        f"_Human-in-the-Loop Validation Active — KisanMitra 🌾_"
    )


def format_saturation(r: dict) -> str:
    fallback_note = (
        "\n\n_💡 Note: Showing Tomato in Chikkaballapur by default. "
        "Specify your crop and district for custom results!_"
        if r.get("is_fallback_default") else ""
    )
    return (
        f"*{r['crop']} Saturation — {r['district']}* {r.get('emoji', '📊')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Saturation: *{r['saturation_pct']:.0f}%*\n"
        f"Risk Level: *{r['risk_level']}*\n"
        f"{r.get('risk_kannada', '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Farmers registered: {r.get('farmer_count', 0)}\n"
        f"Total area: {r.get('total_area', 0):.1f} acres{fallback_note}\n\n"
        f"_KisanMitra 🌾 — ಶ್ರೇಷ್ಠ ಬೆಳೆ ನಿರ್ಧಾರಗಳಿಗೆ_"
    )


def format_declaration(r: dict) -> str:
    risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(r.get("risk_level", ""), "📊")
    is_update = r.get("is_update", False)
    heading   = "✅ *Crop Declaration Updated!*" if is_update else "✅ *Crop Declaration Recorded!*"
    action    = "Updated to" if is_update else "Planted area"
    return (
        f"{heading}\n\n"
        f"Crop: *{r['crop']}* — {action} {r['area']} acres\n"
        f"District: {r['district']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{risk_icon} District Saturation: *{r['saturation_pct']:.0f}%*\n"
        f"Risk: *{r.get('risk_level', '—')}*\n"
        f"{r.get('risk_kannada', '')}\n\n"
        f"_Your declaration helps all farmers in {r['district']} plan better. — KisanMitra 🌾_"
    )


def format_declaration_prompt(r: dict) -> str:
    return (
        f"📝 *Crop Declaration Confirmation*\n\n"
        f"Would you like to record this crop declaration in our database?\n"
        f"• Crop: *{r['crop']}*\n"
        f"• District: *{r['district']}*\n"
        f"• Planted Area: *{r['area']} acres*\n\n"
        f"_Recording your sowing helps all farmers in {r['district']} track district saturation and avoid market crashes. — KisanMitra 🌾_"
    )


def format_advisory(r: dict) -> str:
    return r.get("text", "Sorry, I couldn't get agronomy advice right now. Please try again.")


def format_help() -> str:
    return (
        "🌾 *KisanMitra — ಕೃಷಿ ಮಿತ್ರ*\n\n"
        "I can help you with:\n"
        "• *Price Forecast* — 60-day price prediction for your crop\n"
        "• *Saturation Check* — how many farmers are planting the same crop\n"
        "• *Declare Crop* — register your sowing so others can plan too\n"
        "• *Agronomy Advice* — disease, fertilizer, irrigation questions\n\n"
        "Use the menu buttons below, or just type naturally:\n"
        "_\"tomato price in kolar\"_\n"
        "_\"2 acres ragi in dharwad\"_\n"
        "_\"how to treat brinjal wilt?\"_\n\n"
        "— KisanMitra 🌾"
    )


def format_error(r: dict) -> str:
    detail = r.get("detail", "An error occurred. Please try again in a moment.")
    return f"⚠️ {detail}\n\n_KisanMitra 🌾_"


def format_about() -> str:
    return (
        "🌾 *About KisanMitra*\n\n"
        "KisanMitra is an AI-powered agricultural market intelligence platform "
        "for smallholder farmers across Karnataka.\n\n"
        "*What we do:*\n"
        "• 60-day price forecasting using AGMARKNET market data\n"
        "• District-level crop saturation monitoring (31 districts)\n"
        "• Crowd-sourced sowing declaration to prevent herd-planting\n"
        "• Agronomy advice via AI (RAG-based, crop-specific)\n\n"
        "*Data source:* AGMARKNET, Karnataka Dept. of Agriculture\n"
        "*Model:* Grouped Gradient Boosted Trees "
        "(Storable vs Perishable crop cohorts)\n"
        "*Evaluation:* 13.90% MAPE · ₹268/q MAE · R² 0.6853\n"
        "_(27.6% improvement over baseline Random Forest)_\n\n"
        "_Developed at Atria Institute of Technology, Bengaluru — KisanMitra 🌾_"
    )


# ── Dispatch ─────────────────────────────────────────────────────────────────

def format_result(result: dict) -> str:
    """Route a structured backend result to its formatter."""
    t = result.get("type", "error")
    try:
        if t == "forecast":           return format_forecast(result)
        if t == "anomaly_flagged":    return format_anomaly(result)
        if t == "saturation":         return format_saturation(result)
        if t == "declaration":        return format_declaration(result)
        if t == "declaration_prompt": return format_declaration_prompt(result)
        if t == "advisory":           return format_advisory(result)
        if t == "help":               return format_help()
        if t == "error":              return format_error(result)
        return format_error({"detail": f"Unknown response type: {t!r}"})
    except Exception as exc:
        logger.exception("Formatter error for type=%s: %s", t, exc)
        return "⚠️ Could not format the response. Please try again. — KisanMitra 🌾"
