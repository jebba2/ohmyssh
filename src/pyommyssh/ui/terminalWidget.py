"""A terminal widget that paints a TerminalSession and encodes key presses.

The widget owns no connection. Whatever owns it feeds received bytes in
through ``feed`` and sends the bytes from ``inputBytes`` to the remote side.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget
from pyte.screens import Char

from pyommyssh.core.terminal import (
    SCROLLBACK_LINES,
    CellPosition,
    Selection,
    TerminalSession,
    encodeKey,
    selectedText,
    wordSpanAt,
)

DEFAULT_COLS = 80
DEFAULT_ROWS = 24
WHEEL_LINES_PER_STEP = 3

DEFAULT_FOREGROUND = QColor("#d4d4d4")
DEFAULT_BACKGROUND = QColor("#1e1e1e")
SELECTION_FOREGROUND = QColor("#ffffff")
SELECTION_BACKGROUND = QColor("#264f78")

_NAMED_COLORS: dict[str, QColor] = {
    "black": QColor("#000000"),
    "red": QColor("#cd3131"),
    "green": QColor("#0dbc79"),
    "brown": QColor("#e5e510"),
    "yellow": QColor("#e5e510"),
    "blue": QColor("#2472c8"),
    "magenta": QColor("#bc3fbc"),
    "cyan": QColor("#11a8cd"),
    "white": QColor("#e5e5e5"),
    "brightblack": QColor("#666666"),
    "brightred": QColor("#f14c4c"),
    "brightgreen": QColor("#23d18b"),
    "brightbrown": QColor("#f5f543"),
    "brightyellow": QColor("#f5f543"),
    "brightblue": QColor("#3b8eea"),
    "brightmagenta": QColor("#d670d6"),
    "brightcyan": QColor("#29b8db"),
    "brightwhite": QColor("#ffffff"),
}


def _colorFor(name: str, fallback: QColor) -> QColor:
    """Map a pyte color name or hex triplet to a QColor."""
    if name == "default":
        return fallback
    if name in _NAMED_COLORS:
        return _NAMED_COLORS[name]
    if len(name) == 6:
        return QColor(f"#{name}")
    return fallback


def _keyName(event: QKeyEvent) -> str:
    """Return a key name matching what ``encodeKey`` expects."""
    try:
        name = Qt.Key(event.key()).name.removeprefix("Key_")
    except ValueError:
        return ""
    if len(name) == 1:
        return name
    portable = QKeySequence(event.key()).toString()
    return portable if len(portable) == 1 else name


class TerminalWidget(QWidget):
    """Paints terminal cells and turns keyboard input into terminal bytes."""

    inputBytes = Signal(bytes)
    sizeChanged = Signal(int, int)

    def __init__(self, fontSize: int = 11, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = TerminalSession(DEFAULT_COLS, DEFAULT_ROWS)
        self._scrollOffset = 0
        self._selection: Selection | None = None
        self._anchor = CellPosition(0, 0)
        self._dragging = False
        self._dragMoved = False
        self._clickCount = 0
        self._lastClickTime = 0.0
        self._lastClickCell = CellPosition(-1, -1)
        self._font = QFont("Consolas")
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setFixedPitch(True)
        self._font.setPointSize(fontSize)
        metrics = QFontMetrics(self._font)
        self._cellWidth = max(1, metrics.horizontalAdvance("M"))
        self._cellHeight = max(1, metrics.height())
        self._ascent = metrics.ascent()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def cellSize(self) -> tuple[int, int]:
        """Return the pixel size of one character cell."""
        return self._cellWidth, self._cellHeight

    def gridSize(self) -> tuple[int, int]:
        """Return how many columns and rows fit in the widget."""
        cols = max(2, self.width() // self._cellWidth)
        rows = max(1, self.height() // self._cellHeight)
        return cols, rows

    def sizeHint(self) -> QSize:
        return QSize(self._cellWidth * DEFAULT_COLS, self._cellHeight * DEFAULT_ROWS)

    def scrollOffset(self) -> int:
        """Return how many lines the view is scrolled back into history."""
        return self._scrollOffset

    def feed(self, data: bytes) -> None:
        """Apply remote output and snap the view back to the live screen.

        A selection stays on its lines because they keep their place in the
        buffer, except when full scrollback starts dropping old lines.
        """
        historyWasFull = len(self.session.scrollbackLines()) >= SCROLLBACK_LINES
        self.session.feed(data)
        self._scrollOffset = 0
        if historyWasFull:
            self._selection = None
        self.update()

    def bufferLines(self) -> list[str]:
        """Scrollback followed by the live screen; selections index into this."""
        return self.session.scrollbackLines() + self.session.lines()

    def _viewTop(self) -> int:
        """The buffer row shown at the top of the widget."""
        rows = self.session.size()[1]
        return max(0, len(self.bufferLines()) - self._scrollOffset - rows)

    def visibleLines(self) -> list[str]:
        """Return the rows currently shown, honoring the scrollback offset."""
        if self._scrollOffset == 0:
            return self.session.lines()
        combined = self.bufferLines()
        rows = self.session.size()[1]
        end = len(combined) - self._scrollOffset
        return combined[max(0, end - rows) : end]

    # Selection

    def cellAtPoint(self, point: QPoint) -> tuple[int, int]:
        """The buffer row and column under a widget position, clamped to the grid."""
        cols, rows = self.session.size()
        col = max(0, min(cols - 1, point.x() // self._cellWidth))
        row = max(0, min(rows - 1, point.y() // self._cellHeight))
        return self._viewTop() + row, col

    def selectedText(self) -> str:
        """The selected text, or an empty string."""
        if self._selection is None:
            return ""
        return selectedText(self.bufferLines(), self._selection)

    def copySelection(self) -> bool:
        """Put the selection on the clipboard; False when nothing is selected."""
        text = self.selectedText()
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        return True

    def clearSelection(self) -> None:
        """Drop the selection."""
        if self._selection is not None:
            self._selection = None
            self.update()

    def _setSelection(self, selection: Selection | None) -> None:
        self._selection = selection
        self.update()

    def _isRepeatClick(self, cell: CellPosition) -> bool:
        interval = QApplication.doubleClickInterval() / 1000.0
        return cell == self._lastClickCell and time.monotonic() - self._lastClickTime <= interval

    def _noteClick(self, cell: CellPosition, count: int) -> None:
        self._lastClickCell = cell
        self._lastClickTime = time.monotonic()
        self._clickCount = count

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        row, col = self.cellAtPoint(event.position().toPoint())
        cell = CellPosition(row, col)
        if self._clickCount == 2 and self._isRepeatClick(cell):
            # Third click in a row selects the whole line.
            line = self.bufferLines()[row] if row < len(self.bufferLines()) else ""
            self._setSelection(Selection(CellPosition(row, 0), CellPosition(row, max(0, len(line.rstrip()) - 1))))
            self._noteClick(cell, 0)
            return
        self._anchor = cell
        self._dragging = True
        self._dragMoved = False
        self._noteClick(cell, 1)
        self._setSelection(None)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        row, col = self.cellAtPoint(event.position().toPoint())
        lines = self.bufferLines()
        line = lines[row] if row < len(lines) else ""
        start, end = wordSpanAt(line, col)
        self._dragging = False
        self._noteClick(CellPosition(row, col), 2)
        if end > start:
            self._setSelection(Selection(CellPosition(row, start), CellPosition(row, end - 1)))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        row, col = self.cellAtPoint(event.position().toPoint())
        focus = CellPosition(row, col)
        if focus != self._anchor:
            self._dragMoved = True
        self._setSelection(Selection(self._anchor, focus))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            if not self._dragMoved:
                self._setSelection(None)
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        copyAction = menu.addAction("Copy", self.copySelection)
        copyAction.setEnabled(self._selection is not None)
        menu.addAction("Paste", self.pasteClipboard)
        menu.exec(event.globalPos())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        cols, rows = self.gridSize()
        if (cols, rows) != self.session.size():
            self.session.resize(cols, rows)
            self._scrollOffset = 0
            self.sizeChanged.emit(cols, rows)

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120.0
        historyLength = len(self.session.scrollbackLines())
        wanted = self._scrollOffset + round(steps * WHEEL_LINES_PER_STEP)
        self._scrollOffset = max(0, min(historyLength, wanted))
        event.accept()
        self.update()

    def _isPaste(self, event: QKeyEvent) -> bool:
        modifiers = event.modifiers()
        ctrlShift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        if event.key() == Qt.Key.Key_V and modifiers == ctrlShift:
            return True
        return event.key() == Qt.Key.Key_Insert and modifiers == Qt.KeyboardModifier.ShiftModifier

    def _isCopy(self, event: QKeyEvent) -> bool:
        """Ctrl+Shift+C or Ctrl+Insert; plain Ctrl+C stays the interrupt."""
        modifiers = event.modifiers()
        ctrlShift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        if event.key() == Qt.Key.Key_C and modifiers == ctrlShift:
            return True
        return event.key() == Qt.Key.Key_Insert and modifiers == Qt.KeyboardModifier.ControlModifier

    def pasteClipboard(self) -> None:
        """Send the clipboard text with line endings the shell expects."""
        text = QGuiApplication.clipboard().text()
        if text:
            self.inputBytes.emit(text.replace("\r\n", "\r").replace("\n", "\r").encode())

    def focusNextPrevChild(self, next: bool) -> bool:
        """Keep Tab and Shift+Tab: the shell needs them for completion, not focus traversal."""
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._isCopy(event):
            self.copySelection()
            event.accept()
            return
        if self._isPaste(event):
            self.pasteClipboard()
            return
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        text = event.text()
        if ctrl and alt and text and text.isprintable():
            # AltGr on Windows arrives as Ctrl+Alt; the text is what matters.
            ctrl = alt = False
        encoded = encodeKey(_keyName(event), text=text, ctrl=ctrl, alt=alt, shift=shift)
        if encoded:
            self.inputBytes.emit(encoded)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _paintRow(self, painter: QPainter, row: int, cells: list[Char]) -> None:
        """Paint one row as runs of identically styled characters."""
        y = row * self._cellHeight
        column = 0
        while column < len(cells):
            first = cells[column]
            runEnd = column + 1
            while runEnd < len(cells) and _sameStyle(cells[runEnd], first):
                runEnd += 1
            foreground = _colorFor(first.fg, DEFAULT_FOREGROUND)
            background = _colorFor(first.bg, DEFAULT_BACKGROUND)
            if first.reverse:
                foreground, background = background, foreground
            width = (runEnd - column) * self._cellWidth
            if background != DEFAULT_BACKGROUND:
                painter.fillRect(column * self._cellWidth, y, width, self._cellHeight, background)
            self._font.setBold(first.bold)
            self._font.setItalic(first.italics)
            self._font.setUnderline(first.underscore)
            painter.setFont(self._font)
            painter.setPen(foreground)
            text = "".join(cell.data for cell in cells[column:runEnd])
            painter.drawText(column * self._cellWidth, y + self._ascent, text)
            column = runEnd

    def _paintCursor(self, painter: QPainter) -> None:
        x, y = self.session.cursor()
        rect = QRect(x * self._cellWidth, y * self._cellHeight, self._cellWidth, self._cellHeight)
        if self.hasFocus():
            painter.fillRect(rect, DEFAULT_FOREGROUND)
            painter.setPen(DEFAULT_BACKGROUND)
            painter.setFont(self._font)
            painter.drawText(rect.x(), rect.y() + self._ascent, self.session.cellAt(x, y).data)
        else:
            painter.setPen(DEFAULT_FOREGROUND)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _paintSelection(self, painter: QPainter, row: int, rowText: str) -> None:
        """Highlight the selected part of a visible row, if any."""
        if self._selection is None:
            return
        cols = self.session.size()[0]
        span = self._selection.columnSpan(self._viewTop() + row, cols)
        if span is None or span[1] <= span[0]:
            return
        first, last = span
        y = row * self._cellHeight
        painter.fillRect(first * self._cellWidth, y, (last - first) * self._cellWidth, self._cellHeight, SELECTION_BACKGROUND)
        self._font.setBold(False)
        self._font.setItalic(False)
        self._font.setUnderline(False)
        painter.setFont(self._font)
        painter.setPen(SELECTION_FOREGROUND)
        painter.drawText(first * self._cellWidth, y + self._ascent, rowText[first:last])

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), DEFAULT_BACKGROUND)
        cols, rows = self.session.size()
        if self._scrollOffset == 0:
            for row in range(rows):
                cells = [self.session.cellAt(col, row) for col in range(cols)]
                self._paintRow(painter, row, cells)
                self._paintSelection(painter, row, "".join(cell.data for cell in cells))
            if not self.session.cursorHidden():
                self._paintCursor(painter)
        else:
            self._font.setBold(False)
            self._font.setItalic(False)
            self._font.setUnderline(False)
            painter.setFont(self._font)
            for row, line in enumerate(self.visibleLines()):
                painter.setPen(DEFAULT_FOREGROUND)
                painter.setFont(self._font)
                painter.drawText(0, row * self._cellHeight + self._ascent, line)
                self._paintSelection(painter, row, line)
        painter.end()


def _sameStyle(a: Char, b: Char) -> bool:
    return (
        a.fg == b.fg
        and a.bg == b.bg
        and a.bold == b.bold
        and a.italics == b.italics
        and a.underscore == b.underscore
        and a.reverse == b.reverse
    )
