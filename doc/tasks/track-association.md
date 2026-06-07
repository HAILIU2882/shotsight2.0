# Track Association Module Tasks

## Goal

Maintain local player identities and associate possession, release, and shots
with the correct player.

## Dependencies

Player tracks, ball tracks, camera segments, player repository.

## Checklist

- [ ] `ASC-001` Define local player identity and association-confidence models.
- [ ] `ASC-002` Assign deterministic `Player N` labels within a video.
- [ ] `ASC-003` Link player observations across adjacent frames within one stable segment.
- [ ] `ASC-004` Link compatible player tracks across camera segments without claiming biometric identity.
- [ ] `ASC-005` Calculate ball-to-player possession candidates.
- [ ] `ASC-006` Maintain possession state over short observation gaps.
- [ ] `ASC-007` Identify the shooter at release.
- [ ] `ASC-008` Flag ambiguous possession and shooter attribution.
- [ ] `ASC-009` Preserve player track ID when the display name changes.
- [ ] `ASC-010` Add tests for single player, multiple players, handoff, occlusion, crossing players, camera change, and ambiguous release.
- [ ] `ASC-011` Persist evidence references used by shot attribution.

## Completion Criteria

- [ ] Every automatic shot has a player ID or explicit uncertain attribution.
- [ ] Renaming never changes historical track identity.
- [ ] No cross-video person recognition is performed.

