"""
tests/test_declarations_endpoint.py — Unit tests for GET /api/v1/farmers/{phone}/declarations.

Verifies authentication and authorization guards:
  1. Missing or invalid X-Internal-Secret returns 401 Unauthorized.
  2. Matching X-Internal-Secret but caller_id != phone returns 403 Access Denied.
  3. Valid X-Internal-Secret and matching caller_id == phone returns declarations list.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from backend.core.config import settings
from backend.routers.farmers import farmer_declarations


@pytest.mark.asyncio
async def test_farmer_declarations_missing_secret_returns_401():
    """Missing or empty X-Internal-Secret header raises HTTP 401."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await farmer_declarations(
            phone="9998887776",
            caller_id="9998887776",
            x_internal_secret=None,
            db=db,
        )
    assert exc_info.value.status_code == 401
    assert "Unauthorized client" in exc_info.value.detail


@pytest.mark.asyncio
async def test_farmer_declarations_invalid_secret_returns_401():
    """Incorrect X-Internal-Secret header raises HTTP 401."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await farmer_declarations(
            phone="9998887776",
            caller_id="9998887776",
            x_internal_secret="invalid_secret_token",
            db=db,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_farmer_declarations_idor_mismatch_returns_403():
    """Matching secret but caller_id != phone raises HTTP 403 Access Denied."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await farmer_declarations(
            phone="9998887776",
            caller_id="1112223334",  # different phone number!
            x_internal_secret=settings.secret_key,
            db=db,
        )
    assert exc_info.value.status_code == 403
    assert "Access denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_farmer_declarations_valid_request_returns_data():
    """Valid secret and matching caller_id returns farmer's declarations."""
    db = AsyncMock()
    mock_decl = MagicMock()
    mock_decl.id = 1
    mock_decl.crop = "Tomato"
    mock_decl.district = "Kolar"
    mock_decl.area_acres = 2.5
    mock_decl.season = "Kharif_2026"
    mock_decl.declared_at = None

    scalars_mock = MagicMock()
    scalars_mock.scalars.return_value.all.return_value = [mock_decl]
    db.execute = AsyncMock(return_value=scalars_mock)

    res = await farmer_declarations(
        phone="9998887776",
        caller_id="9998887776",
        x_internal_secret=settings.secret_key,
        db=db,
    )

    assert res["phone"] == "9998887776"
    assert res["count"] == 1
    assert res["declarations"][0]["crop"] == "Tomato"
