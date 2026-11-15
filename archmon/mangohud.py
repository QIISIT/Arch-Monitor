"""MangoHud: конфиг, пресеты, запуск игры и разбор логов. Без Qt, поэтому легко проверить отдельно.

Что такое MangoHud: оверлей, который встраивается в саму игру (слой Vulkan/OpenGL) и рисует поверх неё
FPS, график кадров, нагрузку и температуры. Показывает FPS только он: отдельная программа не видит кадры игры.
Эта часть приложения управляет MangoHud: правит его конфиг, запускает игры через него и читает его логи.
"""
import glob
import math
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

CONFIG_DIR = os.path.expanduser("~/.config/MangoHud")
CONFIG_FILE = os.path.join(CONFIG_DIR, "MangoHud.conf")
MARKER = "# --- managed by Arch Monitor (edit in the app) ---"
INSTALL_HINT = "sudo pacman -S mangohud lib32-mangohud"

# ── Опции-галочки: (ключ в конфиге, подпись в окне, группа) ──────────────────
FLAGS = [
    ("fps", "FPS", "Frames"),
    ("frametime", "Frametime (ms)", "Frames"),
    ("frame_timing", "Frametime graph", "Frames"),
    ("histogram", "Histogram instead of graph", "Frames"),
    ("show_fps_limit", "Current FPS limit", "Frames"),
    ("gpu_stats", "GPU load", "GPU"),
    ("gpu_temp", "GPU temperature", "GPU"),
    ("gpu_core_clock", "GPU core clock", "GPU"),
    ("gpu_mem_clock", "GPU memory clock", "GPU"),
    ("gpu_power", "GPU power", "GPU"),
    ("vram", "VRAM", "GPU"),
    ("gpu_name", "GPU name", "GPU"),
    ("cpu_stats", "CPU load", "CPU and RAM"),
    ("cpu_temp", "CPU temperature", "CPU and RAM"),
    ("cpu_power", "CPU power", "CPU and RAM"),
    ("core_load", "Per-core load", "CPU and RAM"),
    ("ram", "RAM", "CPU and RAM"),
    ("resolution", "Resolution", "Other"),
    ("vulkan_driver", "Vulkan driver", "Other"),
    ("wine", "Wine version", "Other"),
    ("gamemode", "GameMode status", "Other"),
    ("arch", "32/64-bit", "Other"),
]
FLAG_GROUPS = ["Frames", "GPU", "CPU and RAM", "Other"]
FLAG_KEYS = {key for key, _, _ in FLAGS}
DEFAULT_FLAGS = {"fps", "frame_timing", "cpu_stats", "gpu_stats"}

# ── Опции со значением (порядок = порядок записи в файл) ─────────────────────
VALUE_KEYS = ["position", "font_size", "alpha", "background_alpha", "fps_limit", "pci_dev",
              "output_folder", "log_interval", "toggle_hud", "toggle_fps_limit", "toggle_logging"]
POSITIONS = ["top-left", "top-center", "top-right", "middle-left", "middle-right", "bottom-left", "bottom-right"]
DEFAULTS = {"position": "top-left", "font_size": "24", "alpha": "1", "background_alpha": "0.5", "log_interval": "0"}

# ── Пресеты: какие галочки включить ──────────────────────────────────────────
PRESETS = {
    "FPS only": ["fps"],
    "Minimal": ["fps", "frame_timing", "gpu_stats", "cpu_stats"],
    "Standard": ["fps", "frametime", "frame_timing", "gpu_stats", "gpu_temp", "vram", "cpu_stats", "cpu_temp", "ram"],
    "Full": [key for key, _, _ in FLAGS],
}


@dataclass
class HudConfig:
    flags: set = field(default_factory=lambda: set(DEFAULT_FLAGS))
    values: dict = field(default_factory=dict)      # значения: position, font_size, ...
    other_lines: list = field(default_factory=list)  # чужие строки файла (комментарии, неизвестные опции): сохраняем как есть


def load_config(path=CONFIG_FILE):
    """Читает конфиг; если файла нет, возвращает пустой."""
    cfg = HudConfig()
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return cfg
    for raw in text.splitlines():
        line = raw.strip()
        if line == MARKER:
            continue
        if not line or line.startswith("#"):
            cfg.other_lines.append(raw)
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key in FLAG_KEYS:
            if value.lower() in ("0", "false"):
                cfg.flags.discard(key)
            else:
                cfg.flags.add(key)
        elif key in VALUE_KEYS and sep:
            cfg.values[key] = value
        else:
            cfg.other_lines.append(raw)
    return cfg


def save_config(cfg, path=CONFIG_FILE):
    """Записывает конфиг. Старый файл один раз сохраняется как MangoHud.conf.bak; чужие строки остаются."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and not os.path.exists(path + ".bak"):
        shutil.copy2(path, path + ".bak")
    lines = list(cfg.other_lines)
    while lines and not lines[-1].strip():
        lines.pop()
    out = lines + ([""] if lines else []) + [MARKER]
    out += [key if key in cfg.flags else f"{key}=0" for key, _, _ in FLAGS]
    out += [f"{key}={cfg.values[key]}" for key in VALUE_KEYS if cfg.values.get(key) not in (None, "")]
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def mangohud_path():
    """Путь к mangohud или None, если не установлен."""
    return shutil.which("mangohud")


def launch(command, extra_env=None):
    """Запускает команду под mangohud. Возвращает (получилось ли, сообщение)."""
    exe = mangohud_path()
    if not exe:
        return False, f"MangoHud is not installed. Run: {INSTALL_HINT}"
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return False, f"Can't parse the command: {e}"
    if not argv:
        return False, "Type a command or choose a program first."
    try:
        subprocess.Popen([exe, *argv], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, **(extra_env or {})})
    except OSError as e:
        return False, f"Could not start: {e}"
    return True, f"Started: mangohud {command}"


# ── Логи (создаются в игре клавишей логирования, по умолчанию Shift_L+F2) ────
@dataclass
class LogSummary:
    samples: int
    seconds: Optional[float]
    avg_fps: float
    min_fps: float
    max_fps: float
    low_1: float       # показатели выборки; CSV не гарантирует запись каждого кадра
    low_01: float
    frametimes: list   # мс из замеров (для графика)


def list_logs(folder):
    """CSV-логи кадров в папке, новые сверху (файлы *summary* пропускаются)."""
    files = [p for p in glob.glob(os.path.join(os.path.expanduser(folder), "*.csv")) if "summary" not in p.lower()]
    return sorted(files, key=os.path.getmtime, reverse=True)


def _low(frametimes_desc, share):
    """FPS по самым медленным share (0.01 = 1%) кадров."""
    n = max(1, math.ceil(len(frametimes_desc) * share))
    worst = frametimes_desc[:n]
    return 1000 / (sum(worst) / len(worst))


def summarize_log(path):
    """Сводка по логу MangoHud или None, если файл не похож на лог кадров."""
    header, rows = None, []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                parts = [p.strip() for p in line.strip().split(",")]
                if header is None:
                    if parts and parts[0].lower() == "fps":   # строка-заголовок таблицы с данными
                        header = [p.lower() for p in parts]
                    continue
                if len(parts) != len(header):
                    continue
                try:
                    row = [float(x) for x in parts]
                    rows.append(row)
                except ValueError:
                    continue
    except OSError:
        return None
    if not header or not rows:
        return None
    col = {name: i for i, name in enumerate(header)}
    valid = []
    for row in rows:
        fps = row[col["fps"]]
        if not math.isfinite(fps) or fps <= 0:
            continue
        ft = row[col["frametime"]] if "frametime" in col else 1000 / fps
        if math.isfinite(ft) and ft > 0:
            valid.append((row, fps, ft))
    frametimes = [ft for _, _, ft in valid]
    if not frametimes:
        return None
    desc = sorted(frametimes, reverse=True)
    seconds = None
    if "elapsed" in col:
        elapsed = [row[col["elapsed"]] for row, _, _ in valid]
        if (len(elapsed) > 1 and all(math.isfinite(t) and t >= 0 for t in elapsed)
                and all(b >= a for a, b in zip(elapsed, elapsed[1:]))):
            seconds = (elapsed[-1] - elapsed[0]) / 1e9  # MangoHud CSV: наносекунды
    fps_values = [fps for _, fps, _ in valid]
    return LogSummary(samples=len(frametimes), seconds=seconds, avg_fps=sum(fps_values) / len(fps_values),
                      min_fps=min(fps_values), max_fps=max(fps_values),
                      low_1=_low(desc, 0.01), low_01=_low(desc, 0.001), frametimes=frametimes)
