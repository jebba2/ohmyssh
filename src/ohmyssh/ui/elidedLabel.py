"""A single-line label that shortens long text instead of growing to fit it."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPaintEvent, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

# How many average characters the label asks a layout for; beyond that it elides.
PREFERRED_CHARS = 40


class ElidedLabel(QLabel):
    """QLabel that elides its text in the middle to fit the width it is given.

    A plain QLabel asks its layout for the full width of its text, so a long file
    name in a row squeezes the widgets beside it. This label asks for a modest
    width, draws as much of the text as fits with an ellipsis in the middle, and
    keeps the full text as its tooltip.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        """Set the text; the tooltip always shows it in full."""
        super().setText(text)
        self.setToolTip(text)

    def elidedText(self) -> str:
        """The text as drawn at the current width."""
        return self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, self.contentsRect().width())

    def minimumSizeHint(self) -> QSize:
        """Only the height matters; the text shrinks to whatever width is left."""
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        """A width worth a few dozen characters, independent of the text."""
        return QSize(self.fontMetrics().averageCharWidth() * PREFERRED_CHARS, super().sizeHint().height())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        flags = int(self.alignment()) | int(Qt.TextFlag.TextSingleLine)
        painter.drawText(self.contentsRect(), flags, self.elidedText())
