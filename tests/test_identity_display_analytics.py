"""
tests/test_identity_display_analytics.py — Phase 3 identity-aware analytics.

Proves /declarations/summary distinguishes phone-based identities from platform
identies across a MIXED ledger (legacy unclassified, web, WhatsApp, Telegram),
keeps total_farmers backwards compatible, and merges the same person appearing
in both identity spaces (legacy telegram id in phone + new sender_id row).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.routers.farmers import summary


def _row(phone=None, channel=None, sender_id=None, district="Kolar", crop="Tomato"):
    return SimpleNamespace(phone=phone, channel=channel, sender_id=sender_id,
                           district=district, crop=crop)


MIXED = [
    _row(phone="1534422727"),                                   # legacy telegram id in phone
    _row(phone="9812345678"),                                   # web/whatsapp mobile
    _row(phone="9733344455"),                                   # whatsapp mobile
    _row(phone=None, channel="telegram", sender_id="1534422727"),  # same person, new shape
    _row(phone=None, channel="telegram", sender_id="777888999"),   # fresh platform user
]


@pytest.mark.asyncio
async def test_summary_identity_counts_on_mixed_ledger():
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = MIXED
    db.execute = AsyncMock(return_value=res)

    out = await summary(db=db)
    assert out["total_declarations"] == 5
    # historic meaning preserved: distinct non-null phones (NaN excluded)
    assert out["total_farmers"] == 3
    assert out["phone_farmers"] == 3          # 1534422727, 9812345678, 9733344455
    assert out["platform_users"] == 2         # 1534422727, 777888999
    # union: legacy id and sender id merge into ONE identity → 4 people
    assert out["unique_identities"] == 4


@pytest.mark.asyncio
async def test_summary_empty_ledger_has_all_identity_fields_zero():
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=res)

    out = await summary(db=db)
    for field in ("total_farmers", "phone_farmers", "platform_users", "unique_identities"):
        assert out[field] == 0, field
    assert out["message"] == "No declarations yet."


@pytest.mark.asyncio
async def test_summary_case_insensitive_identity_merge():
    """Legacy phones were stored raw; merge must be case-insensitive so the
    same sender value is never double-counted."""
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = [
        _row(phone="ABC123"),                                        # odd legacy non-mobile value
        _row(phone=None, channel="telegram", sender_id="abc123"),
    ]
    db.execute = AsyncMock(return_value=res)
    out = await summary(db=db)
    assert out["unique_identities"] == 1
    assert out["phone_farmers"] == 1 and out["platform_users"] == 1


@pytest.mark.asyncio
async def test_summary_tolerates_rows_without_sender_attr():
    """Old mock-based fixtures / hypothetical row objects lacking the new
    attributes must not crash the summary."""
    class LegacyOnly:
        def __init__(self):
            self.phone, self.district, self.crop = "9812300000", "Kolar", "Ragi"
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = [LegacyOnly()]
    db.execute = AsyncMock(return_value=res)
    out = await summary(db=db)
    assert out["phone_farmers"] == 1 and out["platform_users"] == 0
