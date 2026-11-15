"""Защита от повторного запуска: вторая копия не стартует, а будит первую.

Работает через локальный сокет Qt. Первая копия слушает сокет, вторая подключается,
сообщает «покажись» и сразу завершается.
"""
import getpass

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from . import config as C

SOCKET_NAME = f"{C.DESKTOP_ID}-{getpass.getuser()}"   # свой сокет у каждого пользователя


def already_running(wake=True):
    """True, если другая копия уже запущена.

    wake=True: заодно просит её показать окно. wake=False (запуск с --hidden) ничего не просит.
    """
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"show" if wake else b"ping")
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(300)
    return True


class InstanceServer(QObject):
    """Слушает сокет; когда запускают вторую копию, посылает сигнал activated."""

    activated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.server = QLocalServer(self)
        QLocalServer.removeServer(SOCKET_NAME)   # убрать «мёртвый» сокет, оставшийся после сбоя
        self.server.listen(SOCKET_NAME)
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        conn = self.server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: self._on_message(conn))
            conn.disconnected.connect(conn.deleteLater)

    def _on_message(self, conn):
        if bytes(conn.readAll()) == b"show":
            self.activated.emit()
        conn.disconnectFromServer()
