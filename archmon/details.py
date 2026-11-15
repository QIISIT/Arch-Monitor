"""Окно со сведениями о процессе: открывается двойным кликом или Enter по строке таблицы."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSpinBox,
                             QVBoxLayout)

from . import config as C
from . import system
from .helpers import human_bytes
from .widgets import dim_label

# (поле ProcDetails, подпись). Порядок строк = порядок в окне.
FIELDS = [("pid", "PID"), ("parent", "Parent"), ("user", "User"), ("status", "Status"),
          ("started", "Started"), ("threads", "Threads"), ("children", "Children"), ("memory", "Memory"),
          ("exe", "Executable"), ("cwd", "Working dir"), ("command", "Command")]


class ProcessDialog(QDialog):
    def __init__(self, pid, parent=None):
        super().__init__(parent)
        self.pid = pid
        self._nice_loaded = False
        self.setWindowTitle(f"Process {pid}")
        self.resize(700, 600)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        self.heading = QLabel()
        self.heading.setStyleSheet("font-size:18px; font-weight:500;")
        root.addWidget(self.heading)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(6)
        self.values = {}
        for row, (key, title) in enumerate(FIELDS):
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(dim_label(title), row, 0, alignment=Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        root.addLayout(grid)

        root.addWidget(dim_label("Open files"))
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        mono = QFont()
        mono.setFamilies(C.MONO_FONTS)
        mono.setPointSize(C.TABLE_FONT_SIZE)
        self.files.setFont(mono)
        root.addWidget(self.files, 1)

        bar = QHBoxLayout()
        self.nice = QSpinBox()
        self.nice.setRange(-20, 19)
        apply_button, close_button = QPushButton("Apply"), QPushButton("Close")
        apply_button.clicked.connect(self.apply_nice)
        close_button.clicked.connect(self.close)
        self.message = dim_label("")
        bar.addWidget(dim_label("Priority (nice)"))
        bar.addWidget(self.nice)
        bar.addWidget(apply_button)
        bar.addWidget(self.message, 1)
        bar.addWidget(close_button)
        root.addLayout(bar)

        self.timer = QTimer(self, interval=C.REFRESH_MS, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        d = system.process_details(self.pid)
        if d is None:
            self.heading.setText(f"Process {self.pid} has exited")
            self.timer.stop()
            return
        self.heading.setText(f"{d.name}   (PID {d.pid})")
        memory = None if d.rss is None else f"{human_bytes(d.rss)} resident, {human_bytes(d.vms or 0)} virtual"
        shown = {**vars(d), "memory": memory}
        for key, label in self.values.items():
            value = shown.get(key)
            label.setText("—" if value in (None, "") else str(value))

        if d.open_files is None:
            self.files.setPlainText("Not available (no permission for this process).")
        else:
            lines = d.open_files[:C.DETAILS_MAX_FILES]
            extra = len(d.open_files) - len(lines)
            text = "\n".join(lines) + (f"\n… and {extra} more" if extra > 0 else "")
            if self.files.toPlainText() != text:
                self.files.setPlainText(text or "(none)")

        if not self._nice_loaded and d.nice is not None:   # загружаем один раз, чтобы не мешать вводу
            self.nice.setValue(d.nice)
            self._nice_loaded = True

    def apply_nice(self):
        self.message.setText(system.set_nice(self.pid, self.nice.value()))
