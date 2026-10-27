"""Tests for the dark theme's font choice: the monospace family must be one the platform has."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot

from ohmyssh.ui.theme import PREFERRED_MONOSPACE, darkStylesheet, monospaceFamily


def test_monospace_family_is_installed_and_preferred_when_available(qtbot: QtBot) -> None:
    family = monospaceFamily()
    installed = [candidate for candidate in PREFERRED_MONOSPACE.get(sys.platform, []) if candidate in QFontDatabase.families()]
    if installed:
        assert family == installed[0]
    else:
        assert family == QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def test_card_detail_labels_get_the_installed_monospace_font(qtbot: QtBot, qapp: QApplication) -> None:
    """Naming a font the platform lacks leaves the labels in the proportional UI font and makes Qt warn."""
    qapp.setStyleSheet(darkStylesheet())
    try:
        label = QLabel("cetlocron@cetlodevweb02")
        qtbot.addWidget(label)
        label.setObjectName("hostAddress")
        label.ensurePolished()
        resolved = QFontInfo(label.font())
        assert resolved.family() == monospaceFamily()
        assert resolved.fixedPitch()
    finally:
        qapp.setStyleSheet("")
