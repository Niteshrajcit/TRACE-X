"""
Compares detected communities against the synthetic generator's planted
ground truth (`accounts.ring_id` - app/db/models/accounts.py). Never called
from any API endpoint and never returned to any investigator-facing
response - this module exists purely for developer/ops evaluation
(docs/PRODUCT.md §5: "Do not expose hidden synthetic ground truth to
investigators"), the same way `scripts/rebuild_neo4j_graph.py` is a script,
not an endpoint.

docs/AI_ML_ARCHITECTURE.md §2's "HOW EVALUATED": precision/recall of
recovered ring membership, modularity as a sanity check (computed
separately in app/graph/community_detection.py, part of the detection run's
own summary). This module adds Adjusted Rand Index and Adjusted Mutual
Information, per this phase's explicit instruction to report community-
recovery-appropriate metrics rather than classification accuracy.
"""
from collections import defaultdict
from typing import Optional

from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score
from sqlalchemy.orm import Session

from app.db.models.accounts import Account
from app.db.models.rings import DetectedRingMember

# A detected community is counted as a "false community" if its best
# Jaccard overlap with any planted ring falls below this. 0.3 is a
# commonly-used conservative threshold in the community-detection
# literature for "meaningful" cluster overlap - a chosen, documented
# constant, not derived from this dataset, and adjustable by any caller.
FALSE_COMMUNITY_JACCARD_THRESHOLD = 0.3


def get_ground_truth_rings(db: Session) -> dict[str, set[str]]:
    """ring_id (planted) -> set of account_hash. Only this function and
    evaluate_against_ground_truth touch accounts.ring_id in this module -
    kept deliberately narrow."""
    rings: dict[str, set[str]] = defaultdict(set)
    for account in db.query(Account).filter(Account.ring_id.isnot(None)).all():
        rings[account.ring_id].add(account.account_hash)
    return dict(rings)


def get_detected_rings(db: Session) -> dict[str, set[str]]:
    """detected ring_id -> set of account_hash, via DetectedRingMember."""
    rings: dict[str, set[str]] = defaultdict(set)
    rows = (
        db.query(DetectedRingMember.ring_id, Account.account_hash)
        .join(Account, Account.account_id == DetectedRingMember.account_id)
        .all()
    )
    for ring_id, account_hash in rows:
        rings[ring_id].add(account_hash)
    return dict(rings)


def _best_match(members: set[str], candidates: dict[str, set[str]]) -> tuple[Optional[str], set[str]]:
    best_id, best_members, best_overlap = None, set(), -1
    for candidate_id, candidate_members in candidates.items():
        overlap = len(members & candidate_members)
        if overlap > best_overlap:
            best_id, best_members, best_overlap = candidate_id, candidate_members, overlap
    return best_id, best_members


def evaluate_against_ground_truth(db: Session) -> dict:
    ground_truth = get_ground_truth_rings(db)
    detected = get_detected_rings(db)

    if not ground_truth:
        return {
            "evaluable": False,
            "reason": "No synthetic ground truth found (accounts.ring_id is null everywhere) - "
            "run the synthetic seed generator (scripts/seed_synthetic.py) before evaluating.",
        }

    gt_accounts = sorted(set().union(*ground_truth.values()))
    gt_label_of = {account_hash: ring_id for ring_id, members in ground_truth.items() for account_hash in members}
    detected_label_of = {
        account_hash: ring_id for ring_id, members in detected.items() for account_hash in members
    }

    true_labels, pred_labels = [], []
    undetected_count = 0
    for account_hash in gt_accounts:
        true_labels.append(gt_label_of[account_hash])
        if account_hash in detected_label_of:
            pred_labels.append(detected_label_of[account_hash])
        else:
            # Each undetected account gets its own unique label - it must
            # NOT share a label with other undetected accounts, or ARI/AMI
            # would incorrectly score them as "correctly clustered together."
            pred_labels.append(f"__undetected_{undetected_count}")
            undetected_count += 1

    result: dict = {"evaluable": True}

    if len(set(true_labels)) < 2:
        result["ari"] = None
        result["ami"] = None
        result["ari_ami_caveat"] = (
            "Only one planted ring exists in the ground truth - ARI/AMI are defined by comparing "
            "partitions with at least two distinct true groups; with a single group both metrics "
            "degenerate (ARI is undefined/trivial, AMI collapses toward 0 regardless of detection "
            "quality). Reported as null rather than a misleading number; precision/recall and "
            "coverage below remain meaningful with even one planted ring."
        )
    else:
        result["ari"] = adjusted_rand_score(true_labels, pred_labels)
        result["ami"] = adjusted_mutual_info_score(true_labels, pred_labels)

    per_ring = []
    matched_detected_ids: set[str] = set()
    for ring_id, members in ground_truth.items():
        best_id, best_members = _best_match(members, detected)
        overlap = len(members & best_members)
        union = members | best_members
        precision = (overlap / len(best_members)) if best_members else 0.0
        recall = (overlap / len(members)) if members else 0.0
        jaccard = (overlap / len(union)) if union else 0.0
        if best_id is not None and jaccard >= FALSE_COMMUNITY_JACCARD_THRESHOLD:
            matched_detected_ids.add(best_id)
        per_ring.append(
            {
                "planted_ring_id": ring_id,
                "planted_size": len(members),
                "best_matching_detected_ring_id": best_id,
                "best_matching_detected_size": len(best_members),
                "precision": precision,
                "recall": recall,
                "jaccard": jaccard,
            }
        )
    result["per_ring"] = per_ring

    result["detection_coverage"] = (
        sum(1 for a in gt_accounts if a in detected_label_of) / len(gt_accounts)
    )

    if detected:
        unmatched = 0
        for detected_id, detected_members in detected.items():
            best_jaccard = 0.0
            for members in ground_truth.values():
                union = members | detected_members
                if union:
                    best_jaccard = max(best_jaccard, len(members & detected_members) / len(union))
            if best_jaccard < FALSE_COMMUNITY_JACCARD_THRESHOLD:
                unmatched += 1
        result["false_community_rate"] = unmatched / len(detected)
        result["false_community_threshold"] = FALSE_COMMUNITY_JACCARD_THRESHOLD
    else:
        result["false_community_rate"] = None
        result["false_community_rate_caveat"] = "No communities were detected at all - rate is undefined, not zero."

    result["planted_ring_count"] = len(ground_truth)
    result["detected_community_count"] = len(detected)
    result["planted_account_count"] = len(gt_accounts)

    return result
