import hmac
import hashlib
import json
import requests
import os
from dotenv import load_dotenv

load_dotenv()

def simulate_whatsapp_message(text: str):
    url = "http://localhost:8000/webhook/whatsapp"
    secret = os.getenv("WHATSAPP_APP_SECRET")
    
    if not secret:
        print("❌ WHATSAPP_APP_SECRET not found in .env")
        return

    # 1. Construct Meta-compliant JSON payload
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "123456789", "phone_number_id": "987654321"},
                    "messages": [{
                        "from": "919900000000",
                        "id": "wamid.HBgLOTExOTk...",
                        "timestamp": "1671234567",
                        "text": {"body": text},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    
    payload_bytes = json.dumps(payload).encode('utf-8')

    # 2. Generate HMAC SHA256 signature (Guardrail 3)
    signature = hmac.new(
        secret.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    # 3. Send POST request
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={signature}"
    }

    print(f"🚀 Sending '{text}' to KisanMitra Webhook...")
    try:
        response = requests.post(url, data=payload_bytes, headers=headers)
        print(f"📡 Status Code: {response.status_code}")
        print(f"📥 Response: {response.json()}")
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    simulate_whatsapp_message("Namaskara")
