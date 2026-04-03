# Native Project Window Plan — Remaining Shortcomings

> **Date:** 2026-04-03
> **Against:** `docs/superpowers/plans/2026-04-02-native-project-window.md` (deduplicated)
> **Status:** Known issues not addressed by the current plan. Each item should be resolved before, during, or after implementation — or explicitly deferred with awareness.

## Context

This document catalogs shortcomings in the **Native Project Window Implementation Plan** — the approved plan to replace Fontra Pak's browser handoff with native PyQt6 project windows that embed Fontra views via QtWebEngine.

The plan (`2026-04-02-native-project-window.md`) is ~3,650 lines, organized into 28 tasks across three phases:
- **Phase 0** (Tasks 1–12): Extract the monolithic `FontraPakMain.py` into a `fontra_pak/` package.
- **Phase 1** (Tasks 13–23): Add QtWebEngine, build the `AppWorkspaceController` + `ProjectWindow` + `WorkspacePane` architecture, replace `webbrowser.open()` with embedded views.
- **Phase 2** (Tasks 24–28): Workspace persistence (save/restore), full test suite, manual acceptance testing.

The plan was deduplicated on 2026-04-03: six duplicate task definitions (original Tasks 19–22, 26–27) were removed in favor of their revised "A" counterparts (19A, 20A, 21A, 22A, 26A, 27A). The document is now linear with no conflicting versions.

This shortcomings review was produced after a full read-through of the deduplicated plan, cross-referenced against the codebase's current state (`FontraPakMain.py`, `requirements.txt`, `FontraPak.spec`, existing tests). Items are sorted by priority:

| Level | Meaning |
|-------|---------|
| **P0** | Blocker — must be fixed before or during Phase 1, or the investment is at risk |
| **P1** | Should fix — address during implementation to avoid bugs in the MVP |
| **P2** | Should fix — address in Phase 2/3; causes UX or platform issues but won't break core functionality |
| **P3** | Nice to have — future work, no immediate risk |

---

## P0 — Must address before or during Phase 1

### 1. PyInstaller build verification deferred to "post-MVP"

**Location:** Post-Plan Notes

The plan adds `PyQt6-WebEngine` to requirements (Task 13) and updates `FontraPak.spec` (Task 14), but actual `pyinstaller` build verification is listed under "Not covered (post-MVP / Phase 3)." QtWebEngine packaging is the single largest failure mode: missing `QtWebEngineProcess.exe`, locale files, ICU data, and Qt Quick dependencies routinely break frozen builds. If the PyInstaller build is broken, the entire Phase 1+2 investment is non-shippable.

**Recommendation:** Move PyInstaller verification into Phase 1, right after Task 14 (or as a gate after Task 23). At minimum, run `pyinstaller FontraPak.spec -y` and verify the resulting `.exe` launches on the developer's machine before proceeding to Phase 2.

---

### 2. Historical: original Task 21 had a non-canonical key bug

The *original* Task 21 `_on_exportAs` (deleted during deduplication) passed `project_identifier` instead of the canonicalized `project_key` to the export callback, causing downstream consumers that rely on `path_to_project_key` equality to fail. The revised Task 21A fixes this. This note exists as a paper trail in case anyone reviews the deleted version from git history.

---

## P1 — Should address during implementation

### 2. No automated tests for `PaneNavigationBridge`

**Location:** Task 18

The plan explicitly states: "No tests — this is Qt-dependent and will be verified manually." The navigation bridge (`PaneNavigationBridge` + `_NavigationTrapPage`) is the most complex and failure-prone part of the system — it intercepts every `window.open()` and navigation event from the embedded Fontra frontend. A misclassified URL silently opens the browser (defeating the MVP goal) or blocks valid navigation (breaking the app).

**Recommendation:** Even minimal tests using `unittest.mock` to verify `classify_url` dispatch paths would catch the majority of classification bugs. At least test that `PaneNavigationBridge.acceptNavigationRequest()` returns `True` for known-internal URLs and `False` for external/rejected ones.

---

### 3. Race condition in `_NavigationTrapPage` lifecycle

**Location:** Task 18, `_NavigationTrapPage`

When Fontra calls `window.open()` multiple times in rapid succession (e.g., opening multiple views from a menu), `createWindow()` is called for each, creating a new `_NavigationTrapPage` each time. The pane stores only one reference:

```python
trap = _NavigationTrapPage(self.pane)
self.pane._pending_trap = trap  # overwrites any previous trap
```

If trap #2 overwrites `self.pane._pending_trap` before trap #1 receives its navigation request, trap #1 becomes eligible for garbage collection before its URL is captured — the `window.open()` call is silently dropped.

**Recommendation:** Use a list (`self.pane._pending_traps: list[_NavigationTrapPage]`) instead of a single reference, and have each trap remove itself from the list after classification.

---

### 5. `about:blank` navigation in the main bridge page

**Location:** Task 18, `PaneNavigationBridge.acceptNavigationRequest()`

The `_NavigationTrapPage` explicitly handles `about:blank` by returning `False`. The main `PaneNavigationBridge.acceptNavigationRequest()` does not. If the Fontra frontend navigates to `about:blank` in the main frame (e.g., during iframe teardown, page transitions, or JavaScript `location.replace("about:blank")`), the URL will not match the expected `localhost:port` netloc and will be classified as EXTERNAL — causing `webbrowser.open("about:blank")` to fire in the system browser.

**Recommendation:** Add an early `if url_str == "about:blank": return False` guard at the top of `PaneNavigationBridge.acceptNavigationRequest()`.

---

### 6. Server crash / disconnect detection is missing

**Location:** Task 21A, `notify_server_lost` + Post-Plan Notes

The `notify_server_lost()` method exists on `AppWorkspaceController` but is never wired to any health check, timer, or WebSocket disconnect handler. If the Fontra server process crashes or hangs, project windows continue to render stale content with no indication to the user. The user would need to manually discover the issue.

**Recommendation:** At minimum, add a `QTimer` in `app.py` that periodically checks `serverProcess.is_alive()` and calls `controller.notify_server_lost()` if the process is dead. Better: listen for WebSocket disconnect events from the Fontra server's queue.

---

### 7. Dead code in `launcher.py` after controller wiring

**Location:** Task 22A → Task 23

After Task 23, `queueGetter` routes to `controller.handle_server_message` instead of `mainWindow.messageFromServer`. This means the following methods on `FontraMainWidget` become dead code:
- `messageFromServer()` — never called (controller handles it)
- `projectOpened()` — never called (controller handles it)
- `projectClosed()` — never called (controller handles it)
- `exportAs()` — still called via `controller.set_export_callback(mainWindow.exportAs)` in `app.py`

The plan does not explicitly mark these methods for removal. `messageFromServer`, `projectOpened`, and `projectClosed` can be safely deleted from `FontraMainWidget`.

**Recommendation:** Add a cleanup step to Task 23 or Task 22A that removes the dead methods from `launcher.py`.

---

### 8. Export dialog opens on launcher window, not project window

**Location:** Task 23, `controller.set_export_callback(mainWindow.exportAs)`

The `exportAs` callback is wired to `FontraMainWidget.exportAs`, which shows a `QFileDialog` on the launcher window. If the launcher is minimized or hidden behind project windows, the export dialog will appear behind the active window — a confusing UX. The plan notes this as "post-MVP" but it manifests as soon as Task 23 is complete.

**Recommendation:** Wire the export callback to the active project window's controller, or bring the launcher to the foreground before showing the dialog.

---

## P2 — Should address in Phase 2 or Phase 3

### 9. Windows cache path uses `AppDataLocation` (roaming profile)

**Location:** Task 21A, `_create_profile`

```python
app_data = QStandardPaths.writableLocation(
    QStandardPaths.StandardLocation.AppDataLocation
)
```

On Windows, `AppDataLocation` resolves to `%APPDATA%` (Roaming). Each project's `QWebEngineProfile` stores cache, cookies, and IndexedDB here. A single project can accumulate 50-200 MB of web cache. On corporate networks with roaming profile quotas, this can cause login failures or IT tickets.

**Recommendation:** Use `QStandardPaths.StandardLocation.AppLocalDataLocation` (which maps to `%LOCALAPPDATA%`) for the profile root, and `QStandardPaths.StandardLocation.CacheLocation` for the cache subdirectory.

---

### 10. Server process termination on Windows is abrupt

**Location:** Task 23, `app.py` `cleanup()`

```python
if sys.platform != "win32":
    p.send_signal(psutil.signal.SIGINT)
else:
    p.terminate()
```

On Windows, `terminate()` sends a hard kill signal. The Fontra server process (a `multiprocessing.Process` running `FontraServer`) does not handle `SIGTERM`-equivalent termination gracefully on Windows — it may not close database connections, flush logs, or notify connected QtWebEngine views.

**Recommendation:** Use `subprocess.CREATE_NEW_PROCESS_GROUP` + `Ctrl+Break` signal, or send a shutdown message through the queue before terminating.

---

### 11. No project window `File` or `Help` menu

**Location:** Task 20A, `ProjectWindow._setup_menu_bar()`

The project window only has a `&View` menu. There is no `&File` menu (Close Project, Export As) and no `&Help` menu (Documentation link). The spec mentions "Help > Documentation" as an internal pane, but there is no menu to trigger it. The launcher window has these buttons, but once a project is open, the user must return to the launcher to access them.

**Recommendation:** Add `&File` and `&Help` menus to `ProjectWindow._setup_menu_bar()`.

---

### 12. Launcher close behavior when no projects are open is ambiguous

**Location:** Task 22A, `FontraMainWidget.closeEvent()`

After controller wiring, the launcher's `closeEvent()` calls `controller.begin_bulk_shutdown()` + `controller.close_all_project_windows()`. But when no project windows exist, `has_workspace` is `False` and `needs_confirm` is `False` — the launcher just saves settings and exits. This is consistent with current behavior, but the plan doesn't explicitly state whether closing the launcher should also quit the entire app (call `QApplication.quit()`) or just hide the launcher.

**Recommendation:** Clarify: when the launcher is closed with no open projects, call `app.quit()` to terminate the application. Currently, the launcher's `closeEvent` only saves settings — the app process continues running with no visible windows.

---

### 13. Per-project `QWebEngineProfile` isolation is incomplete

**Location:** Task 21A, `_create_profile`

Each project gets its own `QWebEngineProfile` with separate cache and persistent storage. However, all profiles share the same underlying Chromium renderer process. If Fontra's frontend ever stores cross-project data in a shared location (e.g., `localStorage` keyed by a global identifier, IndexedDB with a shared database name), it would leak between projects.

**Recommendation:** Verify that Fontra's frontend does not use any global storage keys. If it does, prefix them with the `project_key` in a custom `QWebChannel` script or by injecting JavaScript on page load.

---

### 14. Non-ASCII file paths on Windows drag-and-drop

**Location:** Task 22A, `FontraMainWidget.dropEvent()`

```python
files = [u.toLocalFile() for u in event.mimeData().urls()]
```

On Windows, `QUrl.toLocalFile()` may return incorrect results for paths with non-ASCII characters in certain Qt 6 versions (the URL encoding may not be fully decoded). This would cause `controller.open_project(path)` to fail silently.

**Recommendation:** Add a fallback: if `os.path.exists(path)` fails after `toLocalFile()`, try `QUrl.toLocalFile(QUrl.ComponentFormattingOption.FullyDecoded)`.

---

## P3 — Nice to have / future work

### 15. No rollback / feature flag mechanism

If Phase 1 introduces regressions, there is no documented rollback path or feature flag to fall back to the old `webbrowser.open()` behavior. The plan should include a `--legacy-browser` CLI flag or a `QSettings` toggle that skips controller wiring and uses the old launcher-only flow.

---

### 16. No handling for project path disappearing mid-session

If a user deletes or renames a `.ufo` / `.fontra` directory while it is open, `resolve_project_path` still produces a valid key (the resolved path exists as a string, even if the directory is gone). However, the Fontra server will return 404 for all subsequent requests, and `classify_url` will still route them as INTERNAL — the pane will show the server's 404 page inside the project window with no native error overlay.

---

### 17. No handling for port collision on startup

**Location:** Task 23, `app.py` `main()`

```python
port = findFreeTCPPort(host=host)
```

If another process binds the port after `findFreeTCPPort` returns but before the server starts, the server will fail to bind. The plan has no retry or fallback behavior.

---

### 18. `_canonicalize` silently swallows exceptions

**Location:** Task 21A, `AppWorkspaceController._canonicalize()`

```python
def _canonicalize(self, project_identifier: str) -> str | None:
    try:
        return canonical_callback_project_key(project_identifier)
    except Exception:
        logger.warning("Failed to canonicalize: %s", project_identifier)
        return None
```

All three server callback handlers (`_on_projectOpened`, `_on_projectClosed`, `_on_exportAs`) silently skip when `_canonicalize` returns `None`. If canonicalization fails (e.g., due to a path encoding bug), the user sees no error — the project simply doesn't appear in `open_projects` and exports don't fire.

---

## Summary table

| # | Priority | Category | Effort | When to fix |
|---|----------|----------|--------|-------------|
| 1 | P0 | PyInstaller verification deferred | Medium | Move into Phase 1 |
| 3 | P1 | No bridge tests | Medium | During Task 18 |
| 4 | P1 | Trap page race condition | Low | During Task 18 |
| 5 | P1 | `about:blank` misclassification | Low | During Task 18 |
| 6 | P1 | No server crash detection | Medium | During Task 23 |
| 7 | P1 | Dead code in launcher | Low | During Task 23 |
| 8 | P1 | Export dialog on wrong window | Low | During Task 23 |
| 9 | P2 | Roaming profile cache bloat | Low | During Task 21A |
| 10 | P2 | Abrupt server kill on Windows | Medium | During Task 23 |
| 11 | P2 | Missing File/Help menus | Low | During Task 20A |
| 12 | P2 | Launcher quit behavior ambiguity | Low | During Task 22A/23 |
| 13 | P2 | Web profile isolation gap | Medium | Phase 3 |
| 14 | P2 | Non-ASCII drag-and-drop paths | Low | During Task 22A |
| 15 | P3 | No feature flag / rollback | Medium | Phase 3 |
| 16 | P3 | Disappeared project path | Low | Phase 3 |
| 17 | P3 | Port collision | Low | Phase 3 |
| 18 | P3 | Silent canonicalize failures | Low | Phase 3 |
