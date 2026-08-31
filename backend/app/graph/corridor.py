"""
Corridor / Exit-Vector Predictor - docs/AI_ML_ARCHITECTURE.md §3, Phase 2C.

Pipeline: RING_DETECTED -> corridor predictor -> persist prediction ->
CORRIDOR_PREDICTION_COMPLETED (app/graph/handlers.py wires this).

Prototype-honest choice, exactly as documented: engineered lag features
over a ring's hop sequence (direction vector, distance per hop, velocity,
channel-switch pattern) feed a gradient-boosted classifier over
discretized bearing buckets - not an LSTM/Transformer trained from
scratch on a small synthetic corpus. `sklearn.ensemble.GradientBoostingClassifier`
is used because scikit-learn is already a dependency (previously
"evaluation-only" - now also the §3 model itself, which is the same
library, not a new one); XGBoost/Cox/lifelines belong to Phase 2D (§4)
and are not introduced here.

Everything below the OUTPUT line is entirely PostgreSQL-driven (Transaction
rows + Account.branch_lat/lon) - unlike Ring Detection, corridor prediction
never needs a live Neo4j connection, since every input it needs is already
authoritative in Postgres by the time a ring exists.
"""
from datetime import datetime, timezone
from typing import Optional

import joblib
import sklearn
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session

from app.audit.service import append_audit_event
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.db.models.accounts import Account
from app.db.models.exit_channels import ExitChannel
from app.db.models.predictions import Prediction
from app.db.models.rings import DetectedRing, DetectedRingComplaint, DetectedRingMember
from app.db.models.transactions import Transaction
from app.graph.geo import bearing_deg, haversine_km

logger = get_logger(__name__)
settings = get_settings()

ALGORITHM_NAME = "corridor_gbc"

# 8-point compass, 45 degrees per bucket - "discretized bearing/direction
# buckets" per AI_ML_ARCHITECTURE.md §3's OUTPUT/PROCESSING rows.
BEARING_BUCKETS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_BUCKET_CENTER_DEG = {label: i * 45.0 for i, label in enumerate(BEARING_BUCKETS)}
_DEFAULT_EXIT_CHANNEL_TYPE = "atm_cash"  # PRODUCT_EXPERIENCE.md §7's primary/first scenario


def algorithm_version() -> str:
    return f"{ALGORITHM_NAME}-sklearn-{sklearn.__version__}"


def bucket_for_bearing(bearing: float) -> str:
    index = round((bearing % 360) / 45.0) % 8
    return BEARING_BUCKETS[index]


def bucket_center_deg(bucket: str) -> float:
    return _BUCKET_CENTER_DEG[bucket]


def compute_hop_features(hops: list[dict]) -> dict:
    """Pure function, no I/O. `hops` is an ordered (by hop_index) list of
    dicts, each with from_lat, from_lon, to_lat, to_lon (floats), channel
    (str), occurred_at (datetime). Returns exactly the engineered features
    AI_ML_ARCHITECTURE.md §3 names: direction vector, distance per hop,
    velocity, channel-switch pattern - plus the net displacement (first
    hop's origin -> last hop's destination), which is what a "corridor"
    actually means for a multi-hop chain, not any single hop's own
    direction."""
    if not hops:
        raise ValueError("at least one hop is required to compute corridor features")

    distances_km = [
        haversine_km(h["from_lat"], h["from_lon"], h["to_lat"], h["to_lon"]) for h in hops
    ]
    bearings_deg = [
        bearing_deg(h["from_lat"], h["from_lon"], h["to_lat"], h["to_lon"]) for h in hops
    ]

    net_bearing_deg = bearing_deg(
        hops[0]["from_lat"], hops[0]["from_lon"], hops[-1]["to_lat"], hops[-1]["to_lon"]
    )
    net_distance_km = haversine_km(
        hops[0]["from_lat"], hops[0]["from_lon"], hops[-1]["to_lat"], hops[-1]["to_lon"]
    )

    span_hours = (hops[-1]["occurred_at"] - hops[0]["occurred_at"]).total_seconds() / 3600.0
    velocity_km_per_hour = (sum(distances_km) / span_hours) if span_hours > 0 else None

    channel_switches = sum(1 for i in range(1, len(hops)) if hops[i]["channel"] != hops[i - 1]["channel"])
    channel_switch_ratio = (channel_switches / (len(hops) - 1)) if len(hops) > 1 else 0.0

    return {
        "hop_count": len(hops),
        "distances_km": distances_km,
        "bearings_deg": bearings_deg,
        "mean_hop_distance_km": sum(distances_km) / len(hops),
        "max_hop_distance_km": max(distances_km),
        "total_distance_km": sum(distances_km),
        "net_bearing_deg": net_bearing_deg,
        "net_distance_km": net_distance_km,
        "velocity_km_per_hour": velocity_km_per_hour,
        "channel_switch_ratio": channel_switch_ratio,
    }


def feature_vector(features: dict) -> list[float]:
    """Flattens compute_hop_features()'s output into the fixed-order
    numeric vector the classifier trains/predicts on. velocity_km_per_hour
    can be None (a single-hop or zero-span ring) - imputed to 0.0 here,
    same "null when the data can't support a real rate" reasoning as
    app/graph/community_detection.py's _time_features, made concrete for
    a model that needs a real number, not a null, per row."""
    return [
        float(features["hop_count"]),
        features["mean_hop_distance_km"],
        features["max_hop_distance_km"],
        features["total_distance_km"],
        features["net_distance_km"],
        features["velocity_km_per_hour"] if features["velocity_km_per_hour"] is not None else 0.0,
        features["channel_switch_ratio"],
    ]


def _hops_for_accounts(db: Session, account_ids: list[str]) -> list[dict]:
    """Every Transaction strictly internal to the given account set,
    ordered by hop_index - the same "internal edges only" scoping
    app/graph/ring_service.py's feature computation already uses, just
    read from Postgres instead of Neo4j (every field this needs -
    hop_index, occurred_at, channel, and each account's branch_lat/lon -
    is already authoritative there)."""
    accounts = {a.account_id: a for a in db.query(Account).filter(Account.account_id.in_(account_ids)).all()}
    transactions = (
        db.query(Transaction)
        .filter(Transaction.from_account_id.in_(account_ids), Transaction.to_account_id.in_(account_ids))
        .order_by(Transaction.hop_index.asc(), Transaction.occurred_at.asc())
        .all()
    )
    hops = []
    for txn in transactions:
        from_acc = accounts.get(txn.from_account_id)
        to_acc = accounts.get(txn.to_account_id)
        if from_acc is None or to_acc is None:
            continue
        if from_acc.branch_lat is None or from_acc.branch_lon is None:
            continue
        if to_acc.branch_lat is None or to_acc.branch_lon is None:
            continue
        hops.append(
            {
                "from_lat": from_acc.branch_lat,
                "from_lon": from_acc.branch_lon,
                "to_lat": to_acc.branch_lat,
                "to_lon": to_acc.branch_lon,
                "channel": txn.channel.value,
                "occurred_at": txn.occurred_at,
                "amount": txn.amount,  # [Phase 2D] not used by corridor's own features -
                # exit_scorer.py's total_amount/structuring_flag features need it, and this
                # avoids a second, duplicate query over the same transaction set.
            }
        )
    return hops


def _derive_exit_channel_type(db: Session, account_ids: list[str]) -> str:
    """Deliberately a simple, documented heuristic - majority vote over any
    exit channels the ring's own members have already used
    (transactions.exit_channel_id), defaulting to atm_cash - not a trained
    classifier. AI_ML_ARCHITECTURE.md §3 describes one model (bearing
    buckets); a real exit-channel-type *predictor* trained on features is
    §4's XGBoost classifier (Phase 2D), explicitly out of this phase's
    scope. This heuristic exists only because exit_vector's schema
    (API_CONTRACT.md §3) requires some value for exit_channel_type today."""
    rows = (
        db.query(ExitChannel.channel_type)
        .join(Transaction, Transaction.exit_channel_id == ExitChannel.channel_id)
        .filter(Transaction.from_account_id.in_(account_ids) | Transaction.to_account_id.in_(account_ids))
        .all()
    )
    if not rows:
        return _DEFAULT_EXIT_CHANNEL_TYPE
    counts: dict[str, int] = {}
    for (channel_type,) in rows:
        value = channel_type.value if hasattr(channel_type, "value") else channel_type
        counts[value] = counts.get(value, 0) + 1
    return max(counts, key=counts.get)


class CorridorModel:
    """Wraps a trained GradientBoostingClassifier with the label encoding
    it was trained against, so prediction never has to re-derive bucket
    ordering from scratch. Deterministic: `settings.louvain_random_seed`
    is reused as the corridor model's random_state too - both govern
    reproducibility of a Phase 2 ML stage over the same synthetic input,
    and the existing settings docstring already frames that seed as
    "the detection algorithm itself," which this is also an instance of."""

    def __init__(self, classifier: GradientBoostingClassifier, classes: list[str], trained_on: int):
        self.classifier = classifier
        self.classes = classes
        self.trained_on = trained_on
        self.version = algorithm_version()

    def predict_bucket(self, x: list[float]) -> tuple[str, float]:
        probabilities = self.classifier.predict_proba([x])[0]
        best_index = probabilities.argmax()
        return self.classes[best_index], float(probabilities[best_index])


def build_training_dataset(db: Session) -> tuple[list[list[float]], list[str], list[float], list[str]]:
    """Ground truth: docs/AI_ML_ARCHITECTURE.md §2's synthetic ground-truth
    rings (accounts.ring_id, planted by app/synthetic/generator.py::seed_mule_rings).
    "True" corridor direction is the ring's own net displacement (first
    hop's origin -> last hop's destination) - seed_mule_rings does not
    plant a distinct cash-out/exit geolocation separate from the mule
    chain itself, so this is the only ground-truth direction the existing
    generator actually provides. See the Phase 2C closure report's
    evaluation-integrity section for what this does and doesn't prove.
    Returns (X, y_buckets, y_raw_bearings_deg, ring_ids), one row per ring
    with >=1 usable hop. y_raw_bearings_deg is kept alongside the
    discretized bucket labels specifically for evaluate_corridor_predictor's
    bearing-cone hit-rate, which needs the true continuous angle, not just
    which bucket it happened to round into."""
    ring_ids = [r[0] for r in db.query(Account.ring_id).filter(Account.ring_id.isnot(None)).distinct().all()]

    X: list[list[float]] = []
    y: list[str] = []
    raw_bearings: list[float] = []
    kept_ring_ids: list[str] = []
    for ring_id in ring_ids:
        account_ids = [a.account_id for a in db.query(Account).filter(Account.ring_id == ring_id).all()]
        hops = _hops_for_accounts(db, account_ids)
        if not hops:
            continue
        features = compute_hop_features(hops)
        X.append(feature_vector(features))
        y.append(bucket_for_bearing(features["net_bearing_deg"]))
        raw_bearings.append(features["net_bearing_deg"])
        kept_ring_ids.append(ring_id)
    return X, y, raw_bearings, kept_ring_ids


def _circular_diff_deg(a: float, b: float) -> float:
    """Shortest angular distance between two bearings, accounting for
    360-degree wraparound (e.g. 5deg and 355deg are 10deg apart, not 350)."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def evaluate_corridor_predictor(
    db: Session, test_size: float = 0.2, random_state: Optional[int] = None
) -> dict:
    """docs/AI_ML_ARCHITECTURE.md §3's HOW EVALUATED row: "was the true
    cash-out direction within the predicted bearing's confidence cone?",
    reported as a hit-rate at +/-30deg and +/-60deg cones, on a held-out
    split never seen during training. Raises ValueError (never a
    fabricated metric) under the same insufficient-data conditions
    train_corridor_classifier does."""
    random_state = random_state if random_state is not None else settings.louvain_random_seed
    X, y, raw_bearings, ring_ids = build_training_dataset(db)

    if len(X) < 10:
        raise ValueError(
            f"insufficient ground-truth rings for a meaningful held-out corridor evaluation "
            f"(found {len(X)}, need at least 10)"
        )
    if len(set(y)) < 2:
        raise ValueError(
            f"insufficient bearing-bucket diversity in ground truth to evaluate "
            f"(found {len(set(y))} distinct bucket(s): {sorted(set(y))})"
        )

    indices = list(range(len(X)))
    train_idx, test_idx = train_test_split(indices, test_size=test_size, random_state=random_state)

    X_train = [X[i] for i in train_idx]
    y_train = [y[i] for i in train_idx]
    X_test = [X[i] for i in test_idx]
    true_bearings_test = [raw_bearings[i] for i in test_idx]

    classifier = GradientBoostingClassifier(random_state=random_state)
    classifier.fit(X_train, y_train)

    hits_30 = hits_60 = 0
    for x, true_bearing in zip(X_test, true_bearings_test):
        predicted_bucket = classifier.predict([x])[0]
        diff = _circular_diff_deg(bucket_center_deg(predicted_bucket), true_bearing)
        if diff <= 30.0:
            hits_30 += 1
        if diff <= 60.0:
            hits_60 += 1

    n_test = len(X_test)
    return {
        "total_rings": len(X),
        "train_size": len(X_train),
        "test_size": n_test,
        "hit_rate_30deg": (hits_30 / n_test) if n_test else None,
        "hit_rate_60deg": (hits_60 / n_test) if n_test else None,
        "bucket_distribution": {bucket: y.count(bucket) for bucket in sorted(set(y))},
        "random_state": random_state,
    }


def train_corridor_classifier(
    db: Session, test_size: float = 0.2, random_state: Optional[int] = None
) -> tuple[CorridorModel, dict]:
    """Trains on a held-out split of the synthetic ground-truth rings.
    Raises ValueError (never a fabricated model) if there isn't enough
    data or class diversity to fit and evaluate meaningfully - the exact
    "stop and report" case rather than silently training on a
    degenerate single-class dataset."""
    random_state = random_state if random_state is not None else settings.louvain_random_seed
    X, y, _raw_bearings, ring_ids = build_training_dataset(db)

    if len(X) < 10:
        raise ValueError(
            f"insufficient ground-truth rings for a meaningful held-out corridor evaluation "
            f"(found {len(X)}, need at least 10)"
        )
    if len(set(y)) < 2:
        raise ValueError(
            f"insufficient bearing-bucket diversity in ground truth to train a classifier "
            f"(found {len(set(y))} distinct bucket(s): {sorted(set(y))})"
        )

    # Not stratified: stratification requires every class to have >=2
    # members (one for train, one for test), but there are 8 possible
    # bearing buckets - at the ring counts this synthetic dataset actually
    # produces, some buckets routinely have exactly 1 member. A plain
    # random split is used instead; this is a genuine, disclosed limit on
    # the evaluation's statistical rigor at this sample size, not hidden -
    # see the Phase 2C closure report's evaluation-integrity section.
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=random_state)

    classifier = GradientBoostingClassifier(random_state=random_state)
    classifier.fit(X_train, y_train)
    classes = list(classifier.classes_)
    model = CorridorModel(classifier, classes, trained_on=len(X_train))

    metrics = {
        "train_size": len(X_train),
        "test_size": len(X_test),
        "total_rings": len(X),
        "bucket_distribution": {bucket: y.count(bucket) for bucket in sorted(set(y))},
    }
    return model, metrics


_cached_model: Optional[CorridorModel] = None


def get_model() -> CorridorModel:
    """Process-wide cache for the pre-trained production model.
    Loads the model artifact from disk rather than training dynamically."""
    global _cached_model
    if _cached_model is None:
        import os
        model_path = os.path.join(os.getcwd(), settings.corridor_model_path)
        if not os.path.exists(model_path):
            raise RuntimeError(f"Corridor model artifact not found at {model_path}. "
                               f"Please train and export the model using scripts/train_and_export_model.py.")
        _cached_model = joblib.load(model_path)
    return _cached_model


def reset_cached_model() -> None:
    """Test-only escape hatch - mirrors close_driver()'s role for get_driver()."""
    global _cached_model
    _cached_model = None


def predict_exit_vector(db: Session, member_account_ids: list[str]) -> Optional[dict]:
    """The runtime inference path. Returns None (never a fabricated
    vector) if the ring has no internal hops with known geolocation on
    both ends - a ring can be legitimately undetectable here (e.g. every
    member's branch_lat/lon is null) without that being an error."""
    hops = _hops_for_accounts(db, member_account_ids)
    if not hops:
        return None

    features = compute_hop_features(hops)
    model = get_model()
    bucket, confidence = model.predict_bucket(feature_vector(features))

    # Cone width from the model's own confidence in its top bucket -
    # narrower when the classifier is more sure, never asserted as a fixed
    # constant regardless of how confident the prediction actually was.
    confidence_cone_deg = 30.0 if confidence >= 0.5 else 60.0

    distances = features["distances_km"]
    distance_range_km = [round(min(distances), 2), round(max(distances) if len(distances) > 1 else distances[0] * 1.5, 2)]

    return {
        "bearing_deg": round(bucket_center_deg(bucket), 1),
        "distance_range_km": distance_range_km,
        "confidence_cone_deg": confidence_cone_deg,
        "exit_channel_type": _derive_exit_channel_type(db, member_account_ids),
    }


def _persist_prediction(
    db: Session, complaint_id: str, ring_id: str, exit_vector: dict, model_version_ring: str, model_version_corridor: str
) -> Prediction:
    """One Prediction row per (ring, complaint) pair - mirrors
    detected_ring_complaints' own one-ring-to-many-complaints shape, since
    predictions are always queried by complaint_id
    (GET /v1/cases/{complaint_id}/prediction). Pure Postgres, no Neo4j
    write involved anywhere in this stage, so none of Phase 2B's
    commit-ordering concerns apply here - one flush, one audit event, one
    commit."""
    prediction = Prediction(
        complaint_id=complaint_id,
        generated_at=datetime.now(timezone.utc),
        model_version_ring=model_version_ring,
        model_version_corridor=model_version_corridor,
        exit_vector=exit_vector,
        ranked_locations=None,  # Phase 2D (§4) will populate this downstream
    )
    db.add(prediction)
    db.flush()

    append_audit_event(
        db,
        event_type="corridor.predicted",
        subject_type="prediction",
        subject_id=prediction.prediction_id,
        payload={
            "ring_id": ring_id,
            "complaint_id": complaint_id,
            "bearing_deg": exit_vector["bearing_deg"],
            "confidence_cone_deg": exit_vector["confidence_cone_deg"],
            "exit_channel_type": exit_vector["exit_channel_type"],
            "algorithm": model_version_corridor,
        },
    )
    db.commit()
    return prediction


def get_prediction_for_complaint(
    db: Session, complaint_id: str, prediction_id: Optional[str] = None
) -> Optional[Prediction]:
    """GET /v1/complaints/{complaint_id}/prediction's read path
    (API_CONTRACT.md §3: "latest, or ?prediction_id= for a specific run").
    A complaint can have more than one Prediction row (one per associated
    ring) - "latest" means the most recently generated one, a documented
    prototype simplification, not an oversight."""
    query = db.query(Prediction).filter(Prediction.complaint_id == complaint_id)
    if prediction_id is not None:
        return query.filter(Prediction.prediction_id == prediction_id).first()
    return query.order_by(Prediction.generated_at.desc()).first()


def run_corridor_prediction_for_complaint(db: Session, complaint_id: str) -> list[dict]:
    """Every ring already associated with this complaint (detected_ring_complaints,
    Phase 2B) gets one corridor prediction persisted for this complaint.
    Fired off RING_DETECTED (app/graph/handlers.py) - deliberately re-reads
    Postgres by complaint_id rather than requiring RING_DETECTED's payload
    to carry per-ring identifying data it doesn't currently have, so
    Phase 2B's already-verified event contract stays untouched."""
    ring_ids = [
        row[0]
        for row in db.query(DetectedRingComplaint.ring_id)
        .filter(DetectedRingComplaint.complaint_id == complaint_id)
        .all()
    ]

    results = []
    for ring_id in ring_ids:
        ring = db.query(DetectedRing).filter(DetectedRing.ring_id == ring_id).first()
        if ring is None:
            continue
        member_account_ids = [
            row[0]
            for row in db.query(DetectedRingMember.account_id)
            .filter(DetectedRingMember.ring_id == ring_id)
            .all()
        ]
        if not member_account_ids:
            continue

        exit_vector = predict_exit_vector(db, member_account_ids)
        if exit_vector is None:
            continue

        model_version_corridor = get_model().version
        prediction = _persist_prediction(
            db, complaint_id, ring_id, exit_vector, ring.algorithm_version, model_version_corridor
        )
        results.append(
            {
                "ring_id": ring_id,
                "prediction_id": prediction.prediction_id,
                "exit_vector": exit_vector,
                "model_version_corridor": model_version_corridor,
            }
        )
    return results
