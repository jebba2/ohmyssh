"""Tests for the label that shortens long text instead of pushing its neighbors aside."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QWidget
from pytestqt.qtbot import QtBot

from ohmyssh.ui.elidedLabel import ElidedLabel

LONG_TEXT = "Download: " + "a" * 300 + ".bin  1.0 MB / 2.0 MB  (1/2 files)"


def test_long_text_is_elided_in_the_middle_and_kept_in_full(qtbot: QtBot) -> None:
    label = ElidedLabel()
    qtbot.addWidget(label)
    label.setText(LONG_TEXT)
    label.resize(200, 30)
    label.show()
    qtbot.waitExposed(label)
    shown = label.elidedText()
    assert label.text() == LONG_TEXT
    assert label.toolTip() == LONG_TEXT
    assert "…" in shown and len(shown) < len(LONG_TEXT)
    assert shown.startswith("Download: ") and shown.endswith("files)")
    assert label.fontMetrics().horizontalAdvance(shown) <= label.contentsRect().width()


def test_label_does_not_ask_the_layout_for_its_full_text_width(qtbot: QtBot) -> None:
    label = ElidedLabel(LONG_TEXT)
    qtbot.addWidget(label)
    assert label.minimumSizeHint().width() < label.fontMetrics().horizontalAdvance("M" * 10)
    assert label.sizeHint().width() < label.fontMetrics().horizontalAdvance(LONG_TEXT) // 2


def test_label_leaves_room_for_a_neighbor_in_a_row(qtbot: QtBot) -> None:
    row = QWidget()
    qtbot.addWidget(row)
    label = ElidedLabel(LONG_TEXT)
    bar = QProgressBar()
    bar.setMinimumWidth(160)
    layout = QHBoxLayout(row)
    layout.addWidget(label, 1)
    layout.addWidget(bar, 1)
    row.resize(600, 40)
    row.show()
    qtbot.waitExposed(row)
    assert bar.width() >= 160
    assert label.width() + bar.width() <= row.width()
