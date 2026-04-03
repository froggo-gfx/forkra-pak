# Native Project Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the browser handoff with native project windows that embed Fontra views inside `Fontra Pak.exe`, with dockable panes and workspace persistence.

**Architecture:** Keep the existing Python/PyQt6/PyInstaller stack and local Fontra server. Add `PyQt6-WebEngine` to embed Fontra views in `QMainWindow`-based project windows with `QDockWidget` panes. A new `AppWorkspaceController` manages the project window registry, routes server callbacks, and owns quit/restore behavior. Navigation is intercepted at the `QWebEnginePage` level and classified as internal (open/focus pane), external (system browser), or rejected (block + error).

**Tech Stack:** Python 3.12+, PyQt6 6.7, PyQt6-WebEngine, PyInstaller 6.17, pytest

**Spec:** `docs/superpowers/specs/2026-04-01-fontra-native-project-window-design.md`

---

## Important discoveries

1. `FileSystemProjectManager.authorize()` returns `"yes"` unconditionally. The server's `versionToken` is used only for static file cache-busting, not request authentication. The current `openFile()` does not include any token in URLs. Pane URLs do not need a versionToken.

2. Fontra frontend navigation patterns (from `fontra-overview/src-js/`):
   - Overview to editor: `window.open(url)` (no target name — opens new window)
   - Editor to font info: `window.open(url, "fontra.fontinfo.<projectId>")`
   - Any to app settings: `window.open("/applicationsettings.html#panel", "_self" | "fontra.applicationsettings")`
   - Font overview/info from menu: `window.open(url, "fontra.<viewKind>.<uniqueId>" | "_self")`
   - External links: `window.open("https://...", "fontra.website")` or `<a target="_blank">`

   All internal navigation uses `window.open()` with named targets or `_self`. `QWebEnginePage.createWindow()` intercepts all `window.open()` calls with non-`_self` targets. Same-page `_self` navigation goes through `acceptNavigationRequest()`.

---

## File structure

### New package (created alongside `FontraPakMain.py` during Phase 0 — the original file stays untouched until the very end)

```
fontra_pak/
    __init__.py           - Empty package marker
    __main__.py           - Entry point: multiprocessing.freeze_support() + main()
    app.py                - FontraApplication subclass, main() orchestration
    launcher.py           - FontraMainWidget (launcher/drop window)
    server.py             - runFontraServer, FontraPakExportManager, ProjectOpenListener
    ipc.py                - CallInMainThreadScheduler, queueGetter, callInMainThread, callInNewThread
    dialogs.py            - showMessageDialog, getFontPath
    export.py             - exportFontToPath, exportFontToPathAsync, createNewFont
    constants.py          - CSS strings, file type mappings, URLs
    update_checker.py     - fetchLatestReleaseInfo
    controller.py         - AppWorkspaceController (Phase 1)
    project_identity.py   - Project identity contract helpers (Phase 1)
    view_descriptor.py    - ViewDescriptor dataclass (Phase 1)
    routing.py            - URL classification (internal/external/rejected) (Phase 1)
    project_window.py     - ProjectWindow (Phase 1)
    workspace_pane.py     - WorkspacePane + PaneNavigationBridge (Phase 1)
    persistence.py        - Workspace save/restore serialization (Phase 2)
```

### Test files

```
tests/
    test_startup.py                - Existing (unchanged until Phase 0 final step)
    test_fontra_client_bundling.py - Existing (unchanged)
    test_project_identity.py       - Phase 1
    test_view_descriptor.py        - Phase 1
    test_routing.py                - Phase 1
    test_controller_callbacks.py   - Phase 1
    test_persistence.py            - Phase 2
```

---

## Phase 0: Codebase Restructuring

**Rule for Phase 0:** `FontraPakMain.py` is NOT modified until the very last task. All new files are created alongside it. The app remains runnable via `python FontraPakMain.py` at every step. The new package is only verified via `python -m fontra_pak` once all files exist.

### Task 1: Create empty package

**Files:**
- Create: `fontra_pak/__init__.py`

- [ ] **Step 1: Create `fontra_pak/__init__.py`**

Create an empty file:

```python
# fontra_pak/__init__.py
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/__init__.py
git commit -m "refactor: create empty fontra_pak package"
```

### Task 2: Create constants module

**Files:**
- Create: `fontra_pak/constants.py`

- [ ] **Step 1: Create `fontra_pak/constants.py`**

This file contains all module-level constants. Copy the content below exactly:

```python
# fontra_pak/constants.py

commonCSS = """
border-radius: 20px;
border-style: dashed;
font-size: 18px;
padding: 16px;
"""

neutralCSS = (
    """
background-color: rgba(255,255,255,128);
border: 5px solid lightgray;
"""
    + commonCSS
)

droppingCSS = (
    """
background-color: rgba(255,255,255,64);
border: 5px solid gray;
"""
    + commonCSS
)

mainText = """
<span style="font-size: 40px;">Drop font files here</span>
<br>
<br>
Your fonts will stay on your computer and will not be uploaded anywhere.
<br>
<br>
Fontra Pak reads and writes .ufo, .designspace, .rcjk and .fontra
<br>
Additionally, it can read (not write) .ttf, .otf, .woff, .woff2, and (with some limitations)
.glyphs and .glyphspackage
"""

fileTypes = [
    # name, extension
    ("Designspace", "designspace"),
    ("Fontra", "fontra"),
    ("RoboCJK", "rcjk"),
    ("Unified Font Object", "ufo"),
]

fileTypesMapping = {
    f"{name} (*.{extension})": f".{extension}" for name, extension in fileTypes
}

exportFileTypes = [
    # name, extension
    ("TrueType", "ttf"),
    ("OpenType", "otf"),
] + fileTypes

exportFileTypesMapping = {
    f"{name} (*.{extension})": f".{extension}" for name, extension in exportFileTypes
}

exportExtensionMapping = {v: k for k, v in exportFileTypesMapping.items()}

latestReleasePageURL = "https://github.com/fontra/fontra-pak/releases/latest"
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/constants.py
git commit -m "refactor: create fontra_pak/constants.py"
```

### Task 3: Create IPC module

**Files:**
- Create: `fontra_pak/ipc.py`

- [ ] **Step 1: Create `fontra_pak/ipc.py`**

```python
# fontra_pak/ipc.py
import secrets
import threading

from PyQt6.QtCore import QObject, pyqtSignal


class CallInMainThreadScheduler(QObject):
    signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.signal.connect(self.receive)
        self.items = {}

    def receive(self, identifier):
        assert threading.current_thread() is threading.main_thread()
        function, args, kwargs = self.items.pop(identifier)
        function(*args, **kwargs)

    def schedule(self, function, args, kwargs):
        identifier = secrets.token_hex(4)
        self.items[identifier] = function, args, kwargs
        self.signal.emit(identifier)


_callInMainThreadScheduler = CallInMainThreadScheduler()


def callInMainThread(function, *args, **kwargs):
    _callInMainThreadScheduler.schedule(function, args, kwargs)


def callInNewThread(function, *args, **kwargs):
    thread = threading.Thread(target=function, args=args, kwargs=kwargs)
    thread.start()
    return thread


def queueGetter(queue, callback):
    while True:
        item = queue.get()
        if item is None:
            break

        callInMainThread(callback, item)
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/ipc.py
git commit -m "refactor: create fontra_pak/ipc.py"
```

### Task 4: Create dialogs module

**Files:**
- Create: `fontra_pak/dialogs.py`

- [ ] **Step 1: Create `fontra_pak/dialogs.py`**

```python
# fontra_pak/dialogs.py
from PyQt6.QtWidgets import QMessageBox


def showMessageDialog(
    message,
    infoText,
    detailedText=None,
    icon=QMessageBox.Icon.Warning,
    buttons=None,
    defaultButton=None,
):
    dialog = QMessageBox()
    if icon is not None:
        dialog.setIcon(icon)
    dialog.setText(message)
    dialog.setInformativeText(infoText)
    if detailedText is not None:
        dialog.setStyleSheet("QTextEdit { font-weight: regular; }")
        dialog.setDetailedText(detailedText)
    if buttons is not None:
        dialog.setStandardButtons(buttons)
    if defaultButton is not None:
        dialog.setDefaultButton(defaultButton)
        # FIXME: The following does *not* make "escape" equivalent to the default button
        dialog.setEscapeButton(defaultButton)

    return dialog.exec()


def getFontPath(path, fileType, mapping):
    extension = mapping[fileType]
    if not path.endswith(extension):
        path += extension

    return path
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/dialogs.py
git commit -m "refactor: create fontra_pak/dialogs.py"
```

### Task 5: Create export module

**Files:**
- Create: `fontra_pak/export.py`

- [ ] **Step 1: Create `fontra_pak/export.py`**

```python
# fontra_pak/export.py
import asyncio
import pathlib
import sys
from contextlib import aclosing

from fontra.backends import getFileSystemBackend, newFileSystemBackend
from fontra.backends.copy import copyFont
from fontra.backends.populate import populateBackend
from fontra.core.classes import DiscreteFontAxis


def exportFontToPath(sourcePath, destPath, fileExtension, logFilePath):
    logFile = open(logFilePath, "w")
    sys.stdout = sys.stderr = logFile

    try:
        asyncio.run(exportFontToPathAsync(sourcePath, destPath, fileExtension))
    finally:
        logFile.flush()


async def exportFontToPathAsync(sourcePath, destPath, fileExtension):
    sourcePath = pathlib.Path(sourcePath)
    destPath = pathlib.Path(destPath)

    sourceBackend = getFileSystemBackend(sourcePath)

    if fileExtension in {"ttf", "otf"}:
        from fontra.workflow.workflow import Workflow

        continueOnError = False

        # For now, we drop discrete axes, and only export the default
        axes = await sourceBackend.getAxes()
        discreteAxisNames = [
            axis.name for axis in axes.axes if isinstance(axis, DiscreteFontAxis)
        ]

        dropDiscreteAxes = (
            [dict(filter="subset-axes", dropAxisNames=discreteAxisNames)]
            if discreteAxisNames
            else []
        )

        config = dict(
            steps=dropDiscreteAxes
            + [
                dict(filter="decompose-composites", onlyVariableComposites=True),
                dict(filter="drop-unreachable-glyphs"),
                dict(
                    output="compile-fontmake",
                    destination=destPath.name,
                    options={"verbose": "DEBUG", "overlaps-backend": "pathops"},
                ),
            ]
        )

        workflow = Workflow(config=config, parentDir=sourcePath.parent)

        async with workflow.endPoints(sourceBackend) as endPoints:
            assert endPoints.endPoint is not None

            for output in endPoints.outputs:
                await output.process(destPath.parent, continueOnError=continueOnError)
    else:
        destBackend = newFileSystemBackend(destPath)
        async with aclosing(sourceBackend), aclosing(destBackend):
            await copyFont(sourceBackend, destBackend)


async def createNewFont(fontPath):
    destBackend = newFileSystemBackend(fontPath)
    await populateBackend(destBackend)
    await destBackend.aclose()
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/export.py
git commit -m "refactor: create fontra_pak/export.py"
```

### Task 6: Create server module

**Files:**
- Create: `fontra_pak/server.py`

- [ ] **Step 1: Create `fontra_pak/server.py`**

```python
# fontra_pak/server.py
import logging
import multiprocessing
import secrets
from dataclasses import dataclass

from fontra.core.server import FontraServer, findFreeTCPPort
from fontra.filesystem.projectmanager import FileSystemProjectManager

from fontra_pak.constants import exportFileTypes


@dataclass
class FontraPakExportManager:
    appQueue: multiprocessing.Queue

    def getSupportedExportFormats(self):
        return [typ for (_name, typ) in exportFileTypes]

    async def exportAs(self, projectIdentifier, options):
        self.appQueue.put(("exportAs", (projectIdentifier, options)))


@dataclass
class ProjectOpenListener:
    appQueue: multiprocessing.Queue

    def projectOpened(self, projectIdentifier: str) -> None:
        self.appQueue.put(("projectOpened", (projectIdentifier,)))

    def projectClosed(self, projectIdentifier: str) -> None:
        self.appQueue.put(("projectClosed", (projectIdentifier,)))


def runFontraServer(host, port, queue):
    logging.basicConfig(
        format="%(asctime)s %(name)-17s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    projectManager = FileSystemProjectManager(
        None,
        exportManager=FontraPakExportManager(queue),
        projectOpenListener=ProjectOpenListener(queue),
    )

    server = FontraServer(
        host=host,
        httpPort=port,
        projectManager=projectManager,
        versionToken=secrets.token_hex(4),
    )
    server.setup()
    server.run(showLaunchBanner=False)
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/server.py
git commit -m "refactor: create fontra_pak/server.py"
```

### Task 7: Create update checker module

**Files:**
- Create: `fontra_pak/update_checker.py`

- [ ] **Step 1: Create `fontra_pak/update_checker.py`**

```python
# fontra_pak/update_checker.py
import json
import sys
import traceback
from urllib.request import urlopen


def fetchLatestReleaseInfo() -> tuple[str, str | None]:
    try:
        return _fetchLatestReleaseInfo()
    except Exception:
        print("Failed to fetch release info")
        traceback.print_exc()

    return "0.0.0", None


def _fetchLatestReleaseInfo() -> tuple[str, str | None]:
    url = "https://api.github.com/repos/fontra/fontra-pak/releases/latest"
    response = urlopen(url)
    latestRelease = json.loads(response.read().decode("utf-8"))
    latestVersion = latestRelease["tag_name"]

    assetNamePart = None
    match sys.platform:
        case "darwin":
            assetNamePart = "macOS"
        case "win32":
            assetNamePart = "Windows"

    if assetNamePart is None:
        return latestVersion, None

    [assetInfo] = [
        asset for asset in latestRelease["assets"] if assetNamePart in asset["name"]
    ]

    return latestVersion, assetInfo["browser_download_url"]
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/update_checker.py
git commit -m "refactor: create fontra_pak/update_checker.py"
```

### Task 8: Create launcher module

**Files:**
- Create: `fontra_pak/launcher.py`

This is the largest file. It contains `FontraMainWidget` and the `openFile` function. It imports from the package modules created in Tasks 2-7.

- [ ] **Step 1: Create `fontra_pak/launcher.py`**

```python
# fontra_pak/launcher.py
import asyncio
import multiprocessing
import os
import pathlib
import signal
import sys
import tempfile
import webbrowser
from datetime import datetime
from random import random
from urllib.parse import quote

from fontra import __version__ as fontraVersion
from PyQt6.QtCore import QPoint, QSettings, QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from fontra_pak.constants import (
    droppingCSS,
    exportExtensionMapping,
    exportFileTypesMapping,
    fileTypesMapping,
    latestReleasePageURL,
    mainText,
    neutralCSS,
)
from fontra_pak.dialogs import getFontPath, showMessageDialog
from fontra_pak.export import createNewFont, exportFontToPath
from fontra_pak.ipc import callInMainThread, callInNewThread
from fontra_pak.update_checker import fetchLatestReleaseInfo


def openFile(path, port):
    path = pathlib.Path(path).resolve()
    assert path.is_absolute()
    parts = list(path.parts)
    if not path.drive:
        assert parts[0] == "/"
        del parts[0]
    path = "/".join(quote(part, safe="") for part in parts)

    webbrowser.open(f"http://localhost:{port}/fontoverview.html?project={path}")


class FontraMainWidget(QMainWindow):
    def __init__(self, port):
        super().__init__()
        self.port = port
        self.openProjects = set()

        self.setWindowTitle("Fontra Pak")
        self.resize(720, 480)

        self.settings = QSettings("xyz.fontra", "FontraPak")

        self.resize(self.settings.value("size", QSize(720, 480)))
        self.move(self.settings.value("pos", QPoint(50, 50)))

        self.setAcceptDrops(True)

        self.label = QLabel(mainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(neutralCSS)
        self.label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.label.setWordWrap(True)

        layout = QGridLayout()

        button = QPushButton("&New Font...", self)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.clicked.connect(self.newFont)

        buttonDocs = QPushButton("Documentation", self)
        buttonDocs.setToolTip("Open documentation website")
        buttonDocs.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        buttonDocs.clicked.connect(lambda: webbrowser.open("https://docs.fontra.xyz"))

        layout.addWidget(button, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(buttonDocs, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addWidget(self.label, 1, 0, 1, 2)

        layout.addWidget(QLabel(f"Fontra version {fontraVersion}"), 4, 0)

        if sys.platform in {"darwin", "win32"}:
            self.downloadButton = QPushButton("Download latest Fontra Pak", self)
            self.downloadButton.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            self.downloadButton.clicked.connect(self.goToLatestDownload)
            layout.addWidget(
                self.downloadButton, 4, 1, alignment=Qt.AlignmentFlag.AlignRight
            )
            if "test-startup" not in sys.argv:
                self.checkForUpdate(1500)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        self.show()

    def closeEvent(self, event):
        if self.openProjects:
            response = showMessageDialog(
                "There are still open fonts, are you sure you want to quit?",
                "Quitting Fontra Pak will cause open browser tabs to stop working.",
                buttons=QMessageBox.StandardButton.Close
                | QMessageBox.StandardButton.Cancel,
                defaultButton=QMessageBox.StandardButton.Cancel,
            )
            if response == QMessageBox.StandardButton.Cancel:
                event.ignore()

        self.settings.setValue("size", self.size())
        self.settings.setValue("pos", self.pos())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            self.label.setStyleSheet(droppingCSS)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.label.setStyleSheet("background-color: lightgray;")
        self.label.setStyleSheet(neutralCSS)

    def dropEvent(self, event):
        self.label.setStyleSheet(neutralCSS)
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for path in files:
            openFile(path, self.port)
        event.acceptProposedAction()

    @property
    def activeFolder(self):
        activeFolder = self.settings.value("activeFolder", os.path.expanduser("~"))
        if not os.path.isdir(activeFolder):
            activeFolder = os.path.expanduser("~")
        return activeFolder

    def newFont(self):
        fontPath, fileType = QFileDialog.getSaveFileName(
            self,
            "New Font...",
            os.path.join(self.activeFolder, "Untitled"),
            ";;".join(fileTypesMapping),
        )

        if not fontPath:
            return

        fontPath = getFontPath(fontPath, fileType, fileTypesMapping)

        self.settings.setValue("activeFolder", os.path.dirname(fontPath))

        try:
            asyncio.run(createNewFont(fontPath))
        except Exception as e:
            showMessageDialog("The new font could not be saved", repr(e))
            return

        if os.path.exists(fontPath):
            openFile(fontPath, self.port)

    def messageFromServer(self, item):
        action, arguments = item
        handler = getattr(self, action, None)
        if handler is not None:
            handler(*arguments)
        else:
            print("unknown server action:", action)

    def exportAs(self, path, options):
        sourcePath = pathlib.Path(path)
        fileExtension = options["format"]

        wFlags = self.windowFlags()
        self.setWindowFlags(wFlags | Qt.WindowType.WindowStaysOnTopHint)
        self.show()
        self.setWindowFlags(wFlags)
        self.show()

        destPath, fileType = QFileDialog.getSaveFileName(
            self,
            "Export font...",
            os.path.join(self.activeFolder, sourcePath.stem),
            exportExtensionMapping["." + fileExtension],
        )

        if not destPath:
            return

        destPath = getFontPath(destPath, fileType, exportFileTypesMapping)

        self.settings.setValue("activeFolder", os.path.dirname(destPath))

        destPath = pathlib.Path(destPath)

        if sourcePath == destPath:
            showMessageDialog(
                "Cannot export font",
                "The destination file cannot be the same as the source file",
            )
            return

        self.doExportAs(sourcePath, destPath, fileExtension)

    def doExportAs(self, sourcePath, destPath, fileExtension):
        logFilePath = tempfile.NamedTemporaryFile().name

        exportProcess = multiprocessing.Process(
            target=exportFontToPath,
            args=(sourcePath, destPath, fileExtension, logFilePath),
        )

        cancelled = False

        def cancelExport():
            nonlocal cancelled
            cancelled = True
            os.kill(exportProcess.pid, signal.SIGINT)

        progressDialog = QProgressDialog(
            f"Exporting \u201c{os.path.basename(destPath)}\u201d", "Cancel", 0, 0
        )
        progressCancelButton = QPushButton("Cancel")
        progressCancelButton.clicked.connect(cancelExport)

        progressDialog.setCancelButton(progressCancelButton)
        progressDialog.setWindowTitle(f"Export as {fileExtension}")
        progressDialog.show()

        exportProcess.start()

        def exportFinished():
            if cancelled:
                return

            progressDialog.cancel()

            try:
                if exportProcess.exitcode:
                    with open(logFilePath, encoding="utf-8") as logFile:
                        logFile.seek(0)
                        logData = logFile.read()
                        logLines = logData.splitlines()
                        infoText = (
                            logLines[-1] if logLines else "The reason is not clear."
                        )
                        showMessageDialog(
                            "The font could not be exported",
                            infoText,
                            detailedText=logData,
                        )
            finally:
                os.unlink(logFilePath)

        def exportProcessJoin():
            exportProcess.join()
            callInMainThread(exportFinished)

        callInNewThread(exportProcessJoin)

    def projectOpened(self, projectIdentifier):
        self.openProjects.add(projectIdentifier)

    def projectClosed(self, projectIdentifier):
        self.openProjects.discard(projectIdentifier)

    def checkForUpdate(self, msDelay):
        QTimer.singleShot(msDelay, lambda: callInNewThread(self._checkForUpdate))

    def _checkForUpdate(self):
        if "dev" in fontraVersion:
            return

        print(f"Checking for update on {datetime.now()}")

        latestVersion, downloadURL = fetchLatestReleaseInfo()

        if downloadURL is not None and latestVersion != fontraVersion:
            callInMainThread(
                self.downloadButton.setText, "\u203c\ufe0f A new version is available \u203c\ufe0f"
            )
        else:
            hours = 24 + 4 * random()
            minutes = hours * 60
            seconds = minutes * 60
            msDelay = seconds * 1000
            callInMainThread(self.checkForUpdate, int(msDelay))

    def goToLatestDownload(self):
        _, downloadURL = fetchLatestReleaseInfo()

        if downloadURL is None:
            downloadURL = latestReleasePageURL

        webbrowser.open(downloadURL)
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/launcher.py
git commit -m "refactor: create fontra_pak/launcher.py"
```

### Task 9: Create app module

**Files:**
- Create: `fontra_pak/app.py`

- [ ] **Step 1: Create `fontra_pak/app.py`**

```python
# fontra_pak/app.py
import multiprocessing
import sys

import psutil
from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import QApplication

from fontra.core.server import findFreeTCPPort

from fontra_pak.ipc import callInNewThread, queueGetter
from fontra_pak.launcher import FontraMainWidget, openFile
from fontra_pak.server import runFontraServer


class FontraApplication(QApplication):
    def __init__(self, argv, port):
        self.port = port
        super().__init__(argv)

    def event(self, event):
        """Handle macOS FileOpen events."""
        if event.type() == QEvent.Type.FileOpen:
            openFile(event.file(), self.port)
        else:
            return super().event(event)

        return True


def main():
    queue = multiprocessing.Queue()
    host = "localhost"
    port = findFreeTCPPort(host=host)
    serverProcess = multiprocessing.Process(
        target=runFontraServer, args=(host, port, queue)
    )
    serverProcess.start()

    app = FontraApplication(sys.argv, port)

    def cleanup():
        queue.put(None)
        thread.join()
        process = psutil.Process(serverProcess.pid)
        for p in [process] + process.children(recursive=True):
            if sys.platform != "win32":
                p.send_signal(psutil.signal.SIGINT)
            else:
                p.terminate()

    app.aboutToQuit.connect(cleanup)

    mainWindow = FontraMainWidget(port)

    thread = callInNewThread(queueGetter, queue, mainWindow.messageFromServer)

    mainWindow.show()

    if "test-startup" in sys.argv:

        def delayedQuit():
            print("test-startup")
            app.quit()

        QTimer.singleShot(1500, delayedQuit)

    sys.exit(app.exec())
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/app.py
git commit -m "refactor: create fontra_pak/app.py"
```

### Task 10: Create `__main__.py` and verify the package works

**Files:**
- Create: `fontra_pak/__main__.py`

- [ ] **Step 1: Create `fontra_pak/__main__.py`**

```python
# fontra_pak/__main__.py
import multiprocessing

from fontra_pak.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
```

- [ ] **Step 2: Verify the package runs**

Run: `python -m fontra_pak`

Expected: The launcher window appears and behaves identically to `python FontraPakMain.py`. Drop a file — it opens in the browser (same as before). Close the window — it quits cleanly.

- [ ] **Step 3: Commit**

```bash
git add fontra_pak/__main__.py
git commit -m "refactor: create fontra_pak/__main__.py, verify package runs"
```

### Task 11: Replace `FontraPakMain.py` with a redirect

**Files:**
- Modify: `FontraPakMain.py`

Now that the package works, replace the original 668-line file with a 5-line redirect.

- [ ] **Step 1: Replace the entire contents of `FontraPakMain.py`**

Delete everything in `FontraPakMain.py` and replace with:

```python
# Legacy entry point — delegates to fontra_pak package.
# Kept for PyInstaller compatibility during transition.
import multiprocessing

from fontra_pak.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
```

- [ ] **Step 2: Verify the redirect works**

Run: `python FontraPakMain.py`

Expected: Identical behavior to `python -m fontra_pak`.

- [ ] **Step 3: Commit**

```bash
git add FontraPakMain.py
git commit -m "refactor: replace FontraPakMain.py with redirect to fontra_pak package"
```

### Task 12: Verify PyInstaller build

**Files:**
- No changes needed — `FontraPak.spec` already points at `FontraPakMain.py` which now imports from the package.

- [ ] **Step 1: Run the PyInstaller build**

Run: `pyinstaller FontraPak.spec -y`

Expected: Build completes without errors.

- [ ] **Step 2: Run existing tests**

Run: `pytest tests/ -v`

Expected: `test_fontra_client_bundling` passes. `test_startup` passes if a dist build exists on the current platform, otherwise it skips.

- [ ] **Step 3: Commit (only if FontraPak.spec needed changes)**

If the build failed and you had to fix `FontraPak.spec`, commit the fix:

```bash
git add FontraPak.spec
git commit -m "fix: update PyInstaller spec for package extraction"
```

If the build passed with no changes, skip this commit.

---

## Phase 1: Embedded Single Project Window

### Task 13: Add PyQt6-WebEngine to requirements

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add `PyQt6-WebEngine` to `requirements.txt`**

Add this line immediately after the `PyQt6-sip==13.10.2` line:

```
PyQt6-WebEngine==6.7.0
```

- [ ] **Step 2: Install the dependency**

Run: `pip install PyQt6-WebEngine==6.7.0`

- [ ] **Step 3: Verify the import works**

Run: `python -c "from PyQt6.QtWebEngineWidgets import QWebEngineView; print('OK')"`

Expected: prints `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat: add PyQt6-WebEngine dependency"
```

### Task 14: Update PyInstaller spec for QtWebEngine

**Files:**
- Modify: `FontraPak.spec`

- [ ] **Step 1: Add QtWebEngine modules to collection list**

In `FontraPak.spec`, find this block (lines 61-69):

```python
modules_to_collect_all = [
    "fontra",
    "fontra_compile",
    "fontra_glyphs",
    "fontra_rcjk",
    "cffsubr",
    "openstep_plist",
    "glyphsLib.data",
]
```

Replace it with:

```python
modules_to_collect_all = [
    "fontra",
    "fontra_compile",
    "fontra_glyphs",
    "fontra_rcjk",
    "cffsubr",
    "openstep_plist",
    "glyphsLib.data",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
]
```

- [ ] **Step 2: Commit**

```bash
git add FontraPak.spec
git commit -m "feat: collect QtWebEngine modules in PyInstaller spec"
```

### Task 15: Implement project identity contract

**Files:**
- Create: `tests/test_project_identity.py`
- Create: `fontra_pak/project_identity.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_project_identity.py
import os
import pathlib
import sys

import pytest

from fontra_pak.project_identity import (
    canonical_callback_project_key,
    decode_project_query_value,
    encode_project_query_value,
    path_to_project_key,
    project_key_to_profile_dir_name,
    resolve_project_path,
)


def test_path_to_project_key_resolves_and_normcases():
    path = pathlib.Path(__file__).resolve()
    key = path_to_project_key(str(path))
    assert key == os.path.normcase(str(path))


def test_resolve_project_path_returns_absolute_path():
    resolved = resolve_project_path(".")
    assert pathlib.Path(resolved).is_absolute()


def test_path_to_project_key_different_case_same_key():
    if sys.platform != "win32":
        pytest.skip("Case-insensitive paths only on Windows")
    key1 = path_to_project_key("C:\\Fonts\\Demo.ufo")
    key2 = path_to_project_key("c:\\fonts\\demo.ufo")
    assert key1 == key2


def test_encode_project_query_value_matches_current_windows_wire_format():
    if sys.platform != "win32":
        pytest.skip("Drive letter test only on Windows")
    value = encode_project_query_value("C:\\Fonts\\Demo Font.ufo")
    assert value == "C%3A%5C/Fonts/Demo%20Font.ufo"


def test_decode_project_query_value_round_trips_windows_drive_path():
    if sys.platform != "win32":
        pytest.skip("Drive letter test only on Windows")
    decoded = decode_project_query_value("C%3A%5C/Fonts/Demo%20Font.ufo")
    assert decoded == resolve_project_path("C:\\Fonts\\Demo Font.ufo")


def test_encode_and_decode_project_query_value_round_trip_posix_absolute_path():
    if sys.platform == "win32":
        pytest.skip("Unix path test only on Unix")
    path = "/home/user/My Font.ufo"
    encoded = encode_project_query_value(path)
    assert encoded == "home/user/My%20Font.ufo"
    assert decode_project_query_value(encoded) == resolve_project_path(path)


def test_canonical_callback_project_key_uses_shared_contract():
    path = str(pathlib.Path(__file__).resolve())
    assert canonical_callback_project_key(path) == path_to_project_key(path)


def test_profile_dir_name_is_hex_hash():
    name = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    assert all(c in "0123456789abcdef" for c in name)
    assert len(name) == 16


def test_profile_dir_name_is_stable():
    name1 = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    name2 = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    assert name1 == name2


def test_profile_dir_name_differs_per_project():
    name1 = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    name2 = project_key_to_profile_dir_name("c:\\fonts\\other.ufo")
    assert name1 != name2
```

- [ ] **Step 2: Run tests — they should fail**

Run: `pytest tests/test_project_identity.py -v`

Expected: `ModuleNotFoundError: No module named 'fontra_pak.project_identity'`

- [ ] **Step 3: Create `fontra_pak/project_identity.py`**

```python
# fontra_pak/project_identity.py
import hashlib
import os
import pathlib
from urllib.parse import quote, unquote


def resolve_project_path(path: str) -> str:
    return str(pathlib.Path(path).resolve())


def path_to_project_key(path: str) -> str:
    return os.path.normcase(resolve_project_path(path))


def encode_project_query_value(path: str) -> str:
    path_obj = pathlib.Path(resolve_project_path(path))
    assert path_obj.is_absolute()
    parts = list(path_obj.parts)
    if not path_obj.drive:
        assert parts[0] == os.sep
        del parts[0]
    return "/".join(quote(part, safe="") for part in parts)


def decode_project_query_value(project_query_value: str) -> str:
    decoded_parts = [unquote(part) for part in project_query_value.split("/") if part]
    if not decoded_parts:
        raise ValueError("Missing project path parts")

    first_part = decoded_parts[0]
    if first_part.endswith("\\") or first_part.endswith("/") or (
        len(first_part) >= 2 and first_part[1] == ":"
    ):
        reconstructed = pathlib.Path(first_part, *decoded_parts[1:])
    else:
        reconstructed = pathlib.Path(os.sep, *decoded_parts)

    return resolve_project_path(str(reconstructed))


def canonical_callback_project_key(project_identifier: str) -> str:
    return path_to_project_key(project_identifier)


def project_key_to_profile_dir_name(project_key: str) -> str:
    return hashlib.sha256(project_key.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run tests — they should pass**

Run: `pytest tests/test_project_identity.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/project_identity.py tests/test_project_identity.py
git commit -m "feat: implement project identity contract"
```

### Task 16: Implement ViewDescriptor

**Files:**
- Create: `tests/test_view_descriptor.py`
- Create: `fontra_pak/view_descriptor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_view_descriptor.py
from fontra_pak.view_descriptor import ViewDescriptor, default_overview_descriptor


def test_overview_fields():
    d = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    assert d.project_key == "c:\\fonts\\demo.ufo"
    assert d.view_kind == "overview"
    assert d.page_path == "/fontoverview.html"
    assert d.route_hash == ""
    assert d.title_hint == "Overview"


def test_editor_fields():
    d = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    assert d.view_kind == "editor"
    assert d.page_path == "/editor.html"
    assert d.route_hash == "#glyph=A"
    assert d.title_hint == "Editor"


def test_fontinfo_fields():
    d = ViewDescriptor.for_fontinfo("c:\\fonts\\demo.ufo", route_hash="#axes-panel")
    assert d.view_kind == "fontinfo"
    assert d.page_path == "/fontinfo.html"
    assert d.title_hint == "Font Info"


def test_applicationsettings_fields():
    d = ViewDescriptor.for_applicationsettings("c:\\fonts\\demo.ufo")
    assert d.view_kind == "applicationsettings"
    assert d.page_path == "/applicationsettings.html"
    assert d.title_hint == "Application Settings"


def test_build_url_with_hash():
    d = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    url = d.build_url("localhost", 8080, "C%3A%5C/Fonts/Demo.ufo")
    assert url == "http://localhost:8080/editor.html?project=C%3A%5C/Fonts/Demo.ufo#glyph=A"


def test_build_url_without_hash():
    d = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    url = d.build_url("localhost", 8080, "C%3A%5C/Fonts/Demo.ufo")
    assert url == "http://localhost:8080/fontoverview.html?project=C%3A%5C/Fonts/Demo.ufo"


def test_matches_same_kind_same_project():
    d1 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    d2 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    assert d1.matches(d2)


def test_no_match_different_kind():
    d1 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    d2 = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo")
    assert not d1.matches(d2)


def test_no_match_different_project():
    d1 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    d2 = ViewDescriptor.for_overview("c:\\fonts\\other.ufo")
    assert not d1.matches(d2)


def test_matches_different_editor_hashes_do_not_match():
    d1 = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    d2 = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=B")
    assert not d1.matches(d2)


def test_from_page_path_known():
    d = ViewDescriptor.from_page_path("key", "/editor.html", "#hash")
    assert d is not None
    assert d.view_kind == "editor"


def test_from_page_path_unknown_returns_none():
    d = ViewDescriptor.from_page_path("key", "/landing.html")
    assert d is None


def test_to_dict_round_trip():
    original = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    restored = ViewDescriptor.from_dict(original.to_dict())
    assert original.project_key == restored.project_key
    assert original.view_kind == restored.view_kind
    assert original.page_path == restored.page_path
    assert original.route_hash == restored.route_hash
    assert original.title_hint == restored.title_hint


def test_default_overview_descriptor():
    descriptor = default_overview_descriptor("demo-key")
    assert descriptor == ViewDescriptor.for_overview("demo-key")
```

- [ ] **Step 2: Run tests — they should fail**

Run: `pytest tests/test_view_descriptor.py -v`

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `fontra_pak/view_descriptor.py`**

```python
# fontra_pak/view_descriptor.py
from __future__ import annotations

from dataclasses import dataclass

PAGE_PATH_TO_VIEW_KIND = {
    "/fontoverview.html": "overview",
    "/editor.html": "editor",
    "/fontinfo.html": "fontinfo",
    "/applicationsettings.html": "applicationsettings",
}

VIEW_KIND_TO_PAGE_PATH = {v: k for k, v in PAGE_PATH_TO_VIEW_KIND.items()}

KNOWN_PAGE_PATHS = frozenset(PAGE_PATH_TO_VIEW_KIND.keys())

VIEW_KIND_TITLE_HINTS = {
    "overview": "Overview",
    "editor": "Editor",
    "fontinfo": "Font Info",
    "applicationsettings": "Application Settings",
}


@dataclass
class ViewDescriptor:
    project_key: str
    view_kind: str
    page_path: str
    route_hash: str
    title_hint: str

    @classmethod
    def for_overview(cls, project_key: str, route_hash: str = "") -> ViewDescriptor:
        return cls(project_key=project_key, view_kind="overview",
                   page_path="/fontoverview.html", route_hash=route_hash,
                   title_hint="Overview")

    @classmethod
    def for_editor(cls, project_key: str, route_hash: str = "") -> ViewDescriptor:
        return cls(project_key=project_key, view_kind="editor",
                   page_path="/editor.html", route_hash=route_hash,
                   title_hint="Editor")

    @classmethod
    def for_fontinfo(cls, project_key: str, route_hash: str = "") -> ViewDescriptor:
        return cls(project_key=project_key, view_kind="fontinfo",
                   page_path="/fontinfo.html", route_hash=route_hash,
                   title_hint="Font Info")

    @classmethod
    def for_applicationsettings(cls, project_key: str, route_hash: str = "") -> ViewDescriptor:
        return cls(project_key=project_key, view_kind="applicationsettings",
                   page_path="/applicationsettings.html", route_hash=route_hash,
                   title_hint="Application Settings")

    @classmethod
    def from_page_path(cls, project_key: str, page_path: str, route_hash: str = "") -> ViewDescriptor | None:
        view_kind = PAGE_PATH_TO_VIEW_KIND.get(page_path)
        if view_kind is None:
            return None
        return cls(project_key=project_key, view_kind=view_kind,
                   page_path=page_path, route_hash=route_hash,
                   title_hint=VIEW_KIND_TITLE_HINTS[view_kind])

    def build_url(self, host: str, port: int, project_query_value: str) -> str:
        url = f"http://{host}:{port}{self.page_path}?project={project_query_value}"
        if self.route_hash:
            url += self.route_hash
        return url

    def route_identity(self) -> tuple[str, str, str]:
        return (self.project_key, self.page_path, self.route_hash)

    def matches(self, other: ViewDescriptor) -> bool:
        return self.route_identity() == other.route_identity()

    def to_dict(self) -> dict:
        return {"project_key": self.project_key, "view_kind": self.view_kind,
                "page_path": self.page_path, "route_hash": self.route_hash,
                "title_hint": self.title_hint}

    @classmethod
    def from_dict(cls, data: dict) -> ViewDescriptor:
        return cls(project_key=data["project_key"], view_kind=data["view_kind"],
                   page_path=data["page_path"], route_hash=data["route_hash"],
                   title_hint=data["title_hint"])


def default_overview_descriptor(project_key: str) -> ViewDescriptor:
    return ViewDescriptor.for_overview(project_key)
```

- [ ] **Step 4: Run tests — they should pass**

Run: `pytest tests/test_view_descriptor.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/view_descriptor.py tests/test_view_descriptor.py
git commit -m "feat: implement ViewDescriptor"
```

### Task 17: Implement URL routing classification

**Files:**
- Create: `tests/test_routing.py`
- Create: `fontra_pak/routing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_routing.py
import sys

import pytest

from fontra_pak.project_identity import encode_project_query_value
from fontra_pak.routing import RouteClass, classify_url


def test_internal_fontoverview():
    encoded = encode_project_query_value("C:\\Fonts\\Demo.ufo") if sys.platform == "win32" else encode_project_query_value("/tmp/demo.ufo")
    owner_key = "c:\\fonts\\demo.ufo" if sys.platform == "win32" else "/tmp/demo.ufo"
    result = classify_url(
        f"http://localhost:8080/fontoverview.html?project={encoded}",
        host="localhost", port=8080,
        owner_project_key=owner_key,
    )
    assert result.route_class == RouteClass.INTERNAL
    assert result.page_path == "/fontoverview.html"
    assert result.route_hash == ""


def test_internal_editor_with_existing_windows_wire_format():
    if sys.platform != "win32":
        pytest.skip("Windows wire-format lock only on Windows")
    result = classify_url(
        "http://localhost:8080/editor.html?project=C%3A%5C/Fonts/Demo.ufo#glyph=A",
        host="localhost", port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.INTERNAL
    assert result.page_path == "/editor.html"
    assert result.route_hash == "#glyph=A"


def test_external_https():
    result = classify_url(
        "https://fontra.xyz/",
        host="localhost", port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.EXTERNAL


def test_external_different_host():
    result = classify_url(
        "http://example.com/editor.html?project=foo",
        host="localhost", port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.EXTERNAL


def test_rejected_unsupported_page():
    result = classify_url(
        "http://localhost:8080/landing.html",
        host="localhost", port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.REJECTED


def test_rejected_missing_project_param():
    result = classify_url(
        "http://localhost:8080/editor.html",
        host="localhost", port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.REJECTED


def test_rejected_different_project():
    other = encode_project_query_value("C:\\Fonts\\Other.ufo") if sys.platform == "win32" else encode_project_query_value("/tmp/other.ufo")
    owner_key = "c:\\fonts\\demo.ufo" if sys.platform == "win32" else "/tmp/demo.ufo"
    result = classify_url(
        f"http://localhost:8080/editor.html?project={other}",
        host="localhost", port=8080,
        owner_project_key=owner_key,
    )
    assert result.route_class == RouteClass.REJECTED


def test_rejected_unknown_same_origin_path():
    encoded = encode_project_query_value("C:\\Fonts\\Demo.ufo") if sys.platform == "win32" else encode_project_query_value("/tmp/demo.ufo")
    owner_key = "c:\\fonts\\demo.ufo" if sys.platform == "win32" else "/tmp/demo.ufo"
    result = classify_url(
        f"http://localhost:8080/somethingelse.html?project={encoded}",
        host="localhost", port=8080,
        owner_project_key=owner_key,
    )
    assert result.route_class == RouteClass.REJECTED
```

- [ ] **Step 2: Run tests — they should fail**

Run: `pytest tests/test_routing.py -v`

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `fontra_pak/routing.py`**

```python
# fontra_pak/routing.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from urllib.parse import parse_qs, urlparse

from fontra_pak.project_identity import decode_project_query_value, path_to_project_key
from fontra_pak.view_descriptor import KNOWN_PAGE_PATHS


class RouteClass(Enum):
    INTERNAL = auto()
    EXTERNAL = auto()
    REJECTED = auto()


@dataclass
class RouteResult:
    route_class: RouteClass
    page_path: str = ""
    project_key: str = ""
    route_hash: str = ""


def classify_url(
    url: str,
    *,
    host: str,
    port: int,
    owner_project_key: str,
) -> RouteResult:
    parsed = urlparse(url)

    # Non-local origin = external
    expected_netloc = f"{host}:{port}"
    if parsed.scheme not in ("http", "") or parsed.netloc != expected_netloc:
        return RouteResult(route_class=RouteClass.EXTERNAL)

    page_path = parsed.path
    if page_path not in KNOWN_PAGE_PATHS:
        return RouteResult(route_class=RouteClass.REJECTED)

    project_values = parse_qs(parsed.query).get("project")
    if not project_values:
        return RouteResult(route_class=RouteClass.REJECTED)

    try:
        decoded_path = decode_project_query_value(project_values[0])
        project_key = path_to_project_key(decoded_path)
    except Exception:
        return RouteResult(route_class=RouteClass.REJECTED)

    if project_key != owner_project_key:
        return RouteResult(route_class=RouteClass.REJECTED)

    route_hash = ""
    if parsed.fragment:
        route_hash = "#" + parsed.fragment

    return RouteResult(
        route_class=RouteClass.INTERNAL,
        page_path=page_path,
        project_key=project_key,
        route_hash=route_hash,
    )
```

- [ ] **Step 4: Run tests — they should pass**

Run: `pytest tests/test_routing.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/routing.py tests/test_routing.py
git commit -m "feat: implement URL routing classification"
```

### Task 18: Implement PaneNavigationBridge

This is the `QWebEnginePage` subclass that intercepts in-pane navigation and `window.open()` calls. It depends on `routing.py` (Task 17) and `view_descriptor.py` (Task 16). No tests — this is Qt-dependent and will be verified manually in Task 23.

**Files:**
- Create: `fontra_pak/navigation_bridge.py`

- [ ] **Step 1: Create `fontra_pak/navigation_bridge.py`**

```python
# fontra_pak/navigation_bridge.py
from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from fontra_pak.routing import RouteClass, classify_url
from fontra_pak.view_descriptor import ViewDescriptor

if TYPE_CHECKING:
    from fontra_pak.workspace_pane import WorkspacePane


class PaneNavigationBridge(QWebEnginePage):
    """Intercepts same-pane navigation. Attached to one WorkspacePane."""

    def __init__(self, profile: QWebEngineProfile, pane: WorkspacePane):
        super().__init__(profile, pane.web_view)
        self.pane = pane

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:
        if not is_main_frame:
            return True

        url_str = url.toString()
        result = classify_url(
            url_str,
            host=self.pane.host,
            port=self.pane.port,
            owner_project_key=self.pane.descriptor.project_key,
        )

        if result.route_class == RouteClass.INTERNAL:
            new_descriptor = ViewDescriptor.from_page_path(
                self.pane.descriptor.project_key,
                result.page_path,
                result.route_hash,
            )
            if new_descriptor is not None:
                self.pane.descriptor = new_descriptor
                self.pane.update_title()
            return True

        if result.route_class == RouteClass.EXTERNAL:
            webbrowser.open(url_str)
            return False

        # REJECTED — block and show error
        from fontra_pak.dialogs import showMessageDialog
        showMessageDialog(
            "Unsupported destination",
            f"This navigation target is not supported:\n{url_str}",
        )
        return False

    def createWindow(self, window_type):
        """Intercept window.open() calls. Returns a trap page that captures
        the target URL and routes it."""
        trap = _NavigationTrapPage(self.pane)
        self.pane._pending_trap = trap  # prevent garbage collection
        return trap


class _NavigationTrapPage(QWebEnginePage):
    """Temporary page returned from createWindow(). It receives the
    navigation request from window.open(), classifies the URL, and
    routes it. It never actually loads a page."""

    def __init__(self, pane: WorkspacePane):
        super().__init__(pane.page().profile(), None)
        self.pane = pane

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:
        url_str = url.toString()
        if url_str == "about:blank":
            return False

        result = classify_url(
            url_str,
            host=self.pane.host,
            port=self.pane.port,
            owner_project_key=self.pane.descriptor.project_key,
        )

        if result.route_class == RouteClass.INTERNAL:
            new_descriptor = ViewDescriptor.from_page_path(
                self.pane.descriptor.project_key,
                result.page_path,
                result.route_hash,
            )
            if new_descriptor is not None:
                self.pane.project_window.open_view(new_descriptor)
        elif result.route_class == RouteClass.EXTERNAL:
            webbrowser.open(url_str)
        else:
            from fontra_pak.dialogs import showMessageDialog
            showMessageDialog(
                "Unsupported destination",
                f"This navigation target is not supported:\n{url_str}",
            )

        self.pane._pending_trap = None  # allow garbage collection
        return False  # never load anything in this throwaway page
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/navigation_bridge.py
git commit -m "feat: implement PaneNavigationBridge"
```

### Task 19A: Revised WorkspacePane

**Files:**
- Create: `fontra_pak/workspace_pane.py`

- [ ] **Step 1: Create `fontra_pak/workspace_pane.py`**

```python
# fontra_pak/workspace_pane.py
from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QUrl
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QDockWidget, QLabel, QPushButton, QVBoxLayout, QWidget

from fontra_pak.navigation_bridge import PaneNavigationBridge
from fontra_pak.view_descriptor import ViewDescriptor

if TYPE_CHECKING:
    from fontra_pak.project_window import ProjectWindow


class WorkspacePane(QDockWidget):
    def __init__(
        self,
        descriptor: ViewDescriptor,
        profile: QWebEngineProfile,
        host: str,
        port: int,
        project_query_value: str,
        project_window: ProjectWindow,
        pane_instance_id: str | None = None,
    ):
        super().__init__(descriptor.title_hint, project_window)
        self.descriptor = descriptor
        self.host = host
        self.port = port
        self.project_query_value = project_query_value
        self.project_window = project_window
        self.pane_instance_id = pane_instance_id or secrets.token_hex(8)
        self._pending_trap = None

        self.web_view = QWebEngineView()
        page = PaneNavigationBridge(profile, self)
        self.web_view.setPage(page)

        page.titleChanged.connect(self._on_title_changed)
        page.renderProcessTerminated.connect(self._on_render_crash)
        self.web_view.installEventFilter(self)

        self.setWidget(self.web_view)
        self.reload_from_descriptor()

    def page(self) -> PaneNavigationBridge:
        return self.web_view.page()

    def eventFilter(self, watched, event):
        if watched is self.web_view and event.type() in {
            QEvent.Type.FocusIn,
            QEvent.Type.MouseButtonPress,
        }:
            self.project_window.note_pane_activated(self)
        return super().eventFilter(watched, event)

    def focusInEvent(self, event):
        self.project_window.note_pane_activated(self)
        super().focusInEvent(event)

    def apply_descriptor(self, descriptor: ViewDescriptor):
        self.descriptor = descriptor
        self.update_title()

    def update_title(self):
        self.setWindowTitle(self.descriptor.title_hint)

    def _on_title_changed(self, title: str):
        if title and self.descriptor.view_kind == "editor":
            self.descriptor.title_hint = title
            self.setWindowTitle(title)

    def _on_render_crash(self, termination_status, exit_code):
        self._show_error_overlay(
            f"The renderer process terminated (status={termination_status}, code={exit_code})."
        )

    def _show_error_overlay(self, message: str):
        error_widget = QWidget()
        layout = QVBoxLayout(error_widget)
        layout.addWidget(QLabel(message))

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._reload_pane)
        layout.addWidget(reload_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(lambda: self.project_window.close_pane(self))
        layout.addWidget(close_btn)

        self.setWidget(error_widget)

    def reload_from_descriptor(self):
        self.setWidget(self.web_view)
        url = self.descriptor.build_url(self.host, self.port, self.project_query_value)
        self.web_view.setUrl(QUrl(url))

    def _reload_pane(self):
        self.reload_from_descriptor()

    def load_failed(self) -> bool:
        return self.widget() is not self.web_view
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/workspace_pane.py
git commit -m "feat: implement WorkspacePane"
```

### Task 20A: Revised ProjectWindow

**Files:**
- Create: `fontra_pak/project_window.py`

- [ ] **Step 1: Create `fontra_pak/project_window.py`**

```python
# fontra_pak/project_window.py
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from fontra_pak.dialogs import showMessageDialog
from fontra_pak.project_identity import encode_project_query_value
from fontra_pak.view_descriptor import ViewDescriptor, default_overview_descriptor
from fontra_pak.workspace_pane import WorkspacePane

if TYPE_CHECKING:
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from fontra_pak.controller import AppWorkspaceController

logger = logging.getLogger(__name__)


class ProjectWindow(QMainWindow):
    def __init__(
        self,
        project_key: str,
        project_path: str,
        profile: QWebEngineProfile,
        host: str,
        port: int,
        controller: AppWorkspaceController,
    ):
        super().__init__()
        self.project_key = project_key
        self.project_path = project_path
        self.profile = profile
        self.host = host
        self.port = port
        self.controller = controller
        self.project_query_value = encode_project_query_value(project_path)
        self.panes: list[WorkspacePane] = []
        self._active_pane: WorkspacePane | None = None
        self._pane_focus_order: dict[str, int] = {}
        self._focus_generation = 0
        self._suppress_close_confirm = False

        self.setWindowTitle(f"Fontra Pak - {project_path}")
        self.setDockNestingEnabled(True)
        self.profile.downloadRequested.connect(self._on_download_requested)
        self._setup_menu_bar()

    def _setup_menu_bar(self):
        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(
            "Font Overview",
            lambda: self.open_view(ViewDescriptor.for_overview(self.project_key)),
        )
        view_menu.addAction(
            "Font Info",
            lambda: self.open_view(ViewDescriptor.for_fontinfo(self.project_key)),
        )
        view_menu.addAction(
            "Application Settings",
            lambda: self.open_view(ViewDescriptor.for_applicationsettings(self.project_key)),
        )

    def open_initial_pane(self):
        self.open_view(default_overview_descriptor(self.project_key))

    def open_view(self, descriptor: ViewDescriptor, pane_instance_id: str | None = None):
        if pane_instance_id is None:
            pane = self._find_matching_pane(descriptor)
            if pane is not None:
                self.note_pane_activated(pane)
                pane.raise_()
                pane.setFocus()
                return pane

        return self._create_pane(descriptor, pane_instance_id=pane_instance_id)

    def _find_matching_pane(self, descriptor: ViewDescriptor) -> WorkspacePane | None:
        matching = [pane for pane in self.panes if pane.descriptor.matches(descriptor)]
        if not matching:
            return None
        return max(
            matching,
            key=lambda pane: self._pane_focus_order.get(pane.pane_instance_id, 0),
        )

    def note_pane_activated(self, pane: WorkspacePane):
        self._focus_generation += 1
        self._pane_focus_order[pane.pane_instance_id] = self._focus_generation
        self._active_pane = pane

    def _create_pane(self, descriptor: ViewDescriptor, pane_instance_id: str | None = None):
        pane = WorkspacePane(
            descriptor=descriptor,
            profile=self.profile,
            host=self.host,
            port=self.port,
            project_query_value=self.project_query_value,
            project_window=self,
            pane_instance_id=pane_instance_id,
        )
        pane.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        if self.panes:
            self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, pane)
            self.tabifyDockWidget(self.panes[-1], pane)
        else:
            self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, pane)

        self.panes.append(pane)
        self.note_pane_activated(pane)
        pane.raise_()
        pane.setFocus()
        return pane

    def focus_pane_instance(self, pane_instance_id: str) -> bool:
        for pane in self.panes:
            if pane.pane_instance_id == pane_instance_id:
                self.note_pane_activated(pane)
                pane.raise_()
                pane.setFocus()
                return True
        return False

    def close_pane(self, pane: WorkspacePane):
        was_error_pane = pane.load_failed()
        if pane in self.panes:
            self.panes.remove(pane)
        self._pane_focus_order.pop(pane.pane_instance_id, None)
        self.removeDockWidget(pane)
        pane.deleteLater()

        if self._active_pane is pane:
            self._active_pane = None
            if self.panes:
                next_pane = max(
                    self.panes,
                    key=lambda item: self._pane_focus_order.get(item.pane_instance_id, 0),
                )
                self.note_pane_activated(next_pane)
                next_pane.raise_()
                next_pane.setFocus()

        if not self.panes:
            if was_error_pane:
                self.close()
            else:
                self.open_initial_pane()

    def _on_download_requested(self, download):
        suggested_path = os.path.join(
            os.path.expanduser("~"),
            download.downloadFileName(),
        )
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save download",
            suggested_path,
        )
        if save_path:
            download.setDownloadDirectory(os.path.dirname(save_path))
            download.setDownloadFileName(os.path.basename(save_path))
            download.accept()
        else:
            download.cancel()

    def closeEvent(self, event):
        if self._suppress_close_confirm:
            event.accept()
            self.controller.unregister_project_window(self)
            return

        if self.project_key in self.controller.open_projects:
            response = showMessageDialog(
                "Close project?",
                f"The project {self.project_path} is still open in Fontra.\n"
                "Closing this window will disconnect from the project.",
                buttons=QMessageBox.StandardButton.Close | QMessageBox.StandardButton.Cancel,
                defaultButton=QMessageBox.StandardButton.Cancel,
            )
            if response == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        event.accept()
        self.controller.mark_project_locally_closed(self.project_key)
        self.controller.unregister_project_window(self)

    def suppress_close_confirm(self):
        self._suppress_close_confirm = True

    @property
    def active_pane_instance_id(self) -> str | None:
        if self._active_pane is not None:
            return self._active_pane.pane_instance_id
        return None

    def show_connection_lost(self):
        for pane in list(self.panes):
            pane._show_error_overlay(
                "Connection to the Fontra server has been lost.\n"
                "You can try reloading after recovering the server, or close this window."
            )
```

- [ ] **Step 2: Verify pane identity, activation, and download ownership**

Run: `python -m fontra_pak`

Manual checks:
1. Open one project and create two editor panes that land on different glyph hashes. They should remain as two separate panes.
2. Trigger the same glyph route again from Fontra. The already-focused matching pane should be reused instead of opening a duplicate.
3. Switch focus between tabs, close the currently focused pane, and verify the most recently focused remaining pane becomes active.
4. Open several panes and trigger one download. Only one native save dialog should appear.

- [ ] **Step 3: Commit**

```bash
git add fontra_pak/project_window.py
git commit -m "feat: implement ProjectWindow"
```

### Task 21A: Revised AppWorkspaceController

**Files:**
- Create: `fontra_pak/controller.py`
- Create: `tests/test_controller_callbacks.py`

- [ ] **Step 1: Write failing tests for callback routing**

These tests instantiate the controller with fake profile/window factories so they exercise real controller methods instead of logic sketches.

```python
# tests/test_controller_callbacks.py
from fontra_pak.controller import AppWorkspaceController
from fontra_pak.project_identity import path_to_project_key
from fontra_pak.view_descriptor import default_overview_descriptor


class FakeWindow:
    def __init__(self, **kwargs):
        self.project_key = kwargs["project_key"]
        self.project_path = kwargs["project_path"]
        self.profile = kwargs["profile"]
        self.opened_descriptors = []
        self.raised = False
        self.activated = False
        self.connection_lost = False
        self.closed = False

    def show(self):
        pass

    def open_view(self, descriptor, pane_instance_id=None):
        self.opened_descriptors.append((descriptor, pane_instance_id))

    def raise_(self):
        self.raised = True

    def activateWindow(self):
        self.activated = True

    def suppress_close_confirm(self):
        pass

    def close(self):
        self.closed = True

    def show_connection_lost(self):
        self.connection_lost = True


def make_controller():
    created_windows = []

    def fake_window_cls(**kwargs):
        window = FakeWindow(**kwargs)
        created_windows.append(window)
        return window

    controller = AppWorkspaceController(
        "localhost",
        8080,
        project_window_cls=fake_window_cls,
        profile_factory=lambda _project_key: object(),
    )
    return controller, created_windows


def test_open_project_creates_window_and_opens_default_overview(tmp_path):
    controller, created_windows = make_controller()
    project_path = str(tmp_path / "Demo.ufo")

    controller.open_project(project_path)

    assert len(created_windows) == 1
    project_key = path_to_project_key(project_path)
    assert created_windows[0].project_key == project_key
    assert created_windows[0].opened_descriptors == [
        (default_overview_descriptor(project_key), None)
    ]


def test_open_project_reuses_existing_window(tmp_path):
    controller, created_windows = make_controller()
    project_path = str(tmp_path / "Demo.ufo")

    controller.open_project(project_path)
    controller.open_project(project_path)

    assert len(created_windows) == 1
    assert created_windows[0].raised
    assert created_windows[0].activated
    assert len(created_windows[0].opened_descriptors) == 1


def test_project_opened_callback_canonicalizes_identifier(tmp_path):
    controller, _created_windows = make_controller()
    project_path = str(tmp_path / "Demo.ufo")

    controller.handle_server_message(("projectOpened", (project_path,)))

    assert path_to_project_key(project_path) in controller.open_projects


def test_recently_closed_suppresses_late_project_closed(tmp_path):
    controller, _created_windows = make_controller()
    project_path = str(tmp_path / "Demo.ufo")
    project_key = path_to_project_key(project_path)
    controller.open_projects.add(project_key)
    controller._recently_closed.add(project_key)

    controller.handle_server_message(("projectClosed", (project_path,)))

    assert project_key in controller.open_projects
    assert project_key not in controller._recently_closed


def test_export_callback_receives_canonical_key(tmp_path):
    controller, _created_windows = make_controller()
    project_path = str(tmp_path / "Demo.ufo")
    calls = []
    controller.set_export_callback(lambda project_key, options: calls.append((project_key, options)))

    controller.handle_server_message(("exportAs", (project_path, {"format": "otf"})))

    assert calls == [(path_to_project_key(project_path), {"format": "otf"})]
```

- [ ] **Step 2: Run tests - they should fail**

Run: `pytest tests/test_controller_callbacks.py -v`

Expected: `ModuleNotFoundError: No module named 'fontra_pak.controller'`

- [ ] **Step 3: Create `fontra_pak/controller.py`**

```python
# fontra_pak/controller.py
from __future__ import annotations

import logging
import os

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWebEngineCore import QWebEngineProfile

from fontra_pak.dialogs import showMessageDialog
from fontra_pak.project_identity import (
    canonical_callback_project_key,
    path_to_project_key,
    project_key_to_profile_dir_name,
    resolve_project_path,
)
from fontra_pak.project_window import ProjectWindow
from fontra_pak.view_descriptor import ViewDescriptor, default_overview_descriptor

logger = logging.getLogger(__name__)


class AppWorkspaceController:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        project_window_cls=ProjectWindow,
        profile_factory=None,
    ):
        self.host = host
        self.port = port
        self.project_windows: dict[str, ProjectWindow] = {}
        self.open_projects: set[str] = set()
        self._recently_closed: set[str] = set()
        self._export_callback = None
        self._project_window_cls = project_window_cls
        self._profile_factory = profile_factory

    def get_or_create_project_window(self, path: str):
        resolved_path = resolve_project_path(path)
        project_key = path_to_project_key(resolved_path)

        if project_key in self.project_windows:
            window = self.project_windows[project_key]
            window.raise_()
            window.activateWindow()
            return window, False

        profile = self._create_profile(project_key)
        if profile is None:
            showMessageDialog(
                "Could not open project",
                f"Failed to initialize web profile for:\n{resolved_path}",
            )
            return None, False

        window = self._project_window_cls(
            project_key=project_key,
            project_path=resolved_path,
            profile=profile,
            host=self.host,
            port=self.port,
            controller=self,
        )
        self.project_windows[project_key] = window
        window.show()
        return window, True

    def open_project(self, path: str, descriptor: ViewDescriptor | None = None):
        window, created = self.get_or_create_project_window(path)
        if window is None:
            return None

        if descriptor is not None:
            window.open_view(descriptor)
        elif created:
            window.open_view(default_overview_descriptor(window.project_key))
        return window

    def unregister_project_window(self, window: ProjectWindow):
        self.project_windows.pop(window.project_key, None)

    def mark_project_locally_closed(self, project_key: str):
        self.open_projects.discard(project_key)
        self._recently_closed.add(project_key)

    # --- Server callback routing ---

    def handle_server_message(self, item):
        action, arguments = item
        handler = getattr(self, f"_on_{action}", None)
        if handler is not None:
            handler(*arguments)
        else:
            logger.warning("Unknown server action: %s", action)

    def _on_projectOpened(self, project_identifier: str):
        project_key = self._canonicalize(project_identifier)
        if project_key is not None:
            self.open_projects.add(project_key)

    def _on_projectClosed(self, project_identifier: str):
        project_key = self._canonicalize(project_identifier)
        if project_key is None:
            return
        if project_key in self._recently_closed:
            self._recently_closed.discard(project_key)
        else:
            self.open_projects.discard(project_key)

    def _on_exportAs(self, project_identifier: str, options: dict):
        project_key = self._canonicalize(project_identifier)
        if project_key is None:
            return
        if self._export_callback is not None:
            self._export_callback(project_key, options)

    def set_export_callback(self, callback):
        self._export_callback = callback

    def _canonicalize(self, project_identifier: str) -> str | None:
        try:
            return canonical_callback_project_key(project_identifier)
        except Exception:
            logger.warning("Failed to canonicalize: %s", project_identifier)
            return None

    # --- Profile management ---

    def _create_profile(self, project_key: str) -> QWebEngineProfile | None:
        try:
            if self._profile_factory is not None:
                return self._profile_factory(project_key)

            dir_name = project_key_to_profile_dir_name(project_key)
            app_data = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            profile_path = os.path.join(app_data, "webprofiles", dir_name)
            os.makedirs(profile_path, exist_ok=True)
            profile = QWebEngineProfile(dir_name, None)
            profile.setPersistentStoragePath(profile_path)
            profile.setCachePath(os.path.join(profile_path, "cache"))
            return profile
        except Exception:
            logger.exception("Failed to create web profile for %s", project_key)
            return None

    # --- Quit handling ---

    def has_project_windows(self) -> bool:
        return bool(self.project_windows)

    def has_open_projects(self) -> bool:
        return bool(self.open_projects)

    def begin_bulk_shutdown(self):
        for window in list(self.project_windows.values()):
            window.suppress_close_confirm()

    def close_all_project_windows(self):
        for window in list(self.project_windows.values()):
            window.close()

    def notify_server_lost(self):
        for window in self.project_windows.values():
            window.show_connection_lost()
```

- [ ] **Step 4: Run tests - they should pass**

Run: `pytest tests/test_controller_callbacks.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/controller.py tests/test_controller_callbacks.py
git commit -m "feat: implement AppWorkspaceController"
```

### Task 22A: Revised Launcher Integration

**Files:**
- Modify: `fontra_pak/launcher.py`

This task makes four specific edits to `launcher.py`. Each edit is described as an exact string replacement.

- [ ] **Step 1: Change the `FontraMainWidget.__init__` signature to accept a controller**

Find this line in `fontra_pak/launcher.py`:

```python
    def __init__(self, port):
        super().__init__()
        self.port = port
        self.openProjects = set()
```

Replace it with:

```python
    def __init__(self, port, controller=None):
        super().__init__()
        self.port = port
        self.controller = controller
        self.openProjects = set()
```

- [ ] **Step 2: Change `dropEvent` to route through the controller**

Find:

```python
    def dropEvent(self, event):
        self.label.setStyleSheet(neutralCSS)
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for path in files:
            openFile(path, self.port)
        event.acceptProposedAction()
```

Replace with:

```python
    def dropEvent(self, event):
        self.label.setStyleSheet(neutralCSS)
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for path in files:
            if self.controller is not None:
                self.controller.open_project(path)
            else:
                openFile(path, self.port)
        event.acceptProposedAction()
```

- [ ] **Step 3: Change `newFont` to route through the controller**

Find this block at the end of the `newFont` method:

```python
        if os.path.exists(fontPath):
            openFile(fontPath, self.port)
```

Replace with:

```python
        if os.path.exists(fontPath):
            if self.controller is not None:
                self.controller.open_project(fontPath)
            else:
                openFile(fontPath, self.port)
```

- [ ] **Step 4: Change `closeEvent` to use the controller for quit handling**

Find:

```python
    def closeEvent(self, event):
        if self.openProjects:
            response = showMessageDialog(
                "There are still open fonts, are you sure you want to quit?",
                "Quitting Fontra Pak will cause open browser tabs to stop working.",
                buttons=QMessageBox.StandardButton.Close
                | QMessageBox.StandardButton.Cancel,
                defaultButton=QMessageBox.StandardButton.Cancel,
            )
            if response == QMessageBox.StandardButton.Cancel:
                event.ignore()

        self.settings.setValue("size", self.size())
        self.settings.setValue("pos", self.pos())
```

Replace with:

```python
    def closeEvent(self, event):
        has_workspace = (
            self.controller.has_project_windows()
            if self.controller is not None
            else bool(self.openProjects)
        )
        needs_confirm = (
            self.controller.has_open_projects()
            if self.controller is not None
            else bool(self.openProjects)
        )
        if needs_confirm:
            response = showMessageDialog(
                "There are still open fonts, are you sure you want to quit?",
                "Quitting Fontra Pak will close all project windows.",
                buttons=QMessageBox.StandardButton.Close
                | QMessageBox.StandardButton.Cancel,
                defaultButton=QMessageBox.StandardButton.Cancel,
            )
            if response == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        if has_workspace and self.controller is not None:
            self.controller.begin_bulk_shutdown()
            self.controller.close_all_project_windows()

        self.settings.setValue("size", self.size())
        self.settings.setValue("pos", self.pos())
```

- [ ] **Step 5: Verify both launcher entry paths**

Run: `python -m fontra_pak`

Manual checks:
1. Drag a project into the launcher and verify it opens in a native project window.
2. Use `New Font...`, create a project, and verify the newly created project also opens in a native project window.
3. Close the launcher while project windows are open and verify the bulk-shutdown confirmation closes the whole workspace instead of leaving orphaned windows.

- [ ] **Step 6: Commit**

```bash
git add fontra_pak/launcher.py
git commit -m "feat: wire controller into launcher (drop, newFont, closeEvent)"
```

### Task 23: Wire the controller into `app.py`

**Files:**
- Modify: `fontra_pak/app.py`

Replace the entire contents of `fontra_pak/app.py` with the version below. The changes from the Phase 0 version are: (a) imports `AppWorkspaceController`, (b) `FontraApplication.__init__` takes a `controller` param, (c) macOS `FileOpen` routes through `controller.open_project`, (d) `main()` creates the controller and passes it everywhere.

- [ ] **Step 1: Replace `fontra_pak/app.py`**

```python
# fontra_pak/app.py
import multiprocessing
import sys

import psutil
from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import QApplication

from fontra.core.server import findFreeTCPPort

from fontra_pak.controller import AppWorkspaceController
from fontra_pak.ipc import callInNewThread, queueGetter
from fontra_pak.launcher import FontraMainWidget
from fontra_pak.server import runFontraServer


class FontraApplication(QApplication):
    def __init__(self, argv, port, controller):
        self.port = port
        self.controller = controller
        super().__init__(argv)

    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            self.controller.open_project(event.file())
        else:
            return super().event(event)
        return True


def main():
    queue = multiprocessing.Queue()
    host = "localhost"
    port = findFreeTCPPort(host=host)
    serverProcess = multiprocessing.Process(
        target=runFontraServer, args=(host, port, queue)
    )
    serverProcess.start()

    controller = AppWorkspaceController(host, port)

    app = FontraApplication(sys.argv, port, controller)

    def cleanup():
        queue.put(None)
        thread.join()
        process = psutil.Process(serverProcess.pid)
        for p in [process] + process.children(recursive=True):
            if sys.platform != "win32":
                p.send_signal(psutil.signal.SIGINT)
            else:
                p.terminate()

    app.aboutToQuit.connect(cleanup)

    mainWindow = FontraMainWidget(port, controller)

    thread = callInNewThread(queueGetter, queue, controller.handle_server_message)

    controller.set_export_callback(mainWindow.exportAs)

    mainWindow.show()

    if "test-startup" in sys.argv:

        def delayedQuit():
            print("test-startup")
            app.quit()

        QTimer.singleShot(1500, delayedQuit)

    sys.exit(app.exec())
```

- [ ] **Step 2: Verify the app runs**

Run: `python -m fontra_pak`

Expected: The launcher window appears. Drop a font file. A native project window should open with an embedded Fontra overview **inside the app** instead of launching the system browser.

- [ ] **Step 3: Commit**

```bash
git add fontra_pak/app.py
git commit -m "feat: wire controller into app.py, replace browser handoff"
```

---

## Phase 2: Workspace Shell

### Task 24: Implement workspace persistence serialization

**Files:**
- Create: `tests/test_persistence.py`
- Create: `fontra_pak/persistence.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_persistence.py
import json

from fontra_pak.persistence import (
    deserialize_workspace,
    serialize_project_record,
    serialize_workspace,
    validate_pane_record,
)
from fontra_pak.view_descriptor import ViewDescriptor


def test_serialize_project_record_fields():
    record = serialize_project_record(
        project_key="c:\\fonts\\demo.ufo",
        project_path="C:\\Fonts\\Demo.ufo",
        active_pane_instance_id="def456",
        pane_records=[
            {"pane_instance_id": "abc123",
             "descriptor": ViewDescriptor.for_overview("c:\\fonts\\demo.ufo").to_dict()},
        ],
        geometry=b"fake_geometry",
        dock_state=b"fake_dock_state",
    )
    assert record["project_key"] == "c:\\fonts\\demo.ufo"
    assert record["project_path"] == "C:\\Fonts\\Demo.ufo"
    assert record["active_pane_instance_id"] == "def456"
    assert len(record["pane_records"]) == 1


def test_round_trip():
    workspace = {"projects": [
        serialize_project_record(
            project_key="key", project_path="path",
            active_pane_instance_id="id1",
            pane_records=[{"pane_instance_id": "id1",
                           "descriptor": ViewDescriptor.for_overview("key").to_dict()}],
            geometry=b"g", dock_state=b"d",
        )
    ]}
    serialized = serialize_workspace(workspace)
    deserialized = deserialize_workspace(serialized)
    assert deserialized is not None
    assert len(deserialized["projects"]) == 1
    assert deserialized["projects"][0]["project_key"] == "key"


def test_deserialize_corrupt_returns_none():
    assert deserialize_workspace("not json {{{") is None


def test_deserialize_missing_key_returns_none():
    assert deserialize_workspace(json.dumps({"wrong": []})) is None


def test_validate_pane_record_valid():
    record = {"pane_instance_id": "abc",
              "descriptor": ViewDescriptor.for_editor("key", "#hash").to_dict()}
    assert validate_pane_record(record) is not None


def test_validate_pane_record_unknown_page():
    record = {"pane_instance_id": "abc",
              "descriptor": {"project_key": "k", "view_kind": "x",
                             "page_path": "/bad.html", "route_hash": "",
                             "title_hint": "X"}}
    assert validate_pane_record(record) is None


def test_validate_pane_record_missing_descriptor():
    assert validate_pane_record({"pane_instance_id": "abc"}) is None
```

- [ ] **Step 2: Run tests — they should fail**

Run: `pytest tests/test_persistence.py -v`

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `fontra_pak/persistence.py`**

```python
# fontra_pak/persistence.py
from __future__ import annotations

import base64
import json
import logging

from fontra_pak.view_descriptor import KNOWN_PAGE_PATHS, ViewDescriptor

logger = logging.getLogger(__name__)


def serialize_project_record(
    *,
    project_key: str,
    project_path: str,
    active_pane_instance_id: str | None,
    pane_records: list[dict],
    geometry: bytes,
    dock_state: bytes,
) -> dict:
    return {
        "project_key": project_key,
        "project_path": project_path,
        "active_pane_instance_id": active_pane_instance_id,
        "pane_records": pane_records,
        "geometry": base64.b64encode(geometry).decode("ascii"),
        "dock_state": base64.b64encode(dock_state).decode("ascii"),
    }


def deserialize_project_record(data: dict) -> dict | None:
    try:
        return {
            "project_key": data["project_key"],
            "project_path": data["project_path"],
            "active_pane_instance_id": data.get("active_pane_instance_id"),
            "pane_records": data["pane_records"],
            "geometry": base64.b64decode(data["geometry"]),
            "dock_state": base64.b64decode(data["dock_state"]),
        }
    except (KeyError, ValueError, TypeError):
        logger.warning("Corrupt project record, skipping")
        return None


def serialize_workspace(workspace: dict) -> str:
    return json.dumps(workspace)


def deserialize_workspace(data: str) -> dict | None:
    try:
        parsed = json.loads(data)
        if "projects" not in parsed:
            return None
        return parsed
    except (json.JSONDecodeError, TypeError):
        return None


def validate_pane_record(pane_record: dict) -> ViewDescriptor | None:
    try:
        descriptor = ViewDescriptor.from_dict(pane_record["descriptor"])
        if descriptor.page_path not in KNOWN_PAGE_PATHS:
            return None
        return descriptor
    except (KeyError, TypeError):
        return None
```

- [ ] **Step 4: Run tests — they should pass**

Run: `pytest tests/test_persistence.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/persistence.py tests/test_persistence.py
git commit -m "feat: implement workspace persistence serialization"
```

### Task 25: Add workspace snapshot and save support

**Files:**
- Modify: `fontra_pak/controller.py`
- Modify: `fontra_pak/launcher.py`
- Create: `tests/test_controller_workspace_save.py`

- [ ] **Step 1: Write failing tests for shutdown snapshot persistence**

```python
# tests/test_controller_workspace_save.py
import json

from fontra_pak.controller import AppWorkspaceController
from fontra_pak.view_descriptor import ViewDescriptor


class FakeSettings:
    def __init__(self):
        self.values = {}

    def setValue(self, key, value):
        self.values[key] = value

    def value(self, key, default=None):
        return self.values.get(key, default)


class FakePane:
    def __init__(self, pane_instance_id, descriptor):
        self.pane_instance_id = pane_instance_id
        self.descriptor = descriptor


class FakeWindow:
    def __init__(self, project_key, project_path):
        self.project_key = project_key
        self.project_path = project_path
        self.panes = [
            FakePane("pane-1", ViewDescriptor.for_overview(project_key)),
        ]
        self.active_pane_instance_id = "pane-1"

    def saveGeometry(self):
        return b"geom"

    def saveState(self):
        return b"dock"


def test_save_workspace_uses_captured_snapshot_after_windows_close():
    controller = AppWorkspaceController(
        "localhost",
        8080,
        project_window_cls=lambda **kwargs: None,
        profile_factory=lambda _project_key: object(),
    )
    controller.project_windows = {
        "demo-key": FakeWindow("demo-key", "C:\\Fonts\\Demo.ufo")
    }
    settings = FakeSettings()

    controller.capture_workspace_snapshot()
    controller.project_windows = {}
    controller.save_workspace(settings)

    payload = json.loads(settings.value("workspace"))
    assert payload["projects"][0]["project_key"] == "demo-key"
```

- [ ] **Step 2: Run tests - they should fail**

Run: `pytest tests/test_controller_workspace_save.py -v`

Expected: `AttributeError` because `capture_workspace_snapshot` does not exist yet.

- [ ] **Step 3: Add snapshot-aware workspace serialization to `AppWorkspaceController`**

Add these imports at the top of `fontra_pak/controller.py`, after the existing imports:

```python
from fontra_pak.persistence import serialize_project_record, serialize_workspace
```

Add this attribute in `AppWorkspaceController.__init__`:

```python
        self._pending_workspace_payload = None
```

Then add these methods to the `AppWorkspaceController` class after `close_all_project_windows`:

```python
    def _serialize_workspace_payload(self) -> str:
        project_records = []
        for project_key, window in self.project_windows.items():
            pane_records = []
            for pane in window.panes:
                pane_records.append({
                    "pane_instance_id": pane.pane_instance_id,
                    "descriptor": pane.descriptor.to_dict(),
                })
            record = serialize_project_record(
                project_key=project_key,
                project_path=window.project_path,
                active_pane_instance_id=window.active_pane_instance_id,
                pane_records=pane_records,
                geometry=bytes(window.saveGeometry()),
                dock_state=bytes(window.saveState()),
            )
            project_records.append(record)
        return serialize_workspace({"projects": project_records})

    def capture_workspace_snapshot(self):
        self._pending_workspace_payload = self._serialize_workspace_payload()

    def save_workspace(self, settings):
        payload = self._pending_workspace_payload
        if payload is None:
            payload = self._serialize_workspace_payload()
        settings.setValue("workspace", payload)
        self._pending_workspace_payload = None
```

- [ ] **Step 4: Amend launcher quit handling to capture the workspace before bulk shutdown**

In `fontra_pak/launcher.py`, update the revised `closeEvent()` from Task 22A so the bulk-shutdown branch becomes:

```python
        if has_workspace and self.controller is not None:
            self.controller.capture_workspace_snapshot()
            self.controller.begin_bulk_shutdown()
            self.controller.close_all_project_windows()
```

- [ ] **Step 5: Run tests - they should pass**

Run: `pytest tests/test_controller_workspace_save.py -v`

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add fontra_pak/controller.py fontra_pak/launcher.py tests/test_controller_workspace_save.py
git commit -m "feat: preserve workspace during launcher-triggered shutdown"
```

### Task 26A: Revised restore_workspace and restore tests

**Files:**
- Modify: `fontra_pak/controller.py`
- Create: `tests/test_controller_restore.py`

- [ ] **Step 1: Write failing restore tests**

```python
# tests/test_controller_restore.py
from fontra_pak.controller import AppWorkspaceController
from fontra_pak.persistence import serialize_project_record, serialize_workspace
from fontra_pak.project_identity import path_to_project_key
from fontra_pak.view_descriptor import ViewDescriptor, default_overview_descriptor


class FakeSettings:
    def __init__(self, workspace_payload=None):
        self._values = {}
        if workspace_payload is not None:
            self._values["workspace"] = workspace_payload

    def value(self, key, default=None):
        return self._values.get(key, default)

    def setValue(self, key, value):
        self._values[key] = value

    def remove(self, key):
        self._values.pop(key, None)


class FakeWindow:
    def __init__(self, **kwargs):
        self.project_key = kwargs["project_key"]
        self.project_path = kwargs["project_path"]
        self.profile = kwargs["profile"]
        self.opened_descriptors = []
        self.restored_geometry = None
        self.restored_state = None
        self.focused_pane_instance_id = None
        self.restore_geometry_result = kwargs.get("restore_geometry_result", True)
        self.restore_state_result = kwargs.get("restore_state_result", True)
        self.fail_on_open_view = kwargs.get("fail_on_open_view", False)
        self.closed = False

    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def open_view(self, descriptor, pane_instance_id=None):
        if self.fail_on_open_view:
            raise RuntimeError("boom")
        self.opened_descriptors.append((descriptor, pane_instance_id))

    def restoreGeometry(self, value):
        self.restored_geometry = value
        return self.restore_geometry_result

    def restoreState(self, value):
        self.restored_state = value
        return self.restore_state_result

    def focus_pane_instance(self, pane_instance_id):
        self.focused_pane_instance_id = pane_instance_id
        return True

    def suppress_close_confirm(self):
        pass

    def close(self):
        self.closed = True

    def show_connection_lost(self):
        pass


def make_controller(window_overrides=None):
    created_windows = []
    window_overrides = window_overrides or {}

    def fake_window_cls(**kwargs):
        kwargs.update(window_overrides.get(kwargs["project_path"], {}))
        window = FakeWindow(**kwargs)
        created_windows.append(window)
        return window

    controller = AppWorkspaceController(
        "localhost",
        8080,
        project_window_cls=fake_window_cls,
        profile_factory=lambda _project_key: object(),
    )
    return controller, created_windows


def test_restore_workspace_recreates_all_saved_panes(tmp_path):
    controller, created_windows = make_controller()
    project_path = tmp_path / "Demo.ufo"
    project_path.touch()
    project_key = path_to_project_key(str(project_path))
    workspace_payload = serialize_workspace(
        {
            "projects": [
                serialize_project_record(
                    project_key=project_key,
                    project_path=str(project_path),
                    active_pane_instance_id="pane-2",
                    pane_records=[
                        {
                            "pane_instance_id": "pane-1",
                            "descriptor": ViewDescriptor.for_editor(
                                project_key,
                                route_hash="#glyph=A",
                            ).to_dict(),
                        },
                        {
                            "pane_instance_id": "pane-2",
                            "descriptor": ViewDescriptor.for_fontinfo(
                                project_key,
                                route_hash="#axes",
                            ).to_dict(),
                        },
                    ],
                    geometry=b"geom",
                    dock_state=b"dock",
                )
            ]
        }
    )

    errors = controller.restore_workspace(FakeSettings(workspace_payload))

    assert errors == []
    assert len(created_windows) == 1
    assert created_windows[0].opened_descriptors == [
        (ViewDescriptor.for_editor(project_key, route_hash="#glyph=A"), "pane-1"),
        (ViewDescriptor.for_fontinfo(project_key, route_hash="#axes"), "pane-2"),
    ]
    assert created_windows[0].focused_pane_instance_id == "pane-2"


def test_restore_workspace_falls_back_to_overview_when_all_descriptors_invalid(tmp_path):
    controller, created_windows = make_controller()
    project_path = tmp_path / "Demo.ufo"
    project_path.touch()
    project_key = path_to_project_key(str(project_path))
    workspace_payload = serialize_workspace(
        {
            "projects": [
                serialize_project_record(
                    project_key=project_key,
                    project_path=str(project_path),
                    active_pane_instance_id=None,
                    pane_records=[
                        {
                            "pane_instance_id": "pane-1",
                            "descriptor": {
                                "project_key": project_key,
                                "view_kind": "unknown",
                                "page_path": "/bad.html",
                                "route_hash": "",
                                "title_hint": "Bad",
                            },
                        }
                    ],
                    geometry=b"geom",
                    dock_state=b"dock",
                )
            ]
        }
    )

    errors = controller.restore_workspace(FakeSettings(workspace_payload))

    assert len(created_windows) == 1
    assert created_windows[0].opened_descriptors == [
        (default_overview_descriptor(project_key), None)
    ]
    assert errors == [
        f"No valid pane descriptors were saved for {project_path}; reopening overview."
    ]


def test_restore_workspace_reports_restore_state_false(tmp_path):
    project_path = tmp_path / "Demo.ufo"
    project_path.touch()
    controller, created_windows = make_controller(
        {str(project_path): {"restore_state_result": False}}
    )
    project_key = path_to_project_key(str(project_path))
    workspace_payload = serialize_workspace(
        {
            "projects": [
                serialize_project_record(
                    project_key=project_key,
                    project_path=str(project_path),
                    active_pane_instance_id=None,
                    pane_records=[
                        {
                            "pane_instance_id": "pane-1",
                            "descriptor": ViewDescriptor.for_overview(project_key).to_dict(),
                        }
                    ],
                    geometry=b"geom",
                    dock_state=b"dock",
                )
            ]
        }
    )

    errors = controller.restore_workspace(FakeSettings(workspace_payload))

    assert len(created_windows) == 1
    assert errors == [f"Failed to restore dock layout for {project_path}"]


def test_restore_workspace_closes_partial_window_after_open_view_failure(tmp_path):
    broken_path = tmp_path / "Broken.ufo"
    broken_path.touch()
    healthy_path = tmp_path / "Healthy.ufo"
    healthy_path.touch()
    controller, created_windows = make_controller(
        {str(broken_path): {"fail_on_open_view": True}}
    )
    broken_key = path_to_project_key(str(broken_path))
    healthy_key = path_to_project_key(str(healthy_path))
    workspace_payload = serialize_workspace(
        {
            "projects": [
                serialize_project_record(
                    project_key=broken_key,
                    project_path=str(broken_path),
                    active_pane_instance_id=None,
                    pane_records=[
                        {
                            "pane_instance_id": "broken-pane",
                            "descriptor": ViewDescriptor.for_overview(broken_key).to_dict(),
                        }
                    ],
                    geometry=b"geom",
                    dock_state=b"dock",
                ),
                serialize_project_record(
                    project_key=healthy_key,
                    project_path=str(healthy_path),
                    active_pane_instance_id=None,
                    pane_records=[
                        {
                            "pane_instance_id": "healthy-pane",
                            "descriptor": ViewDescriptor.for_overview(healthy_key).to_dict(),
                        }
                    ],
                    geometry=b"geom",
                    dock_state=b"dock",
                ),
            ]
        }
    )

    errors = controller.restore_workspace(FakeSettings(workspace_payload))

    assert errors == [f"Failed to restore {broken_path}: boom"]
    assert created_windows[0].closed is True
    assert healthy_key in controller.project_windows
    assert created_windows[1].opened_descriptors == [
        (ViewDescriptor.for_overview(healthy_key), "healthy-pane")
    ]
```

- [ ] **Step 2: Run tests - they should fail**

Run: `pytest tests/test_controller_restore.py -v`

Expected: `AttributeError: 'AppWorkspaceController' object has no attribute 'restore_workspace'`

- [ ] **Step 3: Add restore imports and `restore_workspace()` to `fontra_pak/controller.py`**

Add these imports near the top of `fontra_pak/controller.py`:

```python
from fontra_pak.persistence import deserialize_project_record, deserialize_workspace, validate_pane_record
```

Then add this method after `save_workspace()` if you already completed Task 25, otherwise add it after `notify_server_lost()` and move it next to `save_workspace()` when reconciling the file:

```python
    def restore_workspace(self, settings) -> list[str]:
        errors = []
        raw = settings.value("workspace", None)
        if raw is None:
            return errors

        workspace = deserialize_workspace(raw)
        if workspace is None:
            errors.append("Saved workspace was unreadable. Starting clean.")
            settings.remove("workspace")
            return errors

        for project_data in workspace["projects"]:
            record = deserialize_project_record(project_data)
            if record is None:
                errors.append("Corrupt project record, skipped.")
                continue

            project_path = record["project_path"]
            if not os.path.exists(project_path):
                errors.append(f"Project path no longer exists: {project_path}")
                continue

            window, _created = self.get_or_create_project_window(project_path)
            if window is None:
                errors.append(
                    f"Failed to restore {project_path}: project window could not be created"
                )
                continue

            try:
                if window.restoreGeometry(record["geometry"]) is False:
                    errors.append(f"Failed to restore geometry for {project_path}")

                valid_panes = []
                for pane_record in record["pane_records"]:
                    descriptor = validate_pane_record(pane_record)
                    pane_instance_id = pane_record.get("pane_instance_id")
                    if descriptor is not None and pane_instance_id:
                        valid_panes.append((descriptor, pane_instance_id))

                if not valid_panes:
                    errors.append(
                        f"No valid pane descriptors were saved for {project_path}; reopening overview."
                    )
                    window.open_view(default_overview_descriptor(window.project_key))
                else:
                    for descriptor, pane_instance_id in valid_panes:
                        window.open_view(descriptor, pane_instance_id=pane_instance_id)

                if window.restoreState(record["dock_state"]) is False:
                    errors.append(f"Failed to restore dock layout for {project_path}")

                target_id = record["active_pane_instance_id"]
                if target_id and not window.focus_pane_instance(target_id):
                    errors.append(f"Saved active pane was missing for {project_path}")
            except Exception as exc:
                self.unregister_project_window(window)
                try:
                    window.close()
                except Exception:
                    pass
                errors.append(f"Failed to restore {project_path}: {exc}")
                continue

        return errors
```

- [ ] **Step 4: Run tests - they should pass**

Run: `pytest tests/test_controller_restore.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/controller.py tests/test_controller_restore.py
git commit -m "feat: restore saved panes without losing the first descriptor"
```

### Task 27A: Revised app startup and restore precedence

**Files:**
- Modify: `fontra_pak/app.py`
- Create: `tests/test_startup_precedence.py`

- [ ] **Step 1: Write failing startup precedence tests**

```python
# tests/test_startup_precedence.py
from fontra_pak.app import classify_startup_requests


def test_explicit_existing_paths_skip_restore(tmp_path):
    project_path = tmp_path / "Demo.ufo"
    project_path.touch()

    requests = classify_startup_requests(["fontra-pak", str(project_path)])

    assert requests == {
        "explicit_paths": [str(project_path)],
        "has_explicit_project_args": True,
        "should_restore_workspace": False,
        "is_startup_smoke_test": False,
    }


def test_explicit_missing_paths_still_skip_restore():
    requests = classify_startup_requests(["fontra-pak", "missing-demo.ufo"])

    assert requests == {
        "explicit_paths": [],
        "has_explicit_project_args": True,
        "should_restore_workspace": False,
        "is_startup_smoke_test": False,
    }


def test_no_explicit_paths_restores_workspace():
    requests = classify_startup_requests(["fontra-pak", "--flag"])

    assert requests == {
        "explicit_paths": [],
        "has_explicit_project_args": False,
        "should_restore_workspace": True,
        "is_startup_smoke_test": False,
    }


def test_test_startup_sentinel_is_not_treated_as_project_request():
    requests = classify_startup_requests(["fontra-pak", "test-startup"])

    assert requests == {
        "explicit_paths": [],
        "has_explicit_project_args": False,
        "should_restore_workspace": False,
        "is_startup_smoke_test": True,
    }
```

- [ ] **Step 2: Run tests - they should fail**

Run: `pytest tests/test_startup_precedence.py -v`

Expected: `ImportError` or `AttributeError` because `classify_startup_requests` does not exist yet.

- [ ] **Step 3: Add `classify_startup_requests()` and wire save/restore lifecycle in `fontra_pak/app.py`**

Add `import os` near the top of `fontra_pak/app.py`, change the QtCore import to include `QSettings`, then add this helper above `main()`:

```python
def classify_startup_requests(argv):
    non_flag_args = [arg for arg in argv[1:] if not arg.startswith("-")]
    is_startup_smoke_test = "test-startup" in non_flag_args
    candidate_args = [arg for arg in non_flag_args if arg != "test-startup"]
    explicit_paths = [arg for arg in candidate_args if os.path.exists(arg)]
    has_explicit_project_args = bool(candidate_args)
    return {
        "explicit_paths": explicit_paths,
        "has_explicit_project_args": has_explicit_project_args,
        "should_restore_workspace": (
            not has_explicit_project_args and not is_startup_smoke_test
        ),
        "is_startup_smoke_test": is_startup_smoke_test,
    }
```

Then update `main()` in three places.

First, insert this line immediately after:

```python
    app = FontraApplication(sys.argv, port, controller)
```

Insert:

```python
    startup = classify_startup_requests(sys.argv)
```

Second, replace this block:

```python
    app.aboutToQuit.connect(cleanup)

    mainWindow = FontraMainWidget(port, controller)
```

with:

```python
    settings = QSettings("xyz.fontra", "FontraPak")

    def save_and_cleanup():
        if not startup["is_startup_smoke_test"]:
            controller.save_workspace(settings)
        cleanup()

    app.aboutToQuit.connect(save_and_cleanup)

    mainWindow = FontraMainWidget(port, controller)
```

Third, replace this block:

```python
    mainWindow.show()

    if "test-startup" in sys.argv:
```

with:

```python
    mainWindow.show()

    if startup["explicit_paths"]:
        for path in startup["explicit_paths"]:
            controller.open_project(path)
    elif startup["has_explicit_project_args"]:
        from fontra_pak.dialogs import showMessageDialog

        showMessageDialog(
            "Some startup projects could not be opened",
            "The app was launched with explicit project paths, but none of them were readable.",
            detailedText="\n".join(
                arg
                for arg in sys.argv[1:]
                if not arg.startswith("-") and arg != "test-startup"
            ),
        )
    elif startup["should_restore_workspace"]:
        errors = controller.restore_workspace(settings)
        if errors:
            from fontra_pak.dialogs import showMessageDialog

            showMessageDialog(
                "Some projects could not be restored",
                "\n".join(errors),
            )

    if "test-startup" in sys.argv:
```

- [ ] **Step 4: Run tests - they should pass**

Run: `pytest tests/test_startup_precedence.py -v`

Expected: All PASS.

- [ ] **Step 5: Verify save and restore preserve the first pane**

Run: `python -m fontra_pak`

Manual checks:
1. Open a project and navigate the only pane from overview to an editor route such as `#glyph=A`.
2. Open a second pane such as `Font Info`.
3. Quit the app cleanly.
4. Re-launch: `python -m fontra_pak`
5. The first restored pane should still be the editor route, the second pane should still be `Font Info`, and the previously active pane should be focused.
6. Launch the app with a nonexistent explicit project argument and verify it does not restore the last workspace.

- [ ] **Step 6: Commit**

```bash
git add fontra_pak/app.py tests/test_startup_precedence.py
git commit -m "feat: wire workspace save/restore into app lifecycle"
```

### Task 28: Run full test suite

**Files:**
- No changes.

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`

Expected results:
- `test_fontra_client_bundling` — PASS
- `test_startup` — PASS or SKIP (platform/dist dependent)
- `test_project_identity` — PASS
- `test_view_descriptor` — PASS
- `test_routing` — PASS
- `test_controller_callbacks` — PASS
- `test_persistence` — PASS

- [ ] **Step 2: Manual acceptance test**

Run: `python -m fontra_pak`

Checklist (from spec "MVP Acceptance Boundary"):
1. Opening a project does NOT launch the system browser.
2. The editor window is owned by `Fontra Pak.exe` (check task manager).
3. One project = one window. Drop the same file again — existing window focuses.
4. View menu opens panes as tabs. Tabs can be dragged to dock side-by-side.
5. Overview, Editor (click a glyph in overview), Font Info, and Application Settings all work as internal panes.
6. `window.open()` from Fontra menus creates panes, not browser windows.
7. External links (Help > Documentation in Fontra menu) open in system browser.
8. Open two different projects — they get separate windows.
9. Clean quit and relaunch restores the workspace.

---

## Post-Plan Notes

### Not covered (post-MVP / Phase 3)

- Crash-session restore
- Server health monitoring (the `notify_server_lost` method exists but is not wired to a health check)
- Moving export dialog execution into `ProjectWindow` (currently delegates to launcher)
- PyInstaller packaging verification (run `pyinstaller FontraPak.spec -y` and test the dist build)
- macOS compatibility
- Windows file-type associations

### Key risk to validate early

After Task 23, manually verify that mouse-profile software sees the focused project window as belonging to `Fontra Pak.exe`. If it sees `QtWebEngineProcess.exe` instead, the entire approach needs re-evaluation before continuing to Phase 2.
