# TRACE-X — AI/ML Architecture

> Depends on: [PRODUCT.md](PRODUCT.md) for the component legend. Every stage below states its classification up front — read that before the detail, it governs how the stage is allowed to be described to judges.

---

## 0. Why this is an ensemble, not one model

The target is a joint distribution over space and time, conditioned on a specific complaint's evolving graph — not a single classification label. PROJECT.md §9 already rejects a single classifier for this reason. Each pipeline stage below does one narrow, evaluable job and hands a typed output to the next stage. This also means a weak stage (inevitable, given synthetic training data) degrades the pipeline gracefully instead of being hidden inside one opaque model.

Pipeline order: **Graph Builder → Ring Detector → Corridor/Exit-Vector Predictor → Exit-Channel + Time-Window Scorer → Risk Field Fusion → Explainer → Intervention Optimizer**.

---

## 1. Fraud Intelligence Graph Builder — 🟢 REAL

| | |
|---|---|
| **INPUT** | New `complaint.created` or `transaction.ingested` event: complaint record, transaction records (from/to account hashes, amount, channel, timestamp), account metadata, device/phone linkage records |
| **PROCESSING** | Deterministic ETL, not ML: upsert nodes/edges into Neo4j (`Complaint`, `Account`, `Transaction`, `Device`, `Phone`, `ExitChannel` nodes — generalized from `CashOutPoint`, DATA_MODEL.md §2–3; `TRANSFERRED_TO`, `EXITED_VIA`, `SHARES_DEVICE_WITH`, `LINKED_TO_CASE`, `HISTORICALLY_EXITED_VIA` edges). Hop index computed via BFS from the victim account, bounded at a configurable max depth (default 6) to keep traversal cost bounded — the direct answer to the "scale to 8,000 complaints/day" concern (PROJECT.md §16) |
| **OUTPUT** | Updated subgraph for the complaint: node/edge counts, hop depth reached, list of touched account hashes passed to the next stage |
| **HOW EVALUATED** | Not a model — evaluated as software: graph-construction correctness tests (does a known synthetic fraud ring produce the expected node/edge set?), traversal latency under bounded hop depth |
| **HOW VISUALIZED** | Investigator Console's graph view: force-directed or hierarchical layout, victim account highlighted, hop distance shown as concentric rings or color gradient |

---

## 2. Ring / Mule-Network Detector — 🔵 ML-PROTO

| | |
|---|---|
| **INPUT** | The subgraph from stage 1, restricted to accounts within the bounded hop depth, plus edge weights (transaction count/amount, shared-device flags) |
| **PROCESSING** | **Prototype-honest choice**: Louvain community detection (unsupervised, `networkx`/`python-louvain`) over the weighted account graph to find densely-connected clusters — these *are* candidate mule rings, found from structure alone, no labels required. A GNN-based ring classifier (PyTorch Geometric, as named in PROJECT.md §10) is documented as the production upgrade because it would need thousands of confirmed-ring labels to train meaningfully, which we do not have honestly; training one now on synthetic labels only and presenting it as learned intelligence would be exactly the kind of overclaim this project explicitly refuses to make (see PRODUCT.md §1, §5) |
| **OUTPUT** | `ring_id` assigned per account, ring cohesion score, list of "sibling" accounts already flagged in other cases within the same ring |
| **HOW EVALUATED** | On synthetic data where we control ground-truth ring membership at generation time: precision/recall of recovered ring membership against the generator's known assignment; modularity score as an unsupervised sanity check |
| **HOW VISUALIZED** | Graph view color-codes nodes by `ring_id`; a side panel lists "N accounts in this ring, M already implicated in other open cases" — this is the concrete mechanism behind PROJECT.md §7.1's claim that a sibling account's past behavior is often the strongest signal |

### 2a. Graph projection (implemented in Phase 2B)

**Do not blindly run Louvain over every node and relationship** - the projection below is deliberately narrower than the raw Neo4j graph.

| Aspect | Definition |
|---|---|
| Included node types | `Account` only. `Device`/`Phone`/`IP`/`VPA`/`ExitChannel`/`Complaint` are never Louvain input nodes - they inform edge construction (below) but are not part of the graph Louvain partitions. |
| Included relationship types | `TRANSFERRED_TO` (direct evidence), plus four *derived* relationships computed fresh at projection time: `SHARES_DEVICE_WITH`, `SHARES_PHONE_WITH`, `SHARES_IP_WITH`, `SHARES_VPA_WITH` (materialized into Neo4j as real, inspectable edges - not just an in-memory artifact - matching DATA_MODEL.md §3's original "derived from shared Device node" design intent, now also extended to IP/VPA for symmetry with Phase 2A's `HAS_IP`/`HAS_VPA`). `INVOLVES`, `HAS_*`, `EXITED_VIA` are read to *derive* the above, never included as projection edges directly. |
| Edge weighting | `weight(A,B) = transferred_to_count(A,B) + 2·shared_device_count(A,B) + 2·shared_phone_count(A,B) + 1·shared_ip_count(A,B) + 2·shared_vpa_count(A,B)`. Every coefficient is stated, not tuned: device/phone/VPA sharing get a 2× weight because two unrelated people plausibly sharing a phone or registering the same VPA is rare - a real signal of common control. IP sharing gets 1× (not 2×) because shared public IPs (carrier-grade NAT, shared WiFi, VPN exit nodes) are common between genuinely unrelated accounts, so it's deliberately the weakest signal, not absent. `transferred_to_count` gets 1× per transaction (see "repeated transactions" below) as the baseline unit the others are calibrated against. |
| Directionality | Collapsed to **undirected** for community detection - ring membership is "who transacts with whom," not flow direction. Flow direction (and hop distance from a victim) is preserved separately in Neo4j's directed `TRANSFERRED_TO` edges and Postgres's `hop_index`; nothing about that is lost, Louvain simply doesn't need it for its own objective (modularity is defined over undirected graphs). |
| Repeated transactions | **Additive, not deduplicated.** Two accounts that transacted 5 times get `transferred_to_count=5` contributing 5 to that pair's weight, not 1 - a pair transacting repeatedly is a stronger signal of a real relationship than a pair transacting once, and the projection should reflect that rather than flattening it to a boolean "connected/not connected." |
| Shared devices/IPs/phones/VPAs | Computed via a Cypher pattern of the shape `MATCH (a:Account)-[:HAS_DEVICE]->(d:Device)<-[:HAS_DEVICE]-(b:Account) WHERE a.account_hash < b.account_hash` (the inequality avoids counting each pair twice and self-pairs), once per entity type. Each distinct shared entity contributes its type's weight per occurrence - two accounts sharing 2 devices contribute `2 × 2 = 4` to their edge weight, consistent with "repeated transactions" being additive too. |
| Minimum graph size | Louvain requires ≥2 nodes and ≥1 edge to produce a meaningful partition. Below that, detection returns an empty result (zero communities), not an error - a single isolated account, or a graph with accounts but no edges yet, is a valid, common state (e.g. immediately after a complaint is filed but before any transaction is traced), not a failure. Detected communities of size 1 (a node Louvain couldn't attach to anything) are filtered out before persistence - a "ring" by definition has ≥2 members. |
| Bounded traversal assumptions | Inherited from Phase 2A, not re-implemented: `TRANSFERRED_TO` edges beyond `settings.max_hop_depth` were never written to Neo4j in the first place (`app/graph/builder.py::apply_transaction` skips them), so the projection is automatically bounded without the projection code needing its own depth limit. |
| Scope | **Global**, not scoped to one complaint - Louvain runs over the *entire* current account graph in one pass. Scoping per-complaint would defeat the purpose: the whole value of ring detection is finding mule networks that span multiple complaints via shared accounts/devices, which a per-complaint view can never see. |
| Determinism | NetworkX's `louvain_communities` takes a `seed` parameter - `settings.louvain_random_seed` (fixed, default 42) is always passed. Combined with the projection's edge weights being a pure function of Neo4j's current state (no randomness in construction), the same graph input always produces the same partition. |

### 2b. Suspiciousness features (transparent, not a single fraud score)

**No single arbitrary score is computed.** Each feature below is reported independently; combining them into one calibrated risk number is Exit-Channel/Risk-Field work (later phases), explicitly out of scope here.

| Feature | Input | Formula | Output | Why it matters |
|---|---|---|---|---|
| `cohesion_score` | Community's internal edge weights, member count `n` | `total_internal_edge_weight / (n·(n-1)/2)` | Normalized density, ≥0 | The same graph-theoretic quantity Louvain itself optimizes (modularity is built from internal-vs-external density) - a high score means members are unusually tightly interconnected relative to how many connections *could* exist, not just how many transactions happened to occur. |
| `entity_sharing_density` | Count of `SHARES_*_WITH` edges internal to the community, `n` | `shared_entity_edges / (n·(n-1)/2)` | 0–1+ ratio | Legitimate accounts rarely share devices/phones/VPAs with many other accounts; a high ratio suggests one operator behind multiple "accounts." |
| `fan_in_to_fan_out_amount_ratio` | Total amount on `TRANSFERRED_TO` edges entering the community from outside vs. leaving it to outside | `fan_in_amount / fan_out_amount` (null if fan-out is zero) | Ratio near 1 | Classic layering signature: money enters from a few victim-side sources and exits at close to the same total, passing through rather than accumulating - unlike a legitimate savings/business account cluster, which typically doesn't. |
| `transaction_velocity` | Count of internal transactions, span between their earliest and latest `occurred_at` | `count / hours_spanned` (null if span is zero or only one transaction - see below) | Transactions/hour | Fast layering (money moved in minutes-to-hours) is a stronger fraud signal than the same transaction count spread over weeks; reported as null rather than a fabricated divide-by-zero guard when the span can't support a rate. |
| `burst_ratio` | Internal transaction timestamps, bucketed into 1-hour windows | `max(transactions in any single 1-hour bucket) / total_internal_transactions` | 0–1 ratio | Near 1 means nearly all activity happened in one burst - consistent with a scripted/orchestrated operation; near 0 means spread out, more consistent with organic, unrelated activity that Louvain happened to connect on a weak signal. |
| `exit_concentration` | Count of distinct `ExitChannel`s reached via `EXITED_VIA` from community members, count of such edges | `1 - (distinct_exit_channels / total_exit_edges)` (null if no exit edges) | 0–1 ratio | Many mule accounts converging on the *same* physical ATM/exchange/merchant is a strong operational signature - the same physical people or the same compromised merchant account are involved, not a coincidence. |
| `geographic_spread_km` | Member accounts' `branch_lat`/`branch_lon` (where present) | Max pairwise Haversine distance among members with known coordinates | Kilometers, null if <2 members have coordinates | Reported descriptively, **not** scored as "higher = more suspicious" - a tight local cluster and a deliberately geographically distributed one are both plausible fraud patterns for different reasons (opportunistic local ring vs. organized effort avoiding a single jurisdiction's attention), and asserting a direction here would be exactly the kind of fabricated correlation this section exists to avoid. |

---

## 3. Corridor / Exit-Vector Predictor — 🔵 ML-PROTO

| | |
|---|---|
| **INPUT** | Sequence of hops for the ring (account → account transitions with amount, channel, elapsed time, and each account's branch geolocation), plus the ring's historical cash-out corridor if any sibling case exists |
| **PROCESSING** | Prototype-honest choice: gradient-boosted sequence features (lag features over the hop sequence — direction vector, distance covered per hop, velocity, channel-switch pattern) feeding a classifier over discretized bearing/direction buckets, rather than a full LSTM/Transformer trained from scratch on a small synthetic corpus (which would overfit and produce a *worse*, not better, result than engineered features at this data volume). The Transformer/seq2seq architecture named in PROJECT.md §9 is documented as the production path once real historical-corridor volume exists |
| **OUTPUT** | A predicted **exit vector**: a bearing/direction and expected distance range from the last-known account's geolocation, i.e. "the money is moving roughly ENE, expect cash-out within the 3–7 km band" — this narrows the candidate H3 cell set handed to stage 4, rather than scoring the entire city blind |
| **HOW EVALUATED** | Held-out synthetic corridors: was the true cash-out direction within the predicted bearing's confidence cone? Reported as a hit-rate at ±30° and ±60° cones |
| **HOW VISUALIZED** | An animated directional cone/wedge on the risk map, rendered before the full hex risk field — this is the "watch the corridor ignite" moment from PROJECT.md §12 step 3 |

---

## 4. Exit-Channel + Time-Window Scorer — 🔵 ML-PROTO

**[Generalized after product review — PRODUCT_EXPERIENCE.md §7]** Originally scoped as a pure "location scorer" over H3 cells. Because Scenario B (crypto P2P) and Scenario C (e-commerce) don't resolve to a bare geographic cell the way an ATM cash-out does, this stage now scores candidate `exit_channels` (DATA_MODEL.md §2), each of which always carries an `h3_cell` via its `geo_anchor` — so the map is never empty — but whose *type-specific* features differ.

| | |
|---|---|
| **INPUT** | Fused feature vector per candidate exit channel (restricted to the exit-vector's candidate set): transaction signals (amount, velocity, hop count, structuring flags), historical signals (past exits by this ring/corridor/cluster), geographic signals (distance from victim, corridor alignment, jurisdiction/border proximity), temporal signals (hour of day, day of week, ATM replenishment cycle / exchange settlement cycle / merchant dispatch SLA), and `channel_attributes` specific to `channel_type` (cash limit/CCTV/footfall for `atm_cash`; exchange KYC tier for `crypto_p2p`; order value/SKU category for `ecommerce_merchant`) |
| **PROCESSING** | Two coupled models, shared across all three channel types with `channel_type` as a categorical feature (not three separate models — one model that has learned the type-conditional pattern, which is also more honest about data volume than training three separate small models): (a) **XGBoost binary classifier** per channel → `P(exit at this channel within horizon)`; (b) **Cox proportional-hazards survival model** (`lifelines`) over the same features → a hazard curve giving `expected time-to-exit`, converted into the actionable time window. Together these produce the full `P(exit | channel, time-bucket)` surface named in PROJECT.md §7.2, honestly split into a spatial/channel model and a temporal model rather than one model faking both |
| **OUTPUT** | Ranked list of `(exit_channel_id, h3_cell, channel_type, probability, time_window, confidence_interval)` |
| **HOW EVALUATED** | **Top-K hit rate** (was the true synthetic exit channel in the top 5/10 ranked channels?), **time-window calibration** (of predictions that said "45 min," what fraction of true events fell in that window — reliability diagram), Brier score for the probability outputs — computed per `channel_type` as well as in aggregate, so a scenario-specific weakness doesn't hide inside a good aggregate number. These are exactly the metrics PROJECT.md §9 commits to and accuracy is explicitly not reported as a headline number, because a spatial distribution has no single "accuracy" |
| **HOW VISUALIZED** | The H3 hex risk surface itself (color-graded by probability), with the headline banner ("87% risk of cash withdrawal in this corridor within the next 45 minutes," or the exchange/merchant equivalent for Scenarios B/C) driven directly by the top-ranked channel's actual model output — never a hardcoded string |

---

## 5. Dynamic Risk Field Fusion — 🟡 ALGO

| | |
|---|---|
| **INPUT** | Per-cell scores from stage 4 across all currently-active complaints in a jurisdiction, plus a decay function applied to previous field states |
| **PROCESSING** | Deterministic fusion, not ML: `risk(cell, t) = Σ_active_complaints score(cell, complaint) · decay(t − t_generated)`, where `decay` is an exponential half-life function (tunable per fraud-type). This is what makes the field "continuously updated" rather than a static heatmap — new transactions push scores up, unrealized risk fades. Also handles overlap: if two complaints both implicate the same cell, their contributions combine rather than overwrite |
| **OUTPUT** | The live jurisdiction-wide risk surface: one probability value per H3 cell per time bucket, refreshed on every `transaction.ingested` event but only recomputed for touched cells (incremental, per ARCHITECTURE.md §5) |
| **HOW EVALUATED** | Software correctness tests (decay curve matches spec, overlap combination is order-independent) — this stage has no learned parameters to evaluate as a model, only the fusion formula's behavior |
| **HOW VISUALIZED** | The dashboard's base heat layer; a time slider lets the investigator scrub the decay in reverse to see how the field looked N minutes ago (supports PROJECT.md §6's "historical replay") |

---

## 6. Explainability — 🟢 REAL

| | |
|---|---|
| **INPUT** | The trained XGBoost model from stage 4, the specific feature vector for the top-ranked cell(s), and the graph path from stage 1/2 |
| **PROCESSING** | `shap.TreeExplainer` computes exact Shapley values for the specific prediction being explained (not a global approximation) → top contributing features with signed weights. Combined with a graph-path extraction query (shortest weighted path from victim account to the flagged exit channel in Neo4j, via the `EXITED_VIA` edge — DATA_MODEL.md §3) and a lookup of comparable historical cases (nearest neighbors in feature space among past resolved cases) |
| **OUTPUT** | A structured explanation object: ranked `(feature, weight)` pairs, the graph path as an ordered node list, 1–3 comparable historical case references, and a plain-language sentence template filled from the top 2–3 features — e.g. PROJECT.md §7.4's example sentence, generated from real SHAP output, not authored per-demo |
| **HOW EVALUATED** | SHAP values are exact for tree ensembles (no approximation error to measure); what's validated is *consistency* — a regression test that the same input always yields the same explanation, and a human-review check that the plain-language template reads sensibly across a sample of generated explanations |
| **HOW VISUALIZED** | Explanation panel: horizontal bar chart of feature weights, the graph path overlaid on the graph view, a small comparable-cases list with links to their case records |

---

## 7. Intervention Optimizer — 🟡 ALGO

**[Generalized after product review — PRODUCT_EXPERIENCE.md §7]** Branches into two genuinely different algorithm classes by the top-ranked exit channel's `intervention_action_type` (DATA_MODEL.md §2) — this is what makes Scenarios A/B/C produce real, structurally different interventions rather than the same output with different labels (greedy-only, per PRODUCT_EXPERIENCE.md §8.5 — no ILP path is built in this phase for either mode).

### 7a. `physical_team_deployment` mode (Scenario A) — coverage maximization

| | |
|---|---|
| **INPUT** | Ranked risk surface for the relevant candidate exit channels, number of available teams (investigator input), team current locations, travel-time matrix (Haversine distance as a proxy, or a real routing API if available), each team's effective coverage radius |
| **PROCESSING** | Real implementation of maximum coverage under a cardinality constraint: greedy algorithm that iteratively picks the team-location assignment adding the most *uncovered* probability mass, accounting for overlap between nearby high-risk cells (the "three ATMs on one street, one team suffices" case from PROJECT.md §7.5). Greedy gives a provable (1 − 1/e) ≈ 63% approximation to the optimal coverage for this problem class |
| **OUTPUT** | Assignment list: `(team_id, exit_channel_id, expected_coverage_contribution, travel_time)`, plus the aggregate **expected intervention coverage** metric |
| **HOW EVALUATED** | Coverage-ratio comparison against the naive baseline ("send teams to the top-N channels by score") — reported as "+X% expected coverage vs. naive top-N," operationalizing PROJECT.md §9's "expected coverage gain" metric |

### 7b. `exchange_freeze_request` / `merchant_hold_request` mode (Scenarios B/C) — resource-constrained ranking

| | |
|---|---|
| **INPUT** | Ranked exit-channel list, number of available request slots (an exchange or merchant compliance desk can only action a bounded number of urgent requests at once — the resource constraint here, standing in for "limited teams"), each channel's hazard curve from stage 4 |
| **PROCESSING** | A ranked knapsack: score each candidate channel by **expected value of requesting now** = `P(exit within window) × amount_at_risk × hazard-adjusted urgency`, then take the top-`request_slot_count` by that score. This is a genuinely different optimization problem from 7a — there is no geography/travel-time to trade off, the scarce resource is compliance-desk attention, not team-hours — which is the concrete proof that Scenarios B/C exercise a different code path, not a relabeled one |
| **OUTPUT** | Ranked list: `(exit_channel_id, priority_rank, expected_value, hazard_at_request_time)` |
| **HOW EVALUATED** | Expected-value-captured comparison against the naive baseline ("request the top-N by probability alone, ignoring amount/urgency") — the equivalent coverage-gain number for this mode |

**HOW VISUALIZED (both modes)**: Deployment pins (7a) or a ranked request list with priority badges (7b) on the map/side-panel; a side-by-side toggle showing "naive top-N" vs. "TRACE-X optimized" so the judge sees the difference, not just the label — this is PROJECT.md §12 step 6's demo beat, made literal for whichever mode the active scenario uses.

---

## 8. Feedback / Retraining Loop — 🟢 REAL mechanism, 🔵 ML-PROTO training job

| | |
|---|---|
| **INPUT** | `intervention.outcome` events: was the predicted cell/window correct, was money recovered, was the deployment useful, investigator's free-text/structured feedback |
| **PROCESSING** | Every outcome is written as a labeled training row (features as they were at prediction time + realized outcome) into a versioned feature/label table — this is the real, working mechanism, not simulated. A scheduled or manually-triggered retraining job (same XGBoost/Cox/Louvain pipeline as stages 2–4) re-fits on the accumulated labeled set and registers a new model version if it beats the current one on the held-out evaluation set |
| **OUTPUT** | A new versioned model artifact + evaluation report; promotion to "active" is a deliberate step, not automatic, so a regression is never silently deployed |
| **HOW EVALUATED** | Champion/challenger comparison on the same held-out set (top-K hit rate, calibration, coverage gain from §§2–7) before promotion |
| **HOW VISUALIZED** | Admin/auditor's model registry view: version history, the metric deltas between versions, which version is currently active |

---

## 9. Model registry & feature store

🟢 REAL, deliberately lightweight. **Model registry**: a Postgres table (`model_id`, `stage`, `version`, `trained_at`, `metrics_json`, `artifact_path`, `is_active`) plus artifacts on local disk/object storage — a full MLflow deployment is named as the production upgrade but is unnecessary complexity for the number of models this system trains. **Feature store**: versioned Postgres tables per stage (not Feast) — every prediction persists the exact feature values used, which is also what makes explanations reproducible (PROJECT.md §13's "every prediction is reproducible: model version, feature values and explanation are stored with it").

## 10. Synthetic data generation — 🟢 REAL (the component, not the data it produces)

See [DEMO_ARCHITECTURE.md](DEMO_ARCHITECTURE.md) for the generator's design. Architecturally relevant point here: the generator must produce data that is **structurally realistic** (fraud rings with real hop patterns, corridors with real geographic movement, cash-out events with real time-to-event distributions) calibrated against published aggregate NCRB/I4C statistics (typical amounts, typical hop counts, typical layering duration), even though no individual synthetic record corresponds to a real case. This is what makes stages 2–7 honestly trainable at all.

## 11. Summary: what's learned vs. what's computed

| Stage | Has learned parameters? | Retrains on feedback? |
|---|---|---|
| Graph Builder | No | N/A |
| Ring Detector | No (unsupervised clustering, no fit parameters persisted as a "model") | Re-run per graph state, not "retrained" |
| Corridor Predictor | Yes (gradient-boosted classifier) | Yes |
| Exit-Channel + Time-Window Scorer | Yes (XGBoost + Cox model) | Yes |
| Risk Field Fusion | No | N/A |
| Explainability | No (derives from stage 4's model) | Tracks stage 4's version |
| Intervention Optimizer | No | N/A |
