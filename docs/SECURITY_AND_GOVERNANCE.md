# TRACE-X — Security & Governance

> Depends on: [PRODUCT.md](PRODUCT.md) §7 (non-goals), [PROJECT.md](../PROJECT.md) §13 for the original commitments this document operationalizes.

---

## 1. Threat model (scoped to what this prototype must actually defend)

In scope: unauthorized cross-jurisdiction/cross-bank data access, tampering with audit records, unauthorized action-taking (an alert sent without approval), PII exposure through the API or logs, replay of a stale prediction as if current.

Out of scope for this phase (named so the boundary is explicit, not ignored): infrastructure-level attacks (DDoS, host compromise), adversarial ML (poisoning the training data via crafted transactions) — flagged as a real production concern worth a dedicated design pass later, not solved here.

## 2. Privacy — PII handling

Account numbers, phone numbers, and any citizen-identifying free text are **hashed at the ingestion boundary** (SHA-256 with a server-side pepper, not a reversible encoding) before any downstream table is written — see DATA_MODEL.md §6 for the schema-level enforcement (no `victim_name` column exists to leak in the first place). Raw values exist only transiently in the request handler's memory during the hash computation and are never logged — request logging middleware explicitly redacts the intake endpoint's raw body fields by name.

Predictions and audit records attach to `complaint_id` / `account_hash`, never to a named individual — this is not just a UI convention, it's the reason PROJECT.md §13's privacy commitment is actually true rather than aspirational.

## 3. Authentication & RBAC

**Auth**: **[Simplified after product review — PRODUCT_EXPERIENCE.md §8.2]** a single moderate-TTL (few hours) JWT access token, no refresh flow and no server-side revocation list for the prototype — appropriate for a handful of known demo accounts logged in for minutes, not for production session management. No session state needed for authorization decisions themselves — everything derives from the token claims. Refresh-token rotation and revocation are named as a production requirement (API_CONTRACT.md §6), reintroduced once a real session store exists for other reasons — not solved with a standalone Redis instance whose only job would be a denylist.

**RBAC matrix** (rows = role, from DATA_MODEL.md §2's `users.role` enum):

| Role | Cases visible | Can approve/reject | Can send alerts | Can view audit log | Can edit model registry |
|---|---|---|---|---|---|
| Investigator | Own jurisdiction | Yes | No (approval triggers it automatically) | Own actions only | No |
| Supervisor | Own jurisdiction + subordinates' | Yes (incl. escalated) | No | Jurisdiction-scoped | No |
| Bank liaison | Alerts naming own `bank_id` only, no case detail | No | N/A (receiver only) | No | No |
| Auditor/Admin | All (read-only content) | No | No | Full, cross-jurisdiction | View + promote/demote model versions |
| Citizen (portal) | Own complaint status only, via incident reference, no login | N/A | N/A | No | No |
| Service *(implemented Phase 2A — API_CONTRACT.md §1a)* | N/A — no case-content access at all, only `POST /v1/transactions/ingest` | N/A | N/A | No | No |

Every scoped query resolves `jurisdiction_id`/`bank_id` from the **verified JWT claim**, never from a client-supplied query parameter — a request for another jurisdiction's data is a 403, tested explicitly (IMPLEMENTATION_PLAN.md testing strategy, RBAC row).

**The `service` role** exists for exactly one endpoint (`POST /v1/transactions/ingest`, Phase 2) — the synthetic harness today, a real bank/NCRP adapter eventually (ARCHITECTURE.md §9). It is deliberately *not* a general machine-to-machine role: it carries no `jurisdiction_id`/`bank_id` claim and `require_roles(UserRole.service)` is never combined with any other role on any endpoint, so a leaked service token cannot read case content, only submit transactions. Minted out-of-band (an admin/CLI script calling the same `create_access_token` every other role uses), never through `/v1/auth/login` — there is no human account behind it.

## 4. Audit architecture — the "blockchain" component, stated honestly

The PS theme is "Blockchain & Cybersecurity." Here is exactly what TRACE-X builds and exactly what it doesn't, so nobody overclaims to a judge who knows what a blockchain actually is.

**What's real and built (🟢 REAL): a hash-chained, tamper-evident, append-only audit ledger.**
- Every state-changing action (view of sensitive case data, decision, alert dispatch, outcome record) writes one `audit_events` row (DATA_MODEL.md §2)
- `this_hash = SHA256(prev_hash || canonical_json(payload) || occurred_at || seq_no)` — each row cryptographically commits to the entire history before it, exactly the core mechanism a blockchain uses (a hash chain), just not distributed across independent nodes
- `GET /v1/audit/verify-chain` recomputes the chain from `seq_no=1` (or a given range) and reports the first row whose stored hash doesn't match its recomputed hash — this is a real, working tamper-detection tool, not a slide claim
- Rows are `INSERT`-only; no application code path performs `UPDATE`/`DELETE` on this table, enforced additionally by a database-level `REVOKE UPDATE, DELETE` grant so it isn't just convention

**What's the honest gap, and the documented upgrade path (⚪ FUTURE): distributed/public verifiability.**
A single-database hash chain is tamper-*evident* (you can prove it was altered) but not tamper-*resistant against the database operator themselves* the way a multi-party distributed ledger is — a DBA with write access could, in principle, rewrite the whole chain consistently. The production-grade answer, named but not built this phase, is periodic **Merkle-root anchoring**: batch the ledger into Merkle trees at an interval, publish the root hash to an external, team-non-controlled anchor (a public blockchain testnet, or a neutral third-party timestamping service) so tampering would require rewriting a record the team doesn't control. This is described here precisely so "we built blockchain" is never said about the hash chain alone — the hash chain is real cryptographic tamper-evidence; the "blockchain" theme is fully satisfied only once anchoring exists.

**[Decision, after product review — PRODUCT_EXPERIENCE.md §8.3]** Merkle-root anchoring is explicitly **not attempted** in this phase. It was left open in the original architecture pass; the decision now is no — a live testnet dependency during a judged demo (network availability, gas/fee handling, key management) is a real failure risk for a beat that isn't necessary to answer the "is this blockchain" question honestly. The hash chain alone, explained precisely as above, is a complete and defensible answer on its own.

## 5. Human-in-the-loop governance

Hard architectural invariant, not a UI nicety: **the Action module's send function requires a `decision_id` referencing an `approved` row and verifies its status server-side before constructing any outbound payload.** There is no code path — no endpoint, no internal function — that can dispatch an alert or represent an "action taken" without that check passing. This is testable (IMPLEMENTATION_PLAN.md, Phase 4 exit criteria) and is the literal mechanism behind PROJECT.md §7.6 and §13's "mandatory human approval" commitment.

Rejections are first-class, not silent: a rejected deployment records the investigator's justification text and is retained exactly like an approved one for audit purposes — this matters for the "what if the prediction is wrong" judge question (PROJECT.md §16): a wrong prediction costs a rejected recommendation and a training label, never an unreviewed action.

## 6. Ethical safeguards against predictive-policing misuse

- The model scores **exit channels (H3-anchored cells, exchange accounts, or merchant orders) and time windows**, never people — there is no schema field, no feature, and no output shape anywhere in DATA_MODEL.md or AI_ML_ARCHITECTURE.md that names or profiles an individual by demographic or identity attribute. Account-level features are behavioral (transaction pattern, KYC tier, graph position), not demographic.
- Predictions are labeled **"investigative lead"** in every UI surface and API response where they appear — never presented as evidence of guilt. Concretely: `GET /v1/cases/{complaint_id}/prediction` (API_CONTRACT.md §3) carries a `disclaimer` field on every response, worded exactly: *"This is an investigative lead based on automated pattern analysis, not a definitive determination of wrongdoing."*
- **Geographic bias audit**: because `historical_incident_count` and jurisdiction-level features are inputs, the model can in principle learn to over-flag districts with more historical *policing/reporting* activity rather than more actual fraud. Mitigation: the evaluation harness (IMPLEMENTATION_PLAN.md, Phase 2) includes a fairness slice — top-K hit rate and false-positive rate computed *per jurisdiction*, not just in aggregate — so a systematic over-flagging pattern would show up as a metric, not go unnoticed until deployment.

## 7. Security controls summary

| Control | Mechanism |
|---|---|
| Transport encryption | TLS everywhere (terminated at a reverse proxy in front of the Compose stack) |
| At-rest encryption | Postgres/Neo4j volume encryption at the infra layer (production concern; noted, not re-implemented in-app) |
| Webhook integrity | HMAC-SHA256 signature header on every outbound alert payload, verified by the receiver |
| Secrets | `.env`-based for the prototype, explicitly named as a vault (e.g. HashiCorp Vault/cloud secret manager) requirement for production |
| Input validation | Pydantic models on every FastAPI route reject malformed payloads before they reach business logic |
| Rate limiting | Public intake endpoint rate-limited per IP to bound abuse of the one unauthenticated surface |
| Audit non-repudiation | `actor_id` on every event resolved from the verified JWT, never client-supplied |

## 8. Reproducibility as a governance property

Every `predictions` row stores its `feature_snapshot` and exact `model_version_*` fields (DATA_MODEL.md §2) — so any prediction shown to any investigator, at any point in the future, can be exactly reconstructed and re-explained. This is what makes PROJECT.md §13's "every prediction is reproducible" true at the schema level rather than a hopeful statement.
