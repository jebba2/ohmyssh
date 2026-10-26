"""Tests for bundled icons."""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from ohmyssh.ui.icons import ICON_NAMES, iconPath, loadIcon


@pytest.mark.parametrize("name", sorted(ICON_NAMES))
def test_every_icon_file_exists_and_loads(qtbot: QtBot, name: str) -> None:
    assert iconPath(name).is_file()
    icon = loadIcon(name)
    assert not icon.isNull()
    assert not icon.pixmap(16, 16).isNull()


def test_unknown_icon_name_raises() -> None:
    with pytest.raises(KeyError, match="nope"):
        iconPath("nope")
