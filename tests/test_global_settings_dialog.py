"""Tests for the global SSH settings dialog that edits the Host * block."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from pyommyssh.core.hosts import GlobalSettings
from pyommyssh.ui.globalSettingsDialog import GlobalSettingsDialog


def test_empty_settings_show_as_not_set(qtbot: QtBot) -> None:
    dialog = GlobalSettingsDialog(GlobalSettings())
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "SSH defaults"
    assert dialog.keepaliveSpin.value() == -1
    assert dialog.keepaliveSpin.text() == "Not set"
    assert dialog.keepaliveCountSpin.text() == "Not set"
    assert dialog.identityEdit.text() == ""
    assert dialog.compressionCombo.currentText() == "Not set"
    assert "end of ~/.ssh/config" in dialog.noteLabel.text()
    assert "ServerAliveCountMax" in dialog.noteLabel.text()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.settings() == GlobalSettings()


def test_fields_round_trip(qtbot: QtBot, tmp_path: Path) -> None:
    initial = GlobalSettings(
        serverAliveInterval=60, serverAliveCountMax=3, identityFile=tmp_path / "id_rsa", compression=True
    )
    dialog = GlobalSettingsDialog(initial)
    qtbot.addWidget(dialog)
    assert dialog.keepaliveSpin.value() == 60
    assert dialog.keepaliveCountSpin.value() == 3
    assert dialog.identityEdit.text() == str(tmp_path / "id_rsa")
    assert dialog.compressionCombo.currentText() == "On"
    assert dialog.settings() == initial

    dialog.keepaliveSpin.setValue(30)
    dialog.keepaliveCountSpin.setValue(-1)
    dialog.identityEdit.setText("")
    dialog.compressionCombo.setCurrentIndex(dialog.compressionCombo.findText("Off"))
    assert dialog.settings() == GlobalSettings(serverAliveInterval=30, compression=False)
