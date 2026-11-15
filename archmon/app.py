"""Запуск приложения.

Ключ --hidden запускает программу сразу в трее (удобно для автозапуска).
Повторный запуск не создаёт вторую копию: он показывает окно первой.
"""
import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from . import config as C
from .single import InstanceServer, already_running
from .window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(C.APP_NAME)
    app.setDesktopFileName(C.DESKTOP_ID)   # связывает окно с ярлыком и иконкой в KDE/Wayland
    font = QFont()
    font.setFamilies(C.UI_FONTS)           # первый установленный шрифт из списка в config.py
    font.setPointSize(10)
    app.setFont(font)
    if already_running(wake="--hidden" not in sys.argv):   # копия уже есть: эта сразу выходит, а первая показывает окно
        return
    window = MainWindow()
    window.instance_server = InstanceServer()   # хранится в окне, чтобы его не удалил сборщик мусора
    window.instance_server.activated.connect(window.show_window)
    app.setQuitOnLastWindowClosed(window.tray is None)   # с треем окно можно закрыть, программа живёт
    if "--hidden" not in sys.argv or window.tray is None:
        window.show()
    sys.exit(app.exec())
