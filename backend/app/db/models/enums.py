"""
Enumerations shared between the ORM layer and the Pydantic API schemas, so a
value accepted by the API is, by construction, a value the database column
can store - there is no separate "API enum" that can drift from the "DB
enum" (docs/DATA_MODEL.md's tables use these exact value sets).
"""
from enum import Enum


class UserRole(str, Enum):
    citizen_portal = "citizen_portal"
    investigator = "investigator"
    supervisor = "supervisor"
    bank_liaison = "bank_liaison"
    auditor = "auditor"
    admin = "admin"
    service = "service"  # [Phase 2A] machine-to-machine only - POST /v1/transactions/ingest.
    # Never combined with any other role on any endpoint (SECURITY_AND_GOVERNANCE.md §3);
    # carries no jurisdiction_id/bank_id claim, minted out-of-band, never via /v1/auth/login.


class FraudType(str, Enum):
    upi_fraud = "upi_fraud"
    phishing = "phishing"
    investment_scam = "investment_scam"
    loan_app_fraud = "loan_app_fraud"
    other = "other"


class ComplaintStatus(str, Enum):
    new = "new"
    graph_building = "graph_building"
    predicted = "predicted"
    action_recommended = "action_recommended"
    approved = "approved"
    rejected = "rejected"
    closed = "closed"


class ComplaintSource(str, Enum):
    own_intake_form = "own_intake_form"
    ncrp_feed_future = "ncrp_feed_future"


class InstitutionType(str, Enum):
    bank = "bank"
    wallet = "wallet"
    merchant = "merchant"
    exchange = "exchange"
    other = "other"


class KycRiskTier(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TransactionChannel(str, Enum):
    upi = "upi"
    imps = "imps"
    neft = "neft"
    card = "card"
    cash_withdrawal = "cash_withdrawal"


class LinkedEntityType(str, Enum):
    device = "device"
    phone = "phone"
    address_cluster = "address_cluster"
    ip = "ip"
    vpa = "vpa"
    email = "email"


class ExitChannelType(str, Enum):
    atm_cash = "atm_cash"
    crypto_p2p = "crypto_p2p"
    ecommerce_merchant = "ecommerce_merchant"


class InterventionActionType(str, Enum):
    physical_team_deployment = "physical_team_deployment"
    exchange_freeze_request = "exchange_freeze_request"
    merchant_hold_request = "merchant_hold_request"


class ResponseUnitStatus(str, Enum):
    available = "available"
    deployed = "deployed"
    offline = "offline"


class OptimizerMode(str, Enum):
    coverage_maximization = "coverage_maximization"
    resource_allocation = "resource_allocation"


class DeploymentStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"


class AlertChannel(str, Enum):
    dashboard = "dashboard"
    sms_sim = "sms_sim"
    email_sim = "email_sim"
    bank_webhook_sim = "bank_webhook_sim"
    i4c_webhook_sim = "i4c_webhook_sim"
    exchange_webhook_sim = "exchange_webhook_sim"
    merchant_webhook_sim = "merchant_webhook_sim"


class OutcomeResult(str, Enum):
    cash_out_prevented = "cash_out_prevented"
    cash_out_occurred_elsewhere = "cash_out_occurred_elsewhere"
    no_activity = "no_activity"
    funds_recovered_partial = "funds_recovered_partial"
    funds_recovered_full = "funds_recovered_full"


class ModelStage(str, Enum):
    ring_detector = "ring_detector"
    corridor_predictor = "corridor_predictor"
    location_scorer = "location_scorer"
    time_window_model = "time_window_model"
