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

**Visual:** left = problem; centre = S0–S6 scientific flow; right = “Complete Production Scope” with five icons for mission coverage, campaigns, governance, air gap and reliability.

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
S6  ADJUST + GRAPH + GATE — Ceres pushbroom/terrain solve, jitter, scene graph,
                            cycle diagnostics, uncertainty and verdict
                              ↓
Registered COG/Zarr + adjusted model + GeoPackage tie points + metrics + provenance
```

### PAYLOAD-SPECIFIC REPRESENTATION

| Route | Representation and geometry strategy |
|---|---|
| **OHRC** | Panchromatic high-resolution tiles; pushbroom geometry; local-GSD model; terrain-aware residual field |
| **TMC-2** | Panchromatic fore/nadir/aft route; stereo-aware geometry; bridge route for lower-resolution products |
| **IIRS** | Label-driven reflective-band selection, thermal correction, PCA/gradient/phase/self-similarity composite; independently validated geometry |

### CORRESPONDENCE AND SOLVE CONTRACT

- Each tie point stores source/reference pixel coordinates, lunar ground estimate, matcher/channel origin, confidence, inlier state, local-warp Jacobian and a 2×2 covariance matrix.
- Verification combines the metadata displacement prior, forward/backward agreement, robust local geometry and neighbourhood consistency before coverage selection.
- The adjustment solves camera/line-state corrections and terrain intersection jointly under robust loss; withheld points, residual structure and covariance conditioning drive the final verdict.
- Cross-sensor residuals are transformed through the local Jacobian before comparison, preserving correct units across different GSDs.

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

Workers execute resumable S0→S6 stages with content-addressed checkpoints.
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

### EVIDENCE STRATEGY

- **Synthetic truth:** exact dense flow for controlled illumination, scale, geometry and sensor degradation.
- **Held-out real scenes:** independently reviewed check points across payload, reference, sun-angle, relief and GSD strata.
- **Leave-one-out validation:** detects over-fitting of the adjustment to selected tie points.
- **Graph diagnostics:** forward/backward and cycle closure expose inconsistent registration paths while remaining separate from absolute control accuracy.

### REQUIREMENT-TO-EVIDENCE TRACEABILITY

| Problem / requirement | Pipeline response | Evidence and gate | Published outcome |
|---|---|---|---|
| Sun-angle and shadow reversal | S2 physical render + S3 real/render/structural channels | Illumination-stratified holdout + render/channel ablation | Registered overlay that remains tied to the real reference |
| 1:320-class scale gap | S0 metadata prior + S1 local-GSD/PSF pyramids | GSD-stratified endpoint error, CE90 and route-success rate | Scale-normalized, verified correspondences |
| OHRC/TMC-2/IIRS modality gap | Payload-specific S1/S3 representations and independently qualified routes | Per-payload × reference-family benchmark matrix | Comparable registered products for all required payloads |
| Pushbroom, terrain and jitter distortion | S6 line-scan/terrain adjustment + jitter spline | Withheld-point error, residual structure and conditioning | Adjusted sensor/model state with uncertainty |
| Clustered or locally convincing matches | S4 eligibility mask + grid/quadtree selection | Cell occupancy, hull coverage and largest empty region | Spatially useful tie-point catalogue |
| Scientific trust and repeatability | S5 covariance + S6 graph/gate + signed manifest | Calibration, provenance-completeness and replay checks | ACCEPT / REVIEW / REJECT product with reproducible evidence |

This matrix closes the loop from each stated challenge to the responsible stage, the measurement that validates it and the exact scientific product delivered.

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

Every published object is bound to a manifest containing the source checksum, reference/control versions, SPICE kernel inventory, parameter set, model IDs, code revision, container digest and stage-artifact hash chain.

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

1. [ISRO — Chandrayaan-2 payload overview](https://www.isro.gov.in/ISRO_EN/Chandrayaan2_science.html).
2. [Current Science — **OHRC instrument design and performance**](https://www.currentscience.ac.in/Volumes/118/04/0560.pdf), 2020.
3. [Current Science — **TMC-2 instrument design and performance**](https://www.currentscience.ac.in/Volumes/118/04/0566.pdf), 2020.
4. [Current Science — **IIRS instrument and science capability**](https://www.currentscience.ac.in/Volumes/118/03/0368.pdf), 2020.
5. [NASA PDS — **PDS4 Information Model Specification**](https://pds.nasa.gov/datastandards/documents/im/current/index_1L00.html) and [USGS Chandrayaan-2 processing guidance](https://astrogeology.usgs.gov/docs/concepts/missions/chandrayaan2/).
6. [Laura, Mapel & Hare — **Planetary sensor-model interoperability using CSM**](https://doi.org/10.1029/2019EA000713), Earth and Space Science 2020.
7. [NASA NAIF — **SPICE**](https://naif.jpl.nasa.gov/naif/) geometry and kernel system.
8. [LROC NAC processing guide](https://lroc.im-ldi.com/data/support/downloads/LROC_NAC_Processing_Guide.pdf) and [JAXA SELENE Terrain Camera](https://www.kaguya.jaxa.jp/en/equipment/tc_e.htm) specifications.
9. [Hapke et al. — **Photometric studies of complex surfaces, with applications to the Moon**](https://doi.org/10.1029/JZ068i015p04545), JGR 1963.
10. [Ye et al. — **Simulated-hillshade lunar image–DEM co-registration**](https://doi.org/10.1016/j.isprsjprs.2018.06.016), ISPRS JPRS 2018.
11. [LoFTR](https://openaccess.thecvf.com/content/CVPR2021/html/Sun_LoFTR_Detector-Free_Local_Feature_Matching_With_Transformers_CVPR_2021_paper.html), [RoMa](https://openaccess.thecvf.com/content/CVPR2024/html/Edstedt_RoMa_Robust_Dense_Feature_Matching_CVPR_2024_paper.html) and [RIFT](https://doi.org/10.1109/TIP.2019.2959244) — detector-free, dense and multimodal correspondence baselines.
12. [NASA Ames Stereo Pipeline](https://stereopipeline.readthedocs.io/en/stable/introduction.html) and [Ceres Solver bundle adjustment](https://ceres-solver.readthedocs.io/latest/nnls_tutorial.html) documentation.
13. [OGC Cloud Optimized GeoTIFF 1.0](https://www.ogc.org/standards/ogc-cloud-optimized-geotiff/) — interoperable tiled raster delivery.
14. [USGS ISIS](https://isis.astrogeology.usgs.gov/) — calibrated planetary-image processing, camera models and map projection.
15. [NASA SLDEM2015](https://pgda.gsfc.nasa.gov/products/54) and LOLA-derived elevation products — terrain support and independent control context.

### BENCHMARK AND ABLATION DESIGN

| Benchmark layer | Dataset design | Reported measures | What it proves |
|---|---|---|---|
| **Controlled correspondence** | Synthetic lunar pairs with exact flow; varied sun/view geometry, GSD, PSF, noise and sensor perturbation | Endpoint error, P90/CE90, calibration error, failure rate | Numerical correctness and sensitivity boundaries |
| **Real cross-mission routes** | Frozen OHRC/TMC-2/IIRS × LRO/SELENE pairs stratified by illumination, relief, overlap and GSD ratio | Source-frame RMSE, inlier ratio, route success, coverage | Real-data robustness for every required route |
| **Independent control** | Withheld expert check points and higher-accuracy LOLA/GCP control where available | Relative pixel error and absolute horizontal error with reference uncertainty | External accuracy rather than fit-to-tie-points |
| **Coverage quality** | Eligible overlap divided into grid/quadtree cells | Occupancy, convex-hull ratio, largest empty region | Matches support the whole image, not one feature cluster |
| **Ablation campaign** | Remove render, PSF matching, structural channels, coverage selection, bias correction and jitter terms one at a time | Metric delta by scene stratum | Which component produces each gain |
| **Production campaign** | Continuous mixed-payload queue with injected worker/storage/model failures | Stage latency, throughput, cache reuse, retry/recovery, gate stability | Operational scalability and graceful recovery |

### EXISTING SOLUTIONS AND SELENE-XR ADVANTAGE

| Existing approach | Primary strength | Remaining gap for SIH26166 | SELENE-XR advantage |
|---|---|---|---|
| **USGS ISIS + Ames Stereo Pipeline** | Mature planetary calibration, camera models, stereo, bundle adjustment and jitter tools | General planetary workflow; cross-modal, extreme-illumination correspondence still needs route-specific representations and gates | Adds payload-aware matching, physical/structural channels, uniform tie-point selection and an operator production layer |
| **SIFT/NCC/phase correlation** | Transparent, reproducible and efficient baseline | Feature repeatability degrades across shadow reversal, large GSD gaps and hyperspectral-to-panchromatic pairs | Fuses metadata-bounded pyramids, multiple representations and robust verification while retaining these as fallbacks |
| **RIFT and multimodal descriptors** | Structural features improve radiation/modality robustness | Does not by itself solve pushbroom geometry, reference uncertainty, spatial coverage or production delivery | Couples multimodal features to SPICE/CSM geometry, covariance and terrain-aware adjustment |
| **LoFTR / RoMa** | Dense detector-free correspondence and strong learned matching | Generic image matching has no lunar photometric model, payload routing, quality verdict or archive provenance | Uses learned matching as one challenger inside a physics-guided, fail-closed scientific system |
| **Image–DEM relighting methods** | Reduce illumination mismatch using terrain and simulated shading | Accuracy is limited by DTM/albedo quality and absent fine texture; usually pairwise research workflows | Keeps the real reference in verification, fuses structural channels and propagates terrain/reference uncertainty |

### WHY SELENE-XR IS STRONGER AS A SYSTEM

- **End-to-end requirement coverage:** all three Chandrayaan-2 payloads, both named reference families, registered products, tie points and evaluation evidence.
- **Multiple independent hypotheses:** geometry, real imagery, physical rendering, structural features, classical matching and learned matching can corroborate or reject one another.
- **Uncertainty is part of the product:** covariance, reference error, residual structure and coverage determine the verdict; confidence is not treated as accuracy.
- **Production continuity:** resumable stages, content-addressed caches, model rollback, signed manifests and air-gapped campaign operation.

### CAPABILITY SUMMARY

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

### TECHNICAL EVIDENCE PACK

- [Complete technical specification](../context/SELENE-XR-Complete-Technical-Specification.md) — requirements, scientific pipeline, data contracts and production architecture.
- [Technical verification](../context/SELENE-XR-Technical-Verification.md) — challenge interpretation, instrument facts, corrections and metric definitions.
- [Architecture-decision index](../adr/README.md) — versioned decisions for coordinates, reference authority, matching, coverage, adjustment, verdicts, lifecycle, security and roles.

**Visual:** use a two-column reference block across the top; place the benchmark table and existing-solution comparison below it. If space is tight, move the detailed benchmark table to an appendix slide and retain its six benchmark-layer labels on Slide 6.

---

## Editing Rules for the Final Deck

- Use **SELENE-XR** consistently; it is independent of JAXA’s SELENE/Kaguya mission.
- Present the complete production architecture and end-to-end operational lifecycle.
- Keep the phrases **“production platform,” “mission-scale,” “air-gapped,” “campaign processing”** and **“signed reproducible products”** visible in the actual slides—not only in speaker notes.
- Never call LRO NAC the lunar datum; call it a reference product with uncertainty.
- Do not claim the relighting channel cancels illumination or that synthetic data removes the need for real validation.
- Do not claim cycle closure is absolute accuracy; it is a consistency diagnostic.
- The project repository is private. Add its URL or QR to the submitted deck only after public visibility or judge access has been verified; apply the same rule to any demo or evidence URL.
