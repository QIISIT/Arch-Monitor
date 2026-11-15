"""Свои виджеты: кольцо Ring, полоса Meter, карточка видеокарты GpuCard, кнопки меню и подсказок."""
from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QStyle, QStyledItemDelegate,
                             QStyleOptionViewItem, QWidget)

try:                                   # значки меню рисуются из SVG; без модуля QtSvg меню просто без значков
    from PyQt6.QtSvg import QSvgRenderer
except ImportError:
    QSvgRenderer = None

from . import config as C
from .gpu import Gpu
from .helpers import human_bytes, program_initial
from .theme import T

ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def make_card():
    """Пустая рамка-карточка (стиль QFrame#card задан в style.py)."""
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def dim_label(text):
    """Подпись приглушённым цветом (цвет задаёт style.py по имени QLabel#dim, поэтому тема меняется на лету)."""
    label = QLabel(text)
    label.setObjectName("dim")
    return label


class HintButton(QPushButton):
    """Плашка-подсказка внизу окна («F3 Search»): «таблетка» с клавишей цвета акцента, нажимается мышью."""

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
        self.setFixedHeight(44)
        self.setIconSize(QSize(18, 18))
        self.refresh()

    def refresh(self):
        """Перекрасить значок под тему: обычный приглушённый, у выбранного пункта цвета акцента."""
        icon = QIcon()
        icon.addPixmap(svg_pixmap(self.icon_path, T.dim), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(svg_pixmap(self.icon_path, T.accent), QIcon.Mode.Normal, QIcon.State.On)
        self.setIcon(icon)


def logo_pixmap(size=30):
    """Логотип: круг цвета акцента с тремя столбиками."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(2 * size / 30, 2 * size / 30)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(T.accent))
    p.drawEllipse(QRectF(0, 0, 30, 30))
    p.setBrush(QColor(T.bg))
    for x, y, h in ((8, 14, 8), (13.25, 9, 13), (18.5, 12, 10)):
        p.drawRoundedRect(QRectF(x, y, 3.5, h), 1.75, 1.75)
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


class Ring(QWidget):
    """Круговой индикатор: дуга заполнения, число в центре, единица под ним и подпись снизу.

    size   диаметр, px
    warm   True: дуга цвета предупреждения (для температур), иначе цвета акцента
    mini   маленькое кольцо ядра: только число моноширинным шрифтом
    """

    def __init__(self, label="", size=112, warm=False, mini=False):
        super().__init__()
        self.label, self.size, self.warm, self.mini = label, size, warm, mini
        self.thickness = max(4, round(size * 0.095))
        self.pct, self.value, self.unit = 0.0, "", ""
        self.label_h = 0 if (mini or not label) else 26
        self.setFixedSize(max(size, 96 if self.label_h else size), size + self.label_h)

    def set(self, pct, value, unit=""):
        self.pct = max(0.0, min(100.0, pct))
        self.value, self.unit = value, unit
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d, t = self.size, self.thickness
        x0 = (self.width() - d) / 2
        rect = QRectF(x0 + t / 2, t / 2, d - t, d - t)

        pen = QPen(QColor(T.line), t)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawEllipse(rect)
        if self.pct > 0:
            pen.setColor(QColor(T.amber if self.warm else T.accent))
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -round(max(self.pct, 1.5) / 100 * 360 * 16))   # по часовой от верха

        box = QRectF(x0, 0, d, d)
        font = QFont(self.font())
        p.setPen(QColor(T.text))
        if self.mini:
            font.setFamilies(C.MONO_FONTS)
            font.setPixelSize(max(8, round(d * 0.27)))
            p.setFont(font)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.value)
            return
        font.setBold(True)
        font.setPixelSize(round(d * 0.22))
        p.setFont(font)
        if self.unit:
            p.drawText(QRectF(x0, 0, d, d * 0.56), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self.value)
            small = QFont(self.font())
            small.setPixelSize(max(9, round(d * 0.1)))
            p.setFont(small)
            p.setPen(QColor(T.dim))
            p.drawText(QRectF(x0, d * 0.58, d, d * 0.3), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.unit)
        else:
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.value)
        if self.label_h:
            lab = QFont(self.font())
            lab.setBold(True)
            lab.setPixelSize(13)
            p.setFont(lab)
            p.setPen(QColor(T.text))
            p.drawText(QRectF(0, d, self.width(), self.label_h), Qt.AlignmentFlag.AlignCenter, self.label)


class CommandDelegate(QStyledItemDelegate):
    """Колонка Command в обычном режиме: круглый значок с первой буквой программы перед командой.

    В режиме дерева и на строке-разделителе рисует как обычно (там в тексте линии дерева).
    owner: главное окно (берём из него tree_mode и номер строки-разделителя).
    """

    DOT = 22

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def paint(self, painter, option, index):
        if self.owner.tree_mode or index.row() == self.owner._sep_row:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text, opt.text = opt.text, ""
        widget = opt.widget
        widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)   # фон и выделение

        r, d = option.rect, self.DOT
        circle = QRectF(r.left() + 6, r.center().y() - d / 2 + 0.5, d, d)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        fg = fg.color() if fg is not None else QColor(T.text)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(T.raised))
        painter.drawEllipse(circle)
        font = QFont(opt.font)
        font.setBold(True)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(fg)
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, program_initial(text))
        painter.setFont(opt.font)
        text_rect = r.adjusted(6 + d + 8, 0, -6, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width()))
        painter.restore()


class Meter(QWidget):
    """Горизонтальная полоса: [подпись] [=====-----] [значение].

    label  подпись слева
    lw     ширина под подпись, px
    tw     ширина под значение справа, px
    heat   True: цвет меняется с ростом (синий, жёлтый, красный); False: всегда синий
    """

    def __init__(self, label, lw=34, tw=52, heat=True):
        super().__init__()
        self.label, self.lw, self.tw, self.heat = label, lw, tw, heat
        self.pct, self.text = 0.0, "0%"
        self.setFixedHeight(24)
        self.setMinimumWidth(140)

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
        bar_w = w - self.lw - self.tw - 8
        bar = QRectF(self.lw, h / 2 - 3, bar_w, 6)

        p.setPen(QColor(T.dim))
        p.drawText(QRectF(0, 0, self.lw, h), ALIGN_LEFT, self.label)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.line))
        p.drawRoundedRect(bar, 3, 3)                       # пустая дорожка
        if self.pct > 0:
            filled = QRectF(bar.x(), bar.y(), max(6.0, bar_w * self.pct / 100), bar.height())
            p.setBrush(QColor(self._fill_color()))
            p.drawRoundedRect(filled, 3, 3)                # заполненная часть

        p.setPen(QColor(T.text))
        p.drawText(QRectF(w - self.tw, 0, self.tw, h), ALIGN_RIGHT, self.text)


class GpuCard(QFrame):
    """Карточка одной видеокарты: две колонки полос.

    Слева:  GPU, VRAM, Temp, Fan.   Справа: Core clk, Mem clk, Power, Volt.
    Чтобы добавить показатель, создай Meter в __init__, положи в сетку и заполни в show_gpu().
    """

    def __init__(self, tag):
        super().__init__()
        self.setObjectName("card")
        self.tag = tag
        self._peak = {}   # максимумы, которые видели сами (если драйвер не сообщает предел)

        grid = QGridLayout(self)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(2)

        self.title = dim_label(tag)
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
