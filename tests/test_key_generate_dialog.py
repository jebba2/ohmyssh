"""Tests for the generate-key dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from pyommyssh.core.keys import KeyType
from pyommyssh.ui.keyGenerateDialog import KeyGenerateDialog, KeyGenerateRequest


def test_defaults_point_at_an_ed25519_key_in_the_ssh_dir(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = KeyGenerateDialog(defaultDir=tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Generate SSH key"
    assert dialog.typeCombo.currentData() == KeyType.ED25519
    assert dialog.pathEdit.text() == str(tmp_path / "id_ed25519")
    assert "@" in dialog.commentEdit.text()
    assert dialog.passphraseEdit.text() == ""
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    request = dialog.request()
    assert request == KeyGenerateRequest(
        privatePath=tmp_path / "id_ed25519",
        keyType=KeyType.ED25519,
        comment=dialog.commentEdit.text(),
        passphrase=None,
    )


def test_changing_the_type_renames_an_untouched_path(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = KeyGenerateDialog(defaultDir=tmp_path)
    qtbot.addWidget(dialog)
    dialog.typeCombo.setCurrentIndex(dialog.typeCombo.findData(KeyType.RSA))
    assert dialog.pathEdit.text() == str(tmp_path / "id_rsa")
    dialog.pathEdit.setText(str(tmp_path / "work_key"))
    dialog.typeCombo.setCurrentIndex(dialog.typeCombo.findData(KeyType.ED25519))
    assert dialog.pathEdit.text() == str(tmp_path / "work_key")
    dialog.accept()
    assert dialog.request().keyType == KeyType.ED25519
    assert dialog.request().privatePath == tmp_path / "work_key"


def test_passphrase_must_be_confirmed(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = KeyGenerateDialog(defaultDir=tmp_path)
    qtbot.addWidget(dialog)
    dialog.passphraseEdit.setText("secret")
    dialog.confirmEdit.setText("secrte")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.errorLabel.text() == "Passphrases do not match"
    dialog.confirmEdit.setText("secret")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.request().passphrase == "secret"


def test_existing_files_and_blank_path_block_accept(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = KeyGenerateDialog(defaultDir=tmp_path)
    qtbot.addWidget(dialog)
    dialog.pathEdit.setText("")
    dialog.accept()
    assert dialog.errorLabel.text() == "Choose where to save the key"

    (tmp_path / "id_ed25519.pub").write_text("taken\n")
    dialog.pathEdit.setText(str(tmp_path / "id_ed25519"))
    dialog.accept()
    assert dialog.errorLabel.text() == f"{tmp_path / 'id_ed25519.pub'} already exists"
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog.pathEdit.setText(str(tmp_path / "fresh"))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_blank_comment_is_kept_blank(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = KeyGenerateDialog(defaultDir=tmp_path)
    qtbot.addWidget(dialog)
    dialog.commentEdit.setText("   ")
    dialog.accept()
    assert dialog.request().comment == ""
