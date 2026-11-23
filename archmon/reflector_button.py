"""Reflector: кнопка, которая перезапускает reflector, и страница с ней в боковом меню.

Команда запускается в фоне (QProcess), поэтому окно не подвисает, пока reflector проверяет зеркала
(обычно 10–60 секунд). Пароль спрашивает сама система через pkexec.
"""
from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from . import config as C
from . import reflector
from .widgets import dim_label, make_section


class ReflectorButton(QPushButton):
    def __init__(self, report, label="Update mirrors"):
        """report(text): куда писать сообщения (строка статуса внизу окна); label: надпись на кнопке."""
        super().__init__(label)
        self.label = label
        self.report = report
        self.process = None
        self.clicked.connect(self.start)
        self.refresh_tooltip()

    def refresh_tooltip(self):
        self.setToolTip(reflector.summary())

    def start(self):
        if self.process is not None:
            return   # уже идёт
        argv = reflector.restart_command()
        if argv is None:
            self.report(reflector.summary().splitlines()[0])
            return
        self.process = QProcess(self)
        self.process.setProgram(argv[0])
        self.process.setArguments(argv[1:])
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._failed_to_start)
        self.setEnabled(False)
        self.setText(self.label + "…")
        self.report("Reflector: updating mirrors, this can take a minute…")
        self.process.start()

    def _done(self):
        self.process.deleteLater()
        self.process = None
        self.setEnabled(True)
        self.setText(self.label)
        self.refresh_tooltip()

    def _failed_to_start(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.report("Reflector: could not start pkexec.")
            self._done()

    def _finished(self, code, _status):
        output = bytes(self.process.readAll()).decode(errors="replace").strip()
        failure = ""
        if code == 0:
            info = reflector.mirror_info()
            count = f" {info.servers} servers in the list." if info else ""
            message = f"Reflector: mirrors updated.{count}"
        elif code in reflector.PKEXEC_CANCELLED:
            message = "Reflector: cancelled (no password entered)."
        else:
            failure = reflector.journal_tail() or output
            last = failure.splitlines()[-1] if failure else ""
            message = f"Reflector: failed (code {code}). {last}".strip()
        self._done()
        if failure:
            self.setToolTip(f"Last run failed:\n{failure}")   # подробности при наведении
        self.report(message)


class ReflectorPage(QWidget):
    """Страница Reflector: сколько зеркал, когда обновлялись, кнопка обновления и журнал последнего запуска."""

    def __init__(self, report):
        super().__init__()
        self.report = report
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        summary = make_section()
        box = QVBoxLayout(summary)
        box.setContentsMargins(0, 18, 0, 18)
        box.setSpacing(12)
        head = QHBoxLayout()
        title = QLabel("Pacman mirrors")
        title.setObjectName("strong")
        self.button = ReflectorButton(self._on_report)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.button)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addLayout(head)
        box.addWidget(self.info)
        root.addWidget(summary)

        log_section = make_section()
        log_box = QVBoxLayout(log_section)
        log_box.setContentsMargins(0, 16, 0, 18)
        log_box.addWidget(dim_label("Last run (reflector.service journal)"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        mono = QFont()
        mono.setFamilies(C.MONO_FONTS)
        mono.setPointSize(C.TABLE_FONT_SIZE)
        self.log.setFont(mono)
        log_box.addWidget(self.log, 1)
        root.addWidget(log_section, 1)

    def _on_report(self, text):
        self.report(text)
        if not text.endswith("…"):   # запуск закончился: показать свежие сведения
            self.refresh()

    def refresh(self):
        self.info.setText(reflector.summary())
        tail = reflector.journal_tail(25)
        self.log.setPlainText(tail or "No journal entries yet, or the system journal is not readable for your user.")
