from app.db.models.enums import UserRole
from tests.conftest import auth_headers, make_token, valid_complaint_payload


def test_login_succeeds_with_correct_credentials(client, db):
    from app.core.security import hash_password
    from app.db.models.users import User

    db.add(
        User(
            email="investigator.test@tracex-demo.com",
            password_hash=hash_password("correct-horse-battery-staple"),
            role=UserRole.investigator,
        )
    )
    db.commit()

    response = client.post(
        "/v1/auth/login",
        json={"email": "investigator.test@tracex-demo.com", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_fails_with_wrong_password(client, db):
    from app.core.security import hash_password
    from app.db.models.users import User

    db.add(
        User(
            email="investigator.test@tracex-demo.com",
            password_hash=hash_password("correct-horse-battery-staple"),
            role=UserRole.investigator,
        )
    )
    db.commit()

    response = client.post(
        "/v1/auth/login",
        json={"email": "investigator.test@tracex-demo.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_get_complaints_without_token_is_rejected(client):
    response = client.get("/v1/complaints")
    assert response.status_code == 401


def test_get_complaints_with_garbage_token_is_rejected(client):
    response = client.get("/v1/complaints", headers=auth_headers("not-a-real-jwt"))
    assert response.status_code == 401


def test_citizen_role_cannot_access_investigator_endpoint(client):
    token = make_token(UserRole.citizen_portal)
    response = client.get("/v1/complaints", headers=auth_headers(token))
    assert response.status_code == 403


def test_bank_liaison_role_cannot_list_complaints(client):
    token = make_token(UserRole.bank_liaison)
    response = client.get("/v1/complaints", headers=auth_headers(token))
    assert response.status_code == 403


def test_investigator_cannot_view_complaint_outside_their_jurisdiction(
    client, jurisdiction_a, jurisdiction_b
):
    submission = client.post(
        "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Coimbatore")
    )
    complaint_id = submission.json()["complaint_id"]

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get(f"/v1/complaints/{complaint_id}", headers=auth_headers(token))
    assert response.status_code == 403


def test_investigator_can_view_complaint_inside_their_jurisdiction(client, jurisdiction_a):
    submission = client.post(
        "/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai")
    )
    complaint_id = submission.json()["complaint_id"]

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get(f"/v1/complaints/{complaint_id}", headers=auth_headers(token))
    assert response.status_code == 200


def test_investigator_list_is_scoped_to_own_jurisdiction(client, jurisdiction_a, jurisdiction_b):
    client.post("/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai"))
    client.post("/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Coimbatore"))

    token = make_token(UserRole.investigator, jurisdiction_id=jurisdiction_a.jurisdiction_id)
    response = client.get("/v1/complaints", headers=auth_headers(token))
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["jurisdiction_id"] == jurisdiction_a.jurisdiction_id


def test_auditor_sees_complaints_across_all_jurisdictions(client, jurisdiction_a, jurisdiction_b):
    client.post("/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Chennai"))
    client.post("/v1/complaints", json=valid_complaint_payload(jurisdiction_hint="Coimbatore"))

    token = make_token(UserRole.auditor)
    response = client.get("/v1/complaints", headers=auth_headers(token))
    assert response.status_code == 200
    assert len(response.json()) == 2
