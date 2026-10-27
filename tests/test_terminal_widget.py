"""Tests for the Qt terminal widget: painting state, keys, resize, paste, scrollback."""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QFontInfo, QFontMetricsF, QGuiApplication, QWheelEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from ohmyssh.ui.terminalWidget import TerminalWidget
from ohmyssh.ui.theme import PREFERRED_MONOSPACE, monospaceFamily


def _collect(widget: TerminalWidget) -> list[bytes]:
    received: list[bytes] = []
    widget.inputBytes.connect(received.append)
    return received


def test_feed_updates_session(qtbot: QtBot) -> None:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    widget.feed(b"hello")
    assert widget.session.lines()[0].startswith("hello")


def test_terminal_uses_an_installed_monospace_font_without_substitution(qtbot: QtBot) -> None:
    """Naming a font the platform lacks makes Qt substitute one and warn on every launch."""
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    font = widget.terminalFont()
    resolved = QFontInfo(font)
    assert resolved.fixedPitch()
    assert font.family() == monospaceFamily()
    installed = [family for family in PREFERRED_MONOSPACE.get(sys.platform, []) if family in QFontDatabase.families()]
    if installed:
        assert font.family() == installed[0] == resolved.family()


def test_text_runs_land_exactly_on_the_cell_grid(qtbot: QtBot) -> None:
    """A run of text must end where the grid says its last cell does, or the cursor floats away from it.

    Fonts have fractional advances, so an integer cell width drifts from the
    drawn text by a pixel per character unless the font is padded to the cell.
    """
    for size in (10, 11, 12, 13):
        widget = TerminalWidget(fontSize=size)
        qtbot.addWidget(widget)
        cellWidth, _ = widget.cellSize()
        prompt = "[cetlocron@cetlodevweb02 ~]$ "
        drawn = QFontMetricsF(widget.terminalFont()).horizontalAdvance(prompt)
        assert abs(drawn - len(prompt) * cellWidth) < 0.01, f"{size}pt: drawn {drawn} vs grid {len(prompt) * cellWidth}"


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


def test_tab_and_shift_tab_go_to_the_shell_not_to_focus_traversal(qtbot: QtBot) -> None:
    window = QWidget()
    layout = QVBoxLayout(window)
    other = QLineEdit()
    widget = TerminalWidget()
    layout.addWidget(other)
    layout.addWidget(widget)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    widget.setFocus()
    qtbot.waitUntil(widget.hasFocus)
    received = _collect(widget)
    qtbot.keyClick(widget, Qt.Key.Key_Tab)
    qtbot.keyClick(widget, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert received == [b"\t", b"\x1b[Z"]
    assert widget.hasFocus()
    assert not other.hasFocus()


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


def _shownTerminal(qtbot: QtBot, cols: int = 40, rows: int = 5) -> TerminalWidget:
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    widget.show()
    cellWidth, cellHeight = widget.cellSize()
    widget.resize(cellWidth * cols, cellHeight * rows)
    qtbot.waitExposed(widget)
    return widget


def _cellCenter(widget: TerminalWidget, row: int, col: int) -> QPoint:
    cellWidth, cellHeight = widget.cellSize()
    return QPoint(col * cellWidth + cellWidth // 2, row * cellHeight + cellHeight // 2)


def _drag(widget: TerminalWidget, qtbot: QtBot, start: tuple[int, int], end: tuple[int, int]) -> None:
    qtbot.mousePress(widget, Qt.MouseButton.LeftButton, pos=_cellCenter(widget, *start))
    qtbot.mouseMove(widget, pos=_cellCenter(widget, *end))
    qtbot.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=_cellCenter(widget, *end))


def test_drag_selects_cells_and_copy_shortcuts_copy_them(qtbot: QtBot) -> None:
    widget = _shownTerminal(qtbot)
    widget.feed(b"hello world\r\nsecond line")
    assert widget.selectedText() == ""
    _drag(widget, qtbot, (0, 6), (1, 5))
    assert widget.selectedText() == "world\nsecond"

    clipboard = QGuiApplication.clipboard()
    clipboard.setText("")
    qtbot.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert clipboard.text() == "world\nsecond"
    clipboard.setText("")
    qtbot.keyClick(widget, Qt.Key.Key_Insert, Qt.KeyboardModifier.ControlModifier)
    assert clipboard.text() == "world\nsecond"

    # Ctrl+C is still the interrupt and never touches the clipboard.
    received = _collect(widget)
    clipboard.setText("untouched")
    qtbot.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert received == [b"\x03"]
    assert clipboard.text() == "untouched"

    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=_cellCenter(widget, 0, 0))
    assert widget.selectedText() == ""


def test_backward_drag_and_copy_without_a_selection(qtbot: QtBot) -> None:
    widget = _shownTerminal(qtbot)
    widget.feed(b"hello world")
    _drag(widget, qtbot, (0, 10), (0, 6))
    assert widget.selectedText() == "world"
    assert widget.copySelection()
    widget.clearSelection()
    assert widget.selectedText() == ""
    assert not widget.copySelection()
    received = _collect(widget)
    QGuiApplication.clipboard().setText("kept")
    qtbot.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert received == []
    assert QGuiApplication.clipboard().text() == "kept"


def test_double_click_selects_a_word_and_triple_click_a_line(qtbot: QtBot) -> None:
    widget = _shownTerminal(qtbot)
    widget.feed(b"ls -la /home/jeb")
    qtbot.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=_cellCenter(widget, 0, 9))
    assert widget.selectedText() == "/home/jeb"
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=_cellCenter(widget, 0, 9))
    assert widget.selectedText() == "ls -la /home/jeb"


def test_selection_stays_on_its_lines_while_scrolling_and_during_output(qtbot: QtBot) -> None:
    widget = _shownTerminal(qtbot)
    widget.feed(b"\r\n".join(f"line{i}".encode() for i in range(20)))
    assert widget.visibleLines()[2].startswith("line17")
    _drag(widget, qtbot, (2, 0), (2, 5))
    assert widget.selectedText() == "line17"

    _wheel(widget, 1)
    assert widget.visibleLines()[0].startswith("line12")
    assert widget.selectedText() == "line17"

    widget.feed(b"\r\nline20")
    assert widget.scrollOffset() == 0
    assert widget.selectedText() == "line17"


def test_selecting_in_a_scrolled_back_view_reads_history(qtbot: QtBot) -> None:
    widget = _shownTerminal(qtbot)
    widget.feed(b"\r\n".join(f"line{i}".encode() for i in range(20)))
    _wheel(widget, 10)
    assert widget.visibleLines()[0].startswith("line0")
    _drag(widget, qtbot, (1, 0), (3, 5))
    assert widget.selectedText() == "line1\nline2\nline3"
    assert widget.cellAtPoint(_cellCenter(widget, 1, 3)) == (1, 3)
