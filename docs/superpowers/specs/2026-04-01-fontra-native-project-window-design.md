# Fontra Pak Native Project Window Design

Date: 2026-04-01
Status: Approved design

## Introduction

Fontra Pak already acts as a native wrapper around Fontra, but today it stops short of owning the real editing experience. The wrapper launches a small native window for opening or dropping projects, then hands the actual editor off to the user's default browser. That breaks the core desktop-app expectations this project cares about: the focused editor window is no longer owned by `Fontra Pak.exe`, mouse-profile software sees the browser instead of the app, and window management is split between the wrapper and external browser windows or tabs.

This project is intended to close that gap without replatforming Fontra Pak or rewriting Fontra itself for MVP. The design keeps the current Python, PyQt, local-server, and packaging model, but turns Fontra Pak into the real desktop shell for editing: one native project window per font, internal panes and tabs for Fontra views, wrapper-owned routing and workspace behavior, and a Windows-first MVP that proves the process/window ownership problem is actually solved.

This introduction is descriptive only. It recaps the problem and intent but does not expand the MVP scope beyond the formal goals, non-goals, and acceptance boundary defined below.

## Summary

Fontra Pak should stop handing editing off to the system browser and instead own both the launcher window and each project editor window as native desktop windows provided by `Fontra Pak.exe`.

The least intrusive path is to keep the existing Python, PyQt, local-server, and PyInstaller architecture, and replace the current `webbrowser.open(...)` handoff with an embedded web runtime hosted inside a new project window. The project window should support one font project per top-level window, plus multiple internal tabs and dockable panes for Fontra views such as overview, glyph editor, font info, and application settings.

MVP scope is wrapper-only. Fontra changes are explicitly out of scope for the first implementation target. If the prototype exposes too much browser-centric friction, or if shared-state/performance optimization becomes necessary, Fontra can later add shell-aware navigation hooks.

For this document, "MVP" means the first build target that is complete enough to ship for evaluation. MVP includes native project-window ownership, internal pane management, deterministic routing rules, per-project session isolation, and clean-close workspace restore.

MVP platform scope is Windows only. Preserving or re-enabling equivalent macOS packaging is desirable later, but it is not part of the MVP acceptance boundary.

## Problem Statement

Current behavior:

- `Fontra Pak.exe` launches a native drop/launcher window.
- Opening a project calls `webbrowser.open(...)`.
- The active editor window therefore belongs to the user's default browser, not to Fontra Pak.

This creates two concrete problems:

- Mouse/profile software that switches on the focused top-level application window sees the browser instead of `Fontra Pak.exe`.
- Desktop window management is split between a small launcher window and browser windows or tabs that Fontra Pak does not control.

## Goals

- Keep `Fontra Pak.exe` as the owning application for both the launcher window and project editor windows.
- Open one top-level native project window per font project.
- Support multiple internal views inside a project window.
- Support basic internal window management inside a project window: tabs, docking, tiling, and drag-based rearrangement.
- Preserve the current local Fontra server model so the MVP does not require a Fontra rewrite.
- Minimize disruption to the existing Python and PyInstaller packaging flow.

## Non-Goals

- No Fontra-side code changes in MVP.
- No Electron or Tauri migration.
- No requirement that the entire app be a literal single OS process.
- No redesign of Fontra's frontend behavior beyond what can be hosted inside the desktop shell.
- No attempt to solve advanced shared-state optimization between panes in MVP.

## Options Considered

### Option 1: Keep current browser-launch model

Pros:

- No implementation work.

Cons:

- Does not solve the focused-window ownership problem.
- Does not allow real internal workspace management.

Decision: rejected.

### Option 2: Replace the wrapper with Electron or Tauri

Pros:

- Strong desktop-shell capabilities.

Cons:

- Replatforms the wrapper instead of fixing the isolated browser handoff.
- Higher migration cost, larger scope, and more packaging churn.

Decision: rejected for MVP.

### Option 3: Keep PyQt and embed the Fontra UI in native project windows

Pros:

- Smallest architectural change that solves the real problem.
- Preserves the current launcher, dialogs, settings, drag/drop, server lifecycle, and packaging model.
- Lets Windows treat the focused editor window as belonging to `Fontra Pak.exe`.

Cons:

- Requires adding an embedded web runtime and packaging it correctly.
- Likely introduces helper renderer processes, even though the top-level app identity remains Fontra Pak.

Decision: recommended.

## Recommendation

Implement a native project window using PyQt and an embedded web runtime, with desktop workspace behavior implemented in the wrapper.

Recommended MVP technology choices:

- Keep `PyQt6` as the shell framework.
- Add `QtWebEngine` for embedded Fontra views.
- Use Qt's built-in `QMainWindow` and `QDockWidget` workspace model first, because it provides native tabs, docking, and tiling with the least added surface area.

This is the minimal change set that should make the focused editor window belong to `Fontra Pak.exe` while adding wrapper-controlled workspace management.

## Architecture

### Current architecture to preserve

- Fontra Pak starts a local `FontraServer` on `localhost`.
- The launcher window remains a native PyQt window.
- Existing native dialogs, file export, settings, and process cleanup logic stay in the wrapper.

### New architecture

- The launcher window remains the entry point for opening or creating projects.
- Opening a project creates a `ProjectWindow` owned by `Fontra Pak.exe`.
- `ProjectWindow` hosts an internal workspace made of dockable panes.
- Each pane hosts an embedded Fontra view backed by the same local server and the same project path.
- Internal navigation opens new tabs or panes inside the project window instead of opening the system browser.

### Core units

#### Launcher Window

Responsibilities:

- Keep the current drop target and "new font" flow.
- Convert user actions into `openProject(projectPath)` or `createProject(...)` requests.
- Never own the project-window registry or open-project tracking.

#### App Workspace Controller

Responsibilities:

- Own the registry of open project windows.
- Receive server-side app callbacks and dispatch them to the correct project window.
- Own app-level behaviors that are not tied to one pane, including export dialog requests, project open and close tracking, and quit guarding.
- Normalize launcher requests into `openProject`, `focusProject`, and `closeProject` actions.

#### Project Window

Responsibilities:

- Own the top-level native editor window for exactly one font project.
- Manage the internal workspace layout.
- Create, focus, close, and persist view panes.
- Route internal versus external destinations for that project window.

#### Workspace Pane

Responsibilities:

- Represent one logical view destination such as overview, glyph editor, font info, or application settings.
- Own exactly one embedded web view widget.
- Expose title, kind, and view-specific identity for tab or pane labeling.
- Own one stable `paneInstanceId` used for active-pane tracking, persistence, and restore.

#### Pane Navigation Bridge

Responsibilities:

- Wrap one embedded page object and translate webview-level events into shell actions.
- Intercept new-window requests, downloads, load failures, title changes, URL changes, and renderer crashes.
- Report those events back to the owning `ProjectWindow`.

#### View Descriptor

Responsibilities:

- Describe one logical destination in wrapper terms.
- Allow the wrapper to decide whether to focus an existing pane or open a new one.
- Provide stable identity for pane deduping and restore.

This unit boundary keeps shell behavior in Fontra Pak and content rendering in Fontra.

### Interface summary

| Unit | Inputs | Outputs | Owns |
|------|--------|---------|------|
| Launcher Window | User drop, open, and create actions | `openProject(projectPath)` requests | Launcher UI only |
| App Workspace Controller | Launcher requests, server queue callbacks, app quit | Create, focus, close project windows; export requests; quit state | Project window registry and app-level state |
| Project Window | `openView(descriptor)`, app callbacks for its project, pane events | Focus, open, close pane operations; persisted workspace state | One project workspace |
| Workspace Pane | View descriptor, resolved URL, shared project web profile | Title updates, current URL changes, failure events | One embedded Fontra view |
| Pane Navigation Bridge | Webview events | Shell navigation, download, and error events | Translation layer between web runtime and wrapper |
| View Descriptor | Wrapper command or intercepted URL | Resolved URL and route identity | Logical destination identity |

### App-level event ownership

The following behaviors are owned by `App Workspace Controller` in MVP:

- Export requests from Fontra
- Project-open and project-close notifications
- Global open-project tracking for quit confirmation
- Reuse and focus behavior when the same project is requested again
- Shared server-process health and connection-lost state transitions

The following behaviors are owned by `ProjectWindow`:

- Open, focus, and close pane
- URL and title updates
- Pane reload after renderer failure
- Docking layout changes and layout persistence
- Native export dialog execution for its project after callback routing
- Native download dialog execution for downloads initiated by panes in that project window

### Callback contract

MVP should treat the existing wrapper queue messages as the authoritative callback contract between the Fontra server process and the desktop shell.

| Event | Payload | Target resolution | Owner action |
|------|---------|-------------------|--------------|
| `projectOpened` | `{ projectIdentifier: str }` | `App Workspace Controller` canonicalizes the incoming identifier with the project identity contract, then matches on `projectKey` | Mark project as open for quit-guard purposes |
| `projectClosed` | `{ projectIdentifier: str }` | Same as above | Mark project as no longer open |
| `exportAs` | `{ projectIdentifier: str, options: dict }` | Same as above | Ask the owning project window to run the native export flow |

If canonicalization fails or no registered project window matches the canonicalized `projectKey`, MVP should log the mismatch and ignore the event rather than guessing a target.

Exception:

- If `projectClosed` arrives for a `projectKey` that was recently closed by the shell, treat it as expected late cleanup and ignore it without warning.

## Workspace Behavior

Each open project gets one top-level native window. Within that window:

- Multiple panes may be opened at once.
- Panes may be docked, tabified, split, rearranged, and retitled by the shell.
- A project may have multiple editor panes open for different glyphs or different editing contexts.
- Non-editor panes such as overview or settings can live beside editor panes in the same project window.

The shell should use Qt's native docking model for MVP:

- `QMainWindow` as the workspace root.
- `QDockWidget` for each pane.
- `tabifyDockWidget(...)` for tab groups.
- Built-in dock movement and split docking for drag-based rearrangement and tiling.

This matches the requested "one project/font = one window" requirement while still allowing many internal views.

## View Descriptor

MVP should make the descriptor explicit so pane behavior is deterministic.

### Project identity contract

The wrapper needs one stable project key for window reuse, callback routing, and per-project profile storage, while still remaining compatible with the existing URL format used by the current browser-launch path.

- `resolvedProjectPath` is `str(pathlib.Path(path).resolve())`.
- `projectKey` is `os.path.normcase(resolvedProjectPath)`.
- `projectQueryValue` is the URL form produced from `resolvedProjectPath` using the existing `openFile()` path-segment encoding algorithm. MVP should extract that algorithm into one shared helper instead of inventing a new wire format.
- Incoming URL `?project=` values are decoded back to `resolvedProjectPath`, then canonicalized to `projectKey`.
- Incoming callback `projectIdentifier` values are canonicalized directly to `projectKey`.
- `projectKey` is the only identity used for:
  - project-window registry keys
  - callback routing after canonicalization
  - URL routing after decode and canonicalization
  - per-project web-profile storage paths and hashes
- Any path string that does not canonicalize to the same `projectKey` is treated as a different project.
- If URL decode fails, callback canonicalization fails, or the decoded path does not resolve to a `projectKey`, the value is rejected.

Concrete compatibility examples:

- Raw project path `C:\Fonts\Demo.ufo`
- `resolvedProjectPath` -> resolved absolute path string
- `projectKey` -> `os.path.normcase(resolvedProjectPath)`
- `projectQueryValue` -> encoded with the existing browser-launch helper
- Callback `projectIdentifier` -> canonicalized to `projectKey` before matching

Required fields:

| Field | Meaning |
|------|---------|
| `projectKey` | Canonical project identity produced by the project identity contract |
| `viewKind` | One of `overview`, `editor`, `fontinfo`, `applicationsettings` |
| `pagePath` | One of `/fontoverview.html`, `/editor.html`, `/fontinfo.html`, `/applicationsettings.html` |
| `routeHash` | Hash fragment kept verbatim, including leading `#` or empty string |
| `titleHint` | Wrapper-visible label fallback before the page reports a better title |

Descriptor rules:

- `projectKey` must always be produced by the project identity contract before descriptor creation.
- A descriptor identifies a route target, not a pane instance.
- Every pane owns a separate `paneInstanceId`.
- Multiple panes may intentionally share the same descriptor after same-pane navigation.
- The wrapper never creates descriptors outside the four known top-level Fontra pages.
- `pagePath` is authoritative; `viewKind` is a fixed derived mapping from `pagePath`.

Reuse and deduping rules:

- `openView(descriptor)` and intercepted new-window requests must focus an existing matching pane if one exists.
- If more than one pane matches, focus the most recently focused matching pane.
- Otherwise they open a new pane.
- Same-pane navigation never steals focus to another pane; it simply updates the current pane descriptor, even if another pane already matches.
- Active-pane persistence and restore use `paneInstanceId`, not descriptor uniqueness.

Title derivation rules:

- `overview` -> `Overview`
- `fontinfo` -> `Font Info`
- `applicationsettings` -> `Application Settings`
- `editor` -> `Editor` until the embedded page reports a more specific title

URL mapping:

- All pane URLs are built from `http://localhost:<port>` plus `pagePath`, query `?project=<projectQueryValue>`, and `routeHash`.
- Wrapper-created panes may target only the four known top-level Fontra pages.

## Routing Model

### Internal destinations

The following top-level destinations should stay inside the project window:

- `/fontoverview.html`
- `/editor.html`
- `/fontinfo.html`
- `/applicationsettings.html`

For MVP, `/applicationsettings.html` is hosted inside the current project window and treated as a normal pane even if its content is app-global. It may exist in more than one project window at the same time; it is not an app-wide singleton in MVP.

### External destinations

The following should continue opening in the user's normal browser:

- Documentation links
- GitHub release pages and asset downloads
- Any non-local URL not served by the local Fontra server for the current project

### Routing rule

The wrapper should classify every top-level navigation into exactly one of three buckets:

- `internal`: same `localhost:<port>`, one of the four supported top-level page paths, and `?project=` canonicalizes to the owning `ProjectWindow.projectKey`
- `external`: non-local HTTP(S) page
- `rejected`: same-origin top-level navigation that is unsupported, malformed, missing `?project=`, or points at a different canonical project

Only `internal` destinations may stay inside a project window.

### Navigation policy

| Trigger | Destination | Interception point | Action |
|------|---------|---------------------|--------|
| Launcher open or create | `internal` | Wrapper command path | Create or focus project window, then open or focus pane |
| Same-pane navigation inside a webview | `internal` | URL change in existing pane | Allow navigation in current pane and update that pane's descriptor |
| `window.open`, `_blank`, or other new-window request | `internal` | `Pane Navigation Bridge` | Open or focus pane inside the same project window |
| Same-pane navigation | `rejected` | URL change in existing pane | Block navigation, keep the current page loaded, and show a native unsupported-destination error |
| New-window request | `rejected` | `Pane Navigation Bridge` | Block new pane creation and show a native unsupported-destination error |
| Any navigation | `external` | `Pane Navigation Bridge` | Open externally in the default browser |
| Download response | File download | Web runtime download callback | Handle as a native download or save action, not as a pane |
| Redirect | Final classified destination | Final URL observed by the pane | Re-run the same classification and action rules on the final URL |

### Popup policy

MVP should not allow embedded views to create unmanaged top-level windows. Any webview request for a new top-level browser window must be intercepted and converted into one of:

- Open or focus a pane in the current project window
- Open externally in the user's browser
- Show an unsupported-destination error

This rule is required to preserve the guarantee that the editor stays owned by `Fontra Pak.exe`.

## State Model

MVP should treat each pane as an embedded Fontra view with its own page and URL state, while sharing one project-level session context inside one project window.

Wrapper-owned state:

- Open project windows
- Open panes per project
- Pane placement and tab grouping
- Active pane
- Window geometry
- Restored workspace layout

View-owned state:

- Fontra page state within a specific embedded view
- URL or hash state used by the hosted Fontra page

Persistence:

- Use `QSettings` for launcher geometry, project-window geometry, dock state, active pane, and the list of pane descriptors for each open project.
- On clean application shutdown, persist the full set of open project records. Each record contains `projectKey`, window geometry, dock state, active `paneInstanceId`, and pane records.
- Each pane record contains `paneInstanceId` plus its current descriptor.
- If the next app launch has no explicit file arguments, auto-reopen the previously open project records from the last clean shutdown.
- If the next app launch includes explicit file arguments, open only the requested projects and skip auto-restore.
- If a restored project path no longer exists or fails to open, skip it, keep restoring the rest, and show one aggregated restore error after startup completes.
- No crash-session restore is required for MVP.
- Do not try to merge or rewrite Fontra frontend state for MVP.

Session isolation:

- All panes in one project window must share one `QWebEngineProfile`.
- Different project windows must use different web profiles.
- The persistent storage path for a profile should be derived from the canonical project path so local storage, cookies, cache, and related browser state stay isolated per project.
- Pane-level web profiles are out of scope because they would break the desired within-project workspace behavior.

## Lifecycle

### Startup request contract

MVP startup accepts three sources of project-open intent:

- Explicit startup file arguments from `argv` or file-association launch
- Restored workspace records from the last clean shutdown
- User-initiated launcher actions after startup

Precedence:

- If explicit startup file arguments exist, they win and workspace restore is skipped.
- If there are no explicit startup file arguments, restore the last clean workspace if present.
- If neither explicit startup file arguments nor a restorable workspace exist, show the launcher idle.

### Open project

- The launcher asks `App Workspace Controller` to open a canonical project path.
- If a `ProjectWindow` for that path already exists, the controller focuses it.
- Otherwise the controller creates a new `ProjectWindow`, initializes its per-project web profile, registers the window immediately, and then opens the initial pane.
- If the first pane fails to load after the window exists, the project window stays open and shows an in-window error pane with reload and close actions.

### Close pane

- Closing a pane only closes that view.
- Pane close never triggers a project-save prompt in MVP.
- If the last pane is closed, the `ProjectWindow` immediately reopens the overview pane so the project window never becomes a blank shell.
- Error-pane `Close` is different: if the error pane is the only pane in the project window, `Close` closes the whole project window; otherwise it closes only that pane.

### Close project window

- Project-window close uses the existing open-project tracking from the server callback contract as the MVP proxy for "project still open in Fontra".
- If the project is marked open, closing the project window shows the same confirmation behavior used today for quitting with open fonts.
- If the user confirms, `App Workspace Controller` immediately marks that project as locally closed for quit purposes, removes it from the live workspace set, and then the project window closes and the embedded views are torn down.
- A later `projectClosed` callback for the same `projectIdentifier` is treated as idempotent cleanup, not as a required prerequisite for window teardown.
- MVP does not add a new unsaved-change protocol between the shell and Fontra.

### App quit

- App quit checks whether any registered project is still marked open.
- If none are open, quit proceeds without prompt.
- If one or more are open, quit shows one confirmation prompt and, on confirmation, snapshots the currently open project windows for restore, then closes all project windows.
- During confirmed app quit, `App Workspace Controller` sets a bulk-shutdown flag so per-window close confirmation prompts are suppressed.
- Clean-shutdown workspace persistence happens on every clean app quit, not only on the code path that shows a confirmation prompt.

### Restore

- Restore happens only after a clean shutdown and only when the new launch has no explicit file arguments.
- Restore recreates project windows first, then applies dock state and pane descriptors, then focuses the recorded active pane.
- Missing or failed project restores are reported after the rest of the workspace restore completes.
- If the top-level `QSettings` workspace payload is unreadable or corrupt, MVP discards the saved workspace and starts clean with one aggregated restore error.
- If one project record is corrupt, skip that record and continue restoring the rest.
- If a project record loads but its pane descriptors are invalid, drop the invalid descriptors and reopen only the overview pane for that project.
- If dock-state restoration fails for a project window, keep that project window open with its panes in the default layout and include the failure in the aggregated restore error.
- If a restore failure happens after a project window has been created but before it is usable, destroy that partial window and continue restoring the remaining projects.
- During restore, profile-initialization and first-pane-open failures are included in the aggregated restore error instead of showing immediate standalone dialogs.

### Shared server runtime

- `App Workspace Controller` owns the shared Fontra server process health.
- If the local server exits, hangs irrecoverably, or becomes unavailable after project windows are already open, all open project windows switch to an in-window "connection lost" error pane.
- In that state, new panes and export actions are disabled.
- MVP does not attempt automatic server restart; the recovery actions are reload after manual recovery, close project window, or quit the app.

## Error Handling

Failure behavior should be explicit:

- If the local Fontra server fails to start, the launcher should show a native error dialog and refuse to open project windows.
- If the first pane fails to load, the project window should stay open and show an error pane with at least reload and close actions.
- If any later embedded pane fails to load, the project window should show an error pane with at least reload and close actions.
- If an embedded renderer process crashes, the project window should remain alive and allow the pane to reload.
- If a new-window request targets an unsupported same-origin top-level route, the wrapper should show a native unsupported-destination error and keep the current workspace intact.
- If per-project web-profile initialization fails, abort opening that project window and show a native profile-initialization error.
- If workspace restore encounters missing or unreadable project paths, skip those projects, restore the rest, and show one aggregated restore error afterward.
- If the shared Fontra server dies after startup, all affected project windows should enter the connection-lost state owned by `App Workspace Controller`.
- External-link handling failure should not kill the project window.

## Packaging Impact

The existing environment already uses PyQt, but it does not currently include QtWebEngine. MVP therefore requires:

- Add the QtWebEngine dependency.
- Update PyInstaller bundling to include QtWebEngine resources, helper executables, and the data files required for packaged page load.
- Verify the packaged Windows app still launches and that project windows can load local Fontra pages.
- Add a packaged smoke test that exercises first-page load in a project window, not just process startup.

Bundle size will increase. That is acceptable because solving focused-window ownership and internal workspace control is the primary requirement.

## MVP Acceptance Boundary

MVP is complete only when all of the following are true:

- Opening or creating a project no longer launches the system browser for project editing.
- The active editor window is a native top-level window owned by `Fontra Pak.exe`.
- One project maps to one project window.
- A project window supports multiple panes with tabs, docking, and tiling.
- The wrapper supports the four known Fontra top-level pages as internal destinations.
- New-window requests from embedded views are intercepted and do not create unmanaged browser windows.
- Project windows use per-project web-profile isolation.
- Clean shutdown restores project-window geometry, dock layout, active pane, and pane descriptors.
- External links and downloads are still handled correctly.

## Testing Strategy

At minimum, MVP planning and implementation should cover:

- Startup test: the packaged application still launches cleanly.
- Project opening test: opening a file creates or focuses a native project window instead of launching the browser.
- Ownership test: project editing occurs in a top-level window owned by Fontra Pak.
- Workspace test: panes can be opened, tabified, docked, and rearranged.
- Routing test: same-window navigation, new-window navigation, external links, and downloads follow the navigation policy.
- Isolation test: two open projects do not share web-profile storage.
- Persistence test: project-window geometry, active pane, and pane layout survive clean restart.
- Lifecycle race test: first-load `projectOpened`, late `projectClosed`, and restore-time profile or initial-pane failures behave according to the lifecycle contract.
- Failure test: broken pane load shows a recoverable in-app error path.

Manual verification on Windows is mandatory because the mouse-profile use case is the primary product reason for the change.

## Suggested Implementation Order

Phases 1 and 2 together define MVP. Phase 3 is post-MVP hardening.

### Phase 1: Embedded single project window

- Add the embedded web runtime.
- Replace `webbrowser.open(...)` for project launch with a native project window.
- Introduce `App Workspace Controller`, exact routing rules, and per-project web profiles.

### Phase 2: Workspace shell

- Add pane creation, docking, tabification, and layout persistence.
- Support the four main Fontra destinations inside one project window.
- Add descriptor persistence and reopen behavior on clean restart.

### Phase 3: Polish and stabilization

- Improve titles, focus behavior, reopen or focus logic, and crash recovery.
- Tighten tests and packaging reliability.

## Future Optimization Path

Fontra-side integration is intentionally out of MVP scope. If the wrapper-only prototype reaches a working state and reveals enough friction, later optimization can introduce explicit shell hooks inside Fontra, such as:

- Structured "open view" events instead of browser-style navigation assumptions
- Cleaner internal view descriptors
- Better shared-state or session coordination between panes

That work should be justified by prototype results, not assumed up front.

## Decision

Proceed with a wrapper-only MVP that keeps the current PyQt and Python architecture, adds an embedded web runtime, and moves project editing into native project windows owned by `Fontra Pak.exe`, with internal tabs and dockable panes managed by the wrapper.
