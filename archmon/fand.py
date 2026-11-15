#!/usr/bin/env python3
"""Arch Monitor: служба кривых вентиляторов. Работает от root (systemd, archmon-fans.service).

Каждые INTERVAL секунд читает температуры и ставит скорость вентиляторов материнской платы
по настройкам из /etc/archmon/fans.json. Файл самодостаточный: при «Apply» он копируется в
/usr/local/lib/archmon/fand.py и не зависит от остального приложения. Окно Arch Monitor берёт
отсюда же формулу кривой и пресеты, чтобы считать одинаково.

Безопасность:
  - скорость по кривой и фиксированная скорость не ниже MIN_PCT;
  - при CPU от EMERGENCY_CPU или GPU от EMERGENCY_GPU градусов все управляемые вентиляторы на 100 %;
  - если нужную температуру прочитать не удалось, этот вентилятор на 100 %;
  - если вентилятор не поддаётся управлению, он возвращается к автоматике платы и больше не трогается;
  - при остановке службы все вентиляторы возвращаются в режим, который был до неё (автоматика платы).

Настройки в BIOS служба не меняет: она управляет вентиляторами, только пока работает.
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time

CONFIG = "/etc/archmon/fans.json"
STATE_DIR = "/run/archmon-fans"          # исходные режимы вентиляторов до службы (очищается при перезагрузке)
HWMON = "/sys/class/hwmon"
INTERVAL = 2.0                           # секунд между шагами
MIN_PCT = 20                             # ниже этой скорости служба вентилятор не опускает
EMERGENCY_CPU = 90                       # °C: все вентиляторы на 100 %
EMERGENCY_GPU = 87
STEP_DOWN = 8                            # на сколько % за шаг можно снижать скорость (без рывков)
CPU_CHIPS = ("coretemp", "k10temp", "zenpower")
CPU_LABELS = ("Package id 0", "Tctl", "Tdie")

PRESETS = {   # t1 °C и ниже: p1 %; t2 °C и выше: p2 %; между ними плавно
    "silent":      {"t1": 45, "p1": 25, "t2": 80, "p2": 100},
    "balanced":    {"t1": 40, "p1": 35, "t2": 75, "p2": 100},
    "performance": {"t1": 35, "p1": 50, "t2": 65, "p2": 100},
}


# ── Кривая ──────────────────────────────────────────────────────────────────
def clean_curve(curve):
    """Кривая с проверенными значениями: температуры 20–100 °C, t2 > t1, скорости от MIN_PCT, p2 ≥ p1."""
    t1 = min(95, max(20, int(curve.get("t1", 40))))
    t2 = min(100, max(t1 + 1, int(curve.get("t2", 75))))
    p1 = min(100, max(MIN_PCT, int(curve.get("p1", 35))))
    p2 = min(100, max(p1, int(curve.get("p2", 100))))
    return {"t1": t1, "p1": p1, "t2": t2, "p2": p2}


def curve_pct(temp, curve):
    """Скорость в % для температуры temp по кривой."""
    c = clean_curve(curve)
    if temp <= c["t1"]:
        return c["p1"]
    if temp >= c["t2"]:
        return c["p2"]
    return c["p1"] + (c["p2"] - c["p1"]) * (temp - c["t1"]) / (c["t2"] - c["t1"])


# ── Датчики ─────────────────────────────────────────────────────────────────
def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _write(path, value):
    with open(path, "w") as f:
        f.write(str(value))


def find_hwmon(chip):
    """Папка hwmon чипа вентиляторов по имени (номер hwmonN после перезагрузки может поменяться)."""
    base = chip.split("_")[0]
    for path in sorted(glob.glob(f"{HWMON}/hwmon*")):
        name = _read(f"{path}/name") or ""
        if name == chip or name.split("_")[0] == base:
            return path
    return None


def cpu_temp():
    for path in glob.glob(f"{HWMON}/hwmon*"):
        if (_read(f"{path}/name") or "") not in CPU_CHIPS:
            continue
        values = []
        for inp in glob.glob(f"{path}/temp*_input"):
            raw = _read(inp)
            if raw is None or not raw.lstrip("-").isdigit():
                continue
            if (_read(inp.replace("_input", "_label")) or "") in CPU_LABELS:
                return int(raw) / 1000
            values.append(int(raw) / 1000)
        if values:
            return max(values)
    return None


def gpu_temp():
    """Самая горячая видеокарта: NVIDIA через nvidia-smi, AMD через hwmon."""
    temps = []
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=3).stdout
            temps += [float(x) for x in out.split() if x.replace(".", "", 1).isdigit()]
        except (OSError, subprocess.SubprocessError):
            pass
    for path in glob.glob(f"{HWMON}/hwmon*"):
        if (_read(f"{path}/name") or "") == "amdgpu":
            raw = _read(f"{path}/temp1_input")
            if raw and raw.isdigit():
                temps.append(int(raw) / 1000)
    return max(temps) if temps else None


def read_temps():
    temps = {"cpu": cpu_temp(), "gpu": gpu_temp()}
    known = [t for t in temps.values() if t is not None]
    temps["hottest"] = max(known) if known else None
    return temps


# ── Управление ──────────────────────────────────────────────────────────────
def load_config(path=None):
    with open(path or CONFIG) as f:
        cfg = json.load(f)
    curves = cfg.setdefault("curves", {})
    for name, curve in PRESETS.items():
        curves.setdefault(name, dict(curve))
    cfg.setdefault("fans", [])
    return cfg


class Controller:
    def __init__(self, cfg, log=print):
        self.cfg, self.log = cfg, log
        self.hw = None
        self.original = {}    # номер -> pwmN_enable до службы
        self.last = {}        # номер -> последняя выставленная скорость, % (только управляемые)
        self.broken = set()   # номера, которыми управлять не вышло
        self.pending = set()  # каналы, исходный режим которых ещё нужно восстановить

    def _save_state(self):
        path = os.path.join(STATE_DIR, "original.json")
        if not self.pending:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            return
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = path + ".new"
        with open(tmp, "w") as f:
            json.dump({"hw": self.hw, "chip": _read(f"{self.hw}/name"),
                       "enable": self.original, "pending": sorted(self.pending)}, f)
        os.replace(tmp, path)

    def attach(self, wait=30):
        """Найти чип (подождать, пока драйвер загрузится) и запомнить исходные режимы вентиляторов."""
        for _ in range(wait + 1):
            self.hw = find_hwmon(self.cfg.get("chip", ""))
            if self.hw:
                break
            time.sleep(1)
        if not self.hw:
            raise SystemExit(f"fan chip {self.cfg.get('chip')!r} not found; is the driver loaded?")
        state = os.path.join(STATE_DIR, "original.json")
        try:
            with open(state) as f:
                saved = json.load(f)
            if saved.get("hw") != self.hw:
                raise RuntimeError("fan device changed; restore the saved state before applying settings")
            self.original = {int(k): v for k, v in saved["enable"].items()}
            self.pending = set(saved.get("pending", self.original))
        except FileNotFoundError:
            pass
        if not self.original:
            for path in glob.glob(f"{self.hw}/pwm*_enable"):
                n = int("".join(ch for ch in os.path.basename(path).split("_")[0] if ch.isdigit()))
                self.original[n] = _read(path)

    def step(self):
        """Один шаг: прочитать температуры и выставить скорости. Возвращает температуры."""
        temps = read_temps()
        emergency = (temps["cpu"] or 0) >= EMERGENCY_CPU or (temps["gpu"] or 0) >= EMERGENCY_GPU
        for fan in self.cfg["fans"]:
            n = int(fan["index"])
            if n in self.broken:
                if not self.release(n) and emergency:
                    # Режим может не переключаться, хотя запись скорости ещё доступна.
                    try:
                        _write(f"{self.hw}/pwm{n}", 255)
                        self.last[n] = 100
                    except OSError as error:
                        self.log(f"fan {n}: emergency speed write failed ({error})")
                continue
            mode = fan.get("mode", "bios")
            if mode not in ("curve", "fixed"):
                self.release(n)
                continue
            if mode == "fixed":
                pct = min(100, max(MIN_PCT, int(fan.get("fixed", 50))))
            else:
                temp = temps.get(fan.get("source", "cpu"))
                curve = self.cfg["curves"].get(fan.get("curve", "balanced"), PRESETS["balanced"])
                pct = 100 if temp is None else curve_pct(temp, curve)
            if emergency:
                pct = 100
            prev = self.last.get(n)
            if prev is not None and pct < prev:
                pct = max(pct, prev - STEP_DOWN)
            try:
                self.set_pct(n, pct)
            except OSError as e:
                self.log(f"fan {n}: can't control it ({e}); trying to restore its original mode")
                self.broken.add(n)
                self.release(n)
        return temps

    def set_pct(self, n, pct):
        if self.original.get(n) is None:
            raise OSError("original PWM mode is unknown; refusing manual control")
        if n not in self.last:
            self.pending.add(n)
            self._save_state()   # сохраняем до записи: переживёт ошибку PWM или перезапуск службы
            _write(f"{self.hw}/pwm{n}_enable", 1)   # ручное управление
        _write(f"{self.hw}/pwm{n}", round(pct * 255 / 100))
        self.last[n] = pct

    def release(self, n):
        """Вернуть вентилятор в исходный режим (автоматика платы)."""
        if n not in self.pending:
            return True
        original = self.original.get(n)
        try:
            if original is None:
                raise OSError("original mode is unknown")
            path = f"{self.hw}/pwm{n}_enable"
            _write(path, original)
            if _read(path) != str(original):
                raise OSError("mode readback does not match")
            self.pending.remove(n)
            self._save_state()
        except OSError as e:
            self.pending.add(n)
            self.log(f"fan {n}: can't restore mode {original} ({e}); will retry")
            return False
        self.last.pop(n, None)
        return True

    def restore_all(self, attempts=3):
        for attempt in range(attempts):
            for n in list(self.pending):
                self.release(n)
            if not self.pending:
                return True
            if attempt + 1 < attempts:
                time.sleep(0.25)
        return False


def restore_saved():
    """Восстановить режимы после остановки службы, включая старую версию или аварийный выход."""
    try:
        with open(os.path.join(STATE_DIR, "original.json")) as f:
            saved = json.load(f)
    except FileNotFoundError:
        return True
    except (OSError, ValueError) as error:
        print(f"Cannot read saved fan state: {error}. Recovery not confirmed.", file=sys.stderr)
        return False
    try:
        hw = saved["hw"]
        if (not isinstance(hw, str) or os.path.dirname(hw) != HWMON
                or not os.path.basename(hw).startswith("hwmon")
                or not os.path.basename(hw)[5:].isdigit()):
            raise ValueError("invalid saved hwmon path")
        chip = saved.get("chip")
        if not chip:   # формат старой службы
            chip = load_config().get("chip")
        if not chip or _read(f"{hw}/name") != chip:
            raise ValueError("saved fan device is unavailable or changed")
        ctl = Controller({}, log=lambda text: print(text, file=sys.stderr, flush=True))
        ctl.hw = hw
        ctl.original = {int(k): v for k, v in saved["enable"].items()}
        ctl.pending = set(saved.get("pending", ctl.original))
        if any(type(n) is not int or not 1 <= n <= 16 or n not in ctl.original for n in ctl.pending):
            raise ValueError("invalid saved fan channels")
        if not ctl.restore_all():
            print("Some fan modes could not be restored. Saved state retained for retry.", file=sys.stderr)
            return False
        ctl._save_state()
        return True
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Fan recovery failed: {error}. Saved state retained.", file=sys.stderr)
        return False


def main():
    cfg = load_config()
    ctl = Controller(cfg, log=lambda text: print(text, flush=True))
    ctl.attach()
    stop = {"now": False}

    def on_signal(*_args):
        stop["now"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    managed = [f["index"] for f in cfg["fans"] if f.get("mode") in ("curve", "fixed")]
    print(f"controlling fans {managed} on {ctl.hw}", flush=True)
    try:
        while not stop["now"]:
            ctl.step()
            time.sleep(INTERVAL)
    finally:
        if ctl.restore_all():
            print("fans returned to their original control modes", flush=True)
        else:
            print("ERROR: some fans remain unrestored; saved state retained for recovery", file=sys.stderr, flush=True)
            raise SystemExit(1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--restore"]:
        sys.exit(0 if restore_saved() else 1)
    elif len(sys.argv) == 1:
        main()
    else:
        sys.exit("usage: fand.py [--restore]")
