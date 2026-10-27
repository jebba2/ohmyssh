"""Dialog that collects what a new SSH key pair should look like and where it goes."""

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
    QPushButton,
    QWidget,
)

from ohmyssh.core.keys import KeyGenerateRequest, KeyType, defaultKeyComment, defaultKeyFileName
from ohmyssh.ui.comboBox import ComboBox

KEY_TYPE_LABELS = {
    KeyType.ED25519: "Ed25519 (recommended)",
    KeyType.RSA: "RSA 4096",
}


class KeyGenerateDialog(QDialog):
    """Asks for key type, comment, save location, and an optional passphrase."""

    def __init__(self, defaultDir: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate SSH key")
        self._defaultDir = defaultDir or Path.home() / ".ssh"

        self.typeCombo = ComboBox()
        for keyType, label in KEY_TYPE_LABELS.items():
            self.typeCombo.addItem(label, keyType)
        self.commentEdit = QLineEdit(defaultKeyComment())
        self.pathEdit = QLineEdit(str(self._defaultPath()))
        self.passphraseEdit = QLineEdit()
        self.passphraseEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphraseEdit.setPlaceholderText("optional")
        self.confirmEdit = QLineEdit()
        self.confirmEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.errorLabel = QLabel("")
        self.errorLabel.setObjectName("errorLabel")
        self.typeCombo.currentIndexChanged.connect(self._onTypeChanged)

        browseButton = QPushButton("Browse...")
        browseButton.clicked.connect(self._browsePath)
        pathRow = QHBoxLayout()
        pathRow.addWidget(self.pathEdit)
        pathRow.addWidget(browseButton)

        form = QFormLayout(self)
        form.addRow("Key type", self.typeCombo)
        form.addRow("Comment", self.commentEdit)
        form.addRow("Save as", pathRow)
        form.addRow("Passphrase", self.passphraseEdit)
        form.addRow("Confirm passphrase", self.confirmEdit)
        form.addRow(QLabel("The public key is written beside it with a .pub extension."))
        form.addRow(self.errorLabel)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _selectedType(self) -> KeyType:
        keyType = self.typeCombo.currentData()
        return keyType if isinstance(keyType, KeyType) else KeyType.ED25519

    def _defaultPath(self, keyType: KeyType = KeyType.ED25519) -> Path:
        return self._defaultDir / defaultKeyFileName(keyType)

    def _onTypeChanged(self) -> None:
        """Follow the type with the default file name unless the user chose their own."""
        defaults = {str(self._defaultPath(keyType)) for keyType in KeyType}
        if self.pathEdit.text().strip() in defaults:
            self.pathEdit.setText(str(self._defaultPath(self._selectedType())))

    def _browsePath(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save private key as", self.pathEdit.text() or str(self._defaultDir)
        )
        if path:
            self.pathEdit.setText(path)

    def _validationError(self) -> str | None:
        rawPath = self.pathEdit.text().strip()
        if not rawPath:
            return "Choose where to save the key"
        privatePath = Path(rawPath)
        for path in (privatePath, privatePath.with_name(privatePath.name + ".pub")):
            if path.exists():
                return f"{path} already exists"
        if self.passphraseEdit.text() != self.confirmEdit.text():
            return "Passphrases do not match"
        return None

    def accept(self) -> None:
        """Accept only when the location is free and the passphrase is confirmed."""
        error = self._validationError()
        if error:
            self.errorLabel.setText(error)
            return
        self.errorLabel.setText("")
        super().accept()

    def request(self) -> KeyGenerateRequest:
        """Build the generation request from the current field values."""
        return KeyGenerateRequest(
            privatePath=Path(self.pathEdit.text().strip()),
            keyType=self._selectedType(),
            comment=self.commentEdit.text().strip(),
            passphrase=self.passphraseEdit.text() or None,
        )
