from app.db.models.enums import UserRole
from tests.conftest import auth_headers, make_token, service_token, valid_transaction_payload


def test_ingest_without_token_is_rejected(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    response = client.post("/v1/transactions/ingest", json=payload)
    assert response.status_code == 401


def test_ingest_with_investigator_token_is_rejected(client, submitted_complaint):
    """Only the service role may call this endpoint - not even an
    investigator, who has broad read access elsewhere."""
    token = make_token(UserRole.investigator, jurisdiction_id=None)
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    response = client.post("/v1/transactions/ingest", json=payload, headers=auth_headers(token))
    assert response.status_code == 403


def test_ingest_with_admin_token_is_rejected(client, submitted_complaint):
    """The service role is not a superset-of-admin shortcut - admin doesn't
    get it for free either."""
    token = make_token(UserRole.admin)
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    response = client.post("/v1/transactions/ingest", json=payload, headers=auth_headers(token))
    assert response.status_code == 403


def test_ingest_with_service_token_succeeds(client, submitted_complaint):
    payload = valid_transaction_payload(complaint_id=submitted_complaint["complaint_id"])
    response = client.post(
        "/v1/transactions/ingest", json=payload, headers=auth_headers(service_token())
    )
    assert response.status_code == 202


def test_service_role_cannot_list_complaints(client):
    """The service role is scoped to exactly one endpoint - it must not
    incidentally satisfy any RBAC check elsewhere (SECURITY_AND_GOVERNANCE.md
    §3: 'the service role can access no other endpoint')."""
    response = client.get("/v1/complaints", headers=auth_headers(service_token()))
    assert response.status_code == 403


def test_service_role_cannot_get_a_complaint(client, submitted_complaint):
    response = client.get(
        f"/v1/complaints/{submitted_complaint['complaint_id']}", headers=auth_headers(service_token())
    )
    assert response.status_code == 403
