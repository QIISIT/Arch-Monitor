"""Окно MangoHud: настройка оверлея, запуск игр через него и разбор логов.

Три вкладки:  HUD (конфиг)  ·  Launch (запуск)  ·  Logs (логи и график кадров).
Вся логика чтения и записи лежит в mangohud.py, здесь только интерфейс.
"""
import os
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)

from . import config as C
from . import mangohud as mh
from .gpu_poll import GpuPoller
from .theme import T
from .widgets import dim_label

STEAM_OPTION = "mangohud %command%"
KEY_PLACEHOLDERS = {"toggle_hud": "Shift_R+F12", "toggle_fps_limit": "Shift_L+F1", "toggle_logging": "Shift_L+F2"}


class FrametimeGraph(QWidget):
    """График времени кадра (мс): линия по логу и пунктиры на 60 и 30 FPS."""

    def __init__(self):
        super().__init__()
        self.frametimes = []
        self.setMinimumHeight(150)

    def set_data(self, frametimes):
        self.frametimes = frametimes
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(T.line), 1))
        p.setBrush(QColor(T.card))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
        data = self.frametimes
        if not data:
            p.setPen(QColor(T.dim))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Select a log to see its frametime graph")
            return
        top = max(40.0, sorted(data)[int(len(data) * 0.995)] * 1.15)     # шкала по почти максимуму, редкие всплески не ломают вид
        left, right, pad = 44.0, 12.0, 10.0
        plot_w, plot_h = w - left - right, h - 2 * pad

        def y_of(ms):
            return pad + plot_h * (1 - min(ms, top) / top)

        for ms, label in ((1000 / 60, "60 fps"), (1000 / 30, "30 fps")):
            if ms < top:
                p.setPen(QPen(QColor(T.line), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(left, y_of(ms)), QPointF(w - right, y_of(ms)))
                p.setPen(QColor(T.dim))
                p.drawText(QRectF(0, y_of(ms) - 8, left - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        step = max(1, len(data) // int(plot_w))                          # прореживаем: не больше одной точки на пиксель
        points = [QPointF(left + plot_w * i / max(1, len(data) - 1), y_of(max(data[i:i + step])))
                  for i in range(0, len(data), step)]
        p.setPen(QPen(QColor(T.accent), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF(points))


class MangoHudDialog(QDialog):
    def __init__(self, parent=None, embedded=False, gpus=None):
        """embedded=True: окно встроено страницей в главное окно (раздел MangoHud бокового меню)."""
        super().__init__(parent)
        self.embedded = embedded
        self.setWindowTitle("MangoHud")
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        else:
            self.resize(900, 680)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.cfg = mh.load_config()

        root = QVBoxLayout(self)
        root.setContentsMargins(*((0, 0, 0, 0) if embedded else (18, 16, 18, 14)))
        tabs = QTabWidget()
        tabs.addTab(self._build_hud_tab(), "HUD")
        tabs.addTab(self._build_launch_tab(), "Launch")
        tabs.addTab(self._build_logs_tab(), "Logs")
        tabs.currentChanged.connect(lambda i: i == 2 and self.refresh_logs())
        root.addWidget(tabs, 1)
        self.status = dim_label("")
        root.addWidget(self.status)
        self._config_to_widgets()
        self.set_gpus(gpus or [])
        if gpus is None:
            self.gpu_poller = GpuPoller(self)
            self.gpu_poller.ready.connect(self.set_gpus)
            self.finished.connect(self.gpu_poller.shutdown)
            self.gpu_poller.request()

    def reject(self):
        """Esc у встроенной страницы ничего не закрывает."""
        if not self.embedded:
            super().reject()

    # ── Вкладка HUD ─────────────────────────────────────────────────────────
    def _build_hud_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        row = QHBoxLayout()
        row.addWidget(dim_label("Presets"))
        for name in mh.PRESETS:
            button = QPushButton(name)
            button.clicked.connect(lambda _checked=False, n=name: self._apply_preset(n))
            row.addWidget(button)
        row.addStretch()
        lay.addLayout(row)

        groups = QHBoxLayout()
        self.flag_boxes = {}
        for group in mh.FLAG_GROUPS:
            box, col = QGroupBox(group), QVBoxLayout()
            box.setLayout(col)
            for key, label, g in mh.FLAGS:
                if g == group:
                    check = QCheckBox(label)
                    check.setToolTip(key)
                    self.flag_boxes[key] = check
                    col.addWidget(check)
            col.addStretch()
            groups.addWidget(box)
        lay.addLayout(groups)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.position = QComboBox()
        self.position.addItems(mh.POSITIONS)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 96)
        self.alpha, self.bg_alpha = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.alpha, self.bg_alpha):
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
        self.fps_limit = QLineEdit()
        self.fps_limit.setPlaceholderText("e.g. 60  or  60,144  (0 = unlimited)")
        self.gpu_choice = QComboBox()
        self.gpu_choice.addItem("Auto (MangoHud decides)", "")
        self.out_folder = QLineEdit()
        self.out_folder.setPlaceholderText(C.MANGOHUD_LOG_DIR)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_log_folder)
        self.log_interval = QSpinBox()
        self.log_interval.setRange(0, 10000)
        self.log_interval.setSpecialValueText("Every frame (0 ms)")
        self.log_interval.setSuffix(" ms")
        self.key_edits = {key: QLineEdit() for key in KEY_PLACEHOLDERS}
        for key, edit in self.key_edits.items():
            edit.setPlaceholderText(KEY_PLACEHOLDERS[key])

        rows = [("Position", self.position, "Font size", self.font_size),
                ("Opacity", self.alpha, "Background opacity", self.bg_alpha),
                ("FPS limit", self.fps_limit, "GPU", self.gpu_choice),
                ("Log folder", self.out_folder, "Log interval", self.log_interval),
                ("Key: toggle HUD", self.key_edits["toggle_hud"], "Key: FPS limit", self.key_edits["toggle_fps_limit"]),
                ("Key: logging", self.key_edits["toggle_logging"], None, None)]
        for r, (l1, w1, l2, w2) in enumerate(rows):
            grid.addWidget(dim_label(l1), r, 0)
            grid.addWidget(w1, r, 1)
            if l2:
                grid.addWidget(dim_label(l2), r, 2)
                grid.addWidget(w2, r, 3)
        grid.addWidget(browse, 3, 4)
        lay.addLayout(grid)

        buttons = QHBoxLayout()
        save, reload_button = QPushButton("Save"), QPushButton("Reload from file")
        save.clicked.connect(self.save)
        reload_button.clicked.connect(self.reload)
        buttons.addWidget(save)
        buttons.addWidget(reload_button)
        buttons.addWidget(dim_label(f"File: {mh.CONFIG_FILE}"), 1)
        lay.addLayout(buttons)
        lay.addStretch()
        return page

    def _apply_preset(self, name):
        for key, check in self.flag_boxes.items():
            check.setChecked(key in mh.PRESETS[name])

    def _browse_log_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder for MangoHud logs")
        if folder:
            self.out_folder.setText(folder)

    def _config_to_widgets(self):
        """Показать содержимое self.cfg в виджетах."""
        for key, check in self.flag_boxes.items():
            check.setChecked(key in self.cfg.flags)
        v = {**mh.DEFAULTS, **self.cfg.values}
        self._select(self.position, v["position"])
        invalid = []
        for key, spin in (("font_size", self.font_size), ("alpha", self.alpha),
                          ("background_alpha", self.bg_alpha), ("log_interval", self.log_interval)):
            try:
                value = float(v[key])
                if not math.isfinite(value) or not spin.minimum() <= value <= spin.maximum():
                    raise ValueError("outside widget range")
            except (TypeError, ValueError, OverflowError):
                value = float(mh.DEFAULTS[key])
                invalid.append(key)
            spin.setValue(int(value) if isinstance(spin, QSpinBox) else value)
        self.fps_limit.setText(v.get("fps_limit", ""))
        pci = v.get("pci_dev", "")
        if self.gpu_choice.findData(pci) < 0:
            self.gpu_choice.addItem(f"Custom: {pci}", pci)   # адрес, которого нет среди найденных карт
        self.gpu_choice.setCurrentIndex(self.gpu_choice.findData(pci))
        self.out_folder.setText(v.get("output_folder", ""))
        for key, edit in self.key_edits.items():
            edit.setText(v.get(key, ""))
        self.status.setText("Invalid settings: " + ", ".join(invalid) +
                            ". Showing defaults; the file has not been changed." if invalid else "")

    def set_gpus(self, gpus):
        """Обновить найденные карты, не сбрасывая выбор пользователя или сохранённый PCI."""
        selected = self.gpu_choice.currentData() or ""
        self.gpu_choice.blockSignals(True)
        self.gpu_choice.clear()
        self.gpu_choice.addItem("Auto (MangoHud decides)", "")
        for n, gpu in enumerate(gpus):
            if gpu.pci:
                self.gpu_choice.addItem(f"GPU {n}: {gpu.name[:34]}", gpu.pci)
        if self.gpu_choice.findData(selected) < 0:
            self.gpu_choice.addItem(f"Custom: {selected}", selected)
        self.gpu_choice.setCurrentIndex(self.gpu_choice.findData(selected))
        self.gpu_choice.blockSignals(False)

    def _select(self, combo, text):
        if combo.findText(text) < 0:
            combo.addItem(text)   # значение из старого конфига, которого нет в списке (например, «left»)
        combo.setCurrentText(text)

    def _widgets_to_config(self):
        """Собрать self.cfg из виджетов. В файл попадает только то, что отличается от значений по умолчанию."""
        self.cfg.flags = {key for key, check in self.flag_boxes.items() if check.isChecked()}
        fmt = lambda x: f"{x:.2f}".rstrip("0").rstrip(".")   # 0.50 -> 0.5, 1.00 -> 1
        values = {"position": self.position.currentText(), "font_size": str(self.font_size.value()),
                  "alpha": fmt(self.alpha.value()), "background_alpha": fmt(self.bg_alpha.value()),
                  "fps_limit": self.fps_limit.text().strip(), "pci_dev": self.gpu_choice.currentData() or "",
                  "output_folder": self.out_folder.text().strip(), "log_interval": str(self.log_interval.value())}
        values.update({key: edit.text().strip() for key, edit in self.key_edits.items()})
        self.cfg.values = {k: v for k, v in values.items() if v and v != mh.DEFAULTS.get(k)}

    def save(self):
        self._widgets_to_config()
        try:
            mh.save_config(self.cfg)
        except OSError as e:
            self.status.setText(f"Could not save: {e}")
            return
        folder = os.path.expanduser(self.cfg.values.get("output_folder", ""))
        if folder:
            os.makedirs(folder, exist_ok=True)   # MangoHud не создаёт папку логов сам
        self.status.setText("Saved. Restart the game, or press the reload key in it (Shift_L+F4 by default).")

    def reload(self):
        self.cfg = mh.load_config()
        self._config_to_widgets()
        if not self.status.text():
            self.status.setText("Reloaded from file.")

    # ── Вкладка Launch ──────────────────────────────────────────────────────
    def _build_launch_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        installed = mh.mangohud_path()
        state = dim_label(f"MangoHud found: {installed}" if installed else
                          f"MangoHud is not installed. Install it with:  {mh.INSTALL_HINT}")
        state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(state)

        lay.addWidget(dim_label("Program or game command"))
        row = QHBoxLayout()
        self.command = QLineEdit()
        self.command.setPlaceholderText("e.g.  vkcube    or    /path/to/game    or    wine game.exe")
        self.command.returnPressed.connect(self.launch)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_program)
        row.addWidget(self.command, 1)
        row.addWidget(browse)
        lay.addLayout(row)

        buttons = QHBoxLayout()
        go = QPushButton("Launch with MangoHud")
        go.clicked.connect(self.launch)
        copy_steam = QPushButton("Copy Steam launch option")
        copy_steam.clicked.connect(lambda: self._copy(STEAM_OPTION, "Steam launch option copied."))
        buttons.addWidget(go)
        buttons.addWidget(copy_steam)
        buttons.addStretch()
        lay.addLayout(buttons)

        help_text = dim_label("Steam: game, Properties, Launch options, paste  " + STEAM_OPTION +
                              "\nLutris: Configure, System options, Command prefix:  mangohud"
                              "\nFor 32-bit games install lib32-mangohud as well."
                              "\nIn the game: HUD toggle Shift_R+F12, logging Shift_L+F2 (unless you changed the keys on the HUD tab).")
        help_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(help_text)
        lay.addStretch()
        return page

    def _browse_program(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a program or game")
        if path:
            self.command.setText(f'"{path}"' if " " in path else path)

    def _copy(self, text, message):
        QApplication.clipboard().setText(text)
        self.status.setText(message)

    def launch(self):
        ok, message = mh.launch(self.command.text())
        self.status.setText(message)

    # ── Вкладка Logs ────────────────────────────────────────────────────────
    def _build_logs_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        top = QHBoxLayout()
        self.log_folder_label = dim_label("")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_logs)
        top.addWidget(self.log_folder_label, 1)
        top.addWidget(refresh)
        lay.addLayout(top)

        self.log_list = QListWidget()
        self.log_list.setMaximumHeight(150)
        self.log_list.currentRowChanged.connect(self._show_log)
        lay.addWidget(self.log_list)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.summary)
        self.graph = FrametimeGraph()
        lay.addWidget(self.graph, 1)
        self._log_files = []
        return page

    def _log_folder(self):
        return os.path.expanduser(self.out_folder.text().strip() or C.MANGOHUD_LOG_DIR)

    def refresh_logs(self):
        folder = self._log_folder()
        self._log_files = mh.list_logs(folder)
        self.log_folder_label.setText(f"Logs in {folder}  (start logging in the game with Shift_L+F2)")
        self.log_list.clear()
        self.log_list.addItems([os.path.basename(p) for p in self._log_files])
        self.summary.setText("" if self._log_files else "No logs yet. Set a log folder on the HUD tab, save, then press the logging key in the game.")
        self.graph.set_data([])

    def _show_log(self, row):
        if row < 0 or row >= len(self._log_files):
            return
        s = mh.summarize_log(self._log_files[row])
        if s is None:
            self.summary.setText("This file does not look like a MangoHud frame log.")
            self.graph.set_data([])
            return
        cell = lambda name, value: f'<span style="color:{T.dim};">{name}</span> <b>{value}</b>'
        self.summary.setText("&nbsp;&nbsp;&nbsp;&nbsp;".join([
            cell("Sample mean", f"{s.avg_fps:.1f} fps"), cell("Sample 1% low", f"{s.low_1:.1f}"),
            cell("Sample 0.1% low", f"{s.low_01:.1f}"),
            cell("Min / Max", f"{s.min_fps:.0f} / {s.max_fps:.0f}"), cell("Samples", f"{s.samples}"),
            cell("Recorded span", f"{s.seconds:.2f} s" if s.seconds is not None else "Unknown")]) +
            "<br>Sample statistics: CSV rows may omit frames. Frame count and true per-frame lows are not inferred.")
        self.graph.set_data(s.frametimes)
