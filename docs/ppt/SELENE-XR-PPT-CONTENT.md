# SELENE-XR — SIH 2026 PPT Content

Paste-ready content for a six-slide SIH submission describing the proposed production-grade system: scientific processing, distributed execution, security, reliability, model governance and air-gapped operations.

## Slide 1 — Title

### SMART INDIA HACKATHON 2026

- **Problem Statement ID:** SIH26166
- **Problem Statement:** Multi-modal, Sun-angle and Scale-invariant Image Correspondence using Chandrayaan-2 Optical Images (OHRC, TMC-2 and IIRS)
- **Theme:** Space Technology
- **Category:** Software
- **Team ID:** SIH145
- **Team:** Horizon

### Project

**SELENE-XR**

*Mission-scale, air-gapped lunar image registration platform*

**One-line pitch:** A production platform that continuously registers Chandrayaan-2 OHRC, TMC-2 and IIRS imagery to LRO and SELENE/Kaguya references—with distributed processing, uniform tie points, quantified uncertainty, human QA and reproducible scientific products.

**Production scope:** Multi-payload science pipeline · campaign processing · role-based operations · model governance · high availability · disaster recovery · signed air-gapped releases

**Visual:** SIH logo at centre-right; a small before/after lunar overlay beneath the project name. Keep this slide sparse.

---

## Slide 2 — Proposed Solution

### WHY THE IMAGES DO NOT OVERLAY

- **Illumination shift:** changing solar azimuth/elevation reverses shadows and local gradients.
- **Scale gap:** OHRC ≈0.25–0.32 m/pixel, TMC-2 5 m/pixel and IIRS ≈80 m/pixel; cross-route ratios can reach roughly **1:320**.
- **Cross-modality:** panchromatic OHRC/TMC-2 and hyperspectral IIRS do not share identical radiometry or texture.
- **Pushbroom geometry:** spacecraft motion, line-wise attitude, terrain relief and residual jitter create spatially varying deformation; one homography is insufficient.
- **Trust gap:** a high match score alone does not prove uniform coverage, sub-pixel accuracy or geodetic correctness.

### THE SOLUTION — PHYSICS-GUIDED, DATA-VERIFIED REGISTRATION

1. **Bound the search with metadata:** PDS4/ISIS labels, SPICE and a validated line-scan sensor model estimate footprint, orientation and local GSD.
2. **Build a physics-guided reference:** LRO/SELENE imagery + DTM/albedo, Hapke BRDF, ray-marched shadows, sensor PSF/noise and common-GSD pyramids.
3. **Match with two independent paths:** reproducible SIFT/RIFT/NCC/phase-correlation baselines plus a LoFTR/RoMa-style detector-free challenger.
4. **Verify before selection:** geometric consistency and local quality filtering remove false correspondences.
5. **Distribute evidence:** grid/quadtree selection maximizes eligible-region coverage after quality filtering.
6. **Refine and solve globally:** ECC/Fourier sub-pixel refinement, learned pixel-locking correction, per-match covariance, Ceres line-scan/jitter adjustment and multi-scene graph consistency.

### WHY IT IS DIFFERENT

- **Scale-equivariant, not blind scale search:** metadata narrows the scale range; imagery estimates only the residual.
- **Payload-aware:** IIRS uses thermal handling and high-SNR structural composites rather than pretending to be synthetic panchromatic imagery.
- **Physics is an auxiliary cue:** relighting/hillshade helps under sun-angle change, while the real reference remains in the verification loop.
- **Refuse rather than guess:** each completed route returns **ACCEPT / REVIEW / REJECT**, reasons and provenance.

### COMPLETE PRODUCTION SCOPE

- **Mission-complete processing:** independently qualified OHRC, TMC-2 and IIRS routes across both LRO and SELENE/Kaguya reference families.
- **Archive operations:** continuous ingestion, single-scene jobs and admission-controlled campaigns with elastic CPU/GPU worker pools for sustained and burst processing.
- **Multi-user governance:** analyst, reviewer, calibration, ML, operator and administrator roles; two-person publication and permanent override history.
- **Sovereign deployment:** on-premises, air-gap capable, no mandatory public-cloud dependency; mirrored data, kernels, packages, containers and models.
- **Operational durability:** high-availability state, resumable stage checkpoints, signed releases, monitored SLOs, backup/PITR and tested recovery.

**Visual:** left = problem; centre = S0–S7 scientific flow; right = “Complete Production Scope” with five icons for mission coverage, campaigns, governance, air gap and reliability.

---

## Slide 3 — Technical Approach

### END-TO-END SCIENTIFIC PIPELINE

```text
Source: OHRC / TMC-2 / IIRS                Reference: LROC NAC / SELENE TC + DTM/control
                 \                                      /
S0  INGEST + PREFLIGHT — schema, checksum, CRS, SPICE coverage, footprint, overlap
                              ↓
S1  REFERENCE + PYRAMIDS — reference selection, local GSD, PSF-aware resampling, masks
                              ↓
S2  PHYSICAL RENDER — DTM + albedo + Hapke BRDF + cast shadows + sensor PSF/noise
                              ↓
S3  MATCH — real reference + render + gradient/phase/curvature + detector-free/classical paths
                              ↓
S4  VERIFY + SELECT — robust geometry, NMS, eligibility mask, grid/quadtree coverage
                              ↓
S5  SUB-PIXEL REFINE — ECC/Fourier shift + bias correction + anisotropic covariance
                              ↓
S6  ADJUST — Ceres pushbroom/terrain solve + robust loss + platform-jitter spline
                              ↓
S7  GRAPH + GATE — multi-scene adjustment, cycle diagnostics, uncertainty, verdict
                              ↓
Registered COG/Zarr + adjusted model + GeoPackage tie points + metrics + provenance
```

### PAYLOAD-SPECIFIC REPRESENTATION

| Route | Representation and geometry strategy |
|---|---|
| **OHRC** | Panchromatic high-resolution tiles; pushbroom geometry; local-GSD model; terrain-aware residual field |
| **TMC-2** | Panchromatic fore/nadir/aft route; stereo-aware geometry; bridge route for lower-resolution products |
| **IIRS** | Label-driven reflective-band selection, thermal correction, PCA/gradient/phase/self-similarity composite; independently validated geometry |

### TRAINING AND CONTINUOUS CALIBRATION

- A physically parameterized corpus generator samples sun/view geometry, GSD ratio, DTM degradation, noise, PSF and sensor-model error while preserving exact correspondence truth.
- MLflow records experiments and ablations; DVC/content hashes pin corpora; the registry promotes models only after synthetic, held-out real and shadow-traffic gates pass.
- Production feedback is separated from the locked benchmark; accepted analyst reviews enter a future training set only through a versioned curation release.

### PRODUCTION PLATFORM ARCHITECTURE

```text
Browser / REST clients / CLI
            ↓
Nginx ingress + Keycloak OIDC + policy enforcement
            ↓
FastAPI modular monolith ───────── PostgreSQL 16 + PostGIS 3.4
            │                      durable jobs, products, metrics, audit
            ├── RabbitMQ quorum queues ── CPU / GPU / IO / solver workers
            ├── Redis ─────────────────── locks, rate limits, live progress
            ├── MinIO/S3 ──────────────── COG, Zarr, models, artifacts, manifests
            └── MLflow + DVC ──────────── experiments, corpora, model promotion

Workers execute resumable S0→S7 stages with content-addressed checkpoints.
OpenTelemetry → Prometheus/Grafana + Loki/Tempo provides end-to-end observability.
```

### PRODUCTION TECHNOLOGY STACK

- **Science:** Python 3.11+, NumPy, Rasterio/GDAL, Shapely, PyProj, SpiceyPy, ISIS/ALE/usgscsm, PyTorch, Ceres.
- **Execution:** Celery 5.4, RabbitMQ 3.13, Redis 7; independent CPU, GPU, IO and solver queues.
- **Data:** PostgreSQL/PostGIS as state authority; MinIO/S3 for immutable raster, model and evidence objects.
- **Interface:** React 18, TypeScript, OpenLayers/deck.gl, TanStack Query; REST/OpenAPI and headless CLI use the same scientific core.
- **Deployment:** Kubernetes, Helm, ArgoCD and Harbor; Docker Compose workstation profile; signed offline OCI bundle.
- **Standards:** PDS4, ISIS, SPICE, CSM, COG/GeoTIFF, GeoPackage, Zarr, STAC and OpenAPI.

**Visual:** pipeline across the upper half; production topology below it. Colour-code control, compute, data and observability planes.

---

## Slide 4 — Feasibility and Viability

### PRODUCTION FEASIBILITY

- **Architecture:** modular-monolith API with an event-driven staged worker fleet—transactional control without coupling long GPU work to HTTP requests.
- **Horizontal scale:** stateless API replicas; CPU/GPU/IO/solver pools scale independently from queue depth; one task per GPU preserves VRAM headroom.
- **Data scale:** tiled GDAL reads prevent full OHRC frames entering memory; PostGIS tables are partitioned; reference cache and products have separate lifecycle policies.
- **Resilience:** deterministic stages are content-addressed and resumable; transient faults retry with backoff; deterministic scientific failures never retry blindly.
- **Deployment:** on-premises Kubernetes is the reference profile, with complete air-gap support; Docker Compose and headless CLI preserve the same schemas and algorithms.

**Production-readiness statement:** SELENE-XR is scoped as an operational mission-data system from ingestion to signed scientific delivery—not only an image-matching model. Science, orchestration, identity, storage, audit, observability and recovery are designed as one governed platform.

### SCIENTIFIC VALIDATION FRAMEWORK

| Gate | Measurement |
|---|---|
| **Accuracy** | Held-out source-frame RMSE_x, RMSE_y, RMSE_2D, median endpoint error, P90 and CE90 |
| **Distribution** | Eligible-cell occupancy, convex-hull coverage and largest-empty-region reporting |
| **Robustness** | Candidate/inlier count, inlier ratio and accept/review/reject rate stratified by payload, illumination, GSD ratio and terrain |
| **Trust** | Covariance valid, adjustment conditioned, required metrics present and complete input/model/code provenance |
| **Compliance** | At least one validated end-to-end route for OHRC, TMC-2 and IIRS; both LRO and SELENE reference families represented |

### PRODUCTION ASSURANCE

| Area | Production capability |
|---|---|
| **Availability** | Redundant API, database, broker, cache and object-storage services; queued work survives compute-pool outages |
| **Performance** | Asynchronous image processing, tiled raster IO, independent worker autoscaling and admission-controlled campaigns |
| **Recovery** | PostgreSQL point-in-time recovery, object versioning, stage checkpointing and rehearsed restoration |
| **Durability** | Configurable product retention, immutable audit history, checksummed artifacts and signed manifests |
| **Continuity** | Cache-only reference mode, queued GPU work, last-known-good models and explicit degraded states |

### RISKS AND ENGINEERING MITIGATIONS

| Risk | Mitigation / fallback |
|---|---|
| Relit terrain does not correlate with real imagery | Treat it as one auxiliary channel; ablate it; fall back to structural + classical paths |
| Synthetic-to-real gap in learned matching | Frozen real holdout, domain randomization, self-supervised adaptation and classical baseline |
| Reference DTM/control limits accuracy | Propagate reference uncertainty; report DTM-limited routes; never convert pixel RMSE directly into unsupported metre accuracy |
| Weak/missing kernels or sensor metadata | Explicit preflight failure; widen coarse search only when justified; record kernel quality |
| IIRS cross-spectral ambiguity | Dedicated label-driven route and independent benchmark; do not claim compliance until it passes |

### SECURITY, GOVERNANCE AND RELEASE CONTROL

- OIDC authorization-code + PKCE, scoped API keys, RBAC/ABAC, in-cluster mTLS and default-deny network policies.
- Hardened PDS4 XML/PVL parsing, GDAL driver allow-list, sandboxed no-egress ingestion workers and argument-array subprocess calls.
- Vault-backed secrets, TLS 1.3, signed images/SBOMs, signed product manifests and append-only audit events.
- Models progress **candidate → shadow → production** only after frozen science, performance, licence and hardware gates; rollback is one reverse promotion.

**Visual:** three bands: production feasibility, scientific validation and service assurance, then risk + security controls.

---

## Slide 5 — Impact, Operations and Benefits

### WHAT ONE VERIFIED RUN DELIVERS

- Registered **COG/GeoTIFF/Zarr** products and adjusted sensor/model state.
- **GeoPackage/CSV tie-point catalogue** with source/reference coordinates, score, inlier state, covariance and selection provenance.
- Validity, overlap, shadow and optional uncertainty masks.
- Machine-readable metric report, QA overlays, residual vectors and uniformity map.
- Signed/checksummed manifest with inputs, reference versions, parameters, model and code release.
- Explicit **ACCEPT / REVIEW / REJECT** verdict with actionable failure reasons.

### USERS AND DOWNSTREAM WORKFLOWS

- **Planetary scientists:** reliable multi-mission overlays and traceable tie points.
- **Archive/production operators:** repeatable batch registration with failure diagnosis.
- **QA and calibration engineers:** route-level benchmarks, residual fields and parameter ablations.
- **Downstream science:** change detection, crater/landform measurement, DTM refinement, landing-site characterization and cross-payload fusion.

### SCIENTIFIC AND OPERATIONAL BENEFIT

- Converts isolated images into a co-registered, queryable lunar observation layer.
- Replaces clustered manual control points with verified, spatially distributed evidence.
- Separates **relative image correspondence** from **absolute map accuracy**, preserving the reference error budget.
- Makes negative results useful: unsupported geometry or weak overlap is reported, not hidden behind a plausible overlay.
- Reproducible artifacts and standards-based formats keep results usable outside the application.

### PRODUCTION OPERATIONS

- **Campaign orchestration:** catalogue-driven bulk submission, preflight cost estimate, priority/concurrency controls and halt-on-failure-rate protection.
- **Failure recovery:** resume from the last valid stage; retry by diagnosed failure class; GPU OOM retries once with a smaller tile.
- **Observability:** per-stage traces, queue depth, GPU/VRAM, cache hit rate, gate-pass ratio, derived tie-point fraction and model-version dashboards.
- **High availability:** PostgreSQL streaming replica/WAL archive, RabbitMQ quorum queues, Redis Sentinel and erasure-coded MinIO.
- **Graceful degradation:** cache-only reference access, queued GPU work, last-known-good models and explicit read-only/identity-provider states.
- **Three access paths:** analyst web console, automation REST API and deterministic CLI for external batch systems.

### END-TO-END PRODUCTION LIFECYCLE

**Ingest → validate → preflight → schedule → process → quality gate → human review → publish → catalogue → monitor → reproduce/reprocess**

### SUCCESS DASHBOARD

**RMSE / CE90 · verified inliers · eligible-cell occupancy · convex-hull coverage · largest empty region · covariance status · runtime/memory · route qualification**

**Visual:** centre a before/after swipe and tie-point coverage map; place deliverables on the left and campaign/operations controls on the right.

---

## Slide 6 — Research, Standards and Differentiation

### PRIMARY TECHNICAL REFERENCES

1. [ISRO — Chandrayaan-2 payload overview](https://www.isro.gov.in/ISRO_EN/Chandrayaan2_science.html) and OHRC, TMC-2 and IIRS instrument papers.
2. [USGS Astrogeology — Chandrayaan-2 processing guidance](https://astrogeology.usgs.gov/docs/concepts/missions/chandrayaan2/); ISIS/ALE/usgscsm sensor-model route.
3. [NASA NAIF — SPICE](https://naif.jpl.nasa.gov/naif/) geometry and kernel system.
4. [LROC NAC processing](https://lroc.im-ldi.com/data/support/downloads/LROC_NAC_Processing_Guide.pdf) and [SELENE/Kaguya Terrain Camera](https://www.kaguya.jaxa.jp/en/equipment/tc_e.htm) specifications.
5. [Ye et al. — simulated-hillshade/photometric lunar image–DEM co-registration](https://doi.org/10.1016/j.isprsjprs.2018.06.016), ISPRS JPRS (2018).
6. [Sun et al. — **LoFTR: Detector-Free Local Feature Matching with Transformers**](https://openaccess.thecvf.com/content/CVPR2021/html/Sun_LoFTR_Detector-Free_Local_Feature_Matching_With_Transformers_CVPR_2021_paper.html), CVPR 2021.
7. [Edstedt et al. — **RoMa: Robust Dense Feature Matching**](https://openaccess.thecvf.com/content/CVPR2024/html/Edstedt_RoMa_Robust_Dense_Feature_Matching_CVPR_2024_paper.html), CVPR 2024.
8. [Li et al. — **RIFT: Radiation-Variation Insensitive Feature Transform**](https://doi.org/10.1109/TIP.2019.2959244), IEEE TIP 2020.

### POSITIONING AGAINST BASELINES

| Capability | SIFT/NCC only | Detector-free only | SELENE-XR |
|---|:---:|:---:|:---:|
| Metadata/line-scan geometry prior | Limited | Optional | **Built into route** |
| Extreme illumination support | Weak | Learned robustness | **Photometric + structural + learned/classical** |
| Known 1:320-class scale handling | Expensive search | Pyramid-dependent | **Metadata-bounded local GSD/PSF pyramid** |
| IIRS-specific cross-spectral path | No | Not by default | **Dedicated structural route** |
| Uniform tie-point distribution | No guarantee | Confidence clusters | **Eligibility-aware grid/quadtree selection** |
| Per-match uncertainty | Usually absent | Confidence only | **Covariance + robust solve** |
| Fail-closed verdict and provenance | No | No | **Accept / review / reject + release trace** |
| Distributed resumable execution | Manual scripts | Model service only | **Stage checkpoints + independent worker pools** |
| Air-gapped production deployment | Ad hoc | Model-dependent | **Signed Kubernetes/Compose/CLI profiles** |

### PROJECT RESOURCES

- **Production repository:** add repository URL
- **Demo:** add video URL
- **Technical specification:** add public document URL
- **Validation evidence:** add benchmark and qualification report URL

**Visual:** research list on the left, comparison matrix on the right, project links in a narrow footer. Use QR codes only for the repository and demo.

---

## Editing Rules for the Final Deck

- Use **SELENE-XR** consistently; it is independent of JAXA’s SELENE/Kaguya mission.
- Present the complete production architecture and end-to-end operational lifecycle.
- Keep the phrases **“production platform,” “mission-scale,” “air-gapped,” “campaign processing”** and **“signed reproducible products”** visible in the actual slides—not only in speaker notes.
- Never call LRO NAC the lunar datum; call it a reference product with uncertainty.
- Do not claim the relighting channel cancels illumination or that synthetic data removes the need for real validation.
- Do not claim cycle closure is absolute accuracy; it is a consistency diagnostic.
- Replace every placeholder link before submission.
