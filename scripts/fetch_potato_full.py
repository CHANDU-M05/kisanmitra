"""
Fetch ALL Karnataka Potato records from data.gov.in
Resource ID: 35985678-0d79-46b4-9ed6-6f13308a1d24
No row cap — downloads until API returns empty page.
After download, checks Dharwar gap specifically.
"""
import requests
import pandas as pd
import time
from pathlib import Path

KEY = "REDACTED_IN_HISTORY"
RESOURCE_ID = "35985678-0d79-46b4-9ed6-6f13308a1d24"
RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = RAW_DIR / "real_agmarknet_potato_full.csv"

session = requests.Session()
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

print("Fetching ALL Karnataka Potato records (no row cap)...")
offset = 0
limit = 500
records = []
max_retries = 5

while True:
    url = (f"https://api.data.gov.in/resource/{RESOURCE_ID}"
           f"?api-key={KEY}&format=json&limit={limit}&offset={offset}"
           f"&filters[State]=Karnataka&filters[Commodity]=Potato")
    success = False
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
                if len(records) % 5000 == 0 or len(batch) < limit:
                    print(f"  {len(records):,} records fetched so far (offset {offset:,})...")
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

    if not success or not records or (success and len(batch) == 0):
        break

df = pd.DataFrame(records)
df["arrival_date"] = pd.to_datetime(df["Arrival_Date"], format="%d/%m/%Y", errors="coerce")
df.dropna(subset=["arrival_date"], inplace=True)
df.sort_values("arrival_date", inplace=True)
df.reset_index(drop=True, inplace=True)

print(f"\nTotal Potato rows fetched: {len(df):,}")
print(f"Date range: {df['arrival_date'].min().date()} to {df['arrival_date'].max().date()}")
df.to_csv(OUT_PATH, index=False)
print(f"Saved -> {OUT_PATH}")

# === DHARWAR GAP CHECK ===
print("\n=== DHARWAR GAP CHECK (full dataset) ===")
dharwar = df[df["Market"].str.contains("Dharwar", case=False, na=False)].sort_values("arrival_date")
if len(dharwar) < 2:
    print("Insufficient Dharwar Potato rows to compute gap.")
else:
    dharwar["gap_days"] = dharwar["arrival_date"].diff().dt.days
    max_gap = dharwar["gap_days"].max()
    max_gap_row = dharwar.loc[dharwar["gap_days"].idxmax()]
    print(f"Dharwar Potato total rows : {len(dharwar)}")
    print(f"Dharwar max gap           : {int(max_gap)} days")
    print(f"Gap window                : {max_gap_row['arrival_date'].date()} (preceded by {(max_gap_row['arrival_date'] - pd.Timedelta(days=int(max_gap))).date()})")
    print(f"\nDharwar Potato year distribution:")
    print(dharwar["arrival_date"].dt.year.value_counts().sort_index().to_string())
