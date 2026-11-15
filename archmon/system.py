"""Данные о системе: ядра, память, батарея, нагрузка, процессы.

Модуль не использует Qt: только psutil, поэтому его легко проверить отдельно:
    python3 -c "from archmon import system; print(system.memory())"
"""
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import psutil

from .helpers import human_bytes  # noqa: F401  (удобно импортировать отсюда)


@dataclass
class Usage:
    """Использование ресурса (память, своп)."""
    percent: float
    used: float
    total: float


@dataclass
class Proc:
    """Одна строка таблицы процессов."""
    pid: int
    user: str
    cpu: float
    mem_percent: float
    rss: int
    command: str
    ppid: int = 0     # PID родителя (нужен для режима дерева)
    name: str = ""     # короткое имя процесса (comm)
    uid: int = -1     # чей процесс
    started: float = 0.0   # время запуска (вместе с PID однозначно определяет процесс)


@dataclass
class ProcessList:
    procs: list      # процессы, прошедшие фильтр (без сортировки)
    total: int       # всего процессов в системе
    running: int     # из них выполняется прямо сейчас


# ── Процессор, память, батарея ──────────────────────────────────────────────
def prime_counters():
    """Первый вызов psutil всегда возвращает нули: «прогреваем» счётчики на старте."""
    psutil.cpu_percent(percpu=True)
    for _ in psutil.process_iter(["cpu_percent"]):
        pass


def cpu_count():
    return psutil.cpu_count() or 1


def cpu_percents():
    """Загрузка каждого логического ядра, % (список длиной cpu_count())."""
    return psutil.cpu_percent(percpu=True)


def memory():
    vm = psutil.virtual_memory()
    return Usage(vm.percent, vm.used, vm.total)


def swap():
    sw = psutil.swap_memory()
    return Usage(sw.percent, sw.used, sw.total)


def has_battery():
    return psutil.sensors_battery() is not None


def battery():
    """(процент, подключено ли питание) или None, если батареи нет."""
    b = psutil.sensors_battery()
    return None if b is None else (b.percent, b.power_plugged)


def load_average():
    """Нагрузка за 1, 5 и 15 минут."""
    return os.getloadavg()


_CPU_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")   # где ядро показывает температуру CPU
_CPU_LABELS = ("Package id 0", "Tctl", "Tdie")                                # предпочтительные датчики


def cpu_temperature():
    """Температура процессора, °C, или None, если датчика нет."""
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    for name in _CPU_SENSORS:
        entries = sensors.get(name)
        if entries:
            best = next((e for e in entries if e.label in _CPU_LABELS), None)
            return (best or max(entries, key=lambda e: e.current or 0)).current
    return None


def fan_speeds():
    """Вентиляторы материнской платы: список (название, обороты в минуту). Может быть пустым."""
    try:
        fans = psutil.sensors_fans()
    except (AttributeError, OSError):
        return []
    return [(f.label or name, f.current) for name, entries in fans.items() for f in entries]


def uptime_text():
    s = int(time.time() - psutil.boot_time())
    hms = f"{s % 86400 // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 86400}d {hms}" if s >= 86400 else hms


# ── Процессы ────────────────────────────────────────────────────────────────
_PROC_ATTRS = ["pid", "ppid", "uids", "create_time", "username", "cpu_percent", "memory_percent", "memory_info", "cmdline", "name", "status"]


def list_processes(query=""):
    """Все процессы, подходящие под query (имя команды, пользователь или точный PID)."""
    q = query.lower().strip()
    procs, total, running = [], 0, 0
    for p in psutil.process_iter(_PROC_ATTRS):
        info = p.info
        total += 1
        running += info["status"] == psutil.STATUS_RUNNING
        command = " ".join(info["cmdline"] or []) or f"[{info['name']}]"
        user = info["username"] or "?"
        if q and q not in command.lower() and q not in user.lower() and q != str(info["pid"]):
            continue
        rss = info["memory_info"].rss if info["memory_info"] else 0
        procs.append(Proc(info["pid"], user, info["cpu_percent"] or 0.0,
                          info["memory_percent"] or 0.0, rss, command, info["ppid"] or 0,
                          name=info["name"] or "", uid=info["uids"].real if info["uids"] else -1,
                          started=info["create_time"] or 0.0))
    return ProcessList(procs, total, running)


def send_signal(pid, sig, expected_started=None):
    """Отправить сигнал процессу. Возвращает сообщение для строки статуса."""
    try:
        process = psutil.Process(pid)
        if expected_started is not None and (expected_started <= 0 or process.create_time() != expected_started):
            return f"PID {pid} has changed or its identity is unknown. Select the process again."
        process.send_signal(sig)
        return f"Sent {sig.name} to PID {pid}."
    except psutil.AccessDenied:
        return f"PID {pid} belongs to another user. Run the app with sudo to stop it."
    except psutil.NoSuchProcess:
        return f"PID {pid} has already exited."


# ── Сведения об одном процессе (панель по двойному клику) ───────────────────
@dataclass
class ProcDetails:
    """None в поле значит «недоступно» (обычно нет прав на чужой процесс)."""
    pid: int
    name: str
    status: str
    user: Optional[str] = None
    parent: Optional[str] = None
    started: Optional[str] = None
    threads: Optional[int] = None
    children: Optional[int] = None
    rss: Optional[int] = None
    vms: Optional[int] = None
    nice: Optional[int] = None
    exe: Optional[str] = None
    cwd: Optional[str] = None
    command: Optional[str] = None
    open_files: Optional[list] = field(default=None)


def _try(fn):
    """Вызвать fn(); если нет прав или данных, вернуть None."""
    try:
        return fn()
    except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return None


def process_details(pid):
    """Подробности о процессе или None, если он уже завершился."""
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            mem = _try(p.memory_info)
            ppid = _try(p.ppid)
            parent = _try(lambda: f"{psutil.Process(ppid).name()} ({ppid})") if ppid else None
            started = _try(lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.create_time())))
            files = _try(lambda: [f.path for f in p.open_files()])
            command = _try(lambda: " ".join(p.cmdline()))
            return ProcDetails(
                pid=pid, name=p.name(), status=p.status(), user=_try(p.username), parent=parent,
                started=started, threads=_try(p.num_threads), children=_try(lambda: len(p.children())),
                rss=mem.rss if mem else None, vms=mem.vms if mem else None, nice=_try(p.nice),
                exe=_try(p.exe) or None, cwd=_try(p.cwd) or None, command=command or None, open_files=files)
    except psutil.NoSuchProcess:
        return None


def set_nice(pid, value):
    """Сменить приоритет (nice: -20 самый высокий … 19 самый низкий). Возвращает сообщение."""
    try:
        psutil.Process(pid).nice(value)
        return f"Priority of PID {pid} set to {value}."
    except psutil.AccessDenied:
        return "Not allowed: raising priority (a lower nice) or changing another user's process needs root."
    except psutil.NoSuchProcess:
        return f"PID {pid} has already exited."
