# Fontra Pak Native Project Window Design

Date: 2026-04-01
Status: Approved design

## Summary

Fontra Pak should stop handing editing off to the system browser and instead own both the launcher window and each project editor window as native desktop windows provided by `Fontra Pak.exe`.

The least intrusive path is to keep the existing Python, PyQt, local-server, and PyInstaller architecture, and replace the current `webbrowser.open(...)` handoff with an embedded web runtime hosted inside a new project window. The project window should support one font project per top-level window, plus multiple internal tabs and dockable panes for Fontra views such as overview, glyph editor, font info, and application settings.

MVP scope is wrapper-only. Fontra changes are explicitly out of scope for the first prototype. If the prototype exposes too much browser-centric friction, or if shared-state/performance optimization becomes necessary, Fontra can later add shell-aware navigation hooks.

## Problem Statement

Current behavior:

- `Fontra Pak.exe` launches a native drop/launcher window.
- Opening a project calls `webbrowser.open(...)`.
- The active editor window therefore belongs to the user's default browser, not to Fontra Pak.

This creates two concrete problems:

- Mouse/profile software that switches on the focused top-level application window sees the browser instead of `Fontra Pak.exe`.
- Desktop window management is split between a small launcher window and browser windows/tabs that Fontra Pak does not control.

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
- Use Qt's built-in `QMainWindow` and `QDockWidget` workspace model first, because it provides native tabs/docking/tiling with the least added surface area.

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
- Internal navigation opens new tabs/panes inside the project window instead of opening the system browser.

### Core units

#### Launcher Window

Responsibilities:

- Keep the current drop target and "new font" flow.
- Open, create, and focus project windows.
- Track which projects already have open windows.

#### Project Window

Responsibilities:

- Own the top-level native editor window for exactly one font project.
- Manage the internal workspace layout.
- Create, focus, close, and persist view panes.
- Route internal versus external destinations.

#### Workspace Pane

Responsibilities:

- Represent one logical view destination such as overview, glyph editor, font info, or application settings.
- Own exactly one embedded web view widget.
- Expose title, kind, and view-specific identity for tab/pane labeling.

#### View Descriptor

Responsibilities:

- Describe a destination in wrapper terms, for example:
  - `overview`
  - `editor(glyph=A)`
  - `fontinfo`
  - `applicationsettings`
- Let the wrapper decide whether to focus an existing pane or open a new one.

This unit boundary keeps shell behavior in Fontra Pak and content rendering in Fontra.

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

## Routing Model

### Internal destinations

The following destinations should stay inside the project window:

- `fontoverview.html`
- `editor.html`
- `fontinfo.html`
- `applicationsettings.html`
- Any additional Fontra project-local routes introduced later

### External destinations

The following should continue opening in the user's normal browser:

- Documentation links
- GitHub release pages and asset downloads
- Any non-local URL not served by the local Fontra server for the current project

### Routing rule

The wrapper should route based on URL origin and known Fontra entry points:

- `http://localhost:<port>/...` plus a recognized Fontra app page for the active project is internal.
- Everything else is external.

## State Model

MVP should treat each pane as an embedded Fontra view with its own page and URL state, while sharing the same project-level session context inside one project window.

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

- Use `QSettings` for launcher geometry, project-window geometry, and workspace layout.
- Persist enough metadata to reopen panes for a project on restart if that behavior is enabled later.
- Do not try to merge or rewrite Fontra frontend state for MVP.

## Error Handling

Failure behavior should be explicit:

- If the local Fontra server fails to start, the launcher should show a native error dialog and refuse to open project windows.
- If an embedded pane fails to load, the project window should show an error pane with at least reload and close actions.
- If an embedded renderer process crashes, the project window should remain alive and allow the pane to reload.
- If a requested internal destination is unsupported, the wrapper may fall back to opening the overview pane for the project instead of crashing.
- External-link handling failure should not kill the project window.

## Packaging Impact

The existing environment already uses PyQt, but it does not currently include QtWebEngine. MVP therefore requires:

- Add the QtWebEngine dependency.
- Update PyInstaller bundling to include QtWebEngine resources and helper executables.
- Verify the packaged Windows app still launches and that project windows can load local Fontra pages.

Bundle size will increase. That is acceptable because solving focused-window ownership and internal workspace control is the primary requirement.

## Testing Strategy

At minimum, MVP planning and implementation should cover:

- Startup test: the packaged application still launches cleanly.
- Project opening test: opening a file creates or focuses a native project window instead of launching the browser.
- Ownership test: project editing occurs in a top-level window owned by Fontra Pak.
- Workspace test: panes can be opened, tabified, docked, and rearranged.
- Persistence test: project-window geometry and workspace layout survive restart.
- External routing test: docs/releases still open externally.
- Failure test: broken pane load shows a recoverable in-app error path.

Manual verification on Windows is mandatory because the mouse-profile use case is the primary product reason for the change.

## Phased Delivery

### Phase 1: Embedded single project window

- Add the embedded web runtime.
- Replace `webbrowser.open(...)` for project launch with a native project window.
- Keep a simple internal host to prove ownership and packaging.

### Phase 2: Workspace shell

- Add pane creation, docking, tabification, and layout persistence.
- Support the main Fontra destinations inside one project window.

### Phase 3: Polish and stabilization

- Improve titles, focus behavior, reopen/focus logic, and crash recovery.
- Tighten tests and packaging reliability.

## Future Optimization Path

Fontra-side integration is intentionally out of MVP scope. If the wrapper-only prototype reaches a working state and reveals enough friction, later optimization can introduce explicit shell hooks inside Fontra, such as:

- Structured "open view" events instead of browser-style navigation assumptions
- Cleaner internal view descriptors
- Better shared-state or session coordination between panes

That work should be justified by prototype results, not assumed up front.

## Decision

Proceed with a wrapper-only MVP that keeps the current PyQt/Python architecture, adds an embedded web runtime, and moves project editing into native project windows owned by `Fontra Pak.exe`, with internal tabs and dockable panes managed by the wrapper.
