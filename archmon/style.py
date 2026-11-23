"""Плоский интерфейс. Цвета элементов берутся из текущей темы."""
from .theme import T, mix


def build_qss():
    subtle = mix(T.bg, T.card, 0.42)
    return f"""
QWidget {{ background:{T.bg}; color:{T.text}; font-size:13px; }}
QLabel#dim {{ color:{T.dim}; font-size:12px; }}
QLabel#title {{ font-size:28px; font-weight:800; }}
QLabel#brand {{ font-size:16px; font-weight:800; }}
QLabel#strong {{ font-weight:700; }}
QLabel#sectionTitle {{ font-size:17px; font-weight:700; }}
QLabel#stat {{ font-size:16px; font-weight:700; }}
QLabel#metricTitle, QLabel#navGroup {{ color:{T.dim}; font-size:11px; font-weight:700; }}
QLabel#metricValue {{ font-size:27px; font-weight:800; }}
QLabel#code {{ background:{T.card}; border:1px solid {T.line}; padding:8px 10px; }}

QFrame#side {{ background:{T.side}; border:0; border-right:1px solid {T.line}; }}
QFrame#side QWidget {{ background:transparent; }}
QLabel#navGroup {{ padding:4px 20px; }}
QFrame#divider, QFrame#side QFrame#divider {{ background:{T.line}; border:0; }}
QFrame#section {{ border:0; border-top:1px solid {T.line}; }}
QFrame#metric {{ border:0; border-right:1px solid {T.line}; }}
QFrame#metric[last="true"] {{ border:0; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background:{T.bg}; border:1px solid {T.line}; padding:4px 8px; min-height:20px; }}
QPlainTextEdit {{ background:{subtle}; border:1px solid {T.line}; padding:6px 8px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border:1px solid {T.accent}; }}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled {{
    color:{T.dim}; background:{subtle}; }}
QComboBox QAbstractItemView {{
    background:{T.card}; border:1px solid {T.line}; selection-background-color:{T.selection}; }}

QPushButton {{ background:{T.bg}; border:1px solid {T.line}; padding:6px 10px; }}
QPushButton:hover, QPushButton:focus {{ border-color:{T.accent}; }}
QPushButton:checked {{ background:{T.selection}; border-color:{T.accent}; color:{T.accent}; }}
QPushButton:disabled {{ color:{T.dim}; border-color:{T.line}; }}
QPushButton#danger {{ color:{T.red}; }}
QPushButton#danger:hover, QPushButton#danger:focus {{ border-color:{T.red}; }}
QPushButton#primary {{ background:{T.accent}; border-color:{T.accent}; color:{T.bg}; font-weight:700; }}
QPushButton#primary:disabled {{ background:{subtle}; border-color:{T.line}; color:{T.dim}; }}

QFrame#side QPushButton#nav {{
    background:transparent; border:0; border-left:3px solid transparent;
    padding:0 17px; text-align:left; color:{T.dim}; font-size:14px; }}
QFrame#side QPushButton#nav:hover {{ background:{T.raised}; color:{T.text}; }}
QFrame#side QPushButton#nav:focus {{ border-left-color:{T.dim}; }}
QFrame#side QPushButton#nav:checked {{
    background:{T.selection}; border-left-color:{T.accent}; color:{T.text}; font-weight:700; }}

QPushButton#hint {{ background:transparent; border:1px solid transparent; padding:0; }}
QPushButton#hint:hover {{ background:{subtle}; border-color:{T.line}; }}
QPushButton#hint QLabel {{ background:transparent; font-size:12px; }}

QTableWidget {{ background:{T.bg}; alternate-background-color:{subtle}; border:0;
    selection-background-color:{T.selection}; selection-color:{T.text}; outline:0; }}
QTableWidget::item {{ padding:0 8px; border:0; border-bottom:1px solid {subtle}; }}
QHeaderView, QHeaderView::section {{ background:{T.card}; }}
QHeaderView::section {{
    color:{T.dim}; border:0; border-bottom:1px solid {T.line}; padding:7px 8px; font-weight:700; }}

QScrollBar:vertical {{ background:{subtle}; width:8px; }}
QScrollBar::handle:vertical {{ background:{T.line}; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{T.accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar:horizontal {{ background:{subtle}; height:8px; }}
QScrollBar::handle:horizontal {{ background:{T.line}; min-width:30px; }}
QScrollBar::handle:horizontal:hover {{ background:{T.accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}

QTabWidget::pane {{ border:0; border-top:1px solid {T.line}; top:-1px; }}
QTabBar::tab {{
    background:transparent; color:{T.dim}; padding:8px 18px;
    border:0; border-bottom:2px solid transparent; }}
QTabBar::tab:selected {{ color:{T.text}; border-bottom-color:{T.accent}; }}
QGroupBox {{ border:0; border-top:1px solid {T.line}; margin-top:13px; padding-top:10px; }}
QGroupBox::title {{ subcontrol-origin:margin; left:0; color:{T.dim}; }}
QCheckBox {{ spacing:8px; }}
QCheckBox::indicator:unchecked {{ width:12px; height:12px; background:{T.bg}; border:1px solid {T.line}; }}
QCheckBox::indicator:unchecked:hover {{ border-color:{T.accent}; }}
QListWidget {{ background:{subtle}; border:1px solid {T.line}; }}
QListWidget::item:selected {{ background:{T.selection}; color:{T.text}; }}
QMenu {{ background:{T.card}; border:1px solid {T.line}; padding:4px; }}
QMenu::item {{ padding:6px 18px; }}
QMenu::item:selected {{ background:{T.selection}; }}
QToolTip {{ background:{T.card}; color:{T.text}; border:1px solid {T.line}; padding:4px; }}
"""
