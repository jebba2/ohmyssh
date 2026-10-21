"""Application-wide Qt stylesheets."""

DARK_STYLESHEET = """
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
    font-family: Consolas, monospace;
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
QLineEdit, QSpinBox, QListWidget, QPlainTextEdit {
    background: #141417;
    color: #e0e0e0;
    border: 1px solid #3a3a44;
    border-radius: 4px;
    padding: 4px;
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
