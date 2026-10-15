"""Tests for the Qt terminal widget: painting state, keys, resize, paste, scrollback."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from pyommyssh.ui.terminalWidget import TerminalWidget


def _collect(widget: TerminalWidget) -> list[bytes]:
    received: list[bytes] = []
    widget.inputBytes.connect(received.append)
    return received


def test_feed_updates_session(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    widget.feed(b"hello")
    assert widget.session.lines()[0].startswith("hello")


def test_resize_follows_cell_grid(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    widget.show()
    cellWidth, cellHeight = widget.cellSize()
    with qtbot.waitSignal(widget.sizeChanged) as blocker:
        widget.resize(cellWidth * 100 + 3, cellHeight * 30 + 2)
    assert blocker.args == [100, 30]
    assert widget.gridSize() == (100, 30)
    assert widget.session.size() == (100, 30)


def test_printable_keys_emit_bytes(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    received = _collect(widget)
    qtbot.keyClick(widget, "a")
    qtbot.keyClick(widget, Qt.Key.Key_Return)
    assert received == [b"a", b"\r"]


def test_control_and_navigation_keys(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    received = _collect(widget)
    qtbot.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(widget, Qt.Key.Key_Up)
    qtbot.keyClick(widget, Qt.Key.Key_BracketLeft, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(widget, Qt.Key.Key_Shift)
    assert received == [b"\x03", b"\x1b[A", b"\x1b"]


def test_paste_sends_clipboard_with_cr_line_endings(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    received = _collect(widget)
    QGuiApplication.clipboard().setText("one\r\ntwo\nthree")
    qtbot.keyClick(
        widget,
        Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert received == [b"one\rtwo\rthree"]


def _wheel(widget: TerminalWidget, steps: int) -> None:
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, steps * 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_wheel_scrolls_into_history_and_output_returns_to_bottom(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    widget.show()
    cellWidth, cellHeight = widget.cellSize()
    widget.resize(cellWidth * 40, cellHeight * 5)
    widget.feed(b"\r\n".join(f"line{i}".encode() for i in range(20)))
    assert widget.scrollOffset() == 0

    _wheel(widget, 1)
    assert widget.scrollOffset() == 3
    assert widget.visibleLines()[0].startswith("line12")

    _wheel(widget, 10)
    assert widget.scrollOffset() == 15
    assert widget.visibleLines()[0].startswith("line0")

    widget.feed(b"\r\nmore")
    assert widget.scrollOffset() == 0
    assert widget.visibleLines()[-1].startswith("more")


def test_visible_lines_match_session_when_not_scrolled(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    widget.feed(b"abc")
    assert widget.visibleLines() == widget.session.lines()
