"""
Creates the canonical demo complaint by POSTing to the real, running API -
not by inserting a row directly - per docs/DEMO_ARCHITECTURE.md §3's rule
that "the canonical demo scenario must be data generated/seeded through the
same interfaces used by the application." This is the literal HTTP call a
citizen's browser would make from the Complaint Portal; nothing about the
demo incident is special-cased in the application logic.

Usage (with the backend already running, e.g. `uvicorn app.main:app`):
    python scripts/seed_demo_complaint.py [--base-url http://localhost:8000]
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    payload = {
        "incident_datetime": (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat(),
        "fraud_type": "upi_fraud",
        "amount": "200000.00",
        "location_text": "T. Nagar, Chennai",
        "location_lat": 13.0418,
        "location_lon": 80.2341,
        "institution_name": "Northbridge Bank",
        "institution_type": "bank",
        "transaction_reference": "TXNDEMO0001",
        "victim_account_number": "DEMO-VICTIM-ACCOUNT-0001",
        "victim_phone": "+91-90000-00001",
        "victim_email": "demo.citizen@example.com",
        "description": (
            "Received a call claiming to be from my bank's fraud department. "
            "Was asked to share an OTP to 'verify a suspicious transaction' and "
            "Rs. 2,00,000 was debited from my UPI-linked account immediately after."
        ),
        "evidence_notes": [
            "Screenshot of the debit SMS alert",
            "Call log showing the incoming number",
        ],
        "jurisdiction_hint": "Chennai",
    }

    response = httpx.post(f"{args.base_url}/v1/complaints", json=payload, timeout=10.0)
    response.raise_for_status()
    body = response.json()
    print("Demo complaint created via the real API:")
    print(f"  complaint_id:       {body['complaint_id']}")
    print(f"  incident_reference: {body['incident_reference']}")
    print(f"  status:             {body['status']}")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Request failed: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        sys.exit(1)
    except httpx.ConnectError:
        print("Could not reach the backend - is it running? (uvicorn app.main:app)", file=sys.stderr)
        sys.exit(1)
