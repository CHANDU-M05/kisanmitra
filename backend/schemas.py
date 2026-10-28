from pydantic import BaseModel, Field, field_validator
from typing import Optional
from backend.core.dates import current_season as _derive_season
from backend.core.phone import normalize_phone, is_valid_indian_mobile

class PriceRequest(BaseModel):
    commodity:       str
    market:          str
    current_price:   float
    arrivals_tonnes: Optional[float] = 100.0

class DeclareRequest(BaseModel):
    farmer_name: str
    phone:       str
    village:     str
    district:    str
    crop:        str
    area_acres:  float
    season: str = Field(default_factory=_derive_season)

    @field_validator("phone")
    @classmethod
    def _normalize_and_validate_phone(cls, v: str) -> str:
        # Canonicalise +91/0 variants to a bare 10-digit national number, then
        # reject anything that still isn't a real Indian mobile. This is the
        # human-entered web path only; Telegram ids never reach this schema.
        normalized = normalize_phone(v)
        if not is_valid_indian_mobile(normalized):
            raise ValueError(
                "Invalid mobile number — enter a 10-digit Indian mobile starting with 6-9."
            )
        return normalized
