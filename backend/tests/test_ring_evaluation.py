"""
docs/AI_ML_ARCHITECTURE.md §2 "HOW EVALUATED" + this phase's explicit
evaluation requirement. Postgres-only (no Neo4j dependency) - constructs
ground truth (accounts.ring_id) and detected rings (DetectedRing/
DetectedRingMember) directly, since app/graph/evaluation.py only ever reads
Postgres.
"""
import uuid

from app.db.models.accounts import Account
from app.db.models.rings import DetectedRing, DetectedRingMember
from app.graph.evaluation import evaluate_against_ground_truth


def _make_account(db, ring_id=None):
    # uuid4, not id(object()) - a throwaway object's id() can be immediately
    # reused by the garbage collector within the same list comprehension,
    # producing duplicate "unique" hashes and a UNIQUE constraint violation.
    account = Account(account_hash=f"hash-{uuid.uuid4().hex}", is_synthetic=True, ring_id=ring_id)
    db.add(account)
    db.flush()
    return account


def _make_detected_ring(db, ring_id, accounts):
    ring = DetectedRing(
        ring_id=ring_id,
        algorithm_name="louvain",
        algorithm_version="test",
        source_graph_fingerprint="test-fingerprint",
        member_count=len(accounts),
        transaction_count=0,
        total_amount=0,
        fan_in_count=0,
        fan_out_count=0,
        fan_in_amount=0,
        fan_out_amount=0,
        device_count=0,
        ip_count=0,
        phone_count=0,
        vpa_count=0,
        cohesion_score=0,
    )
    db.add(ring)
    db.flush()
    for account in accounts:
        db.add(DetectedRingMember(ring_id=ring_id, account_id=account.account_id))
    db.commit()
    return ring


def test_no_ground_truth_is_reported_as_not_evaluable(db):
    result = evaluate_against_ground_truth(db)
    assert result["evaluable"] is False
    assert "ring_id" in result["reason"] or "seed" in result["reason"].lower()


def test_perfect_recovery_scores_high_and_correct_coverage(db):
    ring_a_accounts = [_make_account(db, ring_id="planted-A") for _ in range(4)]
    ring_b_accounts = [_make_account(db, ring_id="planted-B") for _ in range(4)]
    db.commit()

    _make_detected_ring(db, "detected-A", ring_a_accounts)
    _make_detected_ring(db, "detected-B", ring_b_accounts)

    result = evaluate_against_ground_truth(db)
    assert result["evaluable"] is True
    assert result["ari"] == 1.0
    assert result["ami"] == 1.0
    assert result["detection_coverage"] == 1.0
    assert result["false_community_rate"] == 0.0
    for row in result["per_ring"]:
        assert row["precision"] == 1.0
        assert row["recall"] == 1.0


def test_partial_recovery_produces_intermediate_precision_recall(db):
    # Planted ring of 4; detector only finds 2 of them (misses the other 2).
    planted = [_make_account(db, ring_id="planted-C") for _ in range(4)]
    db.commit()
    _make_detected_ring(db, "detected-C", planted[:2])

    result = evaluate_against_ground_truth(db)
    row = result["per_ring"][0]
    assert row["recall"] == 0.5  # found 2 of 4 planted members
    assert row["precision"] == 1.0  # everything it did find was correct
    assert result["detection_coverage"] == 0.5


def test_undetected_accounts_are_not_silently_merged_into_one_bucket(db):
    """Every undetected account must get a unique label internally - if two
    fully undetected accounts were given the *same* label, ARI/AMI would
    incorrectly score them as correctly clustered together. Two planted
    rings (not one) so ARI/AMI are actually computed rather than hitting
    the single-ring caveat tested separately below."""
    _make_account(db, ring_id="planted-D1")
    _make_account(db, ring_id="planted-D1")
    _make_account(db, ring_id="planted-D2")
    _make_account(db, ring_id="planted-D2")
    db.commit()
    # No detected rings at all.

    result = evaluate_against_ground_truth(db)
    assert result["detection_coverage"] == 0.0
    assert all(row["recall"] == 0.0 for row in result["per_ring"])
    # ARI of a partition where every item is its own singleton, compared
    # against two true groups, is well-defined and low (not an error) -
    # if every undetected account shared one label instead, this would
    # spuriously score as a perfect (or near-perfect) match instead.
    assert result["ari"] is not None
    assert result["ari"] < 0.5


def test_false_community_rate_flags_a_detected_community_with_no_planted_overlap(db):
    planted = [_make_account(db, ring_id="planted-E") for _ in range(3)]
    unrelated = [_make_account(db, ring_id=None) for _ in range(3)]  # not planted at all
    db.commit()

    _make_detected_ring(db, "detected-correct", planted)
    _make_detected_ring(db, "detected-spurious", unrelated)  # no ground-truth overlap

    result = evaluate_against_ground_truth(db)
    assert result["detected_community_count"] == 2
    assert result["false_community_rate"] == 0.5  # 1 of 2 detected communities is unmatched


def test_single_planted_ring_reports_ari_ami_caveat_instead_of_a_number(db):
    planted = [_make_account(db, ring_id="only-ring") for _ in range(3)]
    db.commit()
    _make_detected_ring(db, "detected-only", planted)

    result = evaluate_against_ground_truth(db)
    assert result["ari"] is None
    assert result["ami"] is None
    assert "ari_ami_caveat" in result
    # Precision/recall remain meaningful even with only one planted ring.
    assert result["per_ring"][0]["recall"] == 1.0
