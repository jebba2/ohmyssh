"""Tests for the add/edit host dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from pyommyssh.core.hosts import Host, HostSource
from pyommyssh.ui.hostDialog import HostDialog


def test_new_host_from_fields(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = HostDialog(existingNames={"other"})
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Add host"
    dialog.nameEdit.setText("web")
    dialog.hostnameEdit.setText("10.0.0.5")
    dialog.userEdit.setText("deploy")
    dialog.portSpin.setValue(2222)
    dialog.identityEdit.setText(str(tmp_path / "key"))
    dialog.proxyJumpEdit.setText("bastion")
    dialog.tagsEdit.setText("prod, web ,, ")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.host() == Host(
        name="web",
        hostname="10.0.0.5",
        user="deploy",
        port=2222,
        identityFile=tmp_path / "key",
        proxyJump="bastion",
        tags=["prod", "web"],
        source=HostSource.APP,
    )


def test_blank_optional_fields_become_none(qtbot: QtBot) -> None:
    dialog = HostDialog(existingNames=set())
    qtbot.addWidget(dialog)
    dialog.nameEdit.setText("box")
    dialog.hostnameEdit.setText("box.local")
    dialog.accept()
    host = dialog.host()
    assert host.user is None
    assert host.port == 22
    assert host.identityFile is None
    assert host.proxyJump is None
    assert host.tags == []


def test_edit_prefills_fields(qtbot: QtBot, tmp_path: Path) -> None:
    existing = Host(
        name="db",
        hostname="db.local",
        user="pg",
        port=5432,
        identityFile=tmp_path / "id",
        proxyJump="jump",
        tags=["data"],
        source=HostSource.APP,
    )
    dialog = HostDialog(host=existing, existingNames={"db", "web"})
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Edit host"
    assert dialog.nameEdit.text() == "db"
    assert dialog.hostnameEdit.text() == "db.local"
    assert dialog.userEdit.text() == "pg"
    assert dialog.portSpin.value() == 5432
    assert dialog.identityEdit.text() == str(tmp_path / "id")
    assert dialog.proxyJumpEdit.text() == "jump"
    assert dialog.tagsEdit.text() == "data"
    # Keeping its own name is allowed when editing.
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_validation_blocks_accept(qtbot: QtBot) -> None:
    dialog = HostDialog(existingNames={"taken"})
    qtbot.addWidget(dialog)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.errorLabel.text() == "Name is required"

    dialog.nameEdit.setText("taken")
    dialog.accept()
    assert dialog.errorLabel.text() == "A host named 'taken' already exists"

    dialog.nameEdit.setText("fresh")
    dialog.accept()
    assert dialog.errorLabel.text() == "Hostname is required"

    dialog.hostnameEdit.setText("fresh.local")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
