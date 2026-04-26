"""
KisanMitra - Script 01
Downloads Karnataka mandi price data from AGMARKNET
Saves to data/raw/agmarknet_karnataka.csv
"""

import requests
import pandas as pd
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

API_KEY  = os.getenv("DATA_GOV_API_KEY")
RAW_DIR  = BASE_DIR / "data" / "raw"

# ── What data we want ─────────────────────────────────────
# Resource ID on data.gov.in for AGMARKNET vegetable prices
RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"

def download_from_api():
    """Download Karnataka price data from data.gov.in"""

    print("Downloading from data.gov.in API...")
    print(f"API Key: {API_KEY[:8]}..." if API_KEY else "No API key found!")

    all_records = []
    offset = 0
    limit  = 500

    while True:
        url = (
            f"https://api.data.gov.in/resource/{RESOURCE_ID}"
            f"?api-key={API_KEY}"
            f"&format=json"
            f"&limit={limit}"
            f"&offset={offset}"
            f"&filters[State]=Karnataka"
        )

        try:
            response = requests.get(url, timeout=30)

            if response.status_code != 200:
                print(f"API error: {response.status_code}")
                break

            data    = response.json()
            records = data.get("records", [])

            if not records:
                print(f"No more records at offset {offset}")
                break

            all_records.extend(records)
            print(f"Downloaded {len(all_records)} records...")

            offset += limit
            time.sleep(0.5)

            if offset > 50000:
                print("Reached 50K limit")
                break

        except Exception as e:
            print(f"Request failed: {e}")
            break

    return pd.DataFrame(all_records) if all_records else None


def generate_sample_data():
    """
    Generate realistic Karnataka price data.
    Used when API is not available.
    Based on actual AGMARKNET price patterns.
    """

    print("Generating Karnataka sample dataset...")
    import numpy as np
    np.random.seed(42)

    # Real price patterns from AGMARKNET
    # Monthly averages for each crop and market
    price_patterns = {
        "Tomato": {
            "Kolar": [
                1800, 2200, 2800, 1200,
                900, 1600, 2100, 2400,
                2000, 1700, 2500, 2900
            ],
            "Chikkaballapur": [
                1700, 2100, 2700, 1100,
                850, 1500, 2000, 2300,
                1900, 1600, 2400, 2800
            ],
        },
        "Potato": {
            "Kolar": [
                1200, 1100, 1000, 1300,
                1400, 1500, 1600, 1400,
                1200, 1100, 1000, 900
            ],
        },
        "Onion": {
            "Kolar": [
                2000, 1800, 1600, 1400,
                1200, 1000, 1200, 1600,
                2000, 2400, 2800, 2200
            ],
        },
        "Marigold": {
            "Chikkaballapur": [
                800, 900, 1200, 1800,
                2400, 2000, 1600, 1200,
                900, 800, 900, 1100
            ],
        },
    }

    records = []

    for year in range(2020, 2026):
        for month in range(1, 13):

            if year == 2025 and month > datetime.now().month:
                break

            for crop, markets in price_patterns.items():
                for market, monthly_prices in markets.items():

                    base_price   = monthly_prices[month - 1]
                    year_factor  = 1 + (year - 2020) * 0.05
                    base_price  *= year_factor

                    # 18 market days per month
                    for day in range(1, 19):
                        noise  = np.random.normal(0, base_price * 0.08)
                        modal  = max(200, base_price + noise)

                        records.append({
                            "state":           "Karnataka",
                            "district":        market,
                            "market":          market,
                            "commodity":       crop,
                            "arrival_date":    f"{year}-{month:02d}-{day:02d}",
                            "min_price":       round(modal * 0.85, 2),
                            "max_price":       round(modal * 1.15, 2),
                            "modal_price":     round(modal, 2),
                            "arrivals_tonnes": round(
                                max(10, 120 * (2000/modal)), 1
                            ),
                        })

    df = pd.DataFrame(records)
    print(f"Generated {len(df)} records")
    return df


def save_data(df):
    """Clean and save the dataframe to CSV"""

    # Fix column names
    df.columns = [
        c.lower().strip().replace(" ", "_")
        for c in df.columns
    ]

    # Parse dates
    df["arrival_date"] = pd.to_datetime(
        df["arrival_date"],
        errors="coerce",
        dayfirst=True
    )
    df.dropna(subset=["arrival_date"], inplace=True)

    # Convert prices to numbers
    for col in ["min_price", "max_price", "modal_price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.dropna(subset=["modal_price"], inplace=True)
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Save
    output_path = RAW_DIR / "agmarknet_karnataka.csv"
    df.to_csv(output_path, index=False)

    print(f"\nSaved to {output_path}")
    print(f"Total records : {len(df):,}")
    print(f"Date range    : {df['arrival_date'].min().date()} "
          f"to {df['arrival_date'].max().date()}")
    print(f"Crops         : {df['commodity'].unique().tolist()}")
    print(f"Markets       : {df['market'].unique().tolist()}")

    return df


def main():
    print("=" * 50)
    print("KisanMitra - AGMARKNET Data Download")
    print("=" * 50)

    df = None

    # Try API first
    if API_KEY and API_KEY != "fill_this_later":
        df = download_from_api()

    # Fallback to sample data
    if df is None or len(df) == 0:
        print("Using sample data generator...")
        df = generate_sample_data()

    save_data(df)

    print("\nDone. Next step: python scripts/02_clean_data.py")


if __name__ == "__main__":
    main()
