from tests.conftest import valid_complaint_payload


def test_valid_complaint_is_accepted(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload())
    assert response.status_code == 201


def test_rejects_zero_amount(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload(amount="0"))
    assert response.status_code == 422


def test_rejects_negative_amount(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload(amount="-500"))
    assert response.status_code == 422


def test_rejects_invalid_fraud_type(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload(fraud_type="not_a_real_type"))
    assert response.status_code == 422


def test_rejects_missing_description(client):
    payload = valid_complaint_payload()
    del payload["description"]
    response = client.post("/v1/complaints", json=payload)
    assert response.status_code == 422


def test_rejects_too_short_description(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload(description="too short"))
    assert response.status_code == 422


def test_rejects_invalid_email(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload(victim_email="not-an-email"))
    assert response.status_code == 422


def test_rejects_invalid_institution_type(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload(institution_type="spaceship"))
    assert response.status_code == 422


def test_amount_above_ceiling_rejected(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload(amount="999999999999"))
    assert response.status_code == 422
