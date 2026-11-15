"""Делит процессы на «приложения» (программы, которыми пользуешься) и «системные». Без Qt.

Как решаем (по порядку, первое подходящее правило):
  1. Процесс есть в FORCE_SYSTEM / FORCE_APPS (config.py): как там указано. Работает и для root.
     Запись без «/» сравнивается с именем процесса, запись со «/» ищется в командной строке («/opt/happ»).
  2. Поток ядра: системный.
  3. Процесс root: приложение, если его запустили из твоей программы через sudo или pkexec (он в той же группе
     «app-…») или если он лежит не в системных папках, а в APP_PATH_PREFIXES (/opt, /home…). Иначе системный.
     Процессы других пользователей: системные.
  4. Процесс запущен как приложение: среди его cgroup есть «app-…» (так systemd запускает программы из меню
     и значков: app-firefox@….scope, app-org.kde.konsole@….service). Туда же попадают все дочерние процессы
     (вкладки браузера, игры Steam): это приложение.
  5. Обычная служба systemd (pipewire.service, plasma-kwin_wayland.service и т. п.): системный.
  6. Остальное (например, запущено из консоли вне systemd): приложение, если процесс использует графическую
     библиотеку (Wayland или X11), то есть у него есть окно.
"""
import os
import time

from . import config as C

_ME = os.getuid()
_GUI_LIBS = ("libwayland-client", "libxcb.so", "libX11.so")
_YOUNG_SECONDS = 15        # совсем свежие процессы могут ещё не загрузить графику: отрицательный ответ не запоминаем
_cache = {}                # (pid, время запуска) -> True/False


def _cgroup(pid):
    """Путь cgroup процесса (например /user.slice/.../app.slice/app-firefox@x.scope) или ''."""
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                if line.startswith("0::"):
                    return line[3:].strip()
    except OSError:
        pass
    return ""


def _has_gui_libs(pid):
    """Загружены ли в процесс библиотеки Wayland/X11 (значит, есть окно)."""
    try:
        with open(f"/proc/{pid}/maps") as f:
            return any(lib in line for line in f for lib in _GUI_LIBS)
    except OSError:
        return False


def _matches(entries, proc):
    """Подходит ли процесс под один из пунктов FORCE_APPS / FORCE_SYSTEM."""
    command = proc.command.lower()
    return any(proc.name == e or ("/" in e and e.lower() in command) for e in entries)


def _in_app_cgroup(pid):
    return any(p.startswith("app-") for p in _cgroup(pid).strip("/").split("/"))


def _decide(proc):
    if _matches(C.FORCE_SYSTEM, proc):
        return False
    if _matches(C.FORCE_APPS, proc):
        return True
    if proc.command.startswith("["):   # поток ядра
        return False
    if proc.uid == 0 and proc.uid != _ME:
        # root: запущен из твоей программы (sudo, pkexec) или установлен как программа, а не как часть системы
        return _in_app_cgroup(proc.pid) or proc.command.startswith(tuple(C.APP_PATH_PREFIXES))
    if proc.uid != _ME:
        return False
    parts = _cgroup(proc.pid).strip("/").split("/")
    if any(p.startswith("app-") for p in parts):
        return True
    if parts[-1].endswith(".service"):
        return False
    return _has_gui_libs(proc.pid)


def is_app(proc):
    """True, если процесс считается приложением (показывается выше системных)."""
    key = (proc.pid, proc.started)
    if key in _cache:
        return _cache[key]
    result = _decide(proc)
    young = time.time() - proc.started < _YOUNG_SECONDS
    if result or not young:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = result
    return result
