"""Установка службы кривых вентиляторов (archmon-fans.service) и команды для неё. Без Qt.

Первая установка (и после обновления Arch Monitor) идёт одним вызовом pkexec с паролем:
в систему копируются служба fand.py, помощник fanctl, systemd-юнит и правило polkit.
Дальше «Apply» и «Back to BIOS» запускают только помощник: правило polkit пускает к нему
участников группы wheel без пароля, а сам помощник принимает лишь проверенные настройки.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

from . import fand

SERVICE = "archmon-fans.service"
LIB_DIR = "/usr/local/lib/archmon"
DAEMON_PATH = f"{LIB_DIR}/fand.py"
FANCTL_PATH = f"{LIB_DIR}/fanctl"
STAMP_PATH = f"{LIB_DIR}/installed.stamp"        # отпечаток установленной версии (читается без root)
UNIT_PATH = f"/etc/systemd/system/{SERVICE}"
RULE_PATH = "/etc/polkit-1/rules.d/50-archmon-fans.rules"
FANCTL_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fanctl.py")

UNIT = f"""[Unit]
Description=Arch Monitor fan curves
After=systemd-modules-load.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 {DAEMON_PATH}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

RULE = f"""// Arch Monitor: members of wheel may change fan settings without a password.
// Only {FANCTL_PATH} is allowed, and it accepts nothing but a checked fan config.
polkit.addRule(function(action, subject) {{
    if (action.id == "org.freedesktop.policykit.exec" &&
        action.lookup("program") == "{FANCTL_PATH}" &&
        subject.local && subject.active && subject.isInGroup("wheel")) {{
        return polkit.Result.YES;
    }}
}});
"""

# $1 служба, $2 помощник, $3 юнит, $4 правило polkit, $5 отпечаток, $6 настройки
INSTALL_SCRIPT = (
    "set -e; "
    f'install -D -m 0644 "$1" {DAEMON_PATH}; '
    f'install -D -m 0755 "$2" {FANCTL_PATH}; '
    f'install -D -m 0644 "$3" {UNIT_PATH}; '
    f'install -D -m 0644 "$4" {RULE_PATH}; '
    f'install -D -m 0644 "$5" {STAMP_PATH}; '
    "systemctl daemon-reload; "
    f'{FANCTL_PATH} apply < "$6"'
)

MODES = ["bios", "silent", "balanced", "performance", "fixed"]   # как в списке режима на странице
SOURCES = ["cpu", "gpu", "hottest"]


def default_fan(index):
    return {"index": index, "name": "", "mode": "bios", "curve": "balanced", "source": "cpu", "fixed": 50}


def load_config():
    """Сохранённые настройки службы или None, если её ещё не настраивали."""
    try:
        return fand.load_config()
    except (OSError, ValueError):
        return None


def is_active():
    try:
        out = subprocess.run(["systemctl", "is-active", SERVICE], capture_output=True, text=True, timeout=3).stdout
        return out.strip() == "active"
    except (OSError, subprocess.SubprocessError):
        return False


def stamp():
    """Отпечаток всего, что ставится в систему: поменялся код или правило, значит, нужна переустановка."""
    h = hashlib.sha256()
    for path in (fand.__file__, FANCTL_SOURCE):
        with open(path, "rb") as f:
            h.update(f.read())
    h.update(UNIT.encode())
    h.update(RULE.encode())
    return h.hexdigest()[:16]


def installed():
    """Установлена ли в систему именно эта версия службы и помощника."""
    try:
        with open(STAMP_PATH) as f:
            return f.read().strip() == stamp()
    except OSError:
        return False


def apply_command(cfg):
    """(argv, данные для stdin или None, временная папка или None) для применения настроек.

    Если установлена текущая версия: быстрый путь через помощник, без пароля.
    Иначе: полная установка одним pkexec (система спросит пароль).
    """
    data = json.dumps(cfg, ensure_ascii=False).encode()
    if installed():
        return ["pkexec", FANCTL_PATH, "apply"], data, None
    tmp = tempfile.mkdtemp(prefix="archmon-fans-")   # права 0700: доступна только тебе
    files = {"fand.py": None, "fanctl": None, SERVICE: UNIT, "50-archmon-fans.rules": RULE,
             "installed.stamp": stamp() + "\n", "fans.json": data.decode()}
    shutil.copyfile(fand.__file__, os.path.join(tmp, "fand.py"))
    shutil.copyfile(FANCTL_SOURCE, os.path.join(tmp, "fanctl"))
    for name, text in files.items():
        if text is not None:
            with open(os.path.join(tmp, name), "w") as f:
                f.write(text)
    order = ["fand.py", "fanctl", SERVICE, "50-archmon-fans.rules", "installed.stamp", "fans.json"]
    return ["pkexec", "/bin/sh", "-c", INSTALL_SCRIPT, "sh", *[os.path.join(tmp, n) for n in order]], None, tmp


def stop_command():
    """argv для «Back to BIOS» или None, если служба вообще не ставилась."""
    if os.path.exists(FANCTL_PATH):
        return ["pkexec", FANCTL_PATH, "stop"]
    if os.path.exists(UNIT_PATH):   # служба из прошлой версии, ещё без помощника: остановить с паролем
        return ["pkexec", "/bin/sh", "-c", f"systemctl disable --now {SERVICE}"]
    return None
