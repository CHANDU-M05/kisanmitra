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

# Human-facing explanation of each degraded-provenance flag the service reports.
_QUALITY_NOTES = {
    "arrivals_unknown":      "Arrival tonnage is not recorded for this market — no tonnage was assumed",
    "arrivals_imputed":      "Arrival tonnage is not recorded for this market — model used an assumed value",
    "arrivals_other_market": "Arrival tonnage taken from a different mandi than the price",
    "arrivals_date_mismatch":"Arrival tonnage is from a different market day than the price",
    "arrivals_override":     "Arrival tonnage was supplied by the caller — this is a scenario, not an observation",
    "history_sparse":        "Fewer than 3 past records for this market — trend features are estimated",
    "arrival_date_missing":  "Market date of the price record is unknown",
    "other_market_price":    "No record in your area — price taken from another Karnataka mandi",
    "price_override":        "Price was supplied by the caller — this is a what-if scenario, not the mandi rate",
    "price_diverges_from_mandi": "The supplied price differs by more than 25% from the latest verified mandi price",
}


def _age_phrase(days_old) -> str:
    """' (3 days old)' / ' (1 day old)' / '' — never a misleading 'days 1 old'."""
    if not isinstance(days_old, int) or isinstance(days_old, bool):
        return ""
    if days_old <= 0:
        return " (today)"
    return f" ({days_old} day{'s' if days_old != 1 else ''} old)"


def _current_price_label(r: dict) -> str:
    """Only call it 'today's price' when the record is provably from today."""
    days_old = r.get("days_old")
    if isinstance(days_old, int) and not isinstance(days_old, bool) and days_old == 0:
        return "Today's Price"
    return "Latest recorded price"


def _freshness_notes(r: dict) -> str:
    """Honest sourcing lines: as-of date, which market, and any degraded inputs."""
    notes = []
    if r.get("price_as_of"):
        notes.append(f"_Spot price as of {r['price_as_of']}{_age_phrase(r.get('days_old'))}_")
    if r.get("data_source") == "state_fallback":
        src = r.get("source_market") or "another Karnataka mandi"
        notes.append(f"_No {r.get('crop', 'crop')} record found in {r.get('district', 'your district')} — using latest {src} price_")
    for flag in r.get("data_quality") or []:
        note = _QUALITY_NOTES.get(flag)
        if note:
            notes.append(f"_⚠ {note}_")
    return ("\n" + "\n".join(notes)) if notes else ""


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
        f"{_current_price_label(r)}: ₹{r['current_price']:,.0f}/quintal\n"
        f"Forecast: *₹{r['forecast']:,.0f}* (₹{r['lower']:,.0f}–₹{r['upper']:,.0f})\n"
        f"Signal: {r['signal']}\n"
        f"{r.get('signal_kannada', '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Model Reliability: {_reliability(r.get('crop_mape_pct'))}"
        f"{msp_line}{_freshness_notes(r)}{fallback_note}\n\n"
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
        f"{_freshness_notes(r)}\n"
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


def _stale_reason_line(r: dict) -> str:
    """
    Explain WHY there is no current price, using the distinction the service
    made. "The mandi has published nothing anywhere" and "this crop's market is
    missing" are different facts, and blurring them sends the farmer to check
    something that is not the problem.
    """
    reason = r.get("stale_reason")
    feed = r.get("feed_newest_date") or "the last recorded session"
    if reason == "upstream_not_published":
        return (
            f"AGMARKNET has published nothing newer than *{feed}* for any Karnataka "
            f"mandi — this is a data-feed delay, not a problem with your crop."
        )
    if reason == "crop_gap":
        return (
            f"Market data runs up to *{feed}*, but no mandi has reported "
            f"{r.get('crop', 'this crop')} there yet."
        )
    if reason == "upstream_stalled_with_crop_gap":
        # Both are true, and the feed-wide stall is the one the farmer needs to
        # know about — the crop-specific gap is a detail on top of it.
        return (
            f"Market data for all of Karnataka has stopped at *{feed}* "
            f"({r.get('feed_age_days', '?')} days ago), and the latest "
            f"{r.get('crop', 'this crop')} record is older still. This is a "
            f"data-feed delay, not a market signal."
        )
    return "A newer mandi record has not reached us yet."


def format_stale(r: dict) -> str:
    """Freshness SLA breach: report the last known price WITH its age, no forecast."""
    src = r.get("source_market") or "the last reported mandi"
    return (
        f"🕒 *No current price for {r.get('crop', 'this crop')} in {r.get('district', 'your district')}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"The latest mandi record is from *{r.get('price_as_of', 'an unknown date')}* "
        f"({r.get('days_old', '?')} days ago) — older than our {r.get('max_age_days', 3)}-day freshness limit.\n"
        f"Last recorded price: ₹{r.get('current_price', 0):,.0f}/quintal at {src}\n"
        f"{_stale_reason_line(r)}\n\n"
        f"I will not forecast from an old price and present it as today's.\n"
        f"You will get a forecast as soon as the next market session is published.\n\n"
        f"_KisanMitra 🌾_"
    )


def format_no_data(r: dict) -> str:
    return (
        f"📭 *No mandi data for {r.get('crop', 'this crop')} in {r.get('district', 'your district')}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"I could not find any AGMARKNET price record for *{r.get('crop', 'this crop')}*\n"
        f"in *{r.get('district', 'your district')}* or other Karnataka mandis.\n\n"
        f"I will not guess a price — a forecast needs a real spot price first.\n"
        f"Try a different crop, or ask again after the next market day.\n\n"
        f"_KisanMitra 🌾_"
    )


def format_clarify(r: dict) -> str:
    missing = r.get("missing", [])
    if missing == ["crop"]:
        q = "which crop do you want to check?"
    elif missing == ["district"]:
        q = "which district should I check?"
    else:
        q = "which crop and which district?"
    return (
        f"🤔 *{q.capitalize()}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"I don't want to guess and show you the wrong market's numbers.\n\n"
        f"Just add them to your message, e.g.:\n"
        f"_\"tomato price in kolar\"_\n"
        f"_\"onion saturation in bellary\"_\n\n"
        f"Or use the menu buttons below. — KisanMitra 🌾"
    )


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
        "*Evaluation:* Chronological walk-forward test · per-crop median MAPE "
        "8.5–30.7% (shown on every forecast as Model Reliability)\n\n"
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
        if t == "no_data":            return format_no_data(result)
        if t == "stale_data":         return format_stale(result)
        if t == "clarify":            return format_clarify(result)
        if t == "help":               return format_help()
        if t == "error":              return format_error(result)
        return format_error({"detail": f"Unknown response type: {t!r}"})
    except Exception as exc:
        logger.exception("Formatter error for type=%s: %s", t, exc)
        return "⚠️ Could not format the response. Please try again. — KisanMitra 🌾"
