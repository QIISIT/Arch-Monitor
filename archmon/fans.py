"""Вентиляторы материнской платы через hwmon (/sys/class/hwmon). Без Qt, легко проверить отдельно.

Linux видит вентиляторы платы, только если загружен драйвер её чипа (Super I/O): it87 у Gigabyte,
nct6775 у большинства ASUS, MSI и ASRock. Драйвер даёт файлы fanN_input (обороты) и pwmN (скорость 0–255).
Вентиляторы видеокарт сюда не входят: они в разделе GPU.
"""
import glob
import os
from dataclasses import dataclass
from typing import Optional

from .helpers import read_text, to_float

HWMON = "/sys/class/hwmon"
DMI = "/sys/class/dmi/id"
SKIP_CHIPS = {"amdgpu", "nouveau", "radeon", "i915", "xe"}   # видеокарты: их вентиляторы в разделе GPU

# pwmN_enable: 0 = полная скорость, 1 = ручное управление, 2 и выше = автоматика платы (как в BIOS)
MODES = {"0": "full speed", "1": "manual"}


@dataclass
class Fan:
    chip: str                # имя драйвера, например it8689
    path: str                # папка hwmon
    index: int               # N в fanN_input / pwmN
    label: str               # подпись вентилятора
    rpm: Optional[float]     # обороты в минуту; None, если датчика нет
    pwm: Optional[float]     # скорость 0–100 %; None, если управлять нельзя
    mode: Optional[str]      # режим управления; None, если управлять нельзя


def board():
    """Производитель и модель материнской платы: («Gigabyte Technology Co., Ltd.», «B760 GAMING X DDR4»)."""
    return read_text(f"{DMI}/board_vendor") or "", read_text(f"{DMI}/board_name") or ""


def read_fans():
    """Все вентиляторы платы, которые видит Linux."""
    result = []
    for path in sorted(glob.glob(f"{HWMON}/hwmon*")):
        chip = read_text(f"{path}/name") or "?"
        if chip in SKIP_CHIPS:
            continue
        indexes = set()
        for f in glob.glob(f"{path}/fan*_input") + glob.glob(f"{path}/pwm[0-9]*"):
            digits = "".join(ch for ch in os.path.basename(f).split("_")[0] if ch.isdigit())
            if digits:
                indexes.add(int(digits))
        for n in sorted(indexes):
            raw_pwm = to_float(read_text(f"{path}/pwm{n}"))
            enable = read_text(f"{path}/pwm{n}_enable")
            result.append(Fan(
                chip=chip, path=path, index=n,
                label=read_text(f"{path}/fan{n}_label") or f"Fan {n}",
                rpm=to_float(read_text(f"{path}/fan{n}_input")),
                pwm=raw_pwm / 255 * 100 if raw_pwm is not None else None,
                mode=(MODES.get(enable, "auto (BIOS)") if enable is not None else None) if raw_pwm is not None else None))
    return result


def driver_steps():
    """Что сделать, если вентиляторов не видно: команды под производителя платы."""
    vendor, _name = board()
    if "gigabyte" in vendor.lower():
        return ("Many Gigabyte boards use an ITE chip. Identify the chip before choosing a driver. "
                "Try the kernel's it87 module first. If it is unsupported, check whether it87-dkms-git "
                "supports that exact chip and install headers matching your kernel. "
                "Do not bypass ACPI resource conflicts without diagnosing them:",
                "sudo pacman -S --needed lm_sensors\n"
                "sudo sensors-detect\n"
                "sudo modprobe it87\n"
                "sudo journalctl -k -b --grep='it87|ITE|ACPI.*resource'")
    return ("Most ASUS, MSI and ASRock boards use a Nuvoton chip (driver nct6775). Detect and load it:",
            "sudo pacman -S --needed lm_sensors\n"
            "sudo sensors-detect --auto\n"
            "sudo modprobe nct6775")
