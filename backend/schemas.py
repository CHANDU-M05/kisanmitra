from pydantic import BaseModel, Field
from typing import Optional
from backend.core.dates import current_season as _derive_season

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
