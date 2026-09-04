# SELENE-XR — Technical Verification and SIH26166 Compliance Note

Verified on 26 August 2026 against the supplied technical specification, the supplied SIH presentation template, the official SIH 2026 problem statement, and primary mission/software sources.

## Executive verdict

The project has a strong, relevant research direction and it covers the required software, registered product, match-point and evaluation outputs. The original specification is best treated as a long-term architecture and research backlog—not as evidence of an already validated prototype.

The final presentation therefore uses the defensible core:

> Physics-guided, multi-scale image correspondence with payload-aware adapters, coverage-aware tie-point selection, uncertainty-aware sub-pixel refinement, and terrain-aware geometric adjustment.

It does **not** claim that an exact physical render removes all illumination effects, that synthetic data eliminates the real-data problem, or that any runtime/accuracy target has already been achieved.

## Official challenge verification

| Item | Verified status |
| --- | --- |
| Problem Statement ID | **SIH26166** |
| Organization / category / theme | ISRO / Software / Space Technology |
| Required source payloads | Chandrayaan-2 OHRC, TMC-2 and IIRS |
| Required behavior | Multi-modal, sun-angle and scale-robust correspondence; viewpoint variation must also be handled |
| Required output | Software, registered product, corresponding match points and evaluation metrics |
| Accuracy requirement | Sub-pixel accuracy in the **source-image frame** with matches uniformly distributed across the image/valid overlap |
| Reference imagery named | LRO NAC and SELENE imagery |
| Organizer dataset | **TBD as of the verification date** |

Primary source: [official SIH 2026 problem statement](https://sih.gov.in/sih2026PS#ViewProblemStatement26166).

## Verified payload and reference facts

| Sensor/reference | Safe deck wording | Notes |
| --- | --- | --- |
| Chandrayaan-2 OHRC | Visible panchromatic; approximately **0.25–0.32 m/pixel depending on geometry**; 3 km-class swath | 0.25 m is the nadir specification; MapBrowse reports about 0.28 m; the two-look landing-site mode is often quoted at 0.32 m. Do not present these as a contradiction. |
| Chandrayaan-2 TMC-2 | Panchromatic; **5 m/pixel**, 20 km swath; fore/nadir/aft stereo views | Current USGS guidance documents an ISIS/ALE/usgscsm ingest path for calibrated TMC-2 products. |
| Chandrayaan-2 IIRS | Hyperspectral; **~80 m/pixel**, 0.8–5.0 µm, roughly 250 contiguous bands | The exact band count belongs to the product label. IIRS includes reflected and emitted radiance, so thermal handling matters at longer wavelengths. |
| LROC NAC | Paired monochrome pushbroom cameras; typical products roughly **0.5–2.0 m/pixel** depending on orbit/geometry | A NAC image is a reference image, not automatically error-free geodetic truth. Use controlled products/LOLA anchoring where available and state reference uncertainty. |
| SELENE/Kaguya Terrain Camera | Panchromatic pushbroom stereo; nominal **10 m/pixel**, 0.43–0.85 µm | The official SIH line ends with “SELENE Images,” so a SELENE TC reference adapter is included in the final concept. |
| SLDEM2015 | Approximately 60 m/pixel at the equator and limited to about 60°S–60°N | It is not a global polar DTM and cannot synthesize missing OHRC-scale texture. Use LOLA/polar products outside its coverage and use relighting as an auxiliary cue. |

Primary references:

- [ISRO Chandrayaan-2 payload overview](https://www.isro.gov.in/ISRO_EN/Chandrayaan2_science.html)
- [OHRC instrument paper](https://www.currentscience.ac.in/Volumes/118/04/0560.pdf)
- [TMC-2 instrument paper](https://www.currentscience.ac.in/Volumes/118/04/0566.pdf)
- [IIRS instrument paper](https://www.currentscience.ac.in/Volumes/118/03/0368.pdf)
- [ISSDC Chandrayaan-2 archive](https://pradan.issdc.gov.in/ch2/) and [product FAQ](https://pradan.issdc.gov.in/ch2/faq.xhtml)
- [LROC NAC processing guide](https://lroc.im-ldi.com/data/support/downloads/LROC_NAC_Processing_Guide.pdf)
- [JAXA SELENE Terrain Camera specifications](https://www.kaguya.jaxa.jp/en/equipment/tc_e.htm)
- [USGS Chandrayaan-2 processing guidance](https://astrogeology.usgs.gov/docs/concepts/missions/chandrayaan2/)
- [NASA/GSFC SLDEM2015 product page](https://pgda.gsfc.nasa.gov/products/54)
- [ISRO-authored LPSC 2023 product-accuracy summary](https://www.hou.usra.edu/meetings/lpsc2023/pdf/1827.pdf)
- [LoFTR — Detector-Free Local Feature Matching with Transformers](https://openaccess.thecvf.com/content/CVPR2021/html/Sun_LoFTR_Detector-Free_Local_Feature_Matching_With_Transformers_CVPR_2021_paper.html)
- [RoMa — Robust Dense Feature Matching](https://openaccess.thecvf.com/content/CVPR2024/html/Edstedt_RoMa_Robust_Dense_Feature_Matching_CVPR_2024_paper.html)
- [RIFT — Radiation-Variation Insensitive Feature Transform](https://doi.org/10.1109/TIP.2019.2959244)

## High-impact corrections applied

### 1. IIRS is not a synthetic TMC-2/NAC panchromatic image

The specification proposes a spectral-response-weighted IIRS collapse to TMC-2 (around lines 2112–2122). TMC-2 extends roughly 0.4/0.5–0.8/0.85 µm, whereas IIRS begins near 0.8 µm. The overlap is too narrow for a radiometrically faithful TMC-2 or NAC reconstruction, and IIRS also contains thermal emission.

Corrected design: thermally correct the relevant IIRS range; build a structural composite from selected high-SNR reflective bands, PCA/gradient energy, phase congruency and/or learned cross-spectral features; optionally use a TMC-2/WAC bridge when overlap permits. This remains a multi-modal problem and is evaluated separately by payload.

### 2. Relighting is an auxiliary hypothesis, not exact modality cancellation

The specification describes a DTM/Hapke render as if it can recreate the source’s exact OHRC-scale texture. Coarse topography and albedo cannot synthesize sub-metre details that are not present in the terrain model. Regional high-resolution NAC DTMs improve this only where they exist.

Corrected design: use photometric normalization and source-lit hillshade/rendered channels as auxiliary features; retain the real fixed reference in the verification loop; run an ablation to prove whether the physics channel helps. This extends established lunar relighting prior art rather than claiming it is the first such method.

Prior art: [simulated-hillshade, photometric lunar image–DEM co-registration](https://doi.org/10.1016/j.isprsjprs.2018.06.016). A separate [photoclinometry-assisted study](https://doi.org/10.1016/j.isprsjprs.2019.11.017) further supports treating shape/lighting cues as aids rather than exact truth.

### 3. LRO NAC is not the lunar datum

The original specification sometimes fixes NAC geometry as truth. Uncontrolled NAC products can retain positional error.

Corrected design: describe NAC/SELENE as image references; prefer controlled orthomosaics/DTMs and LOLA/GRAIL/IAU lunar-frame control where available; propagate reference uncertainty. Report relative source-pixel correspondence separately from absolute surface error in metres.

### 4. Metadata gives a prior, not exact scale invariance

Local GSD varies with altitude, emission angle, relief and line position. A single metadata scale factor is insufficient.

Corrected design: use metadata to bound the pyramid/search, then estimate residual local scale/affine/deformation during coarse-to-fine matching and terrain-aware adjustment.

### 5. Synthetic data does not remove the real-data problem

Synthetic pairs provide exact internal correspondence, but their photometry and terrain-detail distribution can differ from real products.

Corrected design: synthetic pretraining/controlled-shift tests + classical baselines + self-supervised/few-shot adaptation + held-out real validation. The learned matcher is a challenger, not the only path.

### 6. Cycle closure is consistency, not independent accuracy

Cycle closure can miss common-mode bias and pixels from different sensors are not commensurate without unit/covariance normalization.

Corrected design: use closure/forward-backward error as diagnostics. Independent accuracy comes from withheld check points/control whose uncertainty is stated.

### 7. Unsupported results were changed to provisional targets

The specification contains no implementation evidence for its exact RMSE, runtime, throughput, low-sun, bias-reduction, training-time or deterministic-repeat numbers. The supplied deck incorrectly presented several as prototype results.

Corrected deck wording:

- Primary proposed pass gate: **source-frame 2-D RMSE < 1.0 pixel** on held-out check points.
- Stretch target: **≤0.5 source pixel**.
- Provisional uniformity target: **≥70% occupancy of eligible 8×8 cells**, to be frozen on the official dataset.
- No runtime/throughput figure is called achieved.
- Every job emits **accept / review / reject** plus metrics and provenance.

### 8. Uniformity metrics were simplified and corrected

The specification’s Clark–Evans interpretation is wrong: R=1 represents complete spatial randomness, not regular uniform spacing. Its claimed submodular approximation bound also does not follow after the stated pairwise NMS constraint.

Corrected design: pre-filter/NMS the candidate set, then use grid/quadtree coverage selection. Report eligible-cell occupancy, convex-hull area over valid overlap, and largest empty region/run. Show the point map visually.

### 9. Example arithmetic error removed

The example around lines 1875–1877 calls 1,904 / 41,822 an inlier ratio of 0.71. The correct quotient is approximately **0.0455**. The fabricated sample was removed from the final deck.

### 10. Hackathon scope was reduced to a credible MVP

The full document combines several research programs and an enterprise platform: a custom renderer, learned corpus generation, IIRS cross-spectral modeling, analytic pushbroom/jitter adjustment, shape-from-shading, graph adjustment, Kubernetes, identity, large storage and operations.

Credible MVP:

1. Calibrated PDS4 ingestion and sensor/geometry adapters.
2. Metadata-guided coarse alignment and common-GSD/PSF pyramids.
3. Classical SIFT/RIFT/NCC baselines plus one detector-free challenger.
4. Photometric/structural auxiliary channels and masks.
5. Grid/quadtree tie-point distribution, local sub-pixel refinement and robust adjustment.
6. Registered COG, GeoPackage/CSV match catalogue, metric report and overlay UI.

Training, graph adjustment, advanced jitter/SFS work and production orchestration are now a staged roadmap.

## Challenge-to-solution traceability

| SIH requirement | Final solution mechanism | Evidence/metric |
| --- | --- | --- |
| Multi-modal OHRC/TMC-2/IIRS | Payload-aware preprocessing; dedicated IIRS thermal/structural branch | Per-payload held-out success, inlier count/ratio and error |
| Sun-angle robustness | Photometric normalization, shadow masks, hillshade/render hypothesis, gradient/phase/self-similarity channels | Success/rejection rate and error by solar-elevation/azimuth-difference bins |
| Scale robustness | Metadata/local-GSD prior, PSF-aware pyramid and residual scale/local-warp estimation | Error and success by direction-free coarser/finer GSD ratio |
| Viewpoint/relief | Terrain-aware line-scan/pushbroom adjustment rather than one homography | Residual-vector map, withheld error, relief-correlation diagnostics |
| Sub-pixel source-frame accuracy | ECC/phase-correlation local refinement, robust solve and per-match covariance | RMSE_x, RMSE_y, RMSE_2D, median endpoint error, P90/CE90 |
| Uniform distribution | Eligibility mask + grid/quadtree selection | Occupied-cell %, convex-hull %, largest empty region |
| Generic software | UI, CLI and API over a modular scientific core | End-to-end run on each payload/reference route |
| Registered product | COG/GeoTIFF plus adjusted geometry/model state | Georeferencing round trip and visual overlay |
| Corresponding match points | GeoPackage/CSV source/reference coordinates + score/covariance | Schema validation and map visualization |
| Evaluation metrics | Machine-readable report + QA dashboard + verdict | RMSE, inliers, ratio, coverage, uncertainty, runtime/memory and success rate |

## Metric definitions retained in the final design

- Relative 2-D source-frame error: `RMSE_2D = sqrt(mean(dx² + dy²))` in source pixels.
- Report `RMSE_x`, `RMSE_y`, median endpoint error and P90/CE90 as separate fields.
- Convert reference-pixel residuals through the **local warp Jacobian**, not one scene-wide scale constant.
- Robustness: candidate count, verified inlier count, inlier ratio, automated success/rejection rate.
- Uniformity: eligible grid-cell occupancy, convex-hull/valid-overlap area and largest empty region/run.
- Absolute map quality: horizontal error in metres against higher-accuracy independent control with reference uncertainty stated.
- Stress bins: source payload, reference family, sun-angle difference, view/emission angle, GSD ratio, terrain class and overlap fraction.
- Secondary diagnostics: forward/backward error, cycle closure, residual-vector field, runtime and memory. These are not substitutes for independent accuracy.

## Data and URL corrections

- Valid Chandrayaan-2 MapBrowse: <https://chmapbrowse.issdc.gov.in/> (registration/login is required for download).
- Canonical Chandrayaan-2 archive: <https://pradan.issdc.gov.in/ch2/>.
- The challenge’s `lroc.im.-ldi.com` address contains an extra dot/hyphen. Use <https://lroc.im-ldi.com/>.
- Current LROC data discovery: <https://data.im-ldi.com/> and <https://quickmap.lroc.im-ldi.com/>.
- SELENE/Kaguya data: <https://darts.isas.jaxa.jp/missions/pds/pds_kaguya_en.html>.

## Remaining unknowns that must stay explicit

1. The official benchmark products/product IDs and train/validation/test split are still TBD.
2. Team ID was blank in the supplied template and was intentionally not invented.
3. Numeric thresholds are provisional until calibrated and frozen on the official dataset.
4. A rigorous IIRS camera/geometry adapter must be validated; current documented USGS Chandrayaan-2 CSM guidance explicitly covers calibrated OHRC and TMC-2.
5. Absolute accuracy depends on the control/reference product and its uncertainty; sub-pixel image correspondence must not be translated directly into centimetre-level geodetic accuracy.
6. “SELENE-XR” is an independent Team Horizon project name and is not affiliated with JAXA’s SELENE/Kaguya mission.
