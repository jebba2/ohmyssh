"""Dialog for the defaults every host inherits: the ``Host *`` block of ~/.ssh/config."""

from __future__ import annotations

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
    QPushButton,
    QSpinBox,
    QWidget,
)

from ohmyssh.core.hosts import GlobalSettings

NOT_SET = -1
MAX_SECONDS = 86400
MAX_COUNT = 1000
COMPRESSION_CHOICES = ("Not set", "On", "Off")


def makeOptionalSpin(unsetText: str, maximum: int) -> QSpinBox:
    """A spin box whose lowest value stands for "no value"."""
    spin = QSpinBox()
    spin.setRange(NOT_SET, maximum)
    spin.setSpecialValueText(unsetText)
    spin.setValue(NOT_SET)
    return spin


def optionalInt(spin: QSpinBox) -> int | None:
    """The spin box's value, or None at its "no value" position."""
    return None if spin.value() == NOT_SET else spin.value()


def makeTriStateCombo(choices: tuple[str, str, str]) -> QComboBox:
    """A combo for unset / yes / no, in that order."""
    combo = QComboBox()
    combo.addItems(list(choices))
    return combo


def triState(combo: QComboBox) -> bool | None:
    """None for the first choice, True for the second, False for the third."""
    index = combo.currentIndex()
    return None if index <= 0 else index == 1


def setTriState(combo: QComboBox, value: bool | None) -> None:
    combo.setCurrentIndex(0 if value is None else (1 if value else 2))


class GlobalSettingsDialog(QDialog):
    """Edits keepalive, identity file, and compression defaults."""

    def __init__(self, settings: GlobalSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSH defaults")

        self.keepaliveSpin = makeOptionalSpin("Not set", MAX_SECONDS)
        self.keepaliveSpin.setSuffix(" s")
        self.keepaliveCountSpin = makeOptionalSpin("Not set", MAX_COUNT)
        self.identityEdit = QLineEdit()
        self.compressionCombo = makeTriStateCombo(COMPRESSION_CHOICES)
        self.noteLabel = QLabel(
            "Saved as the Host * block at the end of ~/.ssh/config, so each host's own settings win. "
            "ServerAliveCountMax is written for ssh only; the app's connections use the interval."
        )
        self.noteLabel.setWordWrap(True)
        self.noteLabel.setObjectName("hostAddress")

        browseButton = QPushButton("Browse...")
        browseButton.clicked.connect(self._browseIdentity)
        identityRow = QHBoxLayout()
        identityRow.addWidget(self.identityEdit)
        identityRow.addWidget(browseButton)

        form = QFormLayout(self)
        form.addRow("Keepalive interval", self.keepaliveSpin)
        form.addRow("Keepalive count", self.keepaliveCountSpin)
        form.addRow("Identity file", identityRow)
        form.addRow("Compression", self.compressionCombo)
        form.addRow(self.noteLabel)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if settings.serverAliveInterval is not None:
            self.keepaliveSpin.setValue(settings.serverAliveInterval)
        if settings.serverAliveCountMax is not None:
            self.keepaliveCountSpin.setValue(settings.serverAliveCountMax)
        self.identityEdit.setText(str(settings.identityFile) if settings.identityFile else "")
        setTriState(self.compressionCombo, settings.compression)

    def _browseIdentity(self) -> None:
        startDir = str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, "Choose identity file", startDir)
        if path:
            self.identityEdit.setText(path)

    def settings(self) -> GlobalSettings:
        """Build the settings from the current field values."""
        identity = self.identityEdit.text().strip()
        return GlobalSettings(
            serverAliveInterval=optionalInt(self.keepaliveSpin),
            serverAliveCountMax=optionalInt(self.keepaliveCountSpin),
            identityFile=Path(identity) if identity else None,
            compression=triState(self.compressionCombo),
        )
