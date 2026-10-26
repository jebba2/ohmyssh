"""Tests for the application entry point helpers."""

from __future__ import annotations

import sys

from ohmyssh.app import APP_USER_MODEL_ID, registerWindowsAppId


def test_windows_taskbar_identity_is_registered_only_on_windows() -> None:
    assert APP_USER_MODEL_ID == "ohmyssh.desktop"
    assert registerWindowsAppId() == (sys.platform == "win32")
    # Registering twice is harmless.
    assert registerWindowsAppId() == (sys.platform == "win32")
