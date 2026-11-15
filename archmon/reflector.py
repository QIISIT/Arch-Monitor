"""Reflector: обновление списка зеркал pacman. Без Qt, легко проверить отдельно.

reflector на Arch обычно ставится как служба: reflector.service выполняет
`reflector @/etc/xdg/reflector/reflector.conf` и перезаписывает /etc/pacman.d/mirrorlist.
Кнопка в окне перезапускает эту службу через pkexec (система сама спросит пароль).
Если службы нет, но есть reflector и его конфиг, запускаем reflector напрямую с тем же конфигом.
"""
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

SERVICE = "reflector.service"
CONFIG = "/etc/xdg/reflector/reflector.conf"
MIRRORLIST = "/etc/pacman.d/mirrorlist"
INSTALL_HINT = "sudo pacman -S reflector"

# pkexec: 126 = окно пароля закрыли, 127 = нет прав или не удалось спросить пароль
PKEXEC_CANCELLED = (126, 127)


def _run(argv, timeout=3):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def has_service():
    """Есть ли служба reflector.service."""
    if not shutil.which("systemctl"):
        return False
    r = _run(["systemctl", "show", SERVICE, "-p", "LoadState", "--value"])
    return r is not None and r.stdout.strip() == "loaded"


def restart_command():
    """Команда для перезапуска или None, если reflector не установлен."""
    if not shutil.which("pkexec"):
        return None
    if has_service():
        return ["pkexec", "systemctl", "restart", SERVICE]
    if shutil.which("reflector") and os.path.exists(CONFIG):
        return ["pkexec", "reflector", f"@{CONFIG}"]
    return None


@dataclass
class MirrorInfo:
    servers: int                  # сколько серверов в mirrorlist
    updated: Optional[float]      # когда файл менялся последний раз (time.time())


def mirror_info():
    """Сколько зеркал в /etc/pacman.d/mirrorlist и когда он обновлялся; None, если файла нет."""
    try:
        with open(MIRRORLIST) as f:
            servers = sum(1 for line in f if line.lstrip().startswith("Server"))
        return MirrorInfo(servers, os.path.getmtime(MIRRORLIST))
    except OSError:
        return None


def ago(ts):
    """Сколько прошло: «5 min ago», «3 h ago», «2 days ago»."""
    if ts is None:
        return "never"
    s = max(0, int(time.time() - ts))
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{s // 60} min ago"
    if s < 172800:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def next_timer_run():
    """Когда reflector.timer запустит обновление сам (строка) или None, если таймер выключен."""
    r = _run(["systemctl", "show", "reflector.timer", "-p", "ActiveState", "-p", "NextElapseUSecRealtime"])
    if r is None:
        return None
    values = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    if values.get("ActiveState") != "active":
        return None
    return values.get("NextElapseUSecRealtime") or None


def journal_tail(lines=6):
    """Последние строки журнала службы (почему не получилось). Пусто, если журнал не читается."""
    r = _run(["journalctl", "-u", SERVICE, "-n", str(lines), "--no-pager", "-o", "cat"])
    return r.stdout.strip() if r is not None and r.returncode == 0 else ""


def summary():
    """Текст для подсказки на кнопке."""
    if restart_command() is None:
        if not shutil.which("pkexec"):
            return "pkexec not found (package polkit)."
        return f"reflector is not installed. Install it with: {INSTALL_HINT}"
    info = mirror_info()
    parts = ["Update the pacman mirror list with reflector (asks for your password)."]
    if info:
        parts.append(f"Mirror list: {info.servers} servers, updated {ago(info.updated)}.")
    nxt = next_timer_run()
    parts.append(f"Automatic update: {nxt}." if nxt else "Automatic update (reflector.timer) is off.")
    return "\n".join(parts)
