"""Dialog for adding or editing an app-managed host."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from pyommyssh.core.forwards import ForwardKind, PortForward
from pyommyssh.core.hosts import Host, HostSource

FORWARD_FIELD_HEIGHT = 64

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
    ) -> None:
        super().__init__(parent)
        self._original = host
        self._existingNames = set(existingNames or set())
        self.setWindowTitle("Edit host" if host else "Add host")

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
        form.addRow("Name", self.nameEdit)
        form.addRow("Hostname", self.hostnameEdit)
        form.addRow("User", self.userEdit)
        form.addRow("Port", self.portSpin)
        form.addRow("Identity file", identityRow)
        form.addRow("Proxy jump", self.proxyJumpEdit)
        form.addRow("Tags", self.tagsEdit)
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

    def accept(self) -> None:
        """Accept only when the fields describe a valid, uniquely named host."""
        error = self._validationError()
        if error:
            self.errorLabel.setText(error)
            return
        self.errorLabel.setText("")
        super().accept()

    def host(self) -> Host:
        """Build a Host from the current field values."""
        identity = self.identityEdit.text().strip()
        tags = [tag.strip() for tag in self.tagsEdit.text().split(",") if tag.strip()]
        return Host(
            name=self.nameEdit.text().strip(),
            hostname=self.hostnameEdit.text().strip(),
            user=self.userEdit.text().strip() or None,
            port=self.portSpin.value(),
            identityFile=Path(identity) if identity else None,
            proxyJump=self.proxyJumpEdit.text().strip() or None,
            tags=tags,
            forwards=self._parseForwards(),
            source=HostSource.APP,
        )
