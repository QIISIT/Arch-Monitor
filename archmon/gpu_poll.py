"""Один фоновый опрос GPU за раз; виджеты обновляются только в потоке Qt."""
import logging

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from .gpu import read_gpus


class GpuPoller(QThread):
    ready = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._closed = False
        self._result = []
        self.finished.connect(self._deliver)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def request(self):
        if self._closed or self._busy:
            return
        self._busy = True
        self.start()

    def run(self):
        try:
            self._result = read_gpus()
        except Exception:
            logging.exception("GPU polling failed")
            self._result = []

    @pyqtSlot()
    def _deliver(self):
        self._busy = False
        if not self._closed:
            self.ready.emit(self._result)

    def shutdown(self):
        self._closed = True
        # nvidia-smi имеет ограничение времени. Не уничтожаем работающий QThread.
        self.wait()
