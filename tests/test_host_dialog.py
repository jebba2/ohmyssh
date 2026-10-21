"""Tests for the add/edit host dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from pyommyssh.core.forwards import ForwardKind, PortForward
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


def test_delete_button_only_when_editing_and_names_the_action(qtbot: QtBot) -> None:
    adding = HostDialog(existingNames=set())
    qtbot.addWidget(adding)
    assert adding.deleteButton.isHidden()

    appHost = Host(name="mine", hostname="m.local", source=HostSource.APP)
    editingApp = HostDialog(host=appHost, existingNames={"mine"})
    qtbot.addWidget(editingApp)
    assert not editingApp.deleteButton.isHidden()
    assert editingApp.deleteButton.text() == "Remove host"
    editingApp.deleteButton.click()
    assert editingApp.result() == HostDialog.DELETE

    configHost = Host(name="cfg", hostname="c.local", source=HostSource.SSH_CONFIG)
    editingConfig = HostDialog(host=configHost, existingNames={"cfg"})
    qtbot.addWidget(editingConfig)
    assert editingConfig.deleteButton.text() == "Hide host"
    editingConfig.deleteButton.click()
    assert editingConfig.result() == HostDialog.DELETE


def test_forward_fields_build_rules_in_kind_order(qtbot: QtBot) -> None:
    dialog = HostDialog(existingNames=set())
    qtbot.addWidget(dialog)
    dialog.nameEdit.setText("web")
    dialog.hostnameEdit.setText("web.local")
    dialog.localForwardsEdit.setPlainText("8080:localhost:80\n\n  5432:db.internal:5432  \n")
    dialog.remoteForwardsEdit.setPlainText("9000:127.0.0.1:3000")
    dialog.dynamicForwardsEdit.setPlainText("1080")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.host().forwards == [
        PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80"),
        PortForward.parse(ForwardKind.LOCAL, "5432:db.internal:5432"),
        PortForward.parse(ForwardKind.REMOTE, "9000:127.0.0.1:3000"),
        PortForward.parse(ForwardKind.DYNAMIC, "1080"),
    ]


def test_blank_forward_fields_mean_no_forwards(qtbot: QtBot) -> None:
    dialog = HostDialog(existingNames=set())
    qtbot.addWidget(dialog)
    dialog.nameEdit.setText("box")
    dialog.hostnameEdit.setText("box.local")
    dialog.accept()
    assert dialog.host().forwards == []


def test_edit_prefills_forwards_by_kind(qtbot: QtBot) -> None:
    existing = Host(
        name="web",
        hostname="web.local",
        forwards=[
            PortForward.parse(ForwardKind.DYNAMIC, "1080"),
            PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80"),
            PortForward.parse(ForwardKind.REMOTE, "9000:127.0.0.1:3000"),
            PortForward.parse(ForwardKind.LOCAL, "[::1]:5432:db:5432"),
        ],
        source=HostSource.APP,
    )
    dialog = HostDialog(host=existing, existingNames={"web"})
    qtbot.addWidget(dialog)
    assert dialog.localForwardsEdit.toPlainText() == "8080:localhost:80\n[::1]:5432:db:5432"
    assert dialog.remoteForwardsEdit.toPlainText() == "9000:127.0.0.1:3000"
    assert dialog.dynamicForwardsEdit.toPlainText() == "1080"


def test_invalid_forward_blocks_accept_with_the_reason(qtbot: QtBot) -> None:
    dialog = HostDialog(existingNames=set())
    qtbot.addWidget(dialog)
    dialog.nameEdit.setText("box")
    dialog.hostnameEdit.setText("box.local")
    dialog.localForwardsEdit.setPlainText("8080:localhost:80\nbad")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.errorLabel.text() == "Local forward: expected [bind_address:]port:host:hostport, got 'bad'"

    dialog.localForwardsEdit.setPlainText("8080:localhost:80")
    dialog.dynamicForwardsEdit.setPlainText("70000")
    dialog.accept()
    assert dialog.errorLabel.text() == "Dynamic forward: '70000' is not a port between 1 and 65535 in '70000'"

    dialog.dynamicForwardsEdit.setPlainText("1080")
    dialog.remoteForwardsEdit.setPlainText("9000")
    dialog.accept()
    assert dialog.errorLabel.text() == "Remote forward: expected [bind_address:]port:host:hostport, got '9000'"

    dialog.remoteForwardsEdit.setPlainText("")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
