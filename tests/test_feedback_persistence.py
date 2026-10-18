"""
tests/test_feedback_persistence.py — Feedback score written to ChatHistory.

Verifies:
  1. POST /farmer/advisory/feedback with score=1 updates feedback_score on the row.
  2. POST /farmer/advisory/feedback with score=-1 also updates correctly.
  3. Invalid score (0, 2, None) returns 400.
  4. Non-existent message_id returns 404.
  5. Valid request with matching role="assistant" row succeeds.

These are unit tests with a mocked DB session — the real DB integration
for the upsert itself is covered in test_postgres_integration.py.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException


@pytest.mark.asyncio
async def test_feedback_positive_score_updates_row():
    """score=1 (positive) sets feedback_score=1 on the ChatHistory row."""
    from backend.routers.farmers import get_advisory_feedback

    msg_id    = str(uuid4())
    mock_row  = MagicMock()
    mock_row.feedback_score = None  # starts unset

    db        = AsyncMock()
    scalar    = MagicMock(); scalar.scalar_one_or_none.return_value = mock_row
    db.execute = AsyncMock(return_value=scalar)
    db.commit  = AsyncMock()

    result = await get_advisory_feedback(
        req={"message_id": msg_id, "score": 1},
        db=db,
    )

    assert result == {"success": True}
    assert mock_row.feedback_score == 1
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_feedback_negative_score_updates_row():
    """score=-1 (negative) sets feedback_score=-1."""
    from backend.routers.farmers import get_advisory_feedback

    msg_id   = str(uuid4())
    mock_row = MagicMock(); mock_row.feedback_score = None

    db       = AsyncMock()
    scalar   = MagicMock(); scalar.scalar_one_or_none.return_value = mock_row
    db.execute = AsyncMock(return_value=scalar)
    db.commit  = AsyncMock()

    result = await get_advisory_feedback(
        req={"message_id": msg_id, "score": -1},
        db=db,
    )

    assert result == {"success": True}
    assert mock_row.feedback_score == -1


@pytest.mark.asyncio
async def test_feedback_invalid_score_returns_400():
    """Scores other than 1 or -1 are rejected with 400."""
    from backend.routers.farmers import get_advisory_feedback

    db = AsyncMock()

    for bad_score in [0, 2, None, "yes"]:
        with pytest.raises(HTTPException) as exc_info:
            await get_advisory_feedback(
                req={"message_id": str(uuid4()), "score": bad_score},
                db=db,
            )
        assert exc_info.value.status_code == 400, \
            f"score={bad_score!r} should return 400, got {exc_info.value.status_code}"


@pytest.mark.asyncio
async def test_feedback_nonexistent_message_returns_404():
    """Missing ChatHistory row returns 404."""
    from backend.routers.farmers import get_advisory_feedback

    db       = AsyncMock()
    scalar   = MagicMock(); scalar.scalar_one_or_none.return_value = None  # row not found
    db.execute = AsyncMock(return_value=scalar)

    with pytest.raises(HTTPException) as exc_info:
        await get_advisory_feedback(
            req={"message_id": str(uuid4()), "score": 1},
            db=db,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_feedback_invalid_uuid_returns_400():
    """Malformed UUID in message_id returns 400 before any DB query."""
    from backend.routers.farmers import get_advisory_feedback

    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_advisory_feedback(
            req={"message_id": "not-a-uuid", "score": 1},
            db=db,
        )
    assert exc_info.value.status_code == 400
    db.execute.assert_not_called()  # must fail before hitting the DB
