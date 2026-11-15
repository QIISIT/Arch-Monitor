"""Страница Disks: карточка на каждый диск (скорость, загрузка, температура) и его разделы."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from . import disks
from .helpers import human_bytes
from .widgets import Meter, dim_label, make_card


def rate_text(bytes_per_s):
    return f"{human_bytes(bytes_per_s)}/s" if bytes_per_s >= 1024 else "0 B/s"


class DiskCard:
    """Карточка одного диска. Виджеты создаются один раз, show() только обновляет значения."""

    def __init__(self, disk):
        self.card = make_card()
        box = QVBoxLayout(self.card)
        box.setContentsMargins(22, 16, 22, 16)
        box.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel(disk.model)
        title.setObjectName("strong")
        details = " · ".join(x for x in (disk.kind, human_bytes(disk.size) if disk.size else "",
                                         disk.name if disk.name != "other" else "") if x)
        self.temp = QLabel("")
        self.temp.setObjectName("stat")
        head.addWidget(title)
        head.addSpacing(10)
        head.addWidget(dim_label(details))
        head.addStretch()
        head.addWidget(self.temp)
        box.addLayout(head)

        self.stats = {}
        if disk.name != "other":
            stats = QGridLayout()
            stats.setHorizontalSpacing(28)
            for c, key in enumerate(("Read", "Write", "Busy", "Read since boot", "Written since boot")):
                value = QLabel("—")
                value.setObjectName("stat")
                stats.addWidget(dim_label(key), 0, c)
                stats.addWidget(value, 1, c)
                self.stats[key] = value
            stats.setColumnStretch(5, 1)
            box.addLayout(stats)
            self.busy = Meter("", lw=0, tw=0, heat=True)
            self.busy.setToolTip("How much of the time the disk was busy")
            box.addWidget(self.busy)

        self.parts = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        for r, m in enumerate(disk.mounts):
            where = QLabel("  ·  ".join(m.mountpoints))
            where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            meter = Meter("", lw=0, tw=150, heat=True)
            grid.addWidget(where, r, 0)
            grid.addWidget(dim_label(f"{m.fstype} · {m.device}"), r, 1)
            grid.addWidget(meter, r, 2)
            self.parts[m.device] = meter
        grid.setColumnStretch(2, 1)
        if disk.mounts:
            box.addLayout(grid)
        elif disk.name != "other":
            box.addWidget(dim_label("No mounted partitions"))

    def show(self, disk, rate, total):
        self.temp.setText(f"{disk.temp:.0f}°C" if disk.temp is not None else "")
        self.temp.setToolTip("Drive temperature" if disk.temp is not None else "")
        if self.stats:
            self.stats["Read"].setText(rate_text(rate.read) if rate else "—")
            self.stats["Write"].setText(rate_text(rate.write) if rate else "—")
            busy = rate.busy if rate and rate.busy is not None else None
            self.stats["Busy"].setText(f"{busy:.0f}%" if busy is not None else "—")
            self.busy.set(busy or 0, "")
            self.stats["Read since boot"].setText(human_bytes(total.read_bytes) if total else "—")
            self.stats["Written since boot"].setText(human_bytes(total.write_bytes) if total else "—")
        for m in disk.mounts:
            meter = self.parts.get(m.device)
            if meter is not None:
                meter.set(m.percent, f"{human_bytes(m.used)} / {human_bytes(m.total)}")
                meter.setToolTip(f"{human_bytes(m.total - m.used)} free · {m.percent:.0f}% used")


class DisksPage(QWidget):
    def __init__(self, sampler):
        """sampler: общий disks.IoSampler окна (он опрашивается на каждом шаге обновления)."""
        super().__init__()
        self.sampler = sampler
        self.signature = None
        self.cards = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.box = QVBoxLayout(self.body)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(12)
        scroll.setWidget(self.body)
        outer.addWidget(scroll)
        self.note = dim_label("Drive health (SMART) needs root: run  sudo smartctl -a /dev/<disk>  in a terminal.")

    def refresh(self):
        found = disks.read_disks()
        signature = [(d.name, d.model, tuple((m.device, tuple(m.mountpoints)) for m in d.mounts)) for d in found]
        if signature != self.signature:   # диски или разделы поменялись (например, вставили флешку): строим заново
            self._rebuild(found)
            self.signature = signature
        for d in found:
            self.cards[d.name].show(d, self.sampler.rates.get(d.name), self.sampler.totals.get(d.name))

    def _rebuild(self, found):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget() is not None and item.widget() is not self.note:
                item.widget().deleteLater()
        self.cards = {}
        for d in found:
            card = DiskCard(d)
            self.cards[d.name] = card
            self.box.addWidget(card.card)
        if not found:
            self.box.addWidget(dim_label("No disks found."))
        self.box.addWidget(self.note)
        self.box.addStretch()
