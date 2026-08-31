import httpx
from datetime import datetime, timezone
import os

# To run this script, ensure the backend is running (e.g. via docker-compose up)
# and you have a valid service role JWT token.
#
# You can generate a dev token using:
#   python scripts/generate_dev_token.py service
# (Or whatever script TRACE-X uses to issue tokens).

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "YOUR_JWT_TOKEN_HERE")

def send_real_transaction():
    payload = {
        # This complaint must already exist in the database!
        "complaint_id": "CMP-12345",
        "from_account_number": "ACT-1000",
        "to_account_number": "ACT-1001",
        "amount": "5000.00",
        "channel": "IMPS",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        # Optional context
        "device_id": "device-uuid-987",
        "ip_address": "192.168.1.10",
    }

    print(f"Sending payload: {payload}")
    
    with httpx.Client() as client:
        response = client.post(
            f"{API_BASE_URL}/v1/transactions/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
        )
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")

if __name__ == "__main__":
    send_real_transaction()
