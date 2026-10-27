"""Tests for the themed combo box: its popup must show every choice in full.

The macOS style insets the popup and spends width on a checkmark column, which the offscreen
platform does not reproduce, so run these with QT_QPA_PLATFORM=cocoa on a Mac to see the real thing.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionComboBox
from pytestqt.qtbot import QtBot

from ohmyssh.ui.comboBox import ComboBox
from ohmyssh.ui.theme import darkStylesheet


def test_popup_is_a_list_at_least_as_wide_as_the_combo(qtbot: QtBot, qapp: QApplication) -> None:
    qapp.setStyleSheet(darkStylesheet())
    try:
        combo = ComboBox()
        qtbot.addWidget(combo)
        combo.addItems(["Use global", "On", "Off"])
        combo.show()
        option = QStyleOptionComboBox()
        option.initFrom(combo)
        assert combo.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup, option, combo) == 0
        combo.showPopup()
        qapp.processEvents()
        try:
            assert combo.view().width() >= combo.width()
        finally:
            combo.hidePopup()
    finally:
        qapp.setStyleSheet("")
