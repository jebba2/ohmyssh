"""Application-wide Qt stylesheets."""

import sys

from PySide6.QtGui import QFontDatabase

# Monospace fonts to try per platform, best first. Naming a family the platform lacks makes Qt
# substitute one and log a warning on every launch, so the choice is made from what is installed.
PREFERRED_MONOSPACE = {
    "darwin": ["Menlo", "Monaco"],
    "win32": ["Consolas", "Cascadia Mono"],
    "linux": ["DejaVu Sans Mono", "Liberation Mono"],
}


def monospaceFamily() -> str:
    """Return the first installed font from the platform's preferred list, else the system fixed-pitch font."""
    installed = set(QFontDatabase.families())
    for family in PREFERRED_MONOSPACE.get(sys.platform, []):
        if family in installed:
            return family
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def darkStylesheet() -> str:
    """Return the dark theme with the installed monospace family filled in; needs a running QApplication."""
    return DARK_STYLESHEET_TEMPLATE.replace("MONOSPACE_FAMILY", f'"{monospaceFamily()}"')


# The MONOSPACE_FAMILY placeholder is filled in by darkStylesheet().
DARK_STYLESHEET_TEMPLATE = """
QMainWindow, QDialog, QScrollArea, QTabWidget::pane, QWidget#dashboardContainer {
    background: #1b1b1f;
    color: #d4d4d4;
}
QToolBar {
    background: #232329;
    border-bottom: 1px solid #333;
    spacing: 6px;
    padding: 4px;
}
QToolBar QToolButton {
    color: #d4d4d4;
    padding: 4px 10px;
    border-radius: 4px;
}
QToolBar QToolButton:hover, QToolBar QToolButton:checked {
    background: #3a3a44;
}
QTabBar::tab {
    background: #232329;
    color: #bbbbbb;
    padding: 6px 14px;
    border: 1px solid #333;
    border-bottom: none;
}
QTabBar::tab:selected {
    background: #1b1b1f;
    color: #ffffff;
}
QStatusBar {
    background: #232329;
    color: #9a9a9a;
}
QLabel {
    color: #d4d4d4;
}
QLabel#groupHeader {
    color: #9cdcfe;
    font-size: 14px;
    font-weight: bold;
    padding-top: 8px;
}
QFrame#hostCard {
    background: #26262c;
    border: 1px solid #3a3a44;
    border-radius: 8px;
    padding: 8px;
}
QFrame#hostCard[state="online"] {
    border-color: #3c8a5a;
}
QFrame#hostCard[state="error"] {
    border-color: #a63d3d;
}
QFrame#hostCard[state="connecting"] {
    border-color: #8a7a3c;
}
QLabel#hostName {
    font-size: 15px;
    font-weight: bold;
    color: #ffffff;
}
QToolButton#cardButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}
QToolButton#cardButton:hover {
    background: #3a3a44;
}
QLabel#hostAddress, QLabel#hostProcesses, QLabel#hostForwards {
    color: #9a9a9a;
    font-family: MONOSPACE_FAMILY;
    font-size: 11px;
}
QLabel#hostStatus, QLabel#tunnelStatus {
    color: #c8c8c8;
    font-size: 11px;
}
QLabel#tunnelStatus[tunnelState="up"] {
    color: #7fd39a;
}
QLabel#tunnelStatus[tunnelState="connecting"], QLabel#tunnelStatus[tunnelState="retrying"] {
    color: #e0c56a;
}
QLabel#tunnelStatus[tunnelState="failed"], QLabel#tunnelStatus[tunnelState="auth_required"] {
    color: #ff8a8a;
}
QPushButton#tunnelButton {
    padding: 2px 8px;
    font-size: 11px;
}
QLabel#dockerBadge {
    background: #1f4f78;
    color: #d6ecff;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
}
QProgressBar {
    background: #1b1b1f;
    border: 1px solid #3a3a44;
    border-radius: 4px;
    text-align: center;
    color: #e0e0e0;
    height: 16px;
    font-size: 11px;
}
QProgressBar::chunk {
    background: #3c8a5a;
    border-radius: 3px;
}
QProgressBar[usageLevel="warn"]::chunk {
    background: #c9a227;
}
QProgressBar[usageLevel="critical"]::chunk {
    background: #c94a4a;
}
QProgressBar[usageLevel="unknown"]::chunk {
    background: #3a3a44;
}
QLabel#terminalStatus {
    background: #3a2f1f;
    color: #ffd79a;
    padding: 4px 8px;
}
QLabel#errorLabel {
    color: #ff8a8a;
}
QTableWidget {
    background: #141417;
    color: #e0e0e0;
    border: 1px solid #3a3a44;
    selection-background-color: #34405a;
    selection-color: #ffffff;
    font-size: 12px;
}
QHeaderView::section {
    background: #232329;
    color: #bbbbbb;
    border: none;
    border-bottom: 1px solid #3a3a44;
    padding: 4px 6px;
}
QLabel#paneTitle {
    font-weight: bold;
    color: #ffffff;
}
QLabel#paneStatus {
    color: #ffd79a;
    font-size: 11px;
}
QWidget#transferStrip {
    background: #232329;
    border: 1px solid #3a3a44;
    border-radius: 4px;
}
QSplitter::handle {
    background: #2a2a30;
    width: 6px;
}
QLineEdit, QSpinBox, QListWidget, QPlainTextEdit, QComboBox {
    background: #141417;
    color: #e0e0e0;
    border: 1px solid #3a3a44;
    border-radius: 4px;
    padding: 4px;
}
QComboBox {
    combobox-popup: 0;
}
QComboBox QAbstractItemView {
    background: #141417;
    color: #e0e0e0;
    border: 1px solid #3a3a44;
    selection-background-color: #34405a;
    selection-color: #ffffff;
}
QPushButton {
    background: #3a3a44;
    color: #e0e0e0;
    border-radius: 4px;
    padding: 5px 12px;
}
QPushButton:hover {
    background: #4a4a56;
}
"""
