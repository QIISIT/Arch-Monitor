"""Свои виджеты: сводный показатель, полосы, секция видеокарты, кнопки меню и подсказок."""
from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

try:                                   # значки меню рисуются из SVG; без модуля QtSvg меню просто без значков
    from PyQt6.QtSvg import QSvgRenderer
except ImportError:
    QSvgRenderer = None

from . import config as C
from .gpu import Gpu
from .helpers import human_bytes
from .theme import T

ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def make_section():
    """Секция на общем фоне, отделённая сверху линией."""
    frame = QFrame()
    frame.setObjectName("section")
    return frame


def divider():
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


def dim_label(text):
    """Подпись приглушённым цветом (цвет задаёт style.py по имени QLabel#dim, поэтому тема меняется на лету)."""
    label = QLabel(text)
    label.setObjectName("dim")
    return label


class HintButton(QPushButton):
    """Кликабельная подсказка горячей клавиши внизу окна."""

    def __init__(self, key, name, tooltip=""):
        super().__init__()
        self.key, self.name, self.active = key, name, False
        self.setObjectName("hint")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # клик не уводит фокус из таблицы или поля поиска
        self.setToolTip(tooltip)
        self.setFixedHeight(30)

        self.caption = QLabel()
        self.caption.setTextFormat(Qt.TextFormat.RichText)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # клик достаётся кнопке
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 0, 11, 0)
        layout.addWidget(self.caption)
        self.refresh()

    def sizeHint(self):
        return QSize(self.caption.sizeHint().width() + 22, 30)

    def minimumSizeHint(self):
        return self.sizeHint()

    def refresh(self):
        """Перерисовать с цветами текущей темы (вызывается при смене темы)."""
        key_color = T.amber if self.active else T.accent
        self.caption.setText(f'<b style="color:{key_color}">{self.key}</b>&nbsp;&nbsp;'
                             f'<span style="color:{T.text}">{self.name}</span>')
        self.updateGeometry()

    def set_active(self, active):
        """Подсветить клавишу жёлтым (для включённых режимов, например паузы)."""
        self.active = active
        self.refresh()


def svg_pixmap(path_d, color, size=18):
    """Значок из контура SVG (как в макете) нужного цвета; пустой, если нет QtSvg."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    if QSvgRenderer is not None:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
               f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="{path_d}"/></svg>')
        p = QPainter(pm)
        QSvgRenderer(QByteArray(svg.encode())).render(p)
        p.end()
    pm.setDevicePixelRatio(2)
    return pm


class NavButton(QPushButton):
    """Пункт бокового меню: значок и подпись; выбранный пункт подсвечен."""

    def __init__(self, label, icon_path):
        super().__init__(label)
        self.icon_path = icon_path
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(37)
        self.setIconSize(QSize(18, 18))
        self.refresh()

    def refresh(self):
        """Перекрасить значок под тему: обычный приглушённый, у выбранного пункта цвета акцента."""
        icon = QIcon()
        icon.addPixmap(svg_pixmap(self.icon_path, T.dim), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(svg_pixmap(self.icon_path, T.accent), QIcon.Mode.Normal, QIcon.State.On)
        self.setIcon(icon)


def logo_pixmap(size=30):
    """Логотип: три столбика цвета акцента на квадратном фоне."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(2 * size / 30, 2 * size / 30)
    p.setPen(Qt.PenStyle.NoPen)
    p.fillRect(QRectF(0, 0, 30, 30), QColor(T.selection))
    p.setBrush(QColor(T.accent))
    for x, y, h in ((8, 14, 8), (13.25, 9, 13), (18.5, 12, 10)):
        p.drawRect(QRectF(x, y, 3.5, h))
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


class Metric(QFrame):
    """Сводный показатель: название, число, пояснение и тонкая шкала."""

    def __init__(self, title, last=False):
        super().__init__()
        self.setObjectName("metric")
        self.setProperty("last", last)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0 if last else 16, 0)
        box.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        box.addWidget(title_label)
        box.addSpacing(4)
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        box.addWidget(self.value)
        self.detail = dim_label("")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.detail.setFixedHeight(self.detail.sizeHint().height())
        box.addWidget(self.detail)
        box.addSpacing(4)
        self.meter = Meter("", lw=0, tw=0, heat=False, compact=True)
        self.meter.setFixedHeight(5)
        box.addWidget(self.meter)

    def set(self, percent, value, detail=None):
        self.meter.set(percent, "")
        self.value.setText(value)
        if detail is not None:
            self.set_detail(detail)

    def set_detail(self, text):
        self.detail.setText(text)
        self.detail.setToolTip(text)


class Meter(QWidget):
    """Горизонтальная полоса: [подпись] [=====-----] [значение].

    label  подпись слева
    lw     ширина под подпись, px
    tw     ширина под значение справа, px
    heat   True: цвет меняется с ростом (синий, жёлтый, красный); False: всегда синий
    """

    def __init__(self, label, lw=34, tw=52, heat=True, compact=False):
        super().__init__()
        self.label, self.lw, self.tw, self.heat = label, lw, tw, heat
        self.pct, self.text = 0.0, "0%"
        self.compact = compact
        self.setFixedHeight(20 if compact else 24)
        if compact:
            font = QFont(self.font())
            font.setFamilies(C.MONO_FONTS)
            font.setPixelSize(11)
            self.setFont(font)
        self.setMinimumWidth(lw + tw + 25 if compact else 140)

    def set(self, pct, text=None):
        """pct: заполнение 0..100; text: значение справа (по умолчанию процент)."""
        self.pct = max(0.0, min(100.0, pct))
        self.text = text if text is not None else f"{pct:.0f}%"
        self.update()

    def _fill_color(self):
        if not self.heat or self.pct < C.WARN_AT:
            return T.accent
        return T.amber if self.pct < C.CRIT_AT else T.red

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        space = 5 if self.tw else 0
        bar_w = max(0, w - self.lw - self.tw - space)
        thickness = 3 if self.compact else 4
        bar = QRectF(self.lw, (h - thickness) / 2, bar_w, thickness)

        p.setPen(QColor(T.dim))
        p.drawText(QRectF(0, 0, self.lw, h), ALIGN_LEFT, self.label)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.line))
        p.drawRect(bar)
        if self.pct > 0:
            filled = QRectF(bar.x(), bar.y(), min(bar_w, max(1.0, bar_w * self.pct / 100)), bar.height())
            p.setBrush(QColor(self._fill_color()))
            p.drawRect(filled)

        p.setPen(QColor(T.text))
        p.drawText(QRectF(w - self.tw, 0, self.tw, h), ALIGN_RIGHT, self.text)


class GpuSection(QFrame):
    """Секция одной видеокарты: две колонки полос.

    Слева:  GPU, VRAM, Temp, Fan.   Справа: Core clk, Mem clk, Power, Volt.
    Чтобы добавить показатель, создай Meter в __init__, положи в сетку и заполни в show_gpu().
    """

    def __init__(self, tag):
        super().__init__()
        self.setObjectName("section")
        self.tag = tag
        self._peak = {}   # максимумы, которые видели сами (если драйвер не сообщает предел)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 12, 0, 12)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(2)

        self.title = QLabel(tag)
        self.title.setObjectName("strong")
        grid.addWidget(self.title, 0, 0, 1, 2)

        self.util = Meter("GPU", 44, 52)
        self.vram = Meter("VRAM", 44, 100)
        self.temp = Meter("Temp", 44, 52)
        self.fan = Meter("Fan", 44, 52, heat=False)
        self.core = Meter("Core clk", 62, 76, heat=False)
        self.mem_clk = Meter("Mem clk", 62, 76, heat=False)
        self.power = Meter("Power", 62, 90, heat=False)
        self.volt = Meter("Volt", 62, 70, heat=False)
        for row, meter in enumerate((self.util, self.vram, self.temp, self.fan), 1):
            grid.addWidget(meter, row, 0)
        for row, meter in enumerate((self.core, self.mem_clk, self.power, self.volt), 1):
            grid.addWidget(meter, row, 1)

    def _show_value(self, meter, value, top, key, text):
        """Показать значение на полосе; если датчика нет (None), скрыть полосу.

        top: предел шкалы; если неизвестен, берётся наибольшее значение, виденное раньше.
        """
        if value is None:
            meter.hide()
            return
        self._peak[key] = max(self._peak.get(key, 0.0), value)
        meter.show()
        meter.set(value / (top or self._peak[key] or 1.0) * 100, text)

    def show_gpu(self, g: Gpu):
        self.title.setText(f"{self.tag}   {g.name[:C.GPU_NAME_MAX_CHARS]}")
        self.util.set(g.util, g.util_text)

        self.vram.setVisible(bool(g.vram_total))
        if g.vram_total and g.vram_used is not None:
            self.vram.set(g.vram_used / g.vram_total * 100,
                          f"{human_bytes(g.vram_used)}/{human_bytes(g.vram_total)}")
        elif g.vram_total:
            self.vram.set(0, f"—/{human_bytes(g.vram_total)}")

        def fmt(value, template):
            return "" if value is None else template.format(value)

        self._show_value(self.temp, g.temp, C.TEMP_SCALE_MAX, "temp", fmt(g.temp, "{:.0f}\u00b0C"))
        self._show_value(self.fan, g.fan, 100.0, "fan", fmt(g.fan, "{:.0f}%"))
        self._show_value(self.core, g.core_clk, g.core_max, "core", fmt(g.core_clk, "{:.0f} MHz"))
        self._show_value(self.mem_clk, g.mem_clk, g.mem_max, "mem", fmt(g.mem_clk, "{:.0f} MHz"))

        power_text = ""
        if g.power is not None:
            power_text = f"{g.power:.0f}/{g.power_max:.0f} W" if g.power_max else f"{g.power:.0f} W"
        self._show_value(self.power, g.power, g.power_max, "power", power_text)

        lo, hi = C.VOLT_RANGE_MV
        volt = None if g.voltage is None else g.voltage - lo
        self._show_value(self.volt, volt, hi - lo, "volt", fmt(g.voltage, "{:.0f} mV"))
