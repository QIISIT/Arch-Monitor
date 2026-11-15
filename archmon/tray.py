"""Значок в системном трее: иконка-столбики с живой нагрузкой, подсказка и меню."""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from . import config as C
from .theme import T


def render_icon(levels):
    """Иконка 64×64: по столбику на каждое значение из levels (0..100)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(T.bg))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    bar_w, gap = 10, 6
    x0 = (64 - (len(levels) * bar_w + (len(levels) - 1) * gap)) / 2
    for i, level in enumerate(levels):
        level = max(0.0, min(100.0, level))
        height = 8 + 38 * level / 100
        color = T.accent if level < C.WARN_AT else T.amber if level < C.CRIT_AT else T.red
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(x0 + i * (bar_w + gap), 54 - height, bar_w, height), 3, 3)
    p.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    """Клик по значку показывает или прячет окно; правый клик открывает меню."""

    def __init__(self, window):
        super().__init__(window)
        self.setIcon(render_icon([0, 0, 0]))
        self.menu = QMenu()
        self.menu.addAction("Show / Hide", window.toggle_visible)
        self.menu.addSeparator()
        self.menu.addAction("Quit", window.quit_app)
        self.setContextMenu(self.menu)
        self.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger
                               and window.toggle_visible())
        self.show()

    def set_status(self, levels, tooltip):
        """levels: значения для столбиков иконки; tooltip: текст при наведении."""
        self.setIcon(render_icon(levels))
        self.setToolTip(tooltip)
