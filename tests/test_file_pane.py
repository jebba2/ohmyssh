"""Tests for the file pane widget used on both sides of the SFTP tab."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from pyommyssh.core.sftp import FileEntry
from pyommyssh.ui.filePane import PARENT_ROW_LABEL, FilePane, formatModified, formatSize


def _entries() -> list[FileEntry]:
    return [
        FileEntry("docs", "/home/me/docs", 0, True, 1_760_000_000.0, 0o755),
        FileEntry("a.txt", "/home/me/a.txt", 1536, False, 1_760_000_000.0, 0o644),
        FileEntry("big.bin", "/home/me/big.bin", 5 * 1024 * 1024, False, None, 0o644),
    ]


def _shownPane(qtbot: QtBot) -> FilePane:
    pane = FilePane("Local")
    qtbot.addWidget(pane)
    pane.show()
    qtbot.waitExposed(pane)
    return pane


def _cell(pane: FilePane, row: int, column: int) -> str:
    item = pane.table.item(row, column)
    assert item is not None
    return item.text()


def test_format_helpers() -> None:
    assert formatSize(0) == "0 B"
    assert formatSize(1536) == "1.5 KB"
    assert formatSize(5 * 1024 * 1024) == "5.0 MB"
    assert formatSize(3 * 1024**3) == "3.0 GB"
    assert formatModified(None) == ""
    assert len(formatModified(1_760_000_000.0)) == 16  # YYYY-MM-DD HH:MM


def test_set_entries_shows_parent_row_and_columns(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    assert pane.titleLabel.text() == "Local"
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    assert pane.currentPath() == "/home/me"
    assert pane.pathEdit.text() == "/home/me"
    assert pane.names() == [PARENT_ROW_LABEL, "docs", "a.txt", "big.bin"]
    assert _cell(pane, 1, 1) == ""
    assert _cell(pane, 2, 1) == "1.5 KB"
    assert _cell(pane, 2, 2) == formatModified(1_760_000_000.0)
    assert _cell(pane, 3, 2) == ""
    assert pane.entryAt(2) == _entries()[1]
    assert pane.entryAt(0) is None


def test_root_listing_has_no_parent_row(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/", _entries(), parentPath=None)
    assert _cell(pane, 0, 0) == "docs"
    assert not pane.upButton.isEnabled()
    pane.setEntries("/x", _entries(), parentPath="/")
    assert pane.upButton.isEnabled()


def _doubleClickRow(qtbot: QtBot, pane: FilePane, row: int) -> None:
    """A real double-click: Qt only honors it on a cell that was pressed first."""
    item = pane.table.item(row, 0)
    assert item is not None
    position = pane.table.visualItemRect(item).center()
    qtbot.mouseClick(pane.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    qtbot.mouseDClick(pane.table.viewport(), Qt.MouseButton.LeftButton, pos=position)


def test_double_click_navigates_into_folders_and_up(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    with qtbot.waitSignal(pane.navigateRequested) as intoFolder:
        _doubleClickRow(qtbot, pane, 1)
    assert intoFolder.args == ["/home/me/docs"]
    with qtbot.waitSignal(pane.navigateRequested) as upward:
        _doubleClickRow(qtbot, pane, 0)
    assert upward.args == ["/home"]
    with qtbot.waitSignal(pane.fileActivated) as file:
        _doubleClickRow(qtbot, pane, 2)
    assert file.args == [_entries()[1]]


def test_up_button_and_path_edit_navigate(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    with qtbot.waitSignal(pane.navigateRequested) as upward:
        qtbot.mouseClick(pane.upButton, Qt.MouseButton.LeftButton)
    assert upward.args == ["/home"]
    pane.pathEdit.setText("/etc")
    with qtbot.waitSignal(pane.navigateRequested) as typed:
        qtbot.keyClick(pane.pathEdit, Qt.Key.Key_Return)
    assert typed.args == ["/etc"]


def test_selection_excludes_the_parent_row(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    pane.table.selectRow(0)
    assert pane.selectedEntries() == []
    pane.table.clearSelection()
    pane.table.setSelectionMode(pane.table.SelectionMode.MultiSelection)
    pane.table.selectRow(1)
    pane.table.selectRow(3)
    assert pane.selectedEntries() == [_entries()[0], _entries()[2]]


def test_loading_and_error_states(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    pane.setLoading("/home/me/docs")
    assert pane.statusLabel.text() == "Loading..."
    assert not pane.statusLabel.isHidden()
    pane.setError("Could not list /home/me/docs: permission denied")
    assert pane.statusLabel.text() == "Could not list /home/me/docs: permission denied"
    # The previous listing stays on show behind the message.
    assert pane.currentPath() == "/home/me"
    pane.setEntries("/home/me/docs", [], parentPath="/home/me")
    assert pane.statusLabel.isHidden()


def test_roots_combo_switches_drives(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setRoots(["/"])
    assert pane.rootsCombo.isHidden()
    pane.setRoots(["C:\\", "D:\\"])
    assert not pane.rootsCombo.isHidden()
    pane.setEntries("C:\\Users", _entries(), parentPath="C:\\")
    assert pane.rootsCombo.currentText() == "C:\\"
    with qtbot.waitSignal(pane.navigateRequested) as switched:
        pane.rootsCombo.setCurrentIndex(1)
    assert switched.args == ["D:\\"]


def test_local_pane_default_roots_match_the_platform(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setRoots(["/"] if os.name != "nt" else ["C:\\", "D:\\"])
    assert pane.rootsCombo.isHidden() == (os.name != "nt")
