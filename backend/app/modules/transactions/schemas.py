"""
Pydantic schemas for `POST /v1/transactions/ingest` — docs/API_CONTRACT.md
§1a's implemented contract.

No field on `TransactionIngestRequest` accepts a pre-computed hash for any
identifier - account numbers, device id, IP, phone, VPA are all raw values,
hashed server-side (app/shared/accounts.py, app/core/security.py
`hash_pii`), exactly like `POST /v1/complaints`. `hop_index` is not a
request field at all - it exists only on the response, server-computed by
`app/modules/transactions/service.py`.
"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field

from app.db.models.enums import TransactionChannel


class TransactionIngestRequest(BaseModel):
    complaint_id: str
    from_account_number: Annotated[str, Field(min_length=1, max_length=64)]
    to_account_number: Annotated[str, Field(min_length=1, max_length=64)]
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("100000000"))]
    channel: TransactionChannel
    occurred_at: datetime

    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    # Per-transaction context (API_CONTRACT.md §1a amendment) - describes the
    # from_account's session for this specific transfer, not a fixed
    # property of the account.
    device_id: Optional[str] = Field(default=None, max_length=255)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    originator_phone: Optional[str] = Field(default=None, max_length=20)
    originator_vpa: Optional[str] = Field(default=None, max_length=255)

    # Only meaningful when this transaction is a cash-out/exit; must
    # reference an already-existing exit_channels row (service.py 404s
    # otherwise) - never used to create one.
    exit_channel_id: Optional[str] = None


class TransactionIngestResponse(BaseModel):
    txn_id: str
    hop_index: int
