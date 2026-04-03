# Native Project Window Plan Review Notes

Date: 2026-04-03
Source plan: `docs/superpowers/plans/2026-04-02-native-project-window.md`
Source spec: `docs/superpowers/specs/2026-04-01-fontra-native-project-window-design.md`

## Purpose

This note records the implementation-plan defects found during review and the concrete plan changes required before execution starts. The goal is not strict word-for-word spec alignment; it is to remove plan-level ambiguities and hidden behavior bugs so the plan can be implemented without churn.

## Findings And Required Fixes

### 1. Shared project identity and `?project=` encoding were under-specified

Problems:

- The plan mixed a new Windows query example (`C%3A/fonts/demo.ufo`) with the current wrapper's existing encoding behavior.
- URL decoding logic was duplicated inside routing instead of being owned by the shared project-identity contract.
- The contract did not expose a dedicated callback-canonicalization helper, which left later tasks to re-invent the same logic.

Required fix:

- Make `fontra_pak/project_identity.py` the only owner of path resolution, project-key normalization, query encoding, query decoding, and callback canonicalization.
- Add tests that lock the existing Windows wire format and verify POSIX absolute-path round-tripping.
- Make routing import the shared decode helper instead of reconstructing paths ad hoc.

### 2. Descriptor matching would collapse multiple glyph/editor tabs into one pane

Problems:

- The plan treated editor descriptors with different `route_hash` values as equivalent.
- `open_view()` reused the last matching pane, which meant `#glyph=A` and `#glyph=B` could not coexist as separate tabs.

Required fix:

- Change descriptor matching to preserve route identity.
- Add an explicit default-overview helper for the "open project" fallback case instead of using route-insensitive matching.
- Add manual verification that different glyph routes open distinct panes while re-opening the same route focuses the existing pane.

### 3. Restore logic would lose the first saved pane and replace it with overview

Problems:

- `open_project()` always created an overview pane during restore.
- `restore_workspace()` skipped `pane_records[0]`, so the first saved descriptor was never recreated.
- The restore flow had no explicit fallback for "all descriptors invalid" besides the accidental overview created by `open_project()`.

Required fix:

- Split "create/focus project window" from "open default overview pane".
- Restore all saved pane descriptors, including the first one.
- If no saved descriptor validates, reopen overview deliberately and report that fallback as a restore warning.

### 4. Download handling was attached once per pane instead of once per project profile

Problems:

- Every pane connected to `profile.downloadRequested`.
- A single download could trigger multiple dialogs after multiple panes were opened in one project window.

Required fix:

- Move the download signal connection to `ProjectWindow`, which already owns the per-project profile and native window.
- Keep `WorkspacePane` focused on hosting one embedded Fontra view.

### 5. Pane reuse and active-pane persistence did not track real user focus

Problems:

- Reuse logic picked `matching[-1]`, which reflected creation order, not real pane activation order.
- `_active_pane` only changed on wrapper-driven operations, not on direct user tab clicks/focus changes.

Required fix:

- Add explicit pane-activation tracking in `ProjectWindow`.
- Make `WorkspacePane` notify `ProjectWindow` when the pane or its web view gains focus.
- Use that activation state for reuse decisions and active-pane persistence.

### 6. Controller tests were not exercising the controller

Problems:

- The original "failing tests" passed before `AppWorkspaceController` existed.
- They did not cover window reuse, callback routing, restore interactions, or canonicalized export routing.

Required fix:

- Make `AppWorkspaceController` dependency-injectable for tests.
- Replace the logic sketches with actual controller tests using fake windows/profiles.
- Add restore tests where the controller must recreate all saved panes and fall back to overview only when descriptor restore fails.

### 7. Launcher integration needed explicit verification for both open flows

Problems:

- The plan edited both drag/drop and "New Font..." routing, but only the drag/drop path was clearly exercised in verification.

Required fix:

- Expand manual verification so both drag/drop and "New Font..." are required checks for the launcher-to-controller handoff.

## Remediation Map

- Task 15: expand project identity helpers and tests
- Task 16: change descriptor matching semantics and add default-overview helper
- Task 17: route URL canonicalization through Task 15 helpers
- Task 19: add pane activation hooks and remove profile-level download ownership
- Task 20: move download handling to `ProjectWindow` and track activation order
- Task 21: replace placeholder controller tests with real dependency-injected tests
- Task 22: add explicit launcher verification for drag/drop and "New Font..."
- Task 25-26: preserve every restored pane and make overview fallback explicit

## Exit Criteria For The Revised Plan

- One shared project identity contract is referenced everywhere.
- Multiple editor tabs with different glyph routes can coexist by design.
- Restore recreates all saved pane descriptors before falling back to overview.
- One project download request results in one native download dialog.
- Pane reuse is based on actual activation order, not creation order.
- Controller tests fail before implementation and exercise real controller behavior.
