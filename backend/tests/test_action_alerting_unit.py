"""
Unit tests for Action & Alerting - app/action/signing.py, app/action/dispatcher.py.
docs/SECURITY_AND_GOVERNANCE.md §5's hard invariant (only an approved
deployment may dispatch) and §7 (HMAC-signed webhooks) are checked
directly here, not just via the HTTP layer.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.action.dispatcher import dispatch_action_for_deployment
from app.action.signing import sign_payload, verify_signature
from app.db.models.accounts import Account
from app.db.models.complaints import Complaint
from app.db.models.enums import (
    AlertChannel,
    ComplaintStatus,
    DeploymentStatus,
    ExitChannelType,
    FraudType,
    InstitutionType,
    InterventionActionType,
    OptimizerMode,
)
from app.db.models.exit_channels import ExitChannel
from app.db.models.predictions import Alert, Prediction, RecommendedDeployment


# --- signing --------------------------------------------------------------------


def test_sign_and_verify_round_trip():
    payload = {"alert_id": "abc", "risk_summary": "test"}
    signature = sign_payload(payload)
    assert verify_signature(payload, signature) is True


def test_verify_rejects_tampered_payload():
    payload = {"alert_id": "abc", "risk_summary": "test"}
    signature = sign_payload(payload)
    tampered = {**payload, "risk_summary": "tampered"}
    assert verify_signature(tampered, signature) is False


def test_verify_rejects_missing_signature():
    payload = {"alert_id": "abc"}
    assert verify_signature(payload, "") is False


def test_sign_is_deterministic_regardless_of_key_order():
    a = {"alert_id": "abc", "risk_summary": "test"}
    b = {"risk_summary": "test", "alert_id": "abc"}
    assert sign_payload(a) == sign_payload(b)


# --- dispatch_action_for_deployment ----------------------------------------------


def _make_jurisdiction(db):
    from app.db.models.jurisdictions import Jurisdiction

    j = Jurisdiction(name="Action Test Jurisdiction", state="Tamil Nadu", district="Chennai")
    db.add(j)
    db.flush()
    return j


def _make_complaint(db, jurisdiction_id):
    victim = Account(account_hash=f"action-{uuid.uuid4().hex}", is_synthetic=True)
    db.add(victim)
    db.flush()
    complaint = Complaint(
        incident_reference=f"ACT-{victim.account_id[:8]}",
        incident_datetime=datetime.now(timezone.utc),
        fraud_type=FraudType.upi_fraud,
        amount=120000,
        location_text="Test",
        institution_name="Test Bank",
        institution_type=InstitutionType.bank,
        description="Action & Alerting unit test complaint",
        victim_account_id=victim.account_id,
        jurisdiction_id=jurisdiction_id,
        status=ComplaintStatus.new,
    )
    db.add(complaint)
    db.commit()
    return complaint


def _make_deployment(db, complaint_id, action_type=InterventionActionType.physical_team_deployment, status=DeploymentStatus.approved):
    channel = ExitChannel(
        channel_type=ExitChannelType.atm_cash if action_type == InterventionActionType.physical_team_deployment else ExitChannelType.crypto_p2p,
        external_ref=f"CHANNEL-{uuid.uuid4().hex[:8]}",
        geo_lat=13.0,
        geo_lon=80.0,
        h3_cell="cell1",
        intervention_action_type=action_type,
    )
    db.add(channel)
    db.flush()
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=datetime.now(timezone.utc),
        ranked_locations=[
            {
                "exit_channel_id": channel.channel_id,
                "h3_cell": "cell1",
                "channel_type": channel.channel_type.value,
                "probability": 0.72,
                "time_window_min": [20.0, 50.0],
                "confidence_interval": [0.5, 0.8],
            }
        ],
    )
    db.add(prediction)
    db.flush()
    deployment = RecommendedDeployment(
        prediction_id=prediction.prediction_id,
        optimizer_mode=OptimizerMode.coverage_maximization if action_type == InterventionActionType.physical_team_deployment else OptimizerMode.resource_allocation,
        assignment=[{"team_id": "team-1", "exit_channel_id": channel.channel_id, "expected_coverage": 1.0, "travel_time_min": 10.0}],
        expected_coverage_total=1.0,
        naive_baseline_coverage=1.0,
        status=status,
    )
    db.add(deployment)
    db.commit()
    return deployment


def test_dispatch_rejects_proposed_deployment(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id, status=DeploymentStatus.proposed)

    result = dispatch_action_for_deployment(db, deployment.deployment_id)
    assert result is None
    assert db.query(Alert).count() == 0


def test_dispatch_rejects_rejected_deployment(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id, status=DeploymentStatus.rejected)

    result = dispatch_action_for_deployment(db, deployment.deployment_id)
    assert result is None
    assert db.query(Alert).count() == 0


def test_dispatch_approved_physical_team_deployment_uses_bank_channel(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id, action_type=InterventionActionType.physical_team_deployment)

    alert = dispatch_action_for_deployment(db, deployment.deployment_id)
    assert alert is not None
    assert alert.channel == AlertChannel.bank_webhook_sim
    assert alert.sent_at is not None
    assert alert.delivered_at is not None  # real signature verified by the real mock receiver
    assert alert.payload["deployment_id"] == deployment.deployment_id
    assert alert.payload["complaint_id"] == complaint.complaint_id
    assert "signature" in alert.payload


def test_dispatch_approved_exchange_freeze_uses_exchange_channel(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id, action_type=InterventionActionType.exchange_freeze_request)

    alert = dispatch_action_for_deployment(db, deployment.deployment_id)
    assert alert.channel == AlertChannel.exchange_webhook_sim
    assert alert.payload["recommended_action"] == "request_exchange_freeze"


def test_dispatch_approved_merchant_hold_uses_merchant_channel(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id, action_type=InterventionActionType.merchant_hold_request)

    alert = dispatch_action_for_deployment(db, deployment.deployment_id)
    assert alert.channel == AlertChannel.merchant_webhook_sim
    assert alert.payload["recommended_action"] == "request_merchant_hold"


def test_dispatch_is_idempotent_never_creates_a_second_alert(db):
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    first = dispatch_action_for_deployment(db, deployment.deployment_id)
    second = dispatch_action_for_deployment(db, deployment.deployment_id)

    assert first.alert_id == second.alert_id
    assert db.query(Alert).filter(Alert.prediction_id == deployment.prediction_id).count() == 1


def test_dispatch_never_fabricates_delivery_on_receiver_failure(db, monkeypatch):
    """A receiver that rejects the signature (simulated here by
    monkeypatching verify_signature to always fail) must still record a
    real Alert row (sent_at set) but MUST NOT claim delivery."""
    jurisdiction = _make_jurisdiction(db)
    complaint = _make_complaint(db, jurisdiction.jurisdiction_id)
    deployment = _make_deployment(db, complaint.complaint_id)

    monkeypatch.setattr("app.action.mock_router.verify_signature", lambda payload, sig: False)

    alert = dispatch_action_for_deployment(db, deployment.deployment_id)
    assert alert is not None
    assert alert.sent_at is not None
    assert alert.delivered_at is None  # never fabricated


def test_dispatch_returns_none_for_nonexistent_deployment(db):
    assert dispatch_action_for_deployment(db, str(uuid.uuid4())) is None
