"""Dialog for adding or editing an app-managed host."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ohmyssh.core.forwards import ForwardKind, PortForward
from ohmyssh.core.hosts import Host, HostSource
from ohmyssh.core.sshconfig import hostNameProblem
from ohmyssh.ui.globalSettingsDialog import (
    MAX_COUNT,
    MAX_SECONDS,
    makeOptionalSpin,
    makeTriStateCombo,
    optionalInt,
    setTriState,
    triState,
)

FORWARD_FIELD_HEIGHT = 64
SAVE_IN_SSH_CONFIG = "~/.ssh/config"
SAVE_IN_APP = "App only (hosts.toml)"

_FORWARD_LABELS = {
    ForwardKind.LOCAL: "Local forward",
    ForwardKind.REMOTE: "Remote forward",
    ForwardKind.DYNAMIC: "Dynamic forward",
}
_FORWARD_PLACEHOLDERS = {
    ForwardKind.LOCAL: "[bind_address:]port:host:hostport, one per line",
    ForwardKind.REMOTE: "[bind_address:]port:host:hostport, one per line",
    ForwardKind.DYNAMIC: "[bind_address:]port, one per line",
}


def _nonBlankLines(edit: QPlainTextEdit) -> list[str]:
    return [line.strip() for line in edit.toPlainText().splitlines() if line.strip()]


class HostDialog(QDialog):
    """Collects the fields of a Host and validates them before accepting.

    ``exec`` returns ``Accepted``, ``Rejected``, or ``DELETE`` when the user
    asked for the host to be removed or hidden instead.
    """

    DELETE = 2

    def __init__(
        self,
        host: Host | None = None,
        existingNames: set[str] | None = None,
        parent: QWidget | None = None,
        warn: Callable[[str], None] | None = None,
    ) -> None:
        """``warn`` shows a message the user must dismiss; it defaults to a popup on this dialog."""
        super().__init__(parent)
        self._original = host
        self._existingNames = set(existingNames or set())
        self._warn = warn or self._warnPopup
        self.setWindowTitle("Edit host" if host else "Add host")

        # New hosts go to ~/.ssh/config so plain ssh sees them; an existing host stays where it is.
        self.saveInCombo = QComboBox()
        self.saveInCombo.addItems([SAVE_IN_SSH_CONFIG, SAVE_IN_APP])
        if host is not None:
            self.saveInCombo.setCurrentIndex(0 if host.source == HostSource.SSH_CONFIG else 1)
            self.saveInCombo.setEnabled(False)
        self.aliasLabel = QLabel("")
        self.aliasLabel.setObjectName("aliasWarning")
        self.aliasLabel.setWordWrap(True)
        if host is not None and host.sharedWith:
            self.aliasLabel.setText(
                f"Also applies to {', '.join(host.sharedWith)}: they share this Host line in ~/.ssh/config"
            )
        self.aliasLabel.setVisible(bool(host is not None and host.sharedWith))

        self.nameEdit = QLineEdit()
        self.hostnameEdit = QLineEdit()
        self.userEdit = QLineEdit()
        self.portSpin = QSpinBox()
        self.portSpin.setRange(1, 65535)
        self.portSpin.setValue(22)
        self.identityEdit = QLineEdit()
        self.proxyJumpEdit = QLineEdit()
        self.tagsEdit = QLineEdit()
        self.tagsEdit.setPlaceholderText("comma separated")
        self.keepaliveSpin = makeOptionalSpin("Use global", MAX_SECONDS)
        self.keepaliveSpin.setSuffix(" s")
        self.keepaliveCountSpin = makeOptionalSpin("Use global", MAX_COUNT)
        self.compressionCombo = makeTriStateCombo(("Use global", "On", "Off"))
        self.localForwardsEdit = self._makeForwardEdit(ForwardKind.LOCAL)
        self.remoteForwardsEdit = self._makeForwardEdit(ForwardKind.REMOTE)
        self.dynamicForwardsEdit = self._makeForwardEdit(ForwardKind.DYNAMIC)
        self._forwardEdits = {
            ForwardKind.LOCAL: self.localForwardsEdit,
            ForwardKind.REMOTE: self.remoteForwardsEdit,
            ForwardKind.DYNAMIC: self.dynamicForwardsEdit,
        }
        self.errorLabel = QLabel("")
        self.errorLabel.setObjectName("errorLabel")

        browseButton = QPushButton("Browse...")
        browseButton.clicked.connect(self._browseIdentity)
        identityRow = QHBoxLayout()
        identityRow.addWidget(self.identityEdit)
        identityRow.addWidget(browseButton)

        form = QFormLayout(self)
        form.addRow("Save in", self.saveInCombo)
        form.addRow(self.aliasLabel)
        form.addRow("Name", self.nameEdit)
        form.addRow("Hostname", self.hostnameEdit)
        form.addRow("User", self.userEdit)
        form.addRow("Port", self.portSpin)
        form.addRow("Identity file", identityRow)
        form.addRow("Proxy jump", self.proxyJumpEdit)
        form.addRow("Tags", self.tagsEdit)
        form.addRow("Keepalive interval", self.keepaliveSpin)
        form.addRow("Keepalive count", self.keepaliveCountSpin)
        form.addRow("Compression", self.compressionCombo)
        form.addRow("Local forwards", self.localForwardsEdit)
        form.addRow("Remote forwards", self.remoteForwardsEdit)
        form.addRow("Dynamic forwards", self.dynamicForwardsEdit)
        form.addRow(self.errorLabel)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        isConfigHost = host is not None and host.source == HostSource.SSH_CONFIG
        self.deleteButton = QPushButton("Hide host" if isConfigHost else "Remove host")
        self.deleteButton.setToolTip(
            "Hide this host from the dashboard; ~/.ssh/config is not changed"
            if isConfigHost
            else "Delete this host from hosts.toml"
        )
        self.deleteButton.clicked.connect(lambda: self.done(self.DELETE))
        buttons.addButton(self.deleteButton, QDialogButtonBox.ButtonRole.DestructiveRole)
        self.deleteButton.setVisible(host is not None)
        form.addRow(buttons)

        if host is not None:
            self._prefill(host)

    def _makeForwardEdit(self, kind: ForwardKind) -> QPlainTextEdit:
        edit = QPlainTextEdit()
        edit.setPlaceholderText(_FORWARD_PLACEHOLDERS[kind])
        edit.setFixedHeight(FORWARD_FIELD_HEIGHT)
        edit.setTabChangesFocus(True)
        return edit

    def _prefill(self, host: Host) -> None:
        self.nameEdit.setText(host.name)
        self.hostnameEdit.setText(host.hostname)
        self.userEdit.setText(host.user or "")
        self.portSpin.setValue(host.port)
        self.identityEdit.setText(str(host.identityFile) if host.identityFile else "")
        self.proxyJumpEdit.setText(host.proxyJump or "")
        self.tagsEdit.setText(", ".join(host.tags))
        if host.serverAliveInterval is not None:
            self.keepaliveSpin.setValue(host.serverAliveInterval)
        if host.serverAliveCountMax is not None:
            self.keepaliveCountSpin.setValue(host.serverAliveCountMax)
        setTriState(self.compressionCombo, host.compression)
        for kind, edit in self._forwardEdits.items():
            edit.setPlainText("\n".join(f.spec() for f in host.forwards if f.kind == kind))

    def _parseForwards(self) -> list[PortForward]:
        """Read every forward field; a bad line raises ValueError naming its kind."""
        forwards: list[PortForward] = []
        for kind, edit in self._forwardEdits.items():
            for line in _nonBlankLines(edit):
                try:
                    forwards.append(PortForward.parse(kind, line))
                except ValueError as error:
                    raise ValueError(f"{_FORWARD_LABELS[kind]}: {error}") from error
        return forwards

    def _browseIdentity(self) -> None:
        startDir = str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, "Choose identity file", startDir)
        if path:
            self.identityEdit.setText(path)

    def _validationError(self) -> str | None:
        name = self.nameEdit.text().strip()
        if not name:
            return "Name is required"
        originalName = self._original.name if self._original else None
        if name != originalName and name in self._existingNames:
            return f"A host named '{name}' already exists"
        if not self.hostnameEdit.text().strip():
            return "Hostname is required"
        try:
            self._parseForwards()
        except ValueError as error:
            return str(error)
        return None

    def _warnPopup(self, message: str) -> None:
        QMessageBox.warning(self, "Host name", message)

    def _nameProblem(self) -> str | None:
        """Why the name cannot go into ~/.ssh/config, or None; an app-stored host can be called anything."""
        name = self.nameEdit.text().strip()
        if not name or not self.saveToSshConfig():
            return None
        return hostNameProblem(name)

    def accept(self) -> None:
        """Accept only when the fields describe a valid, uniquely named host.

        A name ssh cannot hold gets a popup, since the rule needs explaining;
        the other problems are shown inline under the fields.
        """
        error = self._nameProblem()
        if error:
            self.errorLabel.setText(error)
            self._warn(error)
            return
        error = self._validationError()
        if error:
            self.errorLabel.setText(error)
            return
        self.errorLabel.setText("")
        super().accept()

    def saveToSshConfig(self) -> bool:
        """True when the host belongs in ~/.ssh/config rather than hosts.toml."""
        return self.saveInCombo.currentIndex() == 0

    def host(self) -> Host:
        """Build a Host from the current field values.

        An edited SSH config host keeps the file and shared names it came
        with, so it is written back to the right block.
        """
        identity = self.identityEdit.text().strip()
        tags = [tag.strip() for tag in self.tagsEdit.text().split(",") if tag.strip()]
        original = self._original
        return Host(
            name=self.nameEdit.text().strip(),
            hostname=self.hostnameEdit.text().strip(),
            user=self.userEdit.text().strip() or None,
            port=self.portSpin.value(),
            identityFile=Path(identity) if identity else None,
            proxyJump=self.proxyJumpEdit.text().strip() or None,
            tags=tags,
            forwards=self._parseForwards(),
            source=HostSource.SSH_CONFIG if self.saveToSshConfig() else HostSource.APP,
            sourceFile=original.sourceFile if original is not None else None,
            sharedWith=list(original.sharedWith) if original is not None else [],
            serverAliveInterval=optionalInt(self.keepaliveSpin),
            serverAliveCountMax=optionalInt(self.keepaliveCountSpin),
            compression=triState(self.compressionCombo),
        )
