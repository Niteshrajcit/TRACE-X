"""
Lightweight contract checks: the OpenAPI schema FastAPI generates from the
Pydantic models must actually match docs/API_CONTRACT.md's Phase 1 surface,
and every response must validate against its declared schema (FastAPI
enforces this on every request already - these tests make it explicit and
regression-proof rather than incidental).
"""
from app.modules.complaints.schemas import ComplaintCreateResponse, ComplaintDetail, ComplaintSummary
from app.db.models.enums import UserRole
from tests.conftest import auth_headers, make_token, valid_complaint_payload


def test_openapi_schema_exposes_exactly_the_phase_1_endpoints(client):
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"].keys())
    expected = {
        "/health",
        "/v1/auth/login",
        "/v1/complaints",
        "/v1/complaints/{complaint_id}",
    }
    assert expected.issubset(paths)


def test_create_complaint_response_matches_schema(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload())
    assert response.status_code == 201
    ComplaintCreateResponse.model_validate(response.json())


def test_complaint_summary_response_matches_schema(client, jurisdiction_a):
    client.post("/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai"))
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get("/v1/complaints", headers=auth_headers(token))
    assert response.status_code == 200
    for item in response.json():
        ComplaintSummary.model_validate(item)


def test_complaint_detail_response_matches_schema_and_omits_pii(client, jurisdiction_a):
    submission = client.post(
        "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai")
    )
    complaint_id = submission.json()["complaint_id"]
    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get(f"/v1/complaints/{complaint_id}", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    ComplaintDetail.model_validate(body)

    # docs/DATA_MODEL.md §6: no victim name/phone/email field ever leaves the API.
    serialized = str(body)
    assert "citizen@example.com" not in serialized
    assert "+91-90000-00001" not in serialized
    assert "1234567890" not in serialized


def test_error_responses_follow_the_documented_shape(client):
    response = client.get("/v1/complaints")  # no auth
    assert response.status_code == 401
    body = response.json()
    assert "error" in body
    assert "code" in body["error"]
    assert "message" in body["error"]
    assert "request_id" in body["error"]
