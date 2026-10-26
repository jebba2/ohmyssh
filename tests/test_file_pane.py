"""Tests for the file pane widget used on both sides of the SFTP tab."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from pytestqt.qtbot import QtBot

from ohmyssh.core.sftp import FileEntry
from ohmyssh.ui.filePane import ENTRIES_MIME_TYPE, PARENT_ROW_LABEL, FilePane, formatModified, formatSize


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


def _selectRows(pane: FilePane, *rows: int) -> None:
    pane.table.clearSelection()
    for row in rows:
        index = pane.table.model().index(row, 0)
        pane.table.selectionModel().select(
            index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        )


def _dropAt(pane: FilePane, mime: QMimeData, point: QPoint) -> None:
    event = QDropEvent(
        QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    pane.table.dropEvent(event)


def _rowCenter(pane: FilePane, row: int) -> QPoint:
    item = pane.table.item(row, 0)
    assert item is not None
    return pane.table.visualItemRect(item).center()


def _emptyArea(pane: FilePane) -> QPoint:
    return QPoint(5, pane.table.viewport().height() - 2)


def test_drag_mime_data_carries_the_selected_paths_and_a_token(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    assert pane.dragMimeData() is None
    _selectRows(pane, 0)
    assert pane.dragMimeData() is None  # the parent row is never dragged
    _selectRows(pane, 0, 1, 2)
    mime = pane.dragMimeData()
    assert mime is not None and mime.hasFormat(ENTRIES_MIME_TYPE)
    payload = json.loads(bytes(mime.data(ENTRIES_MIME_TYPE).data()).decode("utf-8"))
    assert payload == {"token": pane.dragToken, "paths": ["/home/me/docs", "/home/me/a.txt"]}


def test_dropped_entries_target_a_folder_row_or_the_current_folder(qtbot: QtBot) -> None:
    source = _shownPane(qtbot)
    source.setEntries("/src", [FileEntry("x.txt", "/src/x.txt", 1, False, None, None)], parentPath="/")
    _selectRows(source, 1)
    mime = source.dragMimeData()
    assert mime is not None
    target = _shownPane(qtbot)
    target.setEntries("/home/me", _entries(), parentPath="/home")

    with qtbot.waitSignal(target.entriesDropped) as onFolder:
        _dropAt(target, mime, _rowCenter(target, 1))
    assert onFolder.args == [source.dragToken, ["/src/x.txt"], "/home/me/docs"]
    with qtbot.waitSignal(target.entriesDropped) as onFile:
        _dropAt(target, mime, _rowCenter(target, 2))
    assert onFile.args == [source.dragToken, ["/src/x.txt"], "/home/me"]
    with qtbot.waitSignal(target.entriesDropped) as onParentRow:
        _dropAt(target, mime, _rowCenter(target, 0))
    assert onParentRow.args == [source.dragToken, ["/src/x.txt"], "/home/me"]
    with qtbot.waitSignal(target.entriesDropped) as onEmpty:
        _dropAt(target, mime, _emptyArea(target))
    assert onEmpty.args == [source.dragToken, ["/src/x.txt"], "/home/me"]


def test_dropping_on_the_source_pane_does_nothing(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    _selectRows(pane, 2)
    mime = pane.dragMimeData()
    assert mime is not None
    with qtbot.assertNotEmitted(pane.entriesDropped, wait=100):
        _dropAt(pane, mime, _rowCenter(pane, 1))


def test_dropped_os_files_emit_their_local_paths(qtbot: QtBot, tmp_path: Path) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "a.txt")), QUrl("https://example.com/not-a-file")])
    with qtbot.waitSignal(pane.urlsDropped) as dropped:
        _dropAt(pane, mime, _rowCenter(pane, 1))
    assert dropped.args == [[str(tmp_path / "a.txt")], "/home/me/docs"]


def test_drag_enter_accepts_entries_and_files_only(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")

    def enter(mime: QMimeData) -> bool:
        event = QDragEnterEvent(
            QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
        pane.table.dragEnterEvent(event)
        return event.isAccepted()

    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile("C:/x.txt")])
    assert enter(files)
    otherPane = _shownPane(qtbot)
    otherPane.setEntries("/elsewhere", _entries(), parentPath="/")
    _selectRows(otherPane, 1)
    entries = otherPane.dragMimeData()
    assert entries is not None and enter(entries)
    _selectRows(pane, 1)
    ownEntries = pane.dragMimeData()
    assert ownEntries is not None and not enter(ownEntries)
    text = QMimeData()
    text.setText("hello")
    assert not enter(text)


def test_drops_are_always_answered_as_copies_so_the_source_is_never_moved(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile("C:/Users/me/Desktop/report.pdf")])
    # Explorer offers copy and move together; the answer must be copy.
    offered = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    enter = QDragEnterEvent(QPointF(5, 5), offered, files, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    pane.table.dragEnterEvent(enter)
    assert enter.isAccepted() and enter.dropAction() == Qt.DropAction.CopyAction
    drop = QDropEvent(QPointF(5, 5), offered, files, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    with qtbot.waitSignal(pane.urlsDropped):
        pane.table.dropEvent(drop)
    assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction

    # A source that allows only a move is refused outright.
    moveOnly = QDropEvent(
        QPointF(5, 5), Qt.DropAction.MoveAction, files, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    with qtbot.assertNotEmitted(pane.urlsDropped, wait=100):
        pane.table.dropEvent(moveOnly)
    assert not moveOnly.isAccepted()


def test_a_drop_anywhere_on_the_pane_targets_the_folder_on_show(qtbot: QtBot, tmp_path: Path) -> None:
    pane = _shownPane(qtbot)
    pane.setEntries("/home/me", _entries(), parentPath="/home")
    assert pane.acceptDrops()
    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile(str(tmp_path / "a.txt"))])
    offered = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    enter = QDragEnterEvent(QPointF(2, 2), offered, files, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    pane.dragEnterEvent(enter)
    assert enter.isAccepted() and enter.dropAction() == Qt.DropAction.CopyAction
    drop = QDropEvent(
        QPointF(2, 2), Qt.DropAction.CopyAction, files, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    with qtbot.waitSignal(pane.urlsDropped) as dropped:
        pane.dropEvent(drop)
    assert dropped.args == [[str(tmp_path / "a.txt")], "/home/me"]

    other = _shownPane(qtbot)
    other.setEntries("/src", [FileEntry("x.txt", "/src/x.txt", 1, False, None, None)], parentPath="/")
    _selectRows(other, 1)
    rows = other.dragMimeData()
    assert rows is not None
    with qtbot.waitSignal(pane.entriesDropped) as entries:
        pane.dropEvent(
            QDropEvent(QPointF(2, 2), Qt.DropAction.CopyAction, rows, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        )
    assert entries.args == [other.dragToken, ["/src/x.txt"], "/home/me"]


def test_local_pane_default_roots_match_the_platform(qtbot: QtBot) -> None:
    pane = _shownPane(qtbot)
    pane.setRoots(["/"] if os.name != "nt" else ["C:\\", "D:\\"])
    assert pane.rootsCombo.isHidden() == (os.name != "nt")
