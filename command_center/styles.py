DARK_THEME = r"""
QWidget {
    background-color: #07111d;
    color: #e8eef7;
    font-family: "Segoe UI";
    font-size: 14px;
}

QMainWindow, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: #07111d;
}

QFrame#topBar {
    background-color: #0d1a29;
    border-bottom: 1px solid #26374a;
}

QFrame#sideBar {
    background-color: #0a1624;
    border-right: 1px solid #26374a;
}

QLabel#appTitle {
    color: #ffffff;
    font-size: 21px;
    font-weight: 600;
}

QLabel#pageTitle {
    color: #ffffff;
    font-size: 22px;
    font-weight: 600;
}

QLabel#sectionTitle {
    color: #ffffff;
    font-size: 16px;
    font-weight: 600;
}

QLabel[muted="true"] {
    color: #94a8bd;
}

QLabel[status="online"] {
    color: #8de0b1;
    background-color: #123726;
    border-radius: 12px;
    padding: 5px 9px;
}

QLabel[status="warning"] {
    color: #ffd77b;
    background-color: #46330f;
    border-radius: 12px;
    padding: 5px 9px;
}

QLabel[status="offline"] {
    color: #c1cad5;
    background-color: #29333f;
    border-radius: 12px;
    padding: 5px 9px;
}

QFrame#controllerRow,
QFrame#summaryPanel,
QFrame#contentPanel,
QFrame#cameraTile,
QFrame#formPanel {
    background-color: #101e2e;
    border: 1px solid #2a3d52;
    border-radius: 10px;
}

QFrame#metricCell,
QFrame#signalRow,
QFrame#signalMiniTile {
    background-color: #0a1725;
    border: none;
    border-radius: 7px;
}

QFrame#controllerConfigGrid {
    background-color: #0a1725;
    border: 1px solid #263b50;
    border-radius: 8px;
}

QCheckBox {
    spacing: 7px;
    color: #dce8f5;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #4b657e;
    border-radius: 4px;
    background-color: #091522;
}

QCheckBox::indicator:checked {
    background-color: #2e83ca;
    border-color: #76b7ee;
}

QLabel#signalMiniLamp {
    min-width: 14px;
    max-width: 14px;
    min-height: 14px;
    max-height: 14px;
    border-radius: 7px;
}

QLabel#signalMiniLamp[aspect="GREEN"] {
    background-color: #42d58b;
    border: 1px solid #8de0b1;
}

QLabel#signalMiniLamp[aspect="YELLOW"] {
    background-color: #f6c453;
    border: 1px solid #ffe29a;
}

QLabel#signalMiniLamp[aspect="RED"] {
    background-color: #ef5a64;
    border: 1px solid #ff9ca3;
}

QLabel#signalMiniLamp[aspect="OFF"] {
    background-color: #29333f;
    border: 1px solid #536170;
}

QFrame#cameraScreen {
    background-color: #050b12;
    border: 1px solid #31465c;
    border-radius: 7px;
}

QLabel#cameraPlaceholder {
    color: #7890a6;
    background-color: transparent;
    font-size: 16px;
}

QFrame#cameraCaptionBar {
    background-color: #132234;
    border-top: 1px solid #31465c;
}

QLabel#cameraCaption {
    color: #f1f6fc;
    background-color: transparent;
    border: none;
    padding: 0px;
}

QLabel#cameraStreamStatus {
    color: #8de0b1;
    background-color: #0a1725;
    border: 1px solid #31465c;
    border-radius: 7px;
    padding: 1px 3px;
    font-size: 9px;
    font-weight: 600;
}

QPushButton#cameraFullscreenButton {
    min-height: 21px;
    max-height: 21px;
    padding: 0px 3px;
    font-size: 9px;
}

QPushButton {
    min-height: 34px;
    padding: 5px 11px;
    border-radius: 7px;
    border: 1px solid #38506a;
    color: #dce8f5;
    background-color: #15283a;
}

QPushButton:hover {
    background-color: #1c354c;
    border-color: #4d6e90;
}

QPushButton:pressed {
    background-color: #0e1f30;
}

QPushButton#primaryButton {
    color: #ffffff;
    background-color: #1766a8;
    border-color: #2e83ca;
}

QPushButton#compactButton {
    min-height: 27px;
    padding: 2px 9px;
    color: #ffffff;
    background-color: #1766a8;
    border-color: #2e83ca;
}

QLabel[compact="true"] {
    padding: 3px 7px;
}

QPushButton#dangerButton {
    color: #ffd7da;
    background-color: #5a252b;
    border-color: #8e3f48;
}

QPushButton#navButton {
    min-height: 40px;
    text-align: left;
    padding-left: 14px;
    color: #aebed0;
    background-color: transparent;
    border: none;
}

QPushButton#navButton:checked {
    color: #ffffff;
    background-color: #174c79;
}

QPushButton#cameraListButton {
    min-height: 42px;
    text-align: left;
    padding-left: 12px;
    background-color: #0a1725;
    border-color: transparent;
}

QPushButton#cameraListButton:checked {
    background-color: #174c79;
    border-color: #2d78b5;
}

QLineEdit, QComboBox, QSpinBox {
    min-height: 36px;
    padding: 4px 8px;
    color: #edf5ff;
    background-color: #091522;
    border: 1px solid #385069;
    border-radius: 7px;
    selection-background-color: #1766a8;
}

QComboBox QAbstractItemView {
    color: #edf5ff;
    background-color: #101e2e;
    border: 1px solid #385069;
    selection-background-color: #174c79;
}

QScrollBar:vertical {
    width: 11px;
    background: #091522;
}

QScrollBar::handle:vertical {
    min-height: 30px;
    border-radius: 5px;
    background: #385069;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QStatusBar {
    color: #9fb0c2;
    background-color: #0d1a29;
    border-top: 1px solid #26374a;
}
"""
