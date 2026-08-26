"""Application palette and Qt style sheet."""

from __future__ import annotations


COLORS = {
    "navy": "#0F172A",
    "navy_light": "#172554",
    "accent": "#0284C7",
    "accent_hover": "#0369A1",
    "cyan": "#0891B2",
    "green": "#059669",
    "amber": "#D97706",
    "red": "#DC2626",
    "canvas": "#F3F6FA",
    "card": "#FFFFFF",
    "text": "#0F172A",
    "muted": "#64748B",
    "line": "#DCE4EE",
}


APP_STYLE = """
* {
    font-family: "Segoe UI", "Arial";
    font-size: 10pt;
    color: #0F172A;
}
QMainWindow, QWidget#AppRoot, QScrollArea#PageScroll, QScrollArea#PageScroll > QWidget > QWidget {
    background: #F3F6FA;
}
QMenuBar {
    background: #FFFFFF;
    border-bottom: 1px solid #DCE4EE;
    padding: 3px 8px;
}
QMenuBar::item {
    padding: 6px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected { background: #E0F2FE; }
QMenu {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    padding: 6px;
}
QMenu::item { padding: 7px 30px 7px 24px; border-radius: 5px; }
QMenu::item:selected { background: #E0F2FE; color: #075985; }
QFrame#Sidebar { background: #0F172A; border: none; }
QLabel#BrandMark {
    background: #0EA5E9;
    color: white;
    border-radius: 12px;
    font-size: 15pt;
    font-weight: 700;
    padding: 9px;
}
QLabel#BrandTitle { color: #F8FAFC; font-size: 16pt; font-weight: 700; }
QLabel#BrandSubtitle { color: #94A3B8; font-size: 8.5pt; }
QPushButton#NavButton {
    color: #CBD5E1;
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 10px 12px;
    text-align: left;
    font-weight: 500;
}
QPushButton#NavButton:hover { background: #1E293B; color: white; }
QPushButton#NavButton:checked {
    background: #0C4A6E;
    color: #E0F2FE;
    border-left: 3px solid #38BDF8;
    font-weight: 650;
}
QLabel#SidebarStatus {
    color: #94A3B8;
    background: #111C33;
    border: 1px solid #26344C;
    border-radius: 9px;
    padding: 9px;
}
QFrame#TopBar {
    background: #FFFFFF;
    border-bottom: 1px solid #DCE4EE;
}
QLabel#WindowTitle { font-size: 14pt; font-weight: 700; }
QLabel#PathChip {
    color: #475569;
    background: #F1F5F9;
    border: 1px solid #DCE4EE;
    border-radius: 8px;
    padding: 6px 10px;
}
QLabel#TopBarLabel { color: #64748B; font-size: 9pt; font-weight: 600; }
QComboBox#LanguageCombo {
    color: #075985;
    background: #F0F9FF;
    border: 1px solid #7DD3FC;
    border-radius: 8px;
    padding: 6px 24px 6px 9px;
    font-weight: 700;
}
QComboBox#LanguageCombo:hover { background: #E0F2FE; }
QComboBox#LanguageCombo::drop-down { border: none; width: 20px; }
QComboBox#LanguageCombo QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #BAE6FD;
    selection-background-color: #E0F2FE;
    selection-color: #075985;
}
QPushButton#PrimaryButton {
    color: white;
    background: #0284C7;
    border: none;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 650;
}
QPushButton#PrimaryButton:hover { background: #0369A1; }
QPushButton#PrimaryButton:disabled { background: #94A3B8; color: #E2E8F0; }
QPushButton#SecondaryButton, QToolButton#SecondaryButton {
    color: #075985;
    background: #E0F2FE;
    border: 1px solid #BAE6FD;
    border-radius: 8px;
    padding: 7px 12px;
    font-weight: 600;
}
QPushButton#SecondaryButton:hover, QToolButton#SecondaryButton:hover { background: #BAE6FD; }
QPushButton#GhostButton, QToolButton#GhostButton {
    color: #475569;
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 7px;
    padding: 6px 10px;
}
QPushButton#GhostButton:hover, QToolButton#GhostButton:hover { background: #F1F5F9; }
QFrame#Card, QFrame#MetricCard, QFrame#ResultPage, QFrame#ImagePanel, QFrame#TablePanel {
    background: #FFFFFF;
    border: 1px solid #DCE4EE;
    border-radius: 14px;
}
QLabel#PageTitle { font-size: 20pt; font-weight: 750; color: #0F172A; }
QLabel#PageSubtitle { color: #64748B; font-size: 10pt; }
QLabel#CardTitle { font-size: 11pt; font-weight: 700; color: #1E293B; }
QLabel#CardSubtitle { color: #64748B; font-size: 9pt; }
QLabel#MetricValue { font-size: 21pt; font-weight: 750; color: #0F172A; }
QLabel#MetricLabel { color: #64748B; font-size: 9pt; }
QLabel#MetricAccent { color: #0284C7; font-size: 8.5pt; font-weight: 600; }
QLabel#SectionTitle { font-size: 13pt; font-weight: 700; color: #1E293B; }
QLabel#NoticeInfo {
    background: #E0F2FE;
    color: #075985;
    border: 1px solid #BAE6FD;
    border-radius: 9px;
    padding: 10px 12px;
}
QLabel#NoticeWarn {
    background: #FFFBEB;
    color: #92400E;
    border: 1px solid #FDE68A;
    border-radius: 9px;
    padding: 10px 12px;
}
QLabel#StatusSuccess {
    background: #D1FAE5;
    color: #065F46;
    border-radius: 8px;
    padding: 5px 9px;
    font-weight: 650;
}
QLabel#StatusNeutral {
    background: #E2E8F0;
    color: #475569;
    border-radius: 8px;
    padding: 5px 9px;
    font-weight: 650;
}
QTableView {
    background: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #DCE4EE;
    border-radius: 8px;
    gridline-color: #E7EDF4;
    selection-background-color: #D8F0FC;
    selection-color: #0F172A;
}
QHeaderView::section {
    background: #EFF5FA;
    color: #334155;
    border: none;
    border-right: 1px solid #DCE4EE;
    border-bottom: 1px solid #CBD5E1;
    padding: 8px 7px;
    font-weight: 650;
}
QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #DCE4EE;
    border-radius: 9px;
    top: -1px;
}
QTabBar::tab {
    background: #E8EEF5;
    color: #475569;
    border: 1px solid #DCE4EE;
    padding: 8px 13px;
    margin-right: 3px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}
QTabBar::tab:selected { background: #FFFFFF; color: #0369A1; font-weight: 650; }
QScrollBar:vertical { background: #EEF2F7; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #B7C4D3; min-height: 28px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #EEF2F7; height: 11px; }
QScrollBar::handle:horizontal { background: #B7C4D3; min-width: 28px; border-radius: 5px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QStatusBar { background: #FFFFFF; color: #64748B; border-top: 1px solid #DCE4EE; }
QDialog { background: #F8FAFC; }
QTextBrowser, QTextEdit {
    background: #FFFFFF;
    border: 1px solid #DCE4EE;
    border-radius: 9px;
    padding: 8px;
}
QProgressBar {
    background: #E2E8F0;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
}
QProgressBar::chunk { background: #0EA5E9; border-radius: 6px; }
"""
