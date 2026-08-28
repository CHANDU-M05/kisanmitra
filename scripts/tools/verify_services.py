import urllib.request
import json

BASE_URL = "http://localhost:8000"

def check_endpoint(name, url, method="GET", data=None):
    print(f"Testing {name} ({url})... ", end="")
    try:
        req = urllib.request.Request(url, method=method)
        if data:
            req.add_header('Content-Type', 'application/json')
            req.data = json.dumps(data).encode('utf-8')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                print("✅ OK")
                return True
            else:
                print(f"❌ Failed with status {response.status}")
                return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

print("--- KisanMitra System Verification ---")

# 1. System Status (Checks ML Model & DB connection)
check_endpoint("System Status", f"{BASE_URL}/health")

# 2. Latest Prices (Checks AGMARKNET integration)
check_endpoint("Latest Prices", f"{BASE_URL}/prices/latest-watch")

# 3. Declarations Summary (Checks PostgreSQL Reads)
check_endpoint("Declarations Summary", f"{BASE_URL}/declarations/summary")

# 4. Saturation API (Checks Business Logic)
check_endpoint("Saturation API", f"{BASE_URL}/saturation/Kolar/Tomato?season=Kharif%202026")

# 5. RAG Advisory (Checks Gemini / Vector DB)
check_endpoint("AI Advisory", f"{BASE_URL}/farmer/advisory", method="POST", data={
    "query": "What fertilizer is good for tomato?",
    "crop": "Tomato"
})

print("--------------------------------------")
