"""Страница Fans: вентиляторы материнской платы, их кривые и служба, которая эти кривые выполняет.

Если Linux вентиляторы не видит, страница объясняет, какой драйвер поставить для этой платы.
Логика без Qt лежит в fans.py (чтение), fand.py (служба и формула кривой) и fan_service.py (установка).
"""
import shutil

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                             QVBoxLayout, QWidget)

from . import config as C
from . import fan_service
from . import fand
from . import fans
from .widgets import Meter, dim_label, make_section

MODE_LABELS = ["BIOS control", "Curve · Silent", "Curve · Balanced", "Curve · Performance", "Fixed speed"]   # порядок как fan_service.MODES
SOURCE_LABELS = ["CPU", "GPU", "Hottest"]                                              # порядок как fan_service.SOURCES
CURVE_NAMES = ["silent", "balanced", "performance"]


class FanRow:
    """Виджеты одной строки вентилятора."""

    def __init__(self, fan, saved):
        self.index = fan.index
        self.name = QLineEdit(saved.get("name", ""))
        self.name.setPlaceholderText(fan.label)
        self.name.setFixedWidth(150)
        self.rpm = Meter("", lw=0, tw=96, heat=False)
        self.peak = float(C.FAN_SCALE_MIN_RPM)
        self.now = dim_label("")
        self.mode = QComboBox()
        self.mode.addItems(MODE_LABELS)
        self.source = QComboBox()
        self.source.addItems(SOURCE_LABELS)
        self.fixed = QSpinBox()
        self.fixed.setRange(fand.MIN_PCT, 100)
        self.fixed.setSuffix(" %")
        mode = saved.get("mode", "bios")
        ui_mode = saved.get("curve", "balanced") if mode == "curve" else mode
        self.mode.setCurrentIndex(fan_service.MODES.index(ui_mode) if ui_mode in fan_service.MODES else 0)
        self.source.setCurrentIndex(fan_service.SOURCES.index(saved.get("source", "cpu"))
                                    if saved.get("source") in fan_service.SOURCES else 0)
        self.fixed.setValue(int(saved.get("fixed", 50)))
        self.mode.currentIndexChanged.connect(self._sync)
        self._sync()

    def widgets(self):
        return [self.name, self.rpm, self.now, self.mode, self.source, self.fixed]

    def _sync(self, *_args):
        """Источник температуры нужен только кривым, процент только фиксированной скорости."""
        ui_mode = fan_service.MODES[self.mode.currentIndex()]
        self.source.setEnabled(ui_mode in CURVE_NAMES)
        self.fixed.setEnabled(ui_mode == "fixed")

    def config(self):
        ui_mode = fan_service.MODES[self.mode.currentIndex()]
        return {
            "index": self.index,
            "name": self.name.text().strip(),
            "mode": "curve" if ui_mode in CURVE_NAMES else ui_mode,
            "curve": ui_mode if ui_mode in CURVE_NAMES else "balanced",
            "source": fan_service.SOURCES[self.source.currentIndex()],
            "fixed": self.fixed.value(),
        }

    def show(self, fan):
        rpm = f"{fan.rpm:.0f} RPM" if fan.rpm else "stopped"
        self.peak = max(self.peak, fan.rpm or 0)   # шкала по самым высоким оборотам, которые видели у этого вентилятора
        self.rpm.set((fan.rpm or 0) / self.peak * 100, rpm)
        self.rpm.setToolTip(f"Bar: 100% = {self.peak:.0f} RPM, the highest seen for this fan")
        if fan.pwm is None:
            self.now.setText("read only")
        elif fan.mode == "manual":
            self.now.setText(f"{fan.pwm:.0f}%")          # скорость задаёт служба: процент настоящий
        elif fan.mode == "full speed":
            self.now.setText("100% · full speed")
        else:
            self.now.setText("auto (BIOS)")              # в автоматике чип не сообщает реальный процент


class FansPage(QWidget):
    def __init__(self, report=lambda text: None):
        """report(text): куда писать сообщения (строка статуса внизу окна)."""
        super().__init__()
        self.report = report
        self.process, self.tmp = None, None
        saved = fan_service.load_config() or {}
        self.saved_fans = {int(f["index"]): f for f in saved.get("fans", [])}
        self.rows, self.chip = {}, None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        header_section = make_section()
        head = QHBoxLayout(header_section)
        head.setContentsMargins(0, 14, 0, 14)
        title = QLabel("Motherboard fans")
        title.setObjectName("strong")
        vendor, name = fans.board()
        self.service_label = dim_label("")
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply)
        self.bios_button = QPushButton("Back to BIOS")
        self.bios_button.setToolTip("Stop the fan service: fans follow the BIOS curves again")
        self.bios_button.clicked.connect(self.back_to_bios)
        rescan = QPushButton("Check again")
        rescan.clicked.connect(lambda: self.refresh(full=True))
        head.addWidget(title)
        head.addSpacing(10)
        head.addWidget(dim_label(f"{vendor} {name}".strip()))
        head.addSpacing(10)
        head.addWidget(self.service_label)
        head.addStretch()
        for button in (rescan, self.bios_button, self.apply_button):
            head.addWidget(button)
        root.addWidget(header_section)

        # что делать, если вентиляторов не видно
        self.help = make_section()
        help_box = QVBoxLayout(self.help)
        help_box.setContentsMargins(0, 16, 0, 18)
        help_box.setSpacing(10)
        self.help_text = QLabel()
        self.help_text.setWordWrap(True)
        self.help_code = QLabel()
        self.help_code.setObjectName("code")
        self.help_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        mono = self.help_code.font()
        mono.setFamilies(C.MONO_FONTS)
        self.help_code.setFont(mono)
        help_box.addWidget(dim_label("Linux does not see the motherboard fans yet, so they can't be shown or controlled."))
        help_box.addWidget(self.help_text)
        help_box.addWidget(self.help_code)
        help_box.addWidget(dim_label("Then press “Check again”."))
        root.addWidget(self.help)

        # вентиляторы
        self.fans_section = make_section()
        fans_box = QVBoxLayout(self.fans_section)
        fans_box.setContentsMargins(0, 14, 0, 16)
        fans_box.setSpacing(10)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(8)
        for c, text in enumerate(("Name", "Speed", "Now", "Mode", "Follows", "Fixed")):
            self.grid.addWidget(dim_label(text), 0, c)
        self.grid.setColumnStretch(1, 1)
        hint = dim_label("To make a fan follow a temperature, pick a curve in Mode and the temperature in Follows. "
                         "The curves themselves are edited below. Then press Apply.")
        hint.setWordWrap(True)
        fans_box.addWidget(hint)
        fans_box.addLayout(self.grid)
        root.addWidget(self.fans_section)

        # кривые (общие для всех вентиляторов с этим режимом)
        self.curves_section = make_section()
        curves = QGridLayout(self.curves_section)
        curves.setContentsMargins(0, 14, 0, 16)
        curves.setHorizontalSpacing(10)
        curves.setVerticalSpacing(8)
        curves_hint = dim_label("Curves: below the first temperature the fan runs at the first speed, "
                                "above the second at the second speed, smoothly in between.")
        curves_hint.setWordWrap(True)
        curves.addWidget(curves_hint, 0, 0, 1, 9)
        saved_curves = saved.get("curves", {})
        self.curve_spins = {}
        for r, name in enumerate(CURVE_NAMES, start=1):
            curve = fand.clean_curve({**fand.PRESETS[name], **saved_curves.get(name, {})})
            label = QLabel(name.capitalize())
            label.setObjectName("strong")
            spins = {}
            parts = [("t1", "from", 20, 95, " °C"), ("p1", "at", fand.MIN_PCT, 100, " %"),
                     ("t2", "to", 21, 100, " °C"), ("p2", "at", fand.MIN_PCT, 100, " %")]
            curves.addWidget(label, r, 0)
            for c, (key, word, lo, hi, suffix) in enumerate(parts):
                spin = QSpinBox()
                spin.setRange(lo, hi)
                spin.setSuffix(suffix)
                spin.setValue(curve[key])
                spins[key] = spin
                curves.addWidget(dim_label(word), r, 1 + c * 2)
                curves.addWidget(spin, r, 2 + c * 2)
            self.curve_spins[name] = spins
        curves.setColumnStretch(9, 1)
        root.addWidget(self.curves_section)

        safety_note = dim_label(
            f"Safety: speeds never go below {fand.MIN_PCT}%. If the CPU reaches {fand.EMERGENCY_CPU}°C or the GPU "
            f"{fand.EMERGENCY_GPU}°C, all fans go to 100%. If the service stops, fans return to the BIOS curves. "
            "Nothing is written to the BIOS itself. Graphics card fans stay with the NVIDIA driver.")
        safety_note.setWordWrap(True)
        root.addWidget(safety_note)
        root.addStretch()
        self.refresh(full=True)

    # ── Данные ──────────────────────────────────────────────────────────────
    def refresh(self, full=False):
        """Обновить обороты (вызывается каждый шаг, пока страница открыта); full: ещё и состояние службы."""
        found = fans.read_fans()
        controllable = [f for f in found if f.pwm is not None]
        self.help.setVisible(not controllable)
        self.fans_section.setVisible(bool(controllable))
        self.curves_section.setVisible(bool(controllable))
        self.apply_button.setEnabled(bool(controllable) and self.process is None)
        if not controllable:
            text, code = fans.driver_steps()
            self.help_text.setText(text)
            self.help_code.setText(code)
            return
        self.chip = controllable[0].chip
        if set(self.rows) != {f.index for f in controllable}:
            self._build_rows(controllable)
        for f in controllable:
            self.rows[f.index].show(f)
        if full:
            active = fan_service.is_active()
            self.service_label.setText("● fan curves running" if active else "fans follow the BIOS")

    def _build_rows(self, controllable):
        for row in self.rows.values():
            for w in row.widgets():
                self.grid.removeWidget(w)
                w.deleteLater()
        self.rows = {}
        for r, f in enumerate(controllable, start=1):
            row = FanRow(f, self.saved_fans.get(f.index, fan_service.default_fan(f.index)))
            for c, w in enumerate(row.widgets()):
                self.grid.addWidget(w, r, c)
            self.rows[f.index] = row

    def collect(self):
        """Настройки со страницы в виде словаря для /etc/archmon/fans.json."""
        return {
            "version": 1,
            "chip": self.chip,
            "fans": [self.rows[n].config() for n in sorted(self.rows)],
            "curves": {name: fand.clean_curve({k: s.value() for k, s in spins.items()})
                       for name, spins in self.curve_spins.items()},
        }

    # ── Применение ──────────────────────────────────────────────────────────
    def apply(self):
        if not self.rows:
            return
        cfg = self.collect()
        argv, data, self.tmp = fan_service.apply_command(cfg)
        self.saved_fans = {f["index"]: f for f in cfg["fans"]}
        first = "Fans: installing the fan service (asks for your password once)…"
        self._run(argv, "Fans: settings applied. They start again after every reboot.", data, first if self.tmp else None)

    def back_to_bios(self):
        argv = fan_service.stop_command()
        if argv is None:
            self.report("Fans: they already follow the BIOS.")
            return
        self._run(argv, "Fans: back to the BIOS curves.")

    def _run(self, argv, success, data=None, waiting=None):
        if self.process is not None:
            return
        self.process = QProcess(self)
        self.process.setProgram(argv[0])
        self.process.setArguments(argv[1:])
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(lambda code, _status: self._finished(code, success))
        self.process.errorOccurred.connect(self._failed_to_start)
        self.apply_button.setEnabled(False)
        self.bios_button.setEnabled(False)
        self.report(waiting or "Fans: applying…")
        self.process.start()
        if data is not None:   # настройки идут помощнику через stdin, без временных файлов
            self.process.write(data)
            self.process.closeWriteChannel()

    def _failed_to_start(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._done()
            self.report("Fans: could not start pkexec.")

    def _finished(self, code, success):
        output = bytes(self.process.readAll()).decode(errors="replace").strip()
        self._done()
        if code == 0:
            self.report(success)
        elif code in (126, 127):
            self.report("Fans: cancelled (no password entered).")
        else:
            last = output.splitlines()[-1] if output else ""
            self.report(f"Fans: failed (code {code}). {last}".strip())
        self.refresh(full=True)

    def _done(self):
        if self.process is not None:
            self.process.deleteLater()
            self.process = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None
        self.apply_button.setEnabled(bool(self.rows))
        self.bios_button.setEnabled(True)
