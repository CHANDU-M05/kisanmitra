"""
KisanMitra - Real Historical AGMARKNET Data Downloader
Resource ID: 35985678-0d79-46b4-9ed6-6f13308a1d24 (Variety-wise Daily Market Prices Data)
Downloads historical APMC mandi records for Karnataka (2003-2023)
Saves to data/raw/real_karnataka_agmarknet.csv
"""

import sys
import time
import requests
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
from backend.core.config import redact_secrets, settings  # noqa: E402

# This script read config/.env, which does not exist — so it always fell through
# to the hardcoded key below. Credentials now come from the same settings object
# the API uses, with no default.
KEY = settings.data_gov_api_key
if not KEY:
    raise SystemExit("DATA_GOV_API_KEY is not set in .env — cannot download.")
RESOURCE_ID = settings.agmarknet_resource_id
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Commodity mapping to exact data.gov.in historical indexing names
CROP_MAP = {
    "Brinjal": "Brinjal",
    "Maize": "Maize",
    "Onion": "Onion",
    "Potato": "Potato",
    "Ragi": "Ragi (Finger Millet)",
    "Tomato": "Tomato"
}

def main():
    print("=" * 60)
    print("KisanMitra — Real AGMARKNET Historical Data Ingestion")
    print("Resource ID: 35985678-0d79-46b4-9ed6-6f13308a1d24 (DMI Archive)")
    print("=" * 60)

    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    all_records = []

    for crop_label, api_crop_name in CROP_MAP.items():
        crop_out = RAW_DIR / f"real_agmarknet_{crop_label.lower().replace(' ', '_')}.csv"
        if crop_out.exists() and crop_out.stat().st_size > 1000:
            print(f"\n[SKIP] {crop_label} already exists ({crop_out.stat().st_size / 1e6:.2f} MB), skipping download.")
            continue

        print(f"\n[FETCH] Querying {crop_label} (API Commodity: '{api_crop_name}')...")
        offset = 0
        limit = 200
        crop_records = []
        max_retries = 5

        while True:
            url = (
                f"https://api.data.gov.in/resource/{RESOURCE_ID}"
                f"?api-key={KEY}&format=json&limit={limit}&offset={offset}"
                f"&filters[State]=Karnataka"
            )
            params = {"filters[Commodity]": api_crop_name}

            success = False
            for attempt in range(max_retries):
                try:
                    r = session.get(url, params=params, headers=headers, timeout=25)
                    if r.status_code == 200:
                        data = r.json()
                        records = data.get("records", [])
                        if not records:
                            print(f"  Reached end of dataset for {crop_label}. Total: {len(crop_records):,} rows.")
                            success = True
                            break
                        crop_records.extend(records)
                        offset += limit
                        print(f"  Downloaded {len(crop_records):,} records (offset {offset:,})...")
                        success = True
                        time.sleep(1.2)
                        break
                    elif r.status_code == 429:
                        print(f"  Rate limited (HTTP 429) at offset {offset}, sleeping 15s (attempt {attempt+1}/{max_retries})...")
                        time.sleep(15)
                    else:
                        print(f"  HTTP {r.status_code} at offset {offset}, retrying ({attempt+1}/{max_retries})...")
                        time.sleep(3)
                except Exception as e:
                    print(f"  Request exception at offset {offset}: {redact_secrets(str(e))}, retrying ({attempt+1}/{max_retries})...")
                    time.sleep(3)

            if not success or (success and len(data.get("records", [])) == 0):
                break

            # No row cap -- download the full available history for each crop

        # Standardize commodity column back to standard label
        for r in crop_records:
            r["Commodity"] = crop_label
        
        if crop_records:
            df_crop = pd.DataFrame(crop_records)
            df_crop["arrival_date"] = pd.to_datetime(df_crop["Arrival_Date"], format="%d/%m/%Y", errors="coerce")
            df_crop.dropna(subset=["arrival_date"], inplace=True)
            df_crop.sort_values("arrival_date", inplace=True)
            crop_out = RAW_DIR / f"real_agmarknet_{crop_label.lower().replace(' ', '_')}.csv"
            df_crop.to_csv(crop_out, index=False)
            print(f"  [SAVED] {len(df_crop):,} rows for {crop_label} -> {crop_out.name}")

    # Combine all crop files
    crop_files = list(RAW_DIR.glob("real_agmarknet_*.csv"))
    if crop_files:
        combined = pd.concat([pd.read_csv(f) for f in crop_files], ignore_index=True)
        combined["arrival_date"] = pd.to_datetime(combined["arrival_date"], errors="coerce")
        combined.dropna(subset=["arrival_date"], inplace=True)
        combined.drop_duplicates(inplace=True)
        combined.sort_values("arrival_date", inplace=True)
        
        out_path = RAW_DIR / "real_karnataka_agmarknet_combined.csv"
        combined.to_csv(out_path, index=False)
        
        print("\n" + "=" * 60)
        print("COMBINED HISTORICAL DATASET SUMMARY")
        print("=" * 60)
        print(f"Total Rows Downloaded : {len(combined):,}")
        print(f"Date Range            : {combined['arrival_date'].min().date()} to {combined['arrival_date'].max().date()}")
        print("\nPer-Commodity Distribution:")
        print(combined["Commodity"].value_counts().to_string())
        print(f"\nSaved combined dataset -> {out_path}")

if __name__ == "__main__":
    main()
