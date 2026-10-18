"""
scripts/04_sync_surveys.py

Batch sync pipeline that reads farmer survey data from Google Forms CSV
and upserts it into the `crop_declarations` PostgreSQL table.
Dynamically handles sparse/wide columns caused by Google Forms sections.
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from backend.core.database import AsyncSessionLocal
from backend.core.models import CropDeclaration

BASE_DIR = Path(__file__).resolve().parents[1]
CSV_PATH = BASE_DIR / "data" / "raw" / "real_farmer_surveys.csv"

CROP_NORMALIZATION_MAP = {
    "sugercain": "Sugarcane",
    "shugar cane": "Sugarcane",
    "sugar cane": "Sugarcane",
    "sugarcane": "Sugarcane",
    "chilly": "Green Chilli",
    "greeenchilli": "Green Chilli",
    "greenchilli": "Green Chilli",
    "green chilli": "Green Chilli",
    "mirchi": "Green Chilli",
    "hatthi": "Cotton",
    "cotton": "Cotton",
    "pomogranat": "Pomegranate",
    "pomegranate": "Pomegranate",
    "shenga": "Groundnut",
    "groundnut": "Groundnut",
    "shenga groundnut": "Groundnut",
    "shamanthi": "Chrysanthemum",
    "reshmi": "Sericulture",
    "resmi": "Sericulture",
    "alsandi": "Cowpea",
    "avare": "Avarekai",
    "mishra bele": "Mixed Crops",
    "toordal": "Toor Dal",
    "sweetcorn": "Sweet Corn",
    "turmeric": "Turmeric",
    "ಅಡಕ": "Arecanut",
    "brinjal": "Brinjal",
    "capsicum": "Capsicum",
    "coriander": "Coriander",
    "greengram": "Green Gram",
    "soya bean": "Soybean",
    "tobacco": "Tobacco",
    "tomato": "Tomato",
    "potato": "Potato",
    "onion": "Onion",
    "ragi": "Ragi",
    "maize": "Maize",
    "lemon": "Lemon",
    "mango": "Mango",
    "rose": "Rose",
    "cabbage": "Cabbage",
    "sapota": "Sapota",
    "marigold": "Marigold",
    "others": "Others",
}

def parse_area(area_str: str) -> float:
    """Convert survey dropdown text into a mathematical float for acres."""
    area_str = str(area_str).lower()
    if "less than 1 acre" in area_str or "ಕಡಿಮೆ" in area_str:
        return 0.5
    if "1 - 2" in area_str or "1-2" in area_str:
        return 1.5
    if "2 - 4" in area_str or "2 - 5" in area_str:
        return 3.0
    if "4" in area_str or "5 - 10" in area_str:
        return 5.0
    if "10" in area_str:
        return 10.0
    return 1.0

def clean_name(val: str) -> str:
    """Extract English name from 'Kannada / English' strings."""
    if "/" in str(val):
        return str(val).split("/")[-1].split("(")[0].strip()
    return str(val).strip()

def extract_first_valid(row, df, keyword):
    """Scan all columns for a keyword and return the first non-null value."""
    for col in df.columns:
        if keyword.lower() in str(col).lower() and pd.notna(row[col]) and str(row[col]).strip() != "":
            return str(row[col]).strip()
    return ""

def get_normalized_crop(crop_name: str) -> str:
    cn = crop_name.lower().strip()
    return CROP_NORMALIZATION_MAP.get(cn, crop_name.title().strip())

async def sync_surveys():
    print("="*50)
    print("🌾 KISANMITRA REAL SURVEY SYNC PIPELINE 🌾")
    print("="*50)
    print(f"Reading survey data from {CSV_PATH}...")
    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        print(f"Failed to read CSV: {e}")
        return

    print(f"Found {len(df)} real survey responses. Processing...")
    
    async with AsyncSessionLocal() as session:
        # TRUNCATE TABLE TO CLEAR DIRTY DATA
        print("Wiping existing crop declarations to prepare for clean ingest...")
        await session.execute(text("TRUNCATE TABLE crop_declarations RESTART IDENTITY CASCADE"))
        
        count = 0
        for _, row in df.iterrows():
            farmer_name = str(row.iloc[1]).strip()
            phone = str(row.iloc[2]).strip()
            district = clean_name(str(row.iloc[3]))
            
            taluk_raw = extract_first_valid(row, df, "Taluk")
            taluk_clean = clean_name(taluk_raw)
            taluk = re.sub(r'^\d+\.\s*', '', taluk_clean).strip()
            
            village = extract_first_valid(row, df, "Village")
            
            # Extract Crops string (could be comma separated)
            crops_str = extract_first_valid(row, df, "Which crop")
            if not crops_str:
                continue
                
            # Split by commas OR " and " OR " & "
            crops_str = re.sub(r'(?i)\s+and\s+', ',', crops_str)
            crops_str = re.sub(r'\s+&\s+', ',', crops_str)
                
            raw_crops_list = [clean_name(c) for c in crops_str.split(",")]
            raw_crops_list = [re.sub(r'[^\w\s]', '', c).strip() for c in raw_crops_list if c.strip()]
            
            # Normalize them using the dictionary
            crops_list = [get_normalized_crop(c) for c in raw_crops_list if c]
            
            # Extract Acreages
            acres_list = [
                parse_area(extract_first_valid(row, df, "1st crop")),
                parse_area(extract_first_valid(row, df, "2nd crop")),
                parse_area(extract_first_valid(row, df, "3rd crop")),
                parse_area(extract_first_valid(row, df, "4th crop"))
            ]
            
            # Insert a record for each crop the farmer selected
            for idx, crop in enumerate(crops_list):
                area_acres = acres_list[idx] if idx < len(acres_list) else 1.0
                
                decl = CropDeclaration(
                    farmer_name=farmer_name,
                    phone=phone,
                    district=district,
                    taluk=taluk,
                    village=village,
                    crop=crop,
                    area_acres=area_acres,
                    season="Kharif 2026",
                    trust_score=0.8, # Base score for survey data
                    satellite_status="pending"
                )
                session.add(decl)
                count += 1
            
        await session.commit()
        print(f"✅ Successfully inserted {count} real crop declarations into PostgreSQL.")
        print("="*50)

if __name__ == "__main__":
    asyncio.run(sync_surveys())
