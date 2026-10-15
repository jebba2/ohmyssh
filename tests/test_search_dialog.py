"""Tests for the Ctrl+K search palette."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from pyommyssh.core.hosts import Host
from pyommyssh.ui.searchDialog import SearchDialog, SearchEntry

WEB = Host(name="web", hostname="web.example.com", tags=["prod"])
DB = Host(name="db", hostname="10.0.0.9", tags=["data"])


def _entries() -> list[SearchEntry]:
    return [
        SearchEntry(kind="host", label="web", host=WEB),
        SearchEntry(kind="host", label="db", host=DB),
        SearchEntry(kind="session", label="web (terminal 1)", host=WEB, tabIndex=1),
    ]


def test_all_entries_listed_initially(qtbot: QtBot) -> None:
    dialog = SearchDialog(_entries())
    qtbot.addWidget(dialog)
    assert dialog.visibleLabels() == ["web", "db", "web (terminal 1)"]
    assert dialog.listWidget.currentRow() == 0


def test_filter_matches_name_hostname_and_tags(qtbot: QtBot) -> None:
    dialog = SearchDialog(_entries())
    qtbot.addWidget(dialog)
    dialog.searchEdit.setText("EXAMPLE")
    assert dialog.visibleLabels() == ["web", "web (terminal 1)"]
    dialog.searchEdit.setText("data")
    assert dialog.visibleLabels() == ["db"]
    dialog.searchEdit.setText("terminal")
    assert dialog.visibleLabels() == ["web (terminal 1)"]
    dialog.searchEdit.setText("nothing")
    assert dialog.visibleLabels() == []
    assert dialog.selectedEntry() is None


def test_enter_selects_highlighted_entry(qtbot: QtBot) -> None:
    dialog = SearchDialog(_entries())
    qtbot.addWidget(dialog)
    qtbot.keyClick(dialog.searchEdit, Qt.Key.Key_Down)
    qtbot.keyClick(dialog.searchEdit, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    selected = dialog.selectedEntry()
    assert selected is not None
    assert selected.label == "db"


def test_up_and_down_wrap_within_visible_items(qtbot: QtBot) -> None:
    dialog = SearchDialog(_entries())
    qtbot.addWidget(dialog)
    qtbot.keyClick(dialog.searchEdit, Qt.Key.Key_Up)
    assert dialog.listWidget.currentRow() == 2
    qtbot.keyClick(dialog.searchEdit, Qt.Key.Key_Down)
    assert dialog.listWidget.currentRow() == 0


def test_escape_rejects(qtbot: QtBot) -> None:
    dialog = SearchDialog(_entries())
    qtbot.addWidget(dialog)
    qtbot.keyClick(dialog.searchEdit, Qt.Key.Key_Escape)
    assert dialog.result() == QDialog.DialogCode.Rejected
