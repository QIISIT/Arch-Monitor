#!/usr/bin/python3 -I
"""Arch Monitor: помощник для службы вентиляторов. Запускается от root через pkexec.

Устанавливается в /usr/local/lib/archmon/fanctl. Умеет ровно две вещи:
  fanctl apply   читает настройки вентиляторов из stdin, проверяет каждое поле, записывает
                 /etc/archmon/fans.json и (пере)запускает archmon-fans.service;
  fanctl stop    выключает службу: вентиляторы возвращаются к кривым BIOS.

Код и файлы помощник не принимает, поэтому правило polkit разрешает участникам группы wheel
запускать его без пароля. Всё, что можно им сделать, это поменять кривые в пределах защиты из fand.py.
"""
import json
import os
import re
import subprocess
import sys

LIB_DIR = "/usr/local/lib/archmon"
sys.path.insert(0, LIB_DIR)   # fand.py лежит рядом и тоже принадлежит root
import fand  # noqa: E402

SERVICE = "archmon-fans.service"
MAX_INPUT = 64 * 1024
MODES = {"bios", "curve", "fixed"}
SOURCES = {"cpu", "gpu", "hottest"}


def validate(raw):
    """Проверенная копия настроек; ValueError, если что-то не так."""
    if not isinstance(raw, dict):
        raise ValueError("config must be an object")
    chip = raw.get("chip")
    if not isinstance(chip, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", chip):
        raise ValueError("bad chip name")
    fans_in = raw.get("fans")
    if not isinstance(fans_in, list) or len(fans_in) > 16:
        raise ValueError("bad fan list")
    fans, seen = [], set()
    for fan in fans_in:
        if not isinstance(fan, dict):
            raise ValueError("bad fan entry")
        index = fan.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= 16 or index in seen:
            raise ValueError("bad fan index")
        seen.add(index)
        mode = fan.get("mode", "bios")
        curve = fan.get("curve", "balanced")
        source = fan.get("source", "cpu")
        fixed = fan.get("fixed", 50)
        name = fan.get("name", "")
        if mode not in MODES or curve not in fand.PRESETS or source not in SOURCES:
            raise ValueError("bad fan mode, curve or source")
        if not isinstance(fixed, int) or isinstance(fixed, bool):
            raise ValueError("bad fixed speed")
        if not isinstance(name, str):
            raise ValueError("bad fan name")
        fans.append({
            "index": index,
            "name": "".join(ch for ch in name if ch.isprintable())[:40],
            "mode": mode, "curve": curve, "source": source,
            "fixed": min(100, max(fand.MIN_PCT, fixed)),
        })
    curves_in = raw.get("curves", {})
    if not isinstance(curves_in, dict):
        raise ValueError("bad curves")
    curves = {}
    for name, preset in fand.PRESETS.items():
        given = curves_in.get(name, preset)
        if not isinstance(given, dict) or not all(isinstance(given.get(k, 0), int) and not isinstance(given.get(k, 0), bool)
                                                  for k in ("t1", "p1", "t2", "p2")):
            raise ValueError("bad curve values")
        curves[name] = fand.clean_curve({**preset, **given})
    return {"version": 1, "chip": chip, "fans": fans, "curves": curves}


def write_config(cfg, path=None):
    path = path or fand.CONFIG
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".new"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def systemctl(*args):
    subprocess.run(["systemctl", *args], check=True)


def stop_service():
    try:
        systemctl("stop", SERVICE)
    except subprocess.CalledProcessError:
        # Неудачный finally службы может завершиться кодом 1. Если процесс уже
        # остановлен, всё ещё можно восстановить сохранённые режимы отдельно.
        state = subprocess.run(["systemctl", "show", "--property=ActiveState", "--value", SERVICE],
                               check=True, capture_output=True, text=True).stdout.strip()
        if state not in ("inactive", "failed"):
            raise


def main(argv=None, stdin=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (["apply"], ["stop"]):
        print("usage: fanctl apply < config.json | fanctl stop", file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print("fanctl must run as root (through pkexec)", file=sys.stderr)
        return 1
    if argv == ["stop"]:
        systemctl("disable", SERVICE)
        stop_service()
        if not fand.restore_saved():
            return 1
        print("fan service stopped; original fan modes restored")
        return 0
    data = (stdin or sys.stdin).read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        print("config is too large", file=sys.stderr)
        return 1
    try:
        cfg = validate(json.loads(data))
    except ValueError as e:   # json.JSONDecodeError тоже ValueError; содержимое не выводим
        print(f"config rejected: {e}", file=sys.stderr)
        return 1
    # Старые каналы должны восстановиться до смены конфигурации.
    stop_service()
    if not fand.restore_saved():
        return 1
    write_config(cfg)
    systemctl("enable", SERVICE)
    systemctl("restart", SERVICE)
    print("fan settings applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
