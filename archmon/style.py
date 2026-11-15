"""Общая таблица стилей (QSS). Цвета берутся из текущей темы (theme.py).

Кнопки и поля скруглены «таблетками», карточки скруглены на 20 px, как в выбранном макете.
"""
from .theme import T

PILL = 19   # радиус скругления кнопок и полей высотой 38 px


def build_qss():
    return f"""
QWidget {{ background:{T.bg}; color:{T.text}; font-size:13px; }}
QLabel#dim {{ color:{T.dim}; }}
QLabel#title {{ font-size:21px; font-weight:800; }}
QLabel#brand {{ font-size:16px; font-weight:800; }}
QLabel#strong {{ font-weight:700; }}
QLabel#stat {{ font-size:16px; font-weight:800; }}
QLabel#code {{ background:{T.bg}; border:1px solid {T.line}; border-radius:12px; padding:10px 12px; }}

QFrame#side {{ background:{T.side}; border:0; border-right:1px solid {T.line}; }}
QFrame#side QWidget {{ background:transparent; }}
QFrame#card {{ background:{T.card}; border:1px solid {T.line}; border-radius:20px; }}
QFrame#card QWidget {{ background:transparent; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background:{T.card}; border:1px solid {T.line};
    border-radius:{PILL}px; padding:6px 14px; min-height:24px; }}
QPlainTextEdit {{ background:{T.card}; border:1px solid {T.line}; border-radius:14px; padding:6px 10px; }}
QFrame#card QLineEdit, QFrame#card QComboBox, QFrame#card QSpinBox, QFrame#card QDoubleSpinBox,
QFrame#card QPlainTextEdit {{ background:{T.bg}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border:1px solid {T.accent}; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled,
QFrame#card QComboBox:disabled, QFrame#card QSpinBox:disabled, QFrame#card QLineEdit:disabled {{
    color:{T.dim}; background:{T.card}; border:1px dashed {T.line}; }}
QComboBox QAbstractItemView {{ background:{T.card}; border:1px solid {T.line}; selection-background-color:{T.selection}; }}

QPushButton {{ background:{T.card}; border:1px solid {T.line}; border-radius:{PILL}px; padding:8px 16px; }}
QFrame#card QPushButton {{ background:{T.raised}; }}
QPushButton:hover, QFrame#card QPushButton:hover {{ border:1px solid {T.accent}; }}
QPushButton:checked, QFrame#card QPushButton:checked {{ background:{T.accent}; border:1px solid {T.accent};
    color:{T.bg}; font-weight:700; }}
QPushButton:disabled, QFrame#card QPushButton:disabled {{ color:{T.dim}; }}
QPushButton#danger, QFrame#card QPushButton#danger {{ color:{T.red}; }}
QPushButton#primary, QFrame#card QPushButton#primary {{ background:{T.accent}; border:1px solid {T.accent}; color:{T.bg}; font-weight:700; }}
QPushButton#primary:disabled, QFrame#card QPushButton#primary:disabled {{ background:{T.raised}; border:1px solid {T.line}; color:{T.dim}; }}
QPushButton#danger:hover, QFrame#card QPushButton#danger:hover {{ border:1px solid {T.red}; }}

QPushButton#nav, QFrame#side QPushButton#nav {{ background:transparent; border:0; border-radius:22px;
    padding:0 14px; text-align:left; color:{T.dim}; font-weight:600; font-size:14px; }}
QPushButton#nav:hover, QFrame#side QPushButton#nav:hover {{ background:{T.raised}; color:{T.text}; }}
QPushButton#nav:checked, QFrame#side QPushButton#nav:checked {{ background:{T.line}; color:{T.text}; font-weight:700; }}

QPushButton#hint {{ background:{T.card}; border:1px solid {T.line}; border-radius:15px; padding:0; }}
QPushButton#hint:hover {{ border:1px solid {T.accent}; }}
QPushButton#hint QLabel {{ background:transparent; }}

QTableWidget {{ background:transparent; border:0; gridline-color:transparent;
    selection-background-color:{T.selection}; selection-color:{T.text}; outline:0; }}
QTableWidget::item {{ padding:0 8px; border:0; }}
QHeaderView, QHeaderView::section {{ background:transparent; }}
QHeaderView::section {{ color:{T.dim}; border:0; border-bottom:1px solid {T.line}; padding:6px 8px; font-weight:700; }}

QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{T.line}; border-radius:4px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{T.accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{T.line}; border-radius:4px; min-width:30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}

QTabWidget::pane {{ border:1px solid {T.line}; border-radius:14px; top:-1px; }}
QTabBar::tab {{ background:transparent; color:{T.dim}; padding:8px 18px; border:0; border-bottom:2px solid transparent; }}
QTabBar::tab:selected {{ color:{T.text}; border-bottom:2px solid {T.accent}; }}
QGroupBox {{ border:1px solid {T.line}; border-radius:14px; margin-top:14px; padding:12px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin:margin; left:12px; color:{T.dim}; }}
QCheckBox {{ spacing:8px; }}
QListWidget {{ background:{T.card}; border:1px solid {T.line}; border-radius:14px; }}
QListWidget::item:selected {{ background:{T.selection}; color:{T.text}; }}
QMenu {{ background:{T.card}; border:1px solid {T.line}; padding:4px; }}
QMenu::item {{ padding:6px 18px; border-radius:4px; }}
QMenu::item:selected {{ background:{T.selection}; }}
QToolTip {{ background:{T.card}; color:{T.text}; border:1px solid {T.line}; padding:4px; }}
"""
