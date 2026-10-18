"""
tests/test_context_recovery.py — Tests for multi-turn conversation context recovery.

Tests the multi-turn context recovery helpers and conversation_message endpoint:
1. test_context_recovery_inherits_previous_crop
2. test_context_recovery_inherits_previous_district
3. test_context_recovery_falls_back_when_no_history
4. test_previous_intent_recovery
5. test_unknown_intent_without_entities_does_not_trigger_carryover (ISSUE 1 REGRESSION GUARD)
6. test_context_recovery_channel_isolation (ISSUE 2 CHANNEL SCOPING GUARD)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.message_handler import Intent


@pytest.mark.asyncio
async def test_context_recovery_inherits_previous_crop():
    """
    When the current turn specifies a district ("Kolar") but no crop,
    _resolve_conversation_context recovers the previous crop ("Tomato") from ChatHistory.
    """
    from backend.routers.conversation import _resolve_conversation_context

    db = AsyncMock()
    crop_res = MagicMock()
    crop_res.scalar_one_or_none.return_value = "Tomato"
    db.execute = AsyncMock(return_value=crop_res)

    crop, district, crop_from_ctx, dist_from_ctx, crop_used_def, dist_used_def = await _resolve_conversation_context(
        sender_id="1234567890",
        channel="telegram",
        body_crop=None,
        parsed_crop=None,
        body_district=None,
        parsed_district="Kolar",
        db=db,
    )

    assert crop == "Tomato"
    assert district == "Kolar"
    assert crop_from_ctx is True
    assert dist_from_ctx is False
    assert crop_used_def is False
    assert dist_used_def is False


@pytest.mark.asyncio
async def test_context_recovery_inherits_previous_district():
    """
    When the current turn specifies a crop ("Onion") but no district,
    _resolve_conversation_context recovers the previous district ("Belagavi") from ChatHistory.
    """
    from backend.routers.conversation import _resolve_conversation_context

    db = AsyncMock()
    dist_res = MagicMock()
    dist_res.scalar_one_or_none.return_value = "Belagavi"
    db.execute = AsyncMock(return_value=dist_res)

    crop, district, crop_from_ctx, dist_from_ctx, crop_used_def, dist_used_def = await _resolve_conversation_context(
        sender_id="1234567890",
        channel="telegram",
        body_crop=None,
        parsed_crop="Onion",
        body_district=None,
        parsed_district=None,
        db=db,
    )

    assert crop == "Onion"
    assert district == "Belagavi"
    assert crop_from_ctx is False
    assert dist_from_ctx is True
    assert crop_used_def is False
    assert dist_used_def is False


@pytest.mark.asyncio
async def test_context_recovery_falls_back_when_no_history():
    """
    When no prior context exists in ChatHistory, defaults to Tomato / Chikkaballapur
    and sets crop_used_default / dist_used_default to True.
    """
    from backend.routers.conversation import _resolve_conversation_context

    db = AsyncMock()
    empty_res = MagicMock()
    empty_res.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=empty_res)

    crop, district, crop_from_ctx, dist_from_ctx, crop_used_def, dist_used_def = await _resolve_conversation_context(
        sender_id="new_user_999",
        channel="telegram",
        body_crop=None,
        parsed_crop=None,
        body_district=None,
        parsed_district=None,
        db=db,
    )

    assert crop == "Tomato"
    assert district == "Chikkaballapur"
    assert crop_from_ctx is False
    assert dist_from_ctx is False
    assert crop_used_def is True
    assert dist_used_def is True


@pytest.mark.asyncio
async def test_previous_intent_recovery():
    """
    Verifies _get_previous_intent returns the last active non-UNKNOWN intent for (sender_id, channel).
    """
    from backend.routers.conversation import _get_previous_intent

    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = "PRICE_QUERY"
    db.execute = AsyncMock(return_value=res)

    intent = await _get_previous_intent("1234567890", "telegram", db)
    assert intent == Intent.PRICE_QUERY


@pytest.mark.asyncio
async def test_unknown_intent_without_entities_does_not_trigger_carryover():
    """
    ISSUE 1 REGRESSION GUARD:
    If a user sends "thanks" or "hello" (UNKNOWN intent, NO explicit entity in current message),
    intent carryover MUST NOT trigger. The endpoint must return type='help' rather than
    re-executing the previous PRICE_QUERY for Tomato.
    """
    from backend.routers.conversation import ConversationRequest, conversation_message

    db = AsyncMock()
    # Context lookup returns Tomato/Kolar
    ctx_res = MagicMock()
    ctx_res.scalar_one_or_none.return_value = "Tomato"
    db.execute = AsyncMock(return_value=ctx_res)
    db.add = MagicMock()
    db.commit = AsyncMock()

    body = ConversationRequest(
        sender_id="1234567890",
        text="thanks",             # No crop or district in this text!
        channel="telegram",
    )

    req_mock = MagicMock()

    with patch("backend.routers.conversation._handle_price", new_callable=AsyncMock) as mock_price:
        result = await conversation_message(body, req_mock, db)

        # The price handler MUST NOT have been called for "thanks"!
        mock_price.assert_not_called()
        assert result["type"] == "help"


@pytest.mark.asyncio
async def test_context_recovery_channel_isolation():
    """
    ISSUE 2 REGRESSION GUARD:
    Verifies _resolve_conversation_context passes channel to the SQL query
    so a Telegram user and a WhatsApp user with identical sender_id string
    do not share context.
    """
    from backend.routers.conversation import _resolve_conversation_context

    db = AsyncMock()
    empty_res = MagicMock()
    empty_res.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=empty_res)

    await _resolve_conversation_context(
        sender_id="1001",
        channel="telegram",
        body_crop=None,
        parsed_crop=None,
        body_district=None,
        parsed_district=None,
        db=db,
    )

    # Verify that the DB query included channel == "telegram"
    query_call = db.execute.call_args_list[0][0][0]
    compiled_query = str(query_call)
    assert "chat_history.channel" in compiled_query
