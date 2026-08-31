"""
Central runtime configuration. Every value is overridable via environment
variable (or a `.env` file) so the same image runs in local dev, the Docker
Compose stack, and CI without code changes.

Architecture note (docs/ARCHITECTURE.md §1, §8): PostgreSQL+PostGIS is the
locked system of record. DATABASE_URL defaults to a local SQLite file only so
this backend is runnable on a machine without Docker/Postgres installed
(a concrete implementation blocker documented in the Phase 0/1 report) -
docker-compose.yml always injects a real postgresql:// URL for the
documented, canonical deployment.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TRACE-X"
    environment: str = "development"  # development | test | production
    log_level: str = "INFO"

    # Database (docs/DATA_MODEL.md §2). In production, this must be a real PostgreSQL URL.
    database_url: str

    # Neo4j (docs/DATA_MODEL.md §3). Connectivity is best-effort in Phase 1 -
    # no graph is written yet (Graph Builder lands in Phase 2 with the
    # transaction-ingestion endpoint), so a missing/unreachable Neo4j must
    # never crash the API - only degrade its health check.
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "tracex_dev_password"

    # Auth (docs/SECURITY_AND_GOVERNANCE.md §3, simplified per
    # docs/PRODUCT_EXPERIENCE.md §8.2: single moderate-TTL token, no refresh).
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 240

    # PII hashing pepper (docs/SECURITY_AND_GOVERNANCE.md §2).
    pii_hash_pepper: str

    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    synthetic_random_seed: int = 42

    # Bounded graph traversal (docs/AI_ML_ARCHITECTURE.md §1, API_CONTRACT.md §1a) -
    # server-computed hop_index is capped here rather than allowed to grow unbounded.
    max_hop_depth: int = 6

    # Louvain community detection determinism (docs/AI_ML_ARCHITECTURE.md §2a) -
    # a separate seed from synthetic_random_seed above: this one governs the
    # detection algorithm itself, not data generation, and the two must never
    # be conflated even though they default to the same value.
    louvain_random_seed: int = 42

    # Dynamic Risk Field Fusion (docs/AI_ML_ARCHITECTURE.md §5, Phase 2E) -
    # exponential half-life for decaying a prediction's contribution over
    # time. Deliberately one shared default rather than fabricated
    # per-fraud-type numbers: §5 describes the decay as "tunable per
    # fraud-type," which this single, documented, overridable constant
    # supports (app/graph/risk_field.py accepts an explicit override) -
    # without inventing specific per-type values nothing in the
    # architecture or synthetic data actually justifies yet.
    risk_field_half_life_hours: float = 6.0

    # Path to the pre-trained corridor ML model artifact (Phase 2C -> Prod)
    corridor_model_path: str = "models/corridor_model.joblib"

    # Intervention Optimizer (docs/AI_ML_ARCHITECTURE.md §7a, Phase 2G) - two
    # values the architecture names as required inputs ("effective coverage
    # radius", "travel-time matrix... Haversine distance as a proxy") but
    # does not itself specify, so - exactly as risk_field_half_life_hours
    # above - a single, disclosed, overridable default stands in rather than
    # a fabricated per-team/per-channel value nothing in the architecture or
    # synthetic data actually justifies yet.
    team_coverage_radius_km: float = 5.0

    # Action & Alerting (docs/SECURITY_AND_GOVERNANCE.md §7: "HMAC-SHA256
    # signature header on every outbound alert payload, verified by the
    # receiver") - same .env-based secrets pattern as jwt_secret/
    # pii_hash_pepper above, not a new secrets-management approach.
    webhook_hmac_secret: str
    team_response_speed_kmh: float = 30.0  # urban police response, used only to convert
    # Haversine distance into a travel-time proxy (§7a's own documented approach)

    # Fast2SMS API Key for citizen incident registration SMS notifications
    fast2sms_api_key: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
