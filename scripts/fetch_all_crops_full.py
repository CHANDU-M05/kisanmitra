"""
Fetch ALL Karnataka records for Tomato, Onion, Ragi, Maize, Brinjal
from data.gov.in Resource ID: 35985678-0d79-46b4-9ed6-6f13308a1d24
No row cap. After each commodity, runs the same gap analysis used for Potato.
Saves each commodity to data/raw/real_agmarknet_{crop}_full.csv
"""
import requests
import pandas as pd
import time
from pathlib import Path

KEY = "REDACTED_IN_HISTORY"
RESOURCE_ID = "35985678-0d79-46b4-9ed6-6f13308a1d24"
RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

# (api_commodity_name, known_api_total_from_earlier_check, output_label)
CROPS = [
    ("Tomato",              120690, "tomato"),
    ("Onion",               102092, "onion"),
    ("Ragi (Finger Millet)", 56544, "ragi"),
    ("Maize",               176703, "maize"),
    ("Brinjal",              75086, "brinjal"),
]

session = requests.Session()
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def fetch_crop(api_name, label, known_total):
    out_path = RAW_DIR / f"real_agmarknet_{label}_full.csv"
    if out_path.exists() and out_path.stat().st_size > 10000:
        print(f"\n[SKIP] {api_name} already downloaded ({out_path.stat().st_size/1e6:.1f} MB). Loading for gap check.")
        return pd.read_csv(out_path, parse_dates=["arrival_date"])

    print(f"\n{'='*60}")
    print(f"FETCHING: {api_name}  (expected ~{known_total:,} rows)")
    print(f"{'='*60}")

    offset = 0
    limit = 500
    records = []
    max_retries = 5

    while True:
        url = (f"https://api.data.gov.in/resource/{RESOURCE_ID}"
               f"?api-key={KEY}&format=json&limit={limit}&offset={offset}"
               f"&filters[State]=Karnataka&filters[Commodity]={api_name}")
        success = False
        batch = []
        for attempt in range(max_retries):
            try:
                r = session.get(url, headers=headers, timeout=30)
                if r.status_code == 200:
                    batch = r.json().get("records", [])
                    if not batch:
                        print(f"  Empty page at offset {offset}. Done.")
                        success = True
                        break
                    records.extend(batch)
                    offset += limit
                    if len(records) % 10000 == 0 or len(batch) < limit:
                        print(f"  {len(records):,} / ~{known_total:,} records (offset {offset:,})...")
                    success = True
                    time.sleep(1.5)
                    break
                elif r.status_code == 429:
                    print(f"  HTTP 429 at offset {offset}, sleeping 20s (attempt {attempt+1})...")
                    time.sleep(20)
                else:
                    print(f"  HTTP {r.status_code} at offset {offset}, retrying ({attempt+1})...")
                    time.sleep(3)
            except Exception as e:
                print(f"  Exception at offset {offset}: {e}, retrying ({attempt+1})...")
                time.sleep(3)

        if not success or not batch:
            break

    df = pd.DataFrame(records)
    df["arrival_date"] = pd.to_datetime(df["Arrival_Date"], format="%d/%m/%Y", errors="coerce")
    df.dropna(subset=["arrival_date"], inplace=True)
    df.sort_values("arrival_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.to_csv(out_path, index=False)
    print(f"  Saved {len(df):,} rows -> {out_path.name}")
    return df


def gap_analysis(df, crop_label):
    print(f"\n--- GAP ANALYSIS: {crop_label} ---")
    print(f"Total rows : {len(df):,}")
    print(f"Date range : {df['arrival_date'].min().date()} to {df['arrival_date'].max().date()}")

    df2 = df.sort_values(["Market", "arrival_date"]).copy()
    df2["prev_date"] = df2.groupby("Market")["arrival_date"].shift(1)
    df2["gap_days"] = (df2["arrival_date"] - df2["prev_date"]).dt.days

    gap_summary = df2.groupby("Market")["gap_days"].agg(["count", "median", "max"])
    gap_summary = gap_summary.sort_values("max", ascending=False)

    print(f"\nMarkets with max gap > 365 days (will be excluded by filter):")
    excluded = gap_summary[gap_summary["max"] > 365]
    print(excluded.head(20).to_string())

    print(f"\nMarkets passing filter (count >= 500 AND max gap <= 365 days):")
    passing = gap_summary[(gap_summary["count"] >= 500) & (gap_summary["max"] <= 365)]
    print(passing.sort_values("count", ascending=False).to_string())

    # Top 10 worst individual gaps
    print(f"\nTop 10 worst individual gaps:")
    worst = df2.nlargest(10, "gap_days")[["Market", "prev_date", "arrival_date", "gap_days"]]
    print(worst.to_string())


if __name__ == "__main__":
    for api_name, known_total, label in CROPS:
        df = fetch_crop(api_name, label, known_total)
        gap_analysis(df, api_name)

    print("\n\n=== ALL COMMODITIES FETCHED AND GAP-CHECKED ===")
    print("Ready to write 02_clean_data.py against reliable full data.")
