"""Чтение данных о видеокартах: NVIDIA, AMD и Intel.

Единственная функция, которая нужна остальному коду: read_gpus().
Чтобы поддержать новый источник данных, напиши функцию _read_xxx() -> list[Gpu]
и добавь её вызов в read_gpus().
"""
import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from .helpers import read_text, to_float

DRM = "/sys/class/drm"   # здесь ядро Linux показывает видеокарты

# nvidia-smi на новых драйверах часто не отдаёт вольтаж; один раз убедившись в этом, больше не спрашиваем
_nvidia_voltage_supported = True


@dataclass
class Gpu:
    """Состояние одной видеокарты. None значит «этот датчик недоступен»."""
    id: str                               # уникальный ключ карты (по нему ищется карточка в окне)
    name: str
    util: float                           # загрузка, 0..100 (у Intel: частота в % от максимума)
    util_text: str                        # подпись справа от полосы загрузки
    vram_used: Optional[float] = None     # байты
    vram_total: Optional[float] = None
    temp: Optional[float] = None          # °C
    power: Optional[float] = None         # Вт
    power_max: Optional[float] = None     # лимит мощности, Вт
    core_clk: Optional[float] = None      # МГц
    core_max: Optional[float] = None
    mem_clk: Optional[float] = None
    mem_max: Optional[float] = None
    voltage: Optional[float] = None       # мВ
    fan: Optional[float] = None           # обороты вентилятора, % от максимума
    pci: Optional[str] = None             # адрес на шине, например 0000:01:00.0 (нужен MangoHud для выбора карты)


# ── NVIDIA (через nvidia-smi) ───────────────────────────────────────────────
_NVIDIA_FIELDS = ("index,pci.bus_id,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,"
                  "clocks.gr,clocks.mem,clocks.max.gr,clocks.max.mem,power.limit,fan.speed")
_NVIDIA_NUMERIC = 11   # сколько полей с конца строки числовые (имя карты может содержать запятую)


def _nvidia_voltages():
    """Вольтаж каждой карты в мВ (None, если драйвер не отдаёт)."""
    global _nvidia_voltage_supported
    if not _nvidia_voltage_supported:
        return []
    try:
        out = subprocess.run(["nvidia-smi", "-q", "-d", "VOLTAGE"],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return []
    volts = []
    for block in re.split(r"(?m)^GPU ", out)[1:]:
        m = re.search(r"Graphics\s*:\s*([\d.]+)\s*mV", block)
        volts.append(float(m.group(1)) if m else None)
    if not any(v is not None for v in volts):
        _nvidia_voltage_supported = False
    return volts


def _read_nvidia():
    if not shutil.which("nvidia-smi"):
        return []
    gpus = []
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={_NVIDIA_FIELDS}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=2).stdout.splitlines()
        volts = _nvidia_voltages()
        for n, line in enumerate(out):
            p = [x.strip() for x in line.split(",")]
            util, vused, vtotal, temp, power, core, mem, core_max, mem_max, power_max, fan = \
                map(to_float, p[-_NVIDIA_NUMERIC:])
            gpus.append(Gpu(
                id=f"nv{p[0]}", name=",".join(p[2:-_NVIDIA_NUMERIC]), pci=p[1][-12:].lower(),
                util=util or 0.0, util_text=f"{util or 0:.0f}%",
                vram_used=vused * 2**20 if vused is not None else None,     # МиБ в байты
                vram_total=vtotal * 2**20 if vtotal else None,
                temp=temp, power=power, power_max=power_max,
                core_clk=core, core_max=core_max, mem_clk=mem, mem_max=mem_max,
                voltage=volts[n] if n < len(volts) else None, fan=fan))
    except Exception:
        pass
    return gpus


# ── AMD (через sysfs, ставить ничего не нужно) ──────────────────────────────
def _hwmon(dev, name):
    """Первое числовое значение файла hwmon (температура, мощность и т. п.)."""
    for path in glob.glob(f"{dev}/hwmon/hwmon*/{name}"):
        v = to_float(read_text(path))
        if v is not None:
            return v
    return None


def _dpm_clocks(path):
    """Из файла вида '2: 2400Mhz *' достаёт (текущая частота, максимальная), МГц."""
    current, seen = None, []
    for line in (read_text(path) or "").splitlines():
        m = re.search(r"(\d+)\s*[Mm][Hh]z", line)
        if m:
            seen.append(float(m.group(1)))
            if line.rstrip().endswith("*"):
                current = seen[-1]
    return current, (max(seen) if seen else None)


def _read_amd():
    gpus = []
    for dev in sorted(glob.glob(f"{DRM}/card[0-9]/device")):
        busy = to_float(read_text(f"{dev}/gpu_busy_percent"))
        if busy is None:
            continue   # это не карта AMD
        temp = _hwmon(dev, "temp1_input")
        power = _hwmon(dev, "power1_average") or _hwmon(dev, "power1_input")
        cap = _hwmon(dev, "power1_cap")
        core, core_max = _dpm_clocks(f"{dev}/pp_dpm_sclk")
        mem, mem_max = _dpm_clocks(f"{dev}/pp_dpm_mclk")
        freq_core, freq_mem = _hwmon(dev, "freq1_input"), _hwmon(dev, "freq2_input")   # запасной источник, Гц
        card = dev.split("/")[-2]
        pwm, rpm = _hwmon(dev, "pwm1"), _hwmon(dev, "fan1_input")
        if pwm is not None:
            fan = pwm / (_hwmon(dev, "pwm1_max") or 255) * 100
        elif rpm is not None and _hwmon(dev, "fan1_max"):
            fan = rpm / _hwmon(dev, "fan1_max") * 100
        else:
            fan = None
        gpus.append(Gpu(
            id=dev, name=read_text(f"{dev}/product_name") or f"AMD GPU ({card})",
            util=busy, util_text=f"{busy:.0f}%",
            vram_used=to_float(read_text(f"{dev}/mem_info_vram_used")),
            vram_total=to_float(read_text(f"{dev}/mem_info_vram_total")),
            temp=temp / 1000 if temp is not None else None,          # из милли-градусов
            power=power / 1e6 if power is not None else None,        # из микроватт
            power_max=cap / 1e6 if cap else None,
            core_clk=core or (freq_core / 1e6 if freq_core else None), core_max=core_max,
            mem_clk=mem or (freq_mem / 1e6 if freq_mem else None), mem_max=mem_max,
            voltage=_hwmon(dev, "in0_input"), fan=fan, pci=os.path.basename(os.path.realpath(dev))))
    return gpus


# ── Intel (встроенная графика: только частота) ──────────────────────────────
def _read_intel():
    gpus = []
    for card in sorted(glob.glob(f"{DRM}/card[0-9]")):
        cur = to_float(read_text(f"{card}/gt_act_freq_mhz"))
        top = to_float(read_text(f"{card}/gt_max_freq_mhz"))
        if cur is not None and top:
            gpus.append(Gpu(id=card, name=f"Intel GPU ({card.split('/')[-1]})",
                            util=cur / top * 100, util_text=f"{cur:.0f} MHz",
                            core_clk=cur, core_max=top,
                            pci=os.path.basename(os.path.realpath(f"{card}/device"))))
    return gpus


def read_gpus():
    """Все найденные видеокарты: сначала NVIDIA, потом AMD, потом Intel."""
    return _read_nvidia() + _read_amd() + _read_intel()
