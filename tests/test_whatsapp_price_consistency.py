"""Regression checks preventing WhatsApp from reintroducing synthetic prices."""
from pathlib import Path


def test_whatsapp_price_path_delegates_to_canonical_handler():
    source = (Path(__file__).parents[1] / "backend/routers/webhook.py").read_text()
    assert "from backend.services.price_service import get_price_forecast" in source
    assert "result = await get_price_forecast(crop, district, db)" in source
    assert "default_spots" not in source
    assert "1850.0" not in source


def test_whatsapp_formats_state_fallback_as_nonlocal_data():
    source = (Path(__file__).parents[1] / "backend/routers/webhook.py").read_text()
    assert 'result.get("data_source") == "state_fallback"' in source
    assert "source_market" in source
    assert "price_as_of" in source
