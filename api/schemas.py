from pydantic import BaseModel
from typing import Optional

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
    season:      str = "kharif_2025"
