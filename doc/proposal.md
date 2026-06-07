# ShotSight 2.0 Product Requirements Proposal

## 1. Document Status

- **Product:** ShotSight 2.0
- **Document type:** Product requirements proposal
- **Language:** English
- **Status:** Approved baseline for discovery and technical validation
- **Primary user:** A single local user
- **Delivery form:** Local web application
- **Target platforms:** macOS, Windows, and Linux

## 2. Product Vision

ShotSight 2.0 will analyze uploaded basketball videos and produce a reviewable
record of shooting performance. The application will identify shot attempts,
associate attempts with players, classify makes and misses, estimate where each
shot was taken, distinguish two-point and three-point attempts, and present the
results through statistics, a court visualization, replay clips, and an
annotated full-length video.

The application is local-first. Videos, derived media, calibration data, and
analysis results are stored permanently on the user's computer until the user
explicitly deletes them. No paid cloud GPU service is permitted in the initial
scope.

## 3. Goals

1. Analyze basketball videos up to 30 minutes and 1 GB.
2. Support indoor and outdoor footage, half-court and full-court play, individual
   practice, and multiplayer games.
3. Operate on imperfect footage, including low resolution, poor lighting,
   motion blur, partial occlusion, and visually cluttered courts.
4. Automatically detect and separately track players in multiplayer footage.
5. Count every released shot attempt, including blocked shots and air balls.
6. Automatically classify makes and misses, with human correction available.
7. Estimate shot locations in NBA court coordinates when calibration permits,
   while still presenting indicative positions on non-standard courts.
8. Generate total attempts, makes, misses, shooting percentage, shot chart,
   heatmap, per-shot replay clips, and a complete annotated tracking video.
9. Provide an English interface by default with immediate English/Chinese
   language switching.
10. Run locally across macOS, Windows, and Linux.

## 4. Non-Goals for the Initial Release

1. User registration, authentication, teams, and cloud accounts.
2. Cloud video storage or paid cloud inference.
3. Live camera capture or real-time analysis.
4. Coaching recommendations, pose correction, or biomechanical analysis.
5. Guaranteed semantic identification of every player across separate videos.
6. Native iOS or Android applications.

## 5. Users and Primary Workflow

### 5.1 Primary User

The initial release serves one person using a local computer. The architecture
may permit accounts later, but no login is required now.

### 5.2 Primary Workflow

1. The user opens the local web application.
2. The user uploads an existing video.
3. The application validates size, duration, and decodability.
4. FFmpeg normalizes the source into an analysis proxy. A 4K source may be
   downscaled and frame-sampled according to the selected performance profile.
5. The application identifies stable camera segments.
6. For each stable segment, the application attempts automatic rim, court,
   basketball, and player identification.
7. The user is asked to calibrate the rim and court reference points when
   automatic calibration is unavailable or uncertain.
8. The preferred tracker attempts to initialize the basketball automatically.
   If tracking confidence fails, the user may click the ball to reinitialize it.
9. The application tracks players, basketball movement, shot release, rim
   interaction, and post-shot outcome.
10. The application generates statistics and visual outputs.
11. The user reviews attempts and may overwrite attempt ownership, location, or
    make/miss classification.
12. The user may permanently delete a video and all associated data.

## 6. Functional Requirements

### FR-1 Video Ingestion

- The application shall upload existing local video files.
- Maximum file size shall be 1 GB.
- Maximum source duration shall be 30 minutes.
- Maximum expected source resolution shall be 4K.
- "All formats" shall be implemented as all video containers and codecs that
  the installed FFmpeg build can decode. The UI shall explicitly reject and
  explain unsupported or corrupt inputs.
- The upload process shall preserve the original file.
- The application shall collect source metadata: filename, size, duration,
  resolution, frame rate, codec, and container.

### FR-2 Video Preprocessing

- The application shall generate a normalized analysis proxy without modifying
  the original.
- The application may reduce resolution and frame rate to satisfy local
  performance targets.
- The proxy policy shall preserve enough detail for a small, fast basketball.
- Preprocessing shall support rotation metadata, variable frame rate, and common
  smartphone video characteristics.
- The selected proxy settings shall be recorded with each analysis.

### FR-3 Camera Stability and Segmentation

- The camera should remain fixed during each shooting segment.
- The source may contain one or more mid-video camera adjustments.
- The application shall detect camera movement and divide the video into stable
  camera segments.
- Tracking and shot decisions shall pause during unstable transitions.
- Each new stable viewpoint shall have independent calibration and tracking
  state.

### FR-4 Calibration

- The application shall attempt automatic rim and court detection.
- The user shall be able to click the rim and NBA court reference points.
- The user shall be able to recalibrate every stable camera segment.
- Calibration shall be stored by time range.
- NBA court dimensions shall be the standard coordinate reference.
- When the court is non-standard or required markings are invisible, the UI
  shall label shot positions as indicative rather than metrically exact.

### FR-5 Basketball Detection and Tracking

- SAM 3.1 shall be the preferred initial research candidate.
- SAM 3.1 shall remain replaceable through a tracking-backend interface.
- The default workflow shall use automatic concept prompting for "basketball"
  and available visual evidence.
- The user shall be able to click a visible basketball to initialize or repair
  tracking.
- Tracking shall expose confidence, visibility, occlusion, and reinitialization
  events.
- The system shall prevent obvious identity switches to heads, hands, shoes,
  court markings, spectators, and other ball-like objects.
- Lost tracks shall not be silently interpolated across long gaps.

### FR-6 Player Detection and Identity

- Multiplayer footage shall be supported.
- The application shall detect players and maintain separate local track IDs.
- Each shot shall be attributed to a player track.
- The user shall be able to correct player attribution.
- Player identity is scoped to one video; recognizing a person across different
  videos is not required.

### FR-7 Shot Attempt Definition

- A shot attempt begins only when the basketball is released from the shooter.
- Supported shot styles include jump shots, two-point shots, three-point shots,
  free throws, layups, dunks, hooks, and other released shooting motions.
- Blocked attempts count when the ball has been released.
- Air balls count.
- A motion where the basketball never leaves the player's possession does not
  count.
- The detector shall require temporal evidence around possession, release, ball
  flight or immediate block, and result.

### FR-8 Make/Miss Classification

- The default result shall be automatic.
- A made shot requires evidence that the ball passes downward through the rim
  region.
- Other completed attempts shall be classified as misses unless evidence is
  insufficient.
- Uncertain outcomes shall be visibly flagged.
- The user shall be able to overwrite make/miss results.
- Every automatic and corrected decision shall retain its source and timestamp.

### FR-9 Shot Location

- The application shall estimate the shooter's release position.
- Outputs shall include named court region, heatmap position, indicative or
  calibrated coordinate, and two-point/three-point classification.
- Calibrated coordinates shall use meters on an NBA court model.
- Non-standard courts shall still show relative/indicative placement.
- The user shall be able to correct a shot location.

### FR-10 Results

For each analyzed video, the application shall provide:

- total attempts;
- makes;
- misses;
- shooting percentage;
- two-point and three-point breakdown;
- player-level breakdown;
- shot chart;
- heatmap;
- per-shot replay clips;
- full annotated tracking video;
- confidence and review status for each attempt.

### FR-11 Review and Correction

- Automatic analysis is the default.
- The user shall be able to add, remove, and edit attempts.
- The user shall be able to change shooter, make/miss result, shot type, and
  location.
- Aggregate statistics shall update immediately after correction.
- Corrected records shall be distinguishable from automatic predictions.

### FR-12 Persistence and Deletion

- Originals and generated outputs shall persist locally by default.
- Analysis history shall remain available after restarting the application.
- The user shall be able to delete a video.
- Deletion shall include the original, proxies, masks, replays, tracked videos,
  calibration, attempts, and database records after confirmation.

### FR-13 Localization

- English shall be the default interface language.
- The interface shall provide one-step switching between English and Chinese.
- User-facing text shall be stored in translation resources rather than embedded
  in business logic.

## 7. Computer-Vision Requirements

### 7.1 Proposed Pipeline

The product shall use a modular hybrid pipeline rather than assuming one model
can solve the complete problem:

1. FFmpeg decoding and adaptive proxy generation.
2. Camera stability and scene-change segmentation.
3. Rim, court, player, and basketball proposal generation.
4. SAM 3.1 or another backend for object masks and temporal tracking.
5. Track association and confidence management.
6. Shooter possession and release detection.
7. Ball-flight and rim-interaction analysis.
8. Shot lifecycle classification.
9. Homography-based court location mapping.
10. Human review and correction.

### 7.2 SAM 3.1 Feasibility Constraint

SAM 3 supports text, point, box, mask, and exemplar prompts and can detect,
segment, and track concepts in video. SAM 3.1 adds Object Multiplex for faster
multi-object tracking.

However, the official implementation currently specifies Python 3.12+, PyTorch
2.7+, a CUDA-compatible GPU, and CUDA 12.6+. Official video code is not currently
a dependable cross-platform CPU or Apple MPS solution. Model checkpoints also
require approved Hugging Face access.

Therefore:

- SAM 3.1 is preferred, not mandatory.
- A technical spike is required before production integration.
- The application core must run without importing SAM 3.
- Tracking backends must be selectable by capability.
- Candidate fallbacks may include a compact basketball detector, OpenCV motion
  and color proposals, optical flow, conventional multi-object tracking, or a
  platform-specific optimized runtime.
- No cloud GPU dependency may be introduced without a future requirements
  change.

References:

- [Official SAM 3 repository](https://github.com/facebookresearch/sam3)
- [SAM 3.1 release notes](https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md)
- [SAM 3 paper](https://arxiv.org/abs/2511.16719)

## 8. Non-Functional Requirements

### NFR-1 Performance

- Product target: process a 30-minute video in approximately one minute.
- Resolution reduction and temporal sampling are permitted.
- The system shall not omit short release or rim-interaction events merely to
  meet speed targets.
- Performance shall be measured separately for preprocessing, inference,
  lifecycle analysis, and rendering.
- Because local hardware varies and official SAM 3 video inference requires
  CUDA, the one-minute target is an optimization target pending benchmark
  results, not an unconditional first-build guarantee.

### NFR-2 Accuracy

- Product aspiration: 100% attempt counting, outcome classification, and
  two-point/three-point classification.
- Reviewed final results may reach 100% through human correction.
- Automated 100% accuracy cannot be guaranteed for poor-light, low-resolution,
  occluded, multiplayer, or non-standard-court footage.
- The technical spike shall establish benchmark-based automated acceptance
  thresholds before implementation acceptance.
- Accuracy shall be reported independently for:
  - shot-event precision and recall;
  - make/miss accuracy;
  - player attribution accuracy;
  - two-point/three-point accuracy;
  - location error on calibrated courts;
  - track coverage and identity-switch count.

### NFR-3 Portability

- Core application behavior shall support current macOS, Windows, and Linux.
- OS-specific acceleration may differ.
- Unsupported tracking backends shall be disabled with a clear explanation.
- Paths, subprocess calls, and FFmpeg invocation shall be cross-platform.

### NFR-4 Privacy

- No video or derived biometric-like imagery shall leave the local machine by
  default.
- The application shall not require analytics or telemetry.
- Secrets and model-access tokens shall never be stored in Git.

### NFR-5 Reliability

- Analysis jobs shall be resumable or safely restartable.
- Long operations shall expose progress and errors.
- Generated artifacts shall be versioned by analysis configuration.
- Failed analysis shall not corrupt the original video or prior results.

### NFR-6 Maintainability

- Python code shall use type hints and focused module ownership.
- Public functions shall be documented.
- Detection thresholds and model configuration shall not be hidden in UI code.
- Vision backends shall satisfy a shared interface and contract tests.
- Automated tests shall cover domain rules independently of model inference.

## 9. Proposed Technical Architecture

### 9.1 Core Stack

- Python 3.12
- FastAPI local web server
- SQLite metadata and review persistence
- FFmpeg/ffprobe media normalization
- OpenCV and NumPy for image/video utilities
- Pluggable tracking backend with SAM 3.1 as the first research adapter
- Server-rendered or lightweight web UI with translation resources
- pytest, Ruff, mypy, and coverage
- Optional Docker runtime

### 9.2 Main Components

- **Web UI:** upload, calibration, progress, review, dashboards, replay.
- **Application API:** local routes and job orchestration.
- **Media service:** validation, metadata, proxy and clip generation.
- **Segment service:** camera stability and calibration time ranges.
- **Tracking service:** players, basketball, rim, masks, confidence.
- **Shot engine:** release, lifecycle, rim crossing, result, attribution.
- **Court mapper:** NBA coordinate mapping and indicative fallback.
- **Review service:** corrections and aggregate recalculation.
- **Artifact service:** original, proxy, replay, mask, and tracked video storage.
- **Persistence:** SQLite metadata and filesystem media.

## 10. Data Model

Initial entities:

- `Video`
- `AnalysisRun`
- `CameraSegment`
- `Calibration`
- `PlayerTrack`
- `BallTrack`
- `ShotAttempt`
- `ShotLocation`
- `ReviewCorrection`
- `ReplayArtifact`
- `TrackedVideoArtifact`

Every derived record shall include its analysis configuration and model/backend
version for reproducibility.

## 11. UX Requirements

- The first screen shall be the working video library and upload interface, not
  a marketing page.
- Analysis progress shall identify preprocessing, calibration, tracking,
  classification, and rendering stages.
- Manual calibration shall use direct manipulation over a stable video frame.
- Low-confidence moments shall link directly to the relevant timestamp.
- Review shall prioritize keyboard-efficient next/previous and make/miss
  correction.
- Shot charts shall distinguish makes, misses, selected players, and uncertain
  positions.
- Destructive deletion shall require confirmation and clearly list affected
  artifacts.

## 12. Validation Strategy

### 12.1 Ground-Truth Dataset

Create a private local benchmark containing:

- indoor and outdoor videos;
- half-court and full-court footage;
- individual and multiplayer footage;
- 1080p and 4K sources;
- poor light, blur, occlusion, camera adjustment, blocked shots, and air balls;
- standard NBA-style and non-standard courts.

Every attempt shall be manually annotated for shooter, release time, result,
shot type, and indicative/calibrated location.

### 12.2 Technical Spikes

1. **SAM 3.1 ball discovery:** text prompt reliability on small basketballs.
2. **SAM 3.1 prompted tracking:** user-click initialization through release and
   result.
3. **Local hardware benchmark:** CUDA, Apple Silicon fallback, CPU, and Windows.
4. **Adaptive proxy study:** speed versus small-ball recall.
5. **Player association:** multiplayer shooter attribution.
6. **Camera segmentation:** calibration changes after camera movement.
7. **Rim crossing:** make/miss classification under occlusion.

### 12.3 Release Gates

Implementation shall not claim production readiness until:

- benchmark annotations exist;
- every metric has a repeatable evaluation script;
- supported hardware is documented;
- the user can correct every automatic result;
- deleting a video removes all related local data;
- installation and smoke tests pass on macOS, Windows, and Linux.

## 13. Delivery Phases

### Phase 0: Foundation

- Repository and development environment.
- Local application shell and health endpoint.
- Configuration, storage layout, tests, Docker option, and documentation.

### Phase 1: Dataset and Feasibility

- Ground-truth annotation format.
- SAM 3.1 and fallback backend experiments.
- Local hardware and performance report.
- Final automated accuracy acceptance thresholds.

### Phase 2: Single-Player Fixed-Camera MVP

- Upload, preprocessing, calibration, one-player tracking, attempts, outcomes,
  review, and replay.

### Phase 3: Camera Segments and Location

- Mid-video camera changes, segment calibration, NBA coordinates, heatmap, and
  two-point/three-point classification.

### Phase 4: Multiplayer

- Player tracking, shooter attribution, player filters, and corrections.

### Phase 5: Cross-Platform Hardening

- macOS, Windows, and Linux packaging.
- Backend capability detection.
- Performance profiles and Docker documentation.

## 14. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Basketball occupies very few pixels | Lost or incorrect tracks | Adaptive resolution, detector proposals, user re-prompt, benchmark minimum input guidance |
| SAM 3 official video path requires CUDA | Cannot meet local cross-platform requirement | Pluggable backend, feasibility gate, optimized fallback |
| Poor lighting and motion blur | False negatives and body-part switches | Confidence model, temporal constraints, manual review |
| Multiplayer occlusion | Wrong shooter attribution | Player IDs, possession logic, correction UI |
| Camera moves | Invalid rim and court coordinates | Stable-segment detection and per-segment calibration |
| Non-standard court | Misleading exact coordinates | Clearly label location as indicative |
| One-minute performance goal | Accuracy loss from aggressive sampling | Multi-pass pipeline and configurable quality profiles |
| 100% automated accuracy target | Unrealistic acceptance ambiguity | Separate aspiration, measured automation metrics, and reviewed-final accuracy |
| Permanent local storage | Disk growth and privacy exposure | Storage reporting and complete deletion workflow |

## 15. Open Decisions After Technical Validation

The following decisions cannot be finalized until measured:

1. Which local tracking backend is supported on each OS and hardware profile.
2. Minimum usable source resolution and frame rate.
3. Default proxy resolution and sampling strategy.
4. Automated accuracy acceptance thresholds.
5. Whether the one-minute processing target is feasible without unacceptable
   recall loss.
6. Packaging method for each operating system.

## 16. Acceptance of This Proposal

This proposal records the confirmed product intent. It deliberately distinguishes
between desired outcomes and technically verified guarantees. Implementation
shall begin with Phase 0 and Phase 1; results from the benchmark and SAM 3.1
technical spike shall determine the production tracking backend and measurable
acceptance thresholds.

