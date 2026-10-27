"""Tests for the dark theme: the monospace family must be one the platform has, and popups must stay dark."""

from __future__ import annotations

import sys
from collections import Counter

from PySide6.QtGui import QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication, QComboBox, QLabel
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


def test_combo_popup_draws_light_text_on_a_dark_background(qtbot: QtBot, qapp: QApplication) -> None:
    """The popup list inherits the combo's light text; without its own dark background the choices vanish on macOS."""
    qapp.setStyleSheet(darkStylesheet())
    try:
        combo = QComboBox()
        qtbot.addWidget(combo)
        combo.addItems(["Use global", "On", "Off"])
        combo.show()
        combo.showPopup()
        qapp.processEvents()
        image = combo.view().grab().toImage()
        combo.hidePopup()
        pixels = Counter(
            (image.pixelColor(x, y).red(), image.pixelColor(x, y).green(), image.pixelColor(x, y).blue())
            for y in range(image.height())
            for x in range(image.width())
        )
        background = pixels.most_common(1)[0][0]
        assert max(background) < 80, f"popup background {background} is not dark"
        assert any(min(color) > 180 for color in pixels), "no light text pixels in the popup"
    finally:
        qapp.setStyleSheet("")
