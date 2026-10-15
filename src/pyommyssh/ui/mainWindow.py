"""The main window: dashboard tab plus one tab per open terminal."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTabBar,
    QTabWidget,
    QToolBar,
    QWidget,
)

from pyommyssh.core.config import AppSettings
from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.hosts import Host, HostStore, mergeHosts
from pyommyssh.core.metrics import HostMetrics
from pyommyssh.core.ssh import SshCredentials
from pyommyssh.ui.dashboard import DashboardView
from pyommyssh.ui.hostDialog import HostDialog
from pyommyssh.ui.searchDialog import SearchDialog, SearchEntry
from pyommyssh.ui.terminalTab import TerminalTab
from pyommyssh.ui.workers import MetricsWorker

PasswordPrompt = Callable[[Host], str | None]
PASSWORD_REQUIRED = "Password required"
MAX_CONCURRENT_CONNECTIONS = 10
WORKER_SHUTDOWN_TIMEOUT_MS = 15000


def askPasswordWithDialog(parent: QWidget) -> PasswordPrompt:
    """Return a prompt that asks for a password in a modal dialog."""

    def prompt(host: Host) -> str | None:
        text, accepted = QInputDialog.getText(
            parent,
            "Password",
            f"Password for {host.displayAddress()}",
            QLineEdit.EchoMode.Password,
        )
        return text if accepted and text else None

    return prompt


class MainWindow(QMainWindow):
    """Wires hosts, the connection pool, the dashboard, and terminal tabs together."""

    def __init__(
        self,
        settings: AppSettings,
        hostStore: HostStore,
        sshConfigHosts: list[Host],
        knownHostsPath: Path | None,
        passwordPrompt: PasswordPrompt | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._hostStore = hostStore
        self._sshConfigHosts = list(sshConfigHosts)
        self._pool = ConnectionPool(self.hosts, knownHostsPath)
        self._passwordPrompt = passwordPrompt or askPasswordWithDialog(self)
        self._authDeclined: set[str] = set()
        self._liveSignals: set[QObject] = set()
        self._shuttingDown = False
        self._threadPool = QThreadPool(self)
        self._threadPool.setMaxThreadCount(MAX_CONCURRENT_CONNECTIONS)

        self.setWindowTitle("pyommyssh")
        self.resize(1100, 720)

        self.dashboard = DashboardView()
        self.dashboard.openTerminalRequested.connect(self.openTerminal)
        self.dashboard.editRequested.connect(self._editHostDialog)
        self.dashboard.removeRequested.connect(self._confirmRemove)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.closeTab)
        self.tabs.addTab(self.dashboard, "Dashboard")
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        self.setCentralWidget(self.tabs)

        self._buildToolbar()
        self._refreshTimer = QTimer(self)
        self._refreshTimer.setInterval(settings.refreshIntervalSeconds * 1000)
        self._refreshTimer.timeout.connect(self.refreshAll)
        self._refreshTimer.start()

        self.dashboard.setHosts(self.hosts())
        self.statusBar().showMessage(f"{len(self.hosts())} hosts")

    def _buildToolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.addHostAction = QAction("Add host", self)
        self.addHostAction.setShortcut(QKeySequence("Ctrl+N"))
        self.addHostAction.triggered.connect(self._addHostDialog)

        self.refreshAction = QAction("Refresh", self)
        self.refreshAction.setShortcut(QKeySequence("F5"))
        self.refreshAction.triggered.connect(lambda: self.refreshAll(retryDeclined=True))

        self.groupByTagAction = QAction("Group by tag", self)
        self.groupByTagAction.setCheckable(True)
        self.groupByTagAction.toggled.connect(self.dashboard.setGroupByTag)

        self.searchAction = QAction("Search", self)
        self.searchAction.setShortcut(QKeySequence("Ctrl+K"))
        self.searchAction.triggered.connect(self.showSearch)

        for action in (self.addHostAction, self.refreshAction, self.groupByTagAction, self.searchAction):
            toolbar.addAction(action)

    # Hosts

    def hosts(self) -> list[Host]:
        """Return every known host: SSH config first, then app-managed ones."""
        return mergeHosts(self._sshConfigHosts, self._hostStore.hosts())

    def _hostNamed(self, name: str) -> Host | None:
        return next((host for host in self.hosts() if host.name == name), None)

    def _hostsChanged(self) -> None:
        self.dashboard.setHosts(self.hosts())
        self.statusBar().showMessage(f"{len(self.hosts())} hosts")

    def saveNewHost(self, host: Host) -> None:
        """Add a host to the store and the dashboard."""
        self._hostStore.add(host)
        self._hostStore.save()
        self._hostsChanged()

    def saveEditedHost(self, oldName: str, host: Host) -> None:
        """Replace a stored host; any live connection under the old name is dropped."""
        self._hostStore.update(oldName, host)
        self._hostStore.save()
        self._pool.forget(oldName)
        self._hostsChanged()

    def removeHost(self, host: Host) -> None:
        """Delete a stored host and close its connection."""
        self._hostStore.remove(host.name)
        self._hostStore.save()
        self._pool.forget(host.name)
        self._hostsChanged()

    def _addHostDialog(self) -> None:
        dialog = HostDialog(existingNames={host.name for host in self.hosts()}, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            host = dialog.host()
            self.saveNewHost(host)
            self.refreshHost(host)

    def _editHostDialog(self, host: Host) -> None:
        names = {candidate.name for candidate in self.hosts()}
        dialog = HostDialog(host=host, existingNames=names, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            edited = dialog.host()
            self.saveEditedHost(host.name, edited)
            self.refreshHost(edited)

    def _confirmRemove(self, host: Host) -> None:
        answer = QMessageBox.question(self, "Remove host", f"Remove '{host.name}'?")
        if answer == QMessageBox.StandardButton.Yes:
            self.removeHost(host)

    # Credentials

    def _promptCredentials(self, host: Host) -> bool:
        """Ask for a password once; a cancelled prompt is remembered."""
        if host.name in self._authDeclined:
            return False
        password = self._passwordPrompt(host)
        if password is None:
            self._authDeclined.add(host.name)
            return False
        self._pool.setCredentials(host.name, SshCredentials(password=password))
        return True

    # Metrics

    def refreshAll(self, retryDeclined: bool = False) -> None:
        """Probe every host. Manual refreshes retry hosts whose prompt was cancelled."""
        if retryDeclined:
            self._authDeclined.clear()
        for host in self.hosts():
            self.refreshHost(host)

    def refreshHost(self, host: Host) -> None:
        """Probe one host in the background and show the outcome on its card."""
        if host.name in self._authDeclined:
            self.dashboard.showError(host.name, PASSWORD_REQUIRED)
            return
        self.dashboard.showConnecting(host.name)
        worker = MetricsWorker(host, self._pool)
        signals = worker.signals
        self._liveSignals.add(signals)
        signals.metricsReady.connect(self._onMetrics)
        signals.metricsFailed.connect(self._onMetricsFailed)
        signals.authRequired.connect(self._onAuthRequired)
        for signal in (signals.metricsReady, signals.metricsFailed, signals.authRequired):
            signal.connect(lambda *_, s=signals: self._liveSignals.discard(s))
        self._threadPool.start(worker)

    def _onMetrics(self, name: str, metrics: HostMetrics) -> None:
        if not self._shuttingDown:
            self.dashboard.showMetrics(name, metrics)

    def _onMetricsFailed(self, name: str, message: str) -> None:
        if not self._shuttingDown:
            self.dashboard.showError(name, message)

    def _onAuthRequired(self, name: str) -> None:
        host = self._hostNamed(name)
        if host is None or self._shuttingDown:
            return
        if self._promptCredentials(host):
            self.refreshHost(host)
        else:
            self.dashboard.showError(name, PASSWORD_REQUIRED)

    # Terminals

    def terminalTabs(self) -> list[TerminalTab]:
        """Return the open terminal tabs in tab order."""
        return [
            widget
            for widget in (self.tabs.widget(i) for i in range(self.tabs.count()))
            if isinstance(widget, TerminalTab)
        ]

    def openTerminal(self, host: Host) -> None:
        """Open a new tab with a shell on the host."""
        tab = TerminalTab(host, self._pool, self._threadPool, self._settings.terminalFontSize)
        tab.authRequired.connect(lambda: self._onTabAuthRequired(tab))
        tab.titleChanged.connect(lambda title: self.tabs.setTabText(self.tabs.indexOf(tab), title))
        index = self.tabs.addTab(tab, host.name)
        self.tabs.setCurrentIndex(index)
        tab.start()

    def _onTabAuthRequired(self, tab: TerminalTab) -> None:
        if self._promptCredentials(tab.host):
            tab.start()
        else:
            tab.showStatus(PASSWORD_REQUIRED)

    def closeTab(self, index: int) -> None:
        """Close a terminal tab; the dashboard tab stays."""
        widget = self.tabs.widget(index)
        if not isinstance(widget, TerminalTab):
            return
        self.tabs.removeTab(index)
        widget.shutdown()
        widget.deleteLater()

    # Search

    def searchEntries(self) -> list[SearchEntry]:
        """Hosts to open plus terminal tabs to switch to."""
        entries = [SearchEntry(kind="host", label=host.name, host=host) for host in self.hosts()]
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, TerminalTab):
                label = f"{widget.host.name} (tab {index})"
                entries.append(SearchEntry(kind="session", label=label, host=widget.host, tabIndex=index))
        return entries

    def showSearch(self) -> None:
        """Open the Ctrl+K palette and act on the chosen entry."""
        dialog = SearchDialog(self.searchEntries(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        entry = dialog.selectedEntry()
        if entry is None:
            return
        if entry.kind == "session" and entry.tabIndex is not None:
            self.tabs.setCurrentIndex(entry.tabIndex)
        else:
            self.openTerminal(entry.host)

    # Lifecycle

    def shutdown(self) -> None:
        """Stop polling, close terminals, and drop every connection.

        Queued workers are discarded. Workers already running finish once
        their connection is closed under them, and their results are ignored.
        """
        self._shuttingDown = True
        self._refreshTimer.stop()
        self._threadPool.clear()
        for tab in self.terminalTabs():
            tab.shutdown()
        self._pool.closeAll()
        self._threadPool.waitForDone(WORKER_SHUTDOWN_TIMEOUT_MS)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)
