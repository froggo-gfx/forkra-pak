# Native Project Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the browser handoff with native project windows that embed Fontra views inside `Fontra Pak.exe`, with dockable panes and workspace persistence.

**Architecture:** Keep the existing Python/PyQt6/PyInstaller stack and local Fontra server. Add `PyQt6-WebEngine` to embed Fontra views in `QMainWindow`-based project windows with `QDockWidget` panes. A new `AppWorkspaceController` manages the project window registry, routes server callbacks, and owns quit/restore behavior. Navigation is intercepted at the `QWebEnginePage` level and classified as internal (open/focus pane), external (system browser), or rejected (block + error).

**Tech Stack:** Python 3.12+, PyQt6 6.7, PyQt6-WebEngine, PyInstaller 6.17, pytest

**Spec:** `docs/superpowers/specs/2026-04-01-fontra-native-project-window-design.md`

**Important discovery:** `FileSystemProjectManager.authorize()` returns `"yes"` unconditionally. The server's `versionToken` is used only for static file cache-busting, not request authentication. The current `openFile()` does not include any token in URLs. Pane URLs do not need a versionToken.

**Fontra navigation patterns** (from `fontra-overview/src-js/`):
- Overview to editor: `window.open(url)` (no target name — opens new window)
- Editor to font info: `window.open(url, "fontra.fontinfo.<projectId>")`
- Any to app settings: `window.open("/applicationsettings.html#panel", "_self" | "fontra.applicationsettings")`
- Font overview/info from menu: `window.open(url, "fontra.<viewKind>.<uniqueId>" | "_self")`
- External links: `window.open("https://...", "fontra.website")` or `<a target="_blank">`

All internal navigation uses `window.open()` with named targets or `_self`. The `QWebEnginePage.createWindow()` override intercepts all `window.open()` calls with non-`_self` targets. Same-page `_self` navigation goes through `acceptNavigationRequest()`.

---

## File Structure

### New package layout (Phase 0 creates this from the monolithic `FontraPakMain.py`)

```
fontra_pak/
    __init__.py           - Package marker, version
    __main__.py           - Entry point: multiprocessing.freeze_support() + main()
    app.py                - FontraApplication subclass, main() orchestration
    launcher.py           - FontraMainWidget (launcher/drop window)
    server.py             - runFontraServer, FontraPakExportManager, ProjectOpenListener
    ipc.py                - CallInMainThreadScheduler, queueGetter, callInMainThread, callInNewThread
    dialogs.py            - showMessageDialog
    export.py             - exportAs UI, doExportAs, exportFontToPath, createNewFont
    constants.py          - CSS strings, file type mappings, URLs
    update_checker.py     - fetchLatestReleaseInfo, update check logic
    controller.py         - AppWorkspaceController (Phase 1)
    project_identity.py   - Project identity contract helpers (Phase 1)
    view_descriptor.py    - ViewDescriptor dataclass (Phase 1)
    routing.py            - URL classification (internal/external/rejected) (Phase 1)
    project_window.py     - ProjectWindow (Phase 1), pane management (Phase 2)
    workspace_pane.py     - WorkspacePane + PaneNavigationBridge (Phase 1)
    persistence.py        - Workspace save/restore serialization (Phase 2)
```

### Test files

```
tests/
    test_startup.py                - Existing (update entry point path)
    test_fontra_client_bundling.py - Existing (unchanged)
    test_project_identity.py       - Phase 1: project key canonicalization
    test_view_descriptor.py        - Phase 1: descriptor creation, title derivation
    test_routing.py                - Phase 1: URL classification logic
    test_persistence.py            - Phase 2: workspace serialization round-trips
```

### Modified files

```
FontraPakMain.py   - Replaced by fontra_pak/ package (kept as thin redirect or deleted)
FontraPak.spec     - Updated entry point, add QtWebEngine collection
requirements.txt   - Add PyQt6-WebEngine
```

---

## Phase 0: Codebase Restructuring

Pure refactor. No behavior change. Every task produces a passing test suite.

### Task 1: Create package skeleton and entry point

**Files:**
- Create: `fontra_pak/__init__.py`
- Create: `fontra_pak/__main__.py`
- Modify: `FontraPakMain.py`

- [ ] **Step 1: Create the package directory and `__init__.py`**

```python
# fontra_pak/__init__.py
```

- [ ] **Step 2: Create `__main__.py` as thin entry point**

```python
# fontra_pak/__main__.py
import multiprocessing
from fontra_pak.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
```

- [ ] **Step 3: Replace `FontraPakMain.py` with a redirect**

Replace the entire contents of `FontraPakMain.py` with:

```python
# Legacy entry point — delegates to fontra_pak package.
# Kept for PyInstaller compatibility during transition.
import multiprocessing
from fontra_pak.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
```

(Don't move anything else yet — `fontra_pak.app` doesn't exist yet. This file will work once Task 5 is done.)

- [ ] **Step 4: Commit**

```bash
git add fontra_pak/__init__.py fontra_pak/__main__.py FontraPakMain.py
git commit -m "feat: create fontra_pak package skeleton with entry point redirect"
```

### Task 2: Extract constants and file type mappings

**Files:**
- Create: `fontra_pak/constants.py`

- [ ] **Step 1: Create `constants.py`**

Move all module-level constants from `FontraPakMain.py` lines 52-112 into `fontra_pak/constants.py`:

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
git commit -m "refactor: extract constants to fontra_pak/constants.py"
```

### Task 3: Extract IPC utilities

**Files:**
- Create: `fontra_pak/ipc.py`

- [ ] **Step 1: Create `ipc.py`**

Move `CallInMainThreadScheduler`, `callInMainThread`, `callInNewThread`, `queueGetter` from `FontraPakMain.py` lines 584-622:

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
git commit -m "refactor: extract IPC utilities to fontra_pak/ipc.py"
```

### Task 4: Extract dialogs, export, server, and update checker

**Files:**
- Create: `fontra_pak/dialogs.py`
- Create: `fontra_pak/export.py`
- Create: `fontra_pak/server.py`
- Create: `fontra_pak/update_checker.py`

- [ ] **Step 1: Create `dialogs.py`**

Move `showMessageDialog` and `getFontPath` from `FontraPakMain.py`:

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

- [ ] **Step 2: Create `export.py`**

Move `exportFontToPath`, `exportFontToPathAsync`, `createNewFont` from `FontraPakMain.py`:

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

- [ ] **Step 3: Create `server.py`**

Move `FontraPakExportManager`, `ProjectOpenListener`, `runFontraServer` from `FontraPakMain.py`:

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

- [ ] **Step 4: Create `update_checker.py`**

Move `fetchLatestReleaseInfo` and `_fetchLatestReleaseInfo` from `FontraPakMain.py`:

```python
# fontra_pak/update_checker.py
import json
import sys
import traceback
from urllib.request import urlopen

latestReleasePageURL = "https://github.com/fontra/fontra-pak/releases/latest"


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

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/dialogs.py fontra_pak/export.py fontra_pak/server.py fontra_pak/update_checker.py
git commit -m "refactor: extract dialogs, export, server, and update checker modules"
```

### Task 5: Extract launcher and app module, wire everything together

**Files:**
- Create: `fontra_pak/launcher.py`
- Create: `fontra_pak/app.py`
- Modify: `FontraPakMain.py` (already a redirect from Task 1)

- [ ] **Step 1: Create `launcher.py`**

Move `FontraMainWidget` and `openFile` from `FontraPakMain.py`. All imports now come from the package:

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
from random import random
from urllib.parse import quote
from datetime import datetime

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
    mainText,
    neutralCSS,
)
from fontra_pak.dialogs import getFontPath, showMessageDialog
from fontra_pak.export import createNewFont, exportFontToPath
from fontra_pak.ipc import callInMainThread, callInNewThread
from fontra_pak.update_checker import fetchLatestReleaseInfo, latestReleasePageURL


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

- [ ] **Step 2: Create `app.py`**

Move `FontraApplication` and `main()` from `FontraPakMain.py`:

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

- [ ] **Step 3: Verify the app runs from the package**

Run: `python -m fontra_pak`

Expected: The launcher window appears, behaves identically to the original.

- [ ] **Step 4: Commit**

```bash
git add fontra_pak/launcher.py fontra_pak/app.py
git commit -m "refactor: extract launcher and app modules, complete package extraction"
```

### Task 6: Update PyInstaller spec and verify build

**Files:**
- Modify: `FontraPak.spec`

- [ ] **Step 1: Update the Analysis entry point in `FontraPak.spec`**

Change line 85:

```python
# Old:
    ["FontraPakMain.py"],
# New:
    ["FontraPakMain.py"],
```

Keep `FontraPakMain.py` as the entry point since it now redirects to the package. This avoids changing PyInstaller's module resolution. The `fontra_pak/` package will be collected automatically since `FontraPakMain.py` imports from it.

- [ ] **Step 2: Run PyInstaller build**

Run: `pyinstaller FontraPak.spec -y`

Expected: Build completes without errors.

- [ ] **Step 3: Run existing tests**

Run: `pytest tests/ -v`

Expected: Both `test_startup` and `test_fontra_client_bundling` pass (if running on Windows with a dist build, `test_startup` runs; otherwise it skips).

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor: verify PyInstaller build works with package extraction"
```

(Only commit if `FontraPak.spec` actually changed. Otherwise skip.)

---

## Phase 1: Embedded Single Project Window

### Task 7: Add PyQt6-WebEngine dependency

**Files:**
- Modify: `requirements.txt`
- Modify: `FontraPak.spec`

- [ ] **Step 1: Add PyQt6-WebEngine to requirements**

Add to `requirements.txt` after the PyQt6 lines:

```
PyQt6-WebEngine==6.7.0
```

- [ ] **Step 2: Install the dependency**

Run: `pip install PyQt6-WebEngine==6.7.0`

- [ ] **Step 3: Update `FontraPak.spec` to collect QtWebEngine**

Add `"PyQt6.QtWebEngineWidgets"` to the `modules_to_collect_all` list, and add a hidden import:

In `FontraPak.spec`, after the existing `modules_to_collect_all` list (line 61-69), add:

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

# QtWebEngine requires explicit collection of its data files and helper processes
qtwebengine_modules = [
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineCore",
]
```

Then in the collection loop, also collect the QtWebEngine modules:

```python
for module_name in modules_to_collect_all + qtwebengine_modules:
```

- [ ] **Step 4: Verify QtWebEngine imports**

Run: `python -c "from PyQt6.QtWebEngineWidgets import QWebEngineView; print('QtWebEngine OK')"`

Expected: `QtWebEngine OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt FontraPak.spec
git commit -m "feat: add PyQt6-WebEngine dependency and update PyInstaller spec"
```

### Task 8: Implement project identity contract

**Files:**
- Create: `fontra_pak/project_identity.py`
- Create: `tests/test_project_identity.py`

- [ ] **Step 1: Write failing tests for project identity**

```python
# tests/test_project_identity.py
import os
import pathlib
import sys

import pytest

from fontra_pak.project_identity import (
    encode_project_query_value,
    path_to_project_key,
    project_key_to_profile_dir_name,
)


def test_path_to_project_key_resolves_and_normcases():
    # On Windows, normcase lowercases; on Unix it's a no-op
    path = pathlib.Path(__file__).resolve()
    key = path_to_project_key(str(path))
    assert key == os.path.normcase(str(path))


def test_path_to_project_key_different_case_same_key():
    if sys.platform != "win32":
        pytest.skip("Case-insensitive paths only on Windows")
    key1 = path_to_project_key("C:\\Fonts\\Demo.ufo")
    key2 = path_to_project_key("c:\\fonts\\demo.ufo")
    assert key1 == key2


def test_encode_project_query_value_windows_drive():
    if sys.platform != "win32":
        pytest.skip("Drive letter test only on Windows")
    # Simulate a resolved Windows path
    value = encode_project_query_value("C:\\Users\\Test\\My Font.ufo")
    assert "C%3A" in value or "C:" in value
    assert "My%20Font.ufo" in value
    # Should not have backslashes
    assert "\\" not in value


def test_encode_project_query_value_unix():
    if sys.platform == "win32":
        pytest.skip("Unix path test only on Unix")
    value = encode_project_query_value("/home/user/My Font.ufo")
    assert value == "home/user/My%20Font.ufo"


def test_profile_dir_name_is_hex_hash():
    name = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    # Should be a hex string (sha256 truncated)
    assert all(c in "0123456789abcdef" for c in name)
    assert len(name) == 16  # 8 bytes hex


def test_profile_dir_name_stable():
    name1 = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    name2 = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    assert name1 == name2


def test_profile_dir_name_different_for_different_projects():
    name1 = project_key_to_profile_dir_name("c:\\fonts\\demo.ufo")
    name2 = project_key_to_profile_dir_name("c:\\fonts\\other.ufo")
    assert name1 != name2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_project_identity.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'fontra_pak.project_identity'`

- [ ] **Step 3: Implement `project_identity.py`**

```python
# fontra_pak/project_identity.py
"""Project identity contract: canonical keys, URL encoding, profile paths.

Extracted from the existing openFile() path-segment encoding algorithm.
See spec section "Project identity contract" for the full contract.
"""

import hashlib
import os
import pathlib
from urllib.parse import quote


def path_to_project_key(path: str) -> str:
    """Canonicalize a file path to a stable project key.

    resolvedProjectPath = str(pathlib.Path(path).resolve())
    projectKey = os.path.normcase(resolvedProjectPath)
    """
    resolved = str(pathlib.Path(path).resolve())
    return os.path.normcase(resolved)


def encode_project_query_value(path: str) -> str:
    """Encode a resolved path into the URL query format used by Fontra.

    This is the existing openFile() algorithm extracted into a shared helper.
    """
    path_obj = pathlib.Path(path).resolve()
    assert path_obj.is_absolute()
    parts = list(path_obj.parts)
    if not path_obj.drive:
        assert parts[0] == "/"
        del parts[0]
    return "/".join(quote(part, safe="") for part in parts)


def project_key_to_profile_dir_name(project_key: str) -> str:
    """Derive a short, filesystem-safe directory name from a project key.

    Uses a truncated SHA-256 hash to avoid MAX_PATH issues on Windows.
    """
    return hashlib.sha256(project_key.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_project_identity.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/project_identity.py tests/test_project_identity.py
git commit -m "feat: implement project identity contract with tests"
```

### Task 9: Implement ViewDescriptor

**Files:**
- Create: `fontra_pak/view_descriptor.py`
- Create: `tests/test_view_descriptor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_view_descriptor.py
from fontra_pak.view_descriptor import ViewDescriptor


def test_create_overview_descriptor():
    d = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    assert d.project_key == "c:\\fonts\\demo.ufo"
    assert d.view_kind == "overview"
    assert d.page_path == "/fontoverview.html"
    assert d.route_hash == ""
    assert d.title_hint == "Overview"


def test_create_editor_descriptor():
    d = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    assert d.view_kind == "editor"
    assert d.page_path == "/editor.html"
    assert d.route_hash == "#glyph=A"
    assert d.title_hint == "Editor"


def test_create_fontinfo_descriptor():
    d = ViewDescriptor.for_fontinfo("c:\\fonts\\demo.ufo", route_hash="#axes-panel")
    assert d.view_kind == "fontinfo"
    assert d.page_path == "/fontinfo.html"
    assert d.route_hash == "#axes-panel"
    assert d.title_hint == "Font Info"


def test_create_applicationsettings_descriptor():
    d = ViewDescriptor.for_applicationsettings("c:\\fonts\\demo.ufo")
    assert d.view_kind == "applicationsettings"
    assert d.page_path == "/applicationsettings.html"
    assert d.title_hint == "Application Settings"


def test_build_url():
    d = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    url = d.build_url("localhost", 8080, "C%3A/fonts/demo.ufo")
    assert url == "http://localhost:8080/editor.html?project=C%3A/fonts/demo.ufo#glyph=A"


def test_build_url_no_hash():
    d = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    url = d.build_url("localhost", 8080, "C%3A/fonts/demo.ufo")
    assert url == "http://localhost:8080/fontoverview.html?project=C%3A/fonts/demo.ufo"


def test_matches_same_descriptor():
    d1 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    d2 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    assert d1.matches(d2)


def test_no_match_different_view():
    d1 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    d2 = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo")
    assert not d1.matches(d2)


def test_no_match_different_project():
    d1 = ViewDescriptor.for_overview("c:\\fonts\\demo.ufo")
    d2 = ViewDescriptor.for_overview("c:\\fonts\\other.ufo")
    assert not d1.matches(d2)


def test_editor_matches_ignores_hash():
    d1 = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    d2 = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=B")
    assert d1.matches(d2)


def test_to_dict_round_trip():
    d = ViewDescriptor.for_editor("c:\\fonts\\demo.ufo", route_hash="#glyph=A")
    data = d.to_dict()
    d2 = ViewDescriptor.from_dict(data)
    assert d.project_key == d2.project_key
    assert d.view_kind == d2.view_kind
    assert d.page_path == d2.page_path
    assert d.route_hash == d2.route_hash
    assert d.title_hint == d2.title_hint
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_view_descriptor.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `view_descriptor.py`**

```python
# fontra_pak/view_descriptor.py
"""ViewDescriptor: describes one logical navigation destination.

A descriptor identifies a route target, not a pane instance.
See spec section "View Descriptor" for the full contract.
"""

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
        return cls(
            project_key=project_key,
            view_kind="overview",
            page_path="/fontoverview.html",
            route_hash=route_hash,
            title_hint="Overview",
        )

    @classmethod
    def for_editor(cls, project_key: str, route_hash: str = "") -> ViewDescriptor:
        return cls(
            project_key=project_key,
            view_kind="editor",
            page_path="/editor.html",
            route_hash=route_hash,
            title_hint="Editor",
        )

    @classmethod
    def for_fontinfo(cls, project_key: str, route_hash: str = "") -> ViewDescriptor:
        return cls(
            project_key=project_key,
            view_kind="fontinfo",
            page_path="/fontinfo.html",
            route_hash=route_hash,
            title_hint="Font Info",
        )

    @classmethod
    def for_applicationsettings(
        cls, project_key: str, route_hash: str = ""
    ) -> ViewDescriptor:
        return cls(
            project_key=project_key,
            view_kind="applicationsettings",
            page_path="/applicationsettings.html",
            route_hash=route_hash,
            title_hint="Application Settings",
        )

    @classmethod
    def from_page_path(
        cls, project_key: str, page_path: str, route_hash: str = ""
    ) -> ViewDescriptor | None:
        view_kind = PAGE_PATH_TO_VIEW_KIND.get(page_path)
        if view_kind is None:
            return None
        return cls(
            project_key=project_key,
            view_kind=view_kind,
            page_path=page_path,
            route_hash=route_hash,
            title_hint=VIEW_KIND_TITLE_HINTS[view_kind],
        )

    def build_url(self, host: str, port: int, project_query_value: str) -> str:
        url = f"http://{host}:{port}{self.page_path}?project={project_query_value}"
        if self.route_hash:
            url += self.route_hash
        return url

    def matches(self, other: ViewDescriptor) -> bool:
        """Check if two descriptors target the same logical route.

        Matches on project_key, view_kind, and page_path.
        route_hash is intentionally excluded — two editor panes for
        different glyphs in the same project still match for deduping.
        """
        return (
            self.project_key == other.project_key
            and self.view_kind == other.view_kind
            and self.page_path == other.page_path
        )

    def to_dict(self) -> dict:
        return {
            "project_key": self.project_key,
            "view_kind": self.view_kind,
            "page_path": self.page_path,
            "route_hash": self.route_hash,
            "title_hint": self.title_hint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ViewDescriptor:
        return cls(
            project_key=data["project_key"],
            view_kind=data["view_kind"],
            page_path=data["page_path"],
            route_hash=data["route_hash"],
            title_hint=data["title_hint"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_view_descriptor.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/view_descriptor.py tests/test_view_descriptor.py
git commit -m "feat: implement ViewDescriptor with factory methods, matching, and serialization"
```

### Task 10: Implement URL routing classification

**Files:**
- Create: `fontra_pak/routing.py`
- Create: `tests/test_routing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_routing.py
from fontra_pak.routing import classify_url, RouteClass


def test_internal_fontoverview():
    result = classify_url(
        "http://localhost:8080/fontoverview.html?project=C%3A/fonts/demo.ufo",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.INTERNAL
    assert result.page_path == "/fontoverview.html"
    assert result.route_hash == ""


def test_internal_editor_with_hash():
    result = classify_url(
        "http://localhost:8080/editor.html?project=C%3A/fonts/demo.ufo#glyph=A",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.INTERNAL
    assert result.page_path == "/editor.html"
    assert result.route_hash == "#glyph=A"


def test_external_https():
    result = classify_url(
        "https://fontra.xyz/",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.EXTERNAL


def test_external_different_host():
    result = classify_url(
        "http://example.com/editor.html?project=foo",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.EXTERNAL


def test_rejected_unsupported_page():
    result = classify_url(
        "http://localhost:8080/landing.html",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.REJECTED


def test_rejected_missing_project():
    result = classify_url(
        "http://localhost:8080/editor.html",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.REJECTED


def test_rejected_different_project():
    result = classify_url(
        "http://localhost:8080/editor.html?project=C%3A/fonts/other.ufo",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.REJECTED


def test_rejected_same_origin_unknown_path():
    result = classify_url(
        "http://localhost:8080/somethingelse.html?project=C%3A/fonts/demo.ufo",
        host="localhost",
        port=8080,
        owner_project_key="c:\\fonts\\demo.ufo",
    )
    assert result.route_class == RouteClass.REJECTED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routing.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `routing.py`**

```python
# fontra_pak/routing.py
"""URL classification for the navigation policy.

Every navigation is classified as INTERNAL, EXTERNAL, or REJECTED.
See spec section "Routing Model" for the full rules.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from enum import Enum, auto
from urllib.parse import unquote, urlparse

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
    """Classify a URL as internal, external, or rejected.

    Args:
        url: The full URL to classify.
        host: The local server host (e.g. "localhost").
        port: The local server port.
        owner_project_key: The canonical project key of the owning ProjectWindow.
    """
    parsed = urlparse(url)

    # External: non-local origin
    expected_netloc = f"{host}:{port}"
    if parsed.scheme not in ("http", "") or parsed.netloc != expected_netloc:
        return RouteResult(route_class=RouteClass.EXTERNAL)

    # Same-origin from here. Check page path.
    page_path = parsed.path
    if page_path not in KNOWN_PAGE_PATHS:
        return RouteResult(route_class=RouteClass.REJECTED)

    # Check project query parameter
    # Parse query manually to handle the project= value which may contain encoded slashes
    query = parsed.query
    project_value = None
    for param in query.split("&"):
        if param.startswith("project="):
            project_value = param[len("project="):]
            break

    if project_value is None:
        return RouteResult(route_class=RouteClass.REJECTED)

    # Decode project value back to a path and canonicalize
    try:
        decoded_parts = [unquote(part) for part in project_value.split("/")]
        # Reconstruct path: on Windows first part may be "C:", on Unix we prepend /
        if len(decoded_parts) >= 1 and ":" in decoded_parts[0]:
            # Windows drive letter
            reconstructed = os.path.join(decoded_parts[0] + os.sep, *decoded_parts[1:])
        else:
            reconstructed = os.sep + os.path.join(*decoded_parts)
        resolved = str(pathlib.Path(reconstructed).resolve())
        project_key = os.path.normcase(resolved)
    except Exception:
        return RouteResult(route_class=RouteClass.REJECTED)

    # Check project ownership
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routing.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/routing.py tests/test_routing.py
git commit -m "feat: implement URL routing classification with tests"
```

### Task 11: Implement WorkspacePane and PaneNavigationBridge

**Files:**
- Create: `fontra_pak/workspace_pane.py`

- [ ] **Step 1: Implement `workspace_pane.py`**

```python
# fontra_pak/workspace_pane.py
"""WorkspacePane: one dockable view inside a ProjectWindow.

Each pane owns one QWebEngineView, one PaneNavigationBridge (the page),
and one stable paneInstanceId.
"""

from __future__ import annotations

import secrets
import webbrowser
from typing import TYPE_CHECKING

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QDockWidget, QLabel, QPushButton, QVBoxLayout, QWidget

from fontra_pak.routing import RouteClass, classify_url
from fontra_pak.view_descriptor import KNOWN_PAGE_PATHS, PAGE_PATH_TO_VIEW_KIND, ViewDescriptor

if TYPE_CHECKING:
    from fontra_pak.project_window import ProjectWindow


class PaneNavigationBridge(QWebEnginePage):
    """Custom QWebEnginePage that intercepts navigation and new-window requests."""

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
            # Same-pane navigation: allow and update descriptor
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

        # REJECTED
        from fontra_pak.dialogs import showMessageDialog
        showMessageDialog(
            "Unsupported destination",
            f"This navigation target is not supported:\n{url_str}",
        )
        return False

    def createWindow(self, window_type):
        """Intercept window.open() calls.

        Returns a temporary page that captures the target URL,
        then classifies and routes it.
        """
        trap = _NavigationTrapPage(self.pane)
        # Keep a reference so it isn't garbage collected before navigation fires
        self.pane._pending_trap = trap
        return trap


class _NavigationTrapPage(QWebEnginePage):
    """Temporary page that captures the URL from a window.open() call
    and routes it through the project window's navigation policy."""

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

        self.pane._pending_trap = None
        return False


class WorkspacePane(QDockWidget):
    """One dockable view inside a ProjectWindow."""

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

        self.setWidget(self.web_view)

        url = descriptor.build_url(host, port, project_query_value)
        self.web_view.setUrl(QUrl(url))

    def page(self) -> PaneNavigationBridge:
        return self.web_view.page()

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

    def _reload_pane(self):
        self.setWidget(self.web_view)
        url = self.descriptor.build_url(self.host, self.port, self.project_query_value)
        self.web_view.setUrl(QUrl(url))

    def load_failed(self) -> bool:
        """Check if the web view widget has been replaced by an error overlay."""
        return self.widget() is not self.web_view
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/workspace_pane.py
git commit -m "feat: implement WorkspacePane and PaneNavigationBridge"
```

### Task 12: Implement ProjectWindow

**Files:**
- Create: `fontra_pak/project_window.py`

- [ ] **Step 1: Implement `project_window.py`**

```python
# fontra_pak/project_window.py
"""ProjectWindow: one top-level native editor window per font project.

Owns the internal workspace layout and manages dockable panes.
See spec section "Project Window" for the full contract.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from fontra_pak.dialogs import showMessageDialog
from fontra_pak.project_identity import encode_project_query_value
from fontra_pak.view_descriptor import ViewDescriptor
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
        self._suppress_close_confirm = False

        self.setWindowTitle(f"Fontra Pak — {project_path}")
        self.setDockNestingEnabled(True)

    def open_initial_pane(self):
        descriptor = ViewDescriptor.for_overview(self.project_key)
        self._create_pane(descriptor)

    def open_view(self, descriptor: ViewDescriptor, pane_instance_id: str | None = None):
        """Open or focus a pane matching the descriptor."""
        # Dedup: find existing matching pane (skip during restore when ID is given)
        if pane_instance_id is None:
            matching = [p for p in self.panes if p.descriptor.matches(descriptor)]
            if matching:
                # Focus most recently focused matching pane
                pane = matching[-1]
                pane.raise_()
                pane.setFocus()
                self._active_pane = pane
                return

        self._create_pane(descriptor, pane_instance_id=pane_instance_id)

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

        pane.setAllowedAreas(
            Qt.DockWidgetArea.AllDockWidgetAreas
        )

        if self.panes:
            # Tabify with the last pane
            last_pane = self.panes[-1]
            self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, pane)
            self.tabifyDockWidget(last_pane, pane)
        else:
            self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, pane)

        self.panes.append(pane)
        self._active_pane = pane
        pane.raise_()
        pane.setFocus()

    def close_pane(self, pane: WorkspacePane):
        """Close a single pane. Reopen overview if last pane closed."""
        if pane in self.panes:
            self.panes.remove(pane)
        self.removeDockWidget(pane)
        pane.deleteLater()

        if self._active_pane is pane:
            self._active_pane = self.panes[-1] if self.panes else None

        # If last pane was closed, reopen overview
        if not self.panes:
            if pane.load_failed():
                # Error pane was the only pane — close the whole window
                self.close()
            else:
                self.open_initial_pane()

    def closeEvent(self, event):
        if self._suppress_close_confirm:
            event.accept()
            self.controller.unregister_project_window(self)
            return

        if self.project_key in self.controller.open_projects:
            response = showMessageDialog(
                f"Close project?",
                f"The project {self.project_path} is still open in Fontra.\n"
                "Closing this window will disconnect from the project.",
                buttons=QMessageBox.StandardButton.Close
                | QMessageBox.StandardButton.Cancel,
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
        """Replace all panes with a connection-lost error message."""
        for pane in list(self.panes):
            pane._show_error_overlay(
                "Connection to the Fontra server has been lost.\n"
                "You can try reloading after recovering the server, or close this window."
            )
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/project_window.py
git commit -m "feat: implement ProjectWindow with pane management and close guard"
```

### Task 13: Implement AppWorkspaceController

**Files:**
- Create: `fontra_pak/controller.py`

- [ ] **Step 1: Implement `controller.py`**

```python
# fontra_pak/controller.py
"""AppWorkspaceController: owns the project window registry and app-level state.

See spec section "App Workspace Controller" for the full contract.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pathlib

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWebEngineCore import QWebEngineProfile

from fontra_pak.dialogs import showMessageDialog
from fontra_pak.project_identity import (
    path_to_project_key,
    project_key_to_profile_dir_name,
)
from fontra_pak.project_window import ProjectWindow
from fontra_pak.view_descriptor import ViewDescriptor

logger = logging.getLogger(__name__)


class AppWorkspaceController:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.project_windows: dict[str, ProjectWindow] = {}
        self.open_projects: set[str] = set()
        self._recently_closed: set[str] = set()
        self._bulk_shutdown = False

    def open_project(self, path: str):
        """Open a project window for the given path, or focus if already open."""
        project_key = path_to_project_key(path)
        resolved_path = str(pathlib.Path(path).resolve())

        if project_key in self.project_windows:
            window = self.project_windows[project_key]
            window.raise_()
            window.activateWindow()
            return

        profile = self._create_profile(project_key)
        if profile is None:
            showMessageDialog(
                "Could not open project",
                f"Failed to initialize web profile for:\n{resolved_path}",
            )
            return

        window = ProjectWindow(
            project_key=project_key,
            project_path=resolved_path,
            profile=profile,
            host=self.host,
            port=self.port,
            controller=self,
        )
        self.project_windows[project_key] = window
        window.show()
        window.open_initial_pane()

    def focus_project(self, path: str):
        project_key = path_to_project_key(path)
        if project_key in self.project_windows:
            window = self.project_windows[project_key]
            window.raise_()
            window.activateWindow()

    def unregister_project_window(self, window: ProjectWindow):
        if window.project_key in self.project_windows:
            del self.project_windows[window.project_key]

    def mark_project_locally_closed(self, project_key: str):
        self.open_projects.discard(project_key)
        self._recently_closed.add(project_key)

    # --- Server callback handlers ---

    def handle_server_message(self, item):
        """Route a server callback to the appropriate handler."""
        action, arguments = item
        handler = getattr(self, f"_on_{action}", None)
        if handler is not None:
            handler(*arguments)
        else:
            logger.warning("Unknown server action: %s", action)

    def _on_projectOpened(self, project_identifier: str):
        project_key = self._canonicalize_identifier(project_identifier)
        if project_key is None:
            return
        self.open_projects.add(project_key)

    def _on_projectClosed(self, project_identifier: str):
        project_key = self._canonicalize_identifier(project_identifier)
        if project_key is None:
            return
        if project_key in self._recently_closed:
            self._recently_closed.discard(project_key)
            return
        self.open_projects.discard(project_key)

    def _on_exportAs(self, project_identifier: str, options: dict):
        project_key = self._canonicalize_identifier(project_identifier)
        if project_key is None:
            return
        window = self.project_windows.get(project_key)
        if window is not None:
            # Route to the launcher's export flow for now
            # (Phase 2 can move this into ProjectWindow)
            self._export_callback(project_identifier, options)

    def set_export_callback(self, callback):
        """Set the callback for export requests (delegates to launcher for MVP)."""
        self._export_callback = callback

    def _canonicalize_identifier(self, project_identifier: str) -> str | None:
        try:
            return path_to_project_key(project_identifier)
        except Exception:
            logger.warning(
                "Failed to canonicalize project identifier: %s", project_identifier
            )
            return None

    # --- Profile management ---

    def _create_profile(self, project_key: str) -> QWebEngineProfile | None:
        try:
            profile_dir_name = project_key_to_profile_dir_name(project_key)
            app_data = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            profile_path = os.path.join(app_data, "webprofiles", profile_dir_name)
            os.makedirs(profile_path, exist_ok=True)
            profile = QWebEngineProfile(profile_dir_name, None)
            profile.setPersistentStoragePath(profile_path)
            profile.setCachePath(os.path.join(profile_path, "cache"))
            return profile
        except Exception:
            logger.exception("Failed to create web profile for %s", project_key)
            return None

    # --- Quit handling ---

    def has_open_projects(self) -> bool:
        return bool(self.open_projects)

    def begin_bulk_shutdown(self):
        self._bulk_shutdown = True
        for window in list(self.project_windows.values()):
            window.suppress_close_confirm()

    def close_all_project_windows(self):
        for window in list(self.project_windows.values()):
            window.close()

    # --- Connection lost ---

    def notify_server_lost(self):
        for window in self.project_windows.values():
            window.show_connection_lost()
```

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/controller.py
git commit -m "feat: implement AppWorkspaceController with registry, callbacks, and profiles"
```

### Task 14: Wire the controller into the app lifecycle

**Files:**
- Modify: `fontra_pak/app.py`
- Modify: `fontra_pak/launcher.py`

- [ ] **Step 1: Update `app.py` to use AppWorkspaceController**

Replace the contents of `fontra_pak/app.py` with:

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
        """Handle macOS FileOpen events."""
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

    # Route server callbacks through the controller
    thread = callInNewThread(queueGetter, queue, controller.handle_server_message)

    # Wire export callback to launcher (MVP: launcher still owns export UI)
    controller.set_export_callback(mainWindow.exportAs)

    mainWindow.show()

    if "test-startup" in sys.argv:

        def delayedQuit():
            print("test-startup")
            app.quit()

        QTimer.singleShot(1500, delayedQuit)

    sys.exit(app.exec())
```

- [ ] **Step 2: Update `launcher.py` to use the controller**

In `FontraMainWidget.__init__`, accept and store the controller:

Change the constructor signature and the `openFile` calls:

```python
class FontraMainWidget(QMainWindow):
    def __init__(self, port, controller=None):
        super().__init__()
        self.port = port
        self.controller = controller
        self.openProjects = set()  # Keep for backward compat during transition
        # ... rest unchanged
```

Update `dropEvent` to route through controller when available:

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

Update `newFont` to route through controller:

In the `newFont` method, replace the `openFile` call at the end:

```python
        if os.path.exists(fontPath):
            if self.controller is not None:
                self.controller.open_project(fontPath)
            else:
                openFile(fontPath, self.port)
```

Update `closeEvent` to check controller for open projects:

```python
    def closeEvent(self, event):
        has_open = (
            self.controller.has_open_projects()
            if self.controller is not None
            else bool(self.openProjects)
        )
        if has_open:
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

            if self.controller is not None:
                self.controller.begin_bulk_shutdown()
                self.controller.close_all_project_windows()

        self.settings.setValue("size", self.size())
        self.settings.setValue("pos", self.pos())
```

Keep `messageFromServer`, `projectOpened`, `projectClosed` methods for now — the controller is the primary callback receiver since Task 14 Step 1 wired it, but the launcher methods remain as fallbacks until fully removed in a later cleanup.

- [ ] **Step 3: Verify the app runs**

Run: `python -m fontra_pak`

Expected: The launcher window appears. Dropping a font file opens a native project window with an embedded Fontra overview instead of launching the browser.

- [ ] **Step 4: Commit**

```bash
git add fontra_pak/app.py fontra_pak/launcher.py
git commit -m "feat: wire AppWorkspaceController into app lifecycle, replace browser handoff"
```

### Task 15: QtWebEngine smoke test

**Files:**
- Modify: `tests/test_startup.py`

- [ ] **Step 1: Update the startup test**

The existing test already runs the packaged binary with `test-startup`. It should still pass since the entry point is unchanged. Run it to confirm:

Run: `pytest tests/test_startup.py -v`

Expected: PASS (or skip if not on the target platform with a dist build).

- [ ] **Step 2: Commit (if any test changes were needed)**

```bash
git commit -m "test: verify startup test still passes with QtWebEngine"
```

---

## Phase 2: Workspace Shell

### Task 16: Multi-pane workspace with docking and tabification

**Files:**
- Modify: `fontra_pak/project_window.py`

The `ProjectWindow` already supports multiple panes via `open_view()` and tabification in Task 12. This task verifies the four known Fontra destinations work as internal pane targets.

- [ ] **Step 1: Add a menu bar to ProjectWindow for opening views**

Add a `_setup_menu_bar` method to `ProjectWindow.__init__`:

```python
    def __init__(self, ...):
        # ... existing init code ...
        self._setup_menu_bar()

    def _setup_menu_bar(self):
        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu("&View")

        view_menu.addAction("Font Overview", lambda: self.open_view(
            ViewDescriptor.for_overview(self.project_key)
        ))
        view_menu.addAction("Font Info", lambda: self.open_view(
            ViewDescriptor.for_fontinfo(self.project_key)
        ))
        view_menu.addAction("Application Settings", lambda: self.open_view(
            ViewDescriptor.for_applicationsettings(self.project_key)
        ))
```

- [ ] **Step 2: Verify multi-pane workflow**

Run: `python -m fontra_pak`

Manual test:
1. Drop a font file — project window opens with overview pane.
2. Use View menu to open Font Info — appears as a second tab.
3. Use View menu to open Application Settings — appears as a third tab.
4. Drag tabs to dock side-by-side.
5. Close a pane — remaining panes stay.
6. Close all panes — overview reopens automatically.

- [ ] **Step 3: Commit**

```bash
git add fontra_pak/project_window.py
git commit -m "feat: add View menu for opening panes, verify multi-pane docking"
```

### Task 17: Workspace persistence — save

**Files:**
- Create: `fontra_pak/persistence.py`
- Create: `tests/test_persistence.py`

- [ ] **Step 1: Write failing tests for persistence serialization**

```python
# tests/test_persistence.py
import json

from fontra_pak.persistence import (
    deserialize_workspace,
    serialize_project_record,
    serialize_workspace,
)
from fontra_pak.view_descriptor import ViewDescriptor


def test_serialize_project_record():
    panes = [
        {
            "pane_instance_id": "abc123",
            "descriptor": ViewDescriptor.for_overview("c:\\fonts\\demo.ufo").to_dict(),
        },
        {
            "pane_instance_id": "def456",
            "descriptor": ViewDescriptor.for_editor(
                "c:\\fonts\\demo.ufo", route_hash="#glyph=A"
            ).to_dict(),
        },
    ]
    record = serialize_project_record(
        project_key="c:\\fonts\\demo.ufo",
        project_path="C:\\Fonts\\Demo.ufo",
        active_pane_instance_id="def456",
        pane_records=panes,
        geometry=b"fake_geometry",
        dock_state=b"fake_dock_state",
    )
    assert record["project_key"] == "c:\\fonts\\demo.ufo"
    assert record["project_path"] == "C:\\Fonts\\Demo.ufo"
    assert record["active_pane_instance_id"] == "def456"
    assert len(record["pane_records"]) == 2


def test_serialize_workspace_round_trip():
    workspace = {
        "projects": [
            serialize_project_record(
                project_key="c:\\fonts\\demo.ufo",
                project_path="C:\\Fonts\\Demo.ufo",
                active_pane_instance_id="abc123",
                pane_records=[
                    {
                        "pane_instance_id": "abc123",
                        "descriptor": ViewDescriptor.for_overview(
                            "c:\\fonts\\demo.ufo"
                        ).to_dict(),
                    }
                ],
                geometry=b"geom",
                dock_state=b"dock",
            )
        ]
    }
    serialized = serialize_workspace(workspace)
    deserialized = deserialize_workspace(serialized)
    assert deserialized is not None
    assert len(deserialized["projects"]) == 1
    assert deserialized["projects"][0]["project_key"] == "c:\\fonts\\demo.ufo"


def test_deserialize_corrupt_returns_none():
    result = deserialize_workspace("not valid json {{{")
    assert result is None


def test_deserialize_missing_key_returns_none():
    result = deserialize_workspace(json.dumps({"wrong_key": []}))
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_persistence.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `persistence.py`**

```python
# fontra_pak/persistence.py
"""Workspace persistence: serialize and deserialize project records for QSettings.

See spec section "State Model > Persistence" for the full contract.
"""

from __future__ import annotations

import base64
import json
import logging

from fontra_pak.view_descriptor import ViewDescriptor

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
        descriptor_data = pane_record["descriptor"]
        descriptor = ViewDescriptor.from_dict(descriptor_data)
        if descriptor.page_path not in (
            "/fontoverview.html",
            "/editor.html",
            "/fontinfo.html",
            "/applicationsettings.html",
        ):
            return None
        return descriptor
    except (KeyError, TypeError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_persistence.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add fontra_pak/persistence.py tests/test_persistence.py
git commit -m "feat: implement workspace persistence serialization with tests"
```

### Task 18: Wire persistence into save and restore

**Files:**
- Modify: `fontra_pak/controller.py`
- Modify: `fontra_pak/app.py`

- [ ] **Step 1: Add save/restore methods to AppWorkspaceController**

Add to `fontra_pak/controller.py`:

```python
    def save_workspace(self, settings):
        """Persist all open project windows for restore on next launch."""
        from fontra_pak.persistence import serialize_project_record, serialize_workspace

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

        workspace = {"projects": project_records}
        settings.setValue("workspace", serialize_workspace(workspace))

    def restore_workspace(self, settings) -> list[str]:
        """Restore project windows from a previous clean shutdown.

        Returns a list of error messages for projects that failed to restore.
        """
        from fontra_pak.persistence import (
            deserialize_project_record,
            deserialize_workspace,
            validate_pane_record,
        )

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
                errors.append(f"Corrupt project record, skipped.")
                continue

            project_path = record["project_path"]
            if not os.path.exists(project_path):
                errors.append(f"Project path no longer exists: {project_path}")
                continue

            try:
                self.open_project(project_path)
            except Exception as e:
                errors.append(f"Failed to restore {project_path}: {e}")
                continue

            window = self.project_windows.get(record["project_key"])
            if window is None:
                continue

            # Restore geometry and dock state
            try:
                window.restoreGeometry(record["geometry"])
            except Exception:
                errors.append(f"Failed to restore geometry for {project_path}")

            # Restore additional panes beyond the initial overview
            for pane_record in record["pane_records"][1:]:
                descriptor = validate_pane_record(pane_record)
                if descriptor is not None:
                    window._create_pane(descriptor, pane_instance_id=pane_record.get("pane_instance_id"))

            # Restore dock state after all panes exist
            try:
                window.restoreState(record["dock_state"])
            except Exception:
                errors.append(f"Failed to restore dock layout for {project_path}")

            # Focus the active pane
            target_id = record["active_pane_instance_id"]
            if target_id:
                for pane in window.panes:
                    if pane.pane_instance_id == target_id:
                        pane.raise_()
                        pane.setFocus()
                        break

        return errors
```

Add `import os` to the top of `controller.py` if not already present.

- [ ] **Step 2: Update `app.py` to handle save/restore and startup arguments**

In `main()`, add workspace restore logic after creating the launcher window, and save on quit:

```python
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

    settings = QSettings("xyz.fontra", "FontraPak")

    def cleanup():
        # Save workspace before shutting down
        controller.save_workspace(settings)
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

    # Handle startup: explicit file arguments vs workspace restore
    file_args = [arg for arg in sys.argv[1:] if not arg.startswith("-") and os.path.exists(arg)]

    if file_args:
        for path in file_args:
            controller.open_project(path)
    elif "test-startup" not in sys.argv:
        errors = controller.restore_workspace(settings)
        if errors:
            from fontra_pak.dialogs import showMessageDialog
            showMessageDialog(
                "Some projects could not be restored",
                "\n".join(errors),
            )

    if "test-startup" in sys.argv:

        def delayedQuit():
            print("test-startup")
            app.quit()

        QTimer.singleShot(1500, delayedQuit)

    sys.exit(app.exec())
```

Add `import os` and `from PyQt6.QtCore import QSettings` to the imports in `app.py`.

- [ ] **Step 3: Verify save and restore**

Run: `python -m fontra_pak`

Manual test:
1. Open a project, open multiple panes, rearrange tabs.
2. Quit the app cleanly.
3. Re-launch — project window should restore with the same layout.

- [ ] **Step 4: Commit**

```bash
git add fontra_pak/controller.py fontra_pak/app.py
git commit -m "feat: implement workspace save and restore on clean shutdown"
```

### Task 19: Download handling

**Files:**
- Modify: `fontra_pak/workspace_pane.py`

- [ ] **Step 1: Add download handling to PaneNavigationBridge**

In `workspace_pane.py`, add a download handler to `WorkspacePane.__init__`:

```python
        # In WorkspacePane.__init__, after setting the page:
        profile.downloadRequested.connect(self._on_download_requested)
```

Add the download handler method to `WorkspacePane`:

```python
    def _on_download_requested(self, download):
        """Handle file downloads initiated by embedded views."""
        from PyQt6.QtWidgets import QFileDialog

        suggested_path = os.path.join(
            os.path.expanduser("~"),
            download.downloadFileName(),
        )
        save_path, _ = QFileDialog.getSaveFileName(
            self.project_window,
            "Save download",
            suggested_path,
        )
        if save_path:
            download.setDownloadDirectory(os.path.dirname(save_path))
            download.setDownloadFileName(os.path.basename(save_path))
            download.accept()
        else:
            download.cancel()
```

Add `import os` to the imports in `workspace_pane.py`.

- [ ] **Step 2: Commit**

```bash
git add fontra_pak/workspace_pane.py
git commit -m "feat: handle downloads from embedded views with native save dialog"
```

### Task 20: Run full test suite and verify

**Files:**
- No new files

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`

Expected: All tests pass:
- `test_fontra_client_bundling` — PASS
- `test_startup` — PASS (or skip)
- `test_project_identity` — PASS
- `test_view_descriptor` — PASS
- `test_routing` — PASS
- `test_persistence` — PASS

- [ ] **Step 2: Run the app and test the full workflow**

Run: `python -m fontra_pak`

Manual acceptance checklist (from spec "MVP Acceptance Boundary"):
1. Opening a project does NOT launch the system browser.
2. The editor window is owned by `Fontra Pak.exe` (check task manager).
3. One project = one window.
4. Panes can be tabbed, docked, and tiled.
5. All four Fontra pages work as internal destinations.
6. `window.open()` from embedded views creates panes, not browser windows.
7. External links (Help > Documentation in Fontra menu) open in browser.
8. Different projects use different web profiles.
9. Clean quit and relaunch restores the workspace.

- [ ] **Step 3: Commit any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during full integration testing"
```

---

## Post-Plan Notes

### What this plan does NOT cover (post-MVP / Phase 3)

- Crash-session restore
- Server health monitoring and connection-lost detection (the `notify_server_lost` method exists but is not wired to a health check)
- Moving export dialog execution into `ProjectWindow` (currently delegates to launcher)
- Polished title/focus behavior for the `_self` navigation edge case in application settings
- PyInstaller packaging verification (requires running `pyinstaller FontraPak.spec -y` and testing the dist build — depends on environment)
- macOS compatibility
- Windows file-type associations

### Key risk to validate early (Phase 1, Task 15)

After Task 14, manually verify that mouse-profile software sees the focused project window as belonging to `Fontra Pak.exe`. If it sees `QtWebEngineProcess.exe` instead, the entire approach needs re-evaluation before continuing to Phase 2.
