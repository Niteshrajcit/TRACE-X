import re

from tests.conftest import valid_complaint_payload

INCIDENT_REFERENCE_PATTERN = re.compile(r"^TX-\d{4}-[0-9A-F]{8}$")


def test_incident_reference_matches_expected_format(client):
    response = client.post("/v1/complaints", json=valid_complaint_payload())
    body = response.json()
    assert INCIDENT_REFERENCE_PATTERN.match(body["incident_reference"]), body["incident_reference"]


def test_incident_references_are_unique_across_submissions(client):
    refs = set()
    for _ in range(5):
        response = client.post("/v1/complaints", json=valid_complaint_payload())
        refs.add(response.json()["incident_reference"])
    assert len(refs) == 5


def test_complaint_ids_are_unique(client):
    ids = set()
    for _ in range(5):
        response = client.post("/v1/complaints", json=valid_complaint_payload())
        ids.add(response.json()["complaint_id"])
    assert len(ids) == 5
