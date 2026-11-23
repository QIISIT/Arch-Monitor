"""Мелкие функции без зависимостей от Qt и psutil."""


def to_float(value):
    """Строку в число; None, если не получилось (например, "[N/A]")."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_text(path):
    """Содержимое текстового файла без пробелов по краям; None, если файла нет."""
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def human_bytes(n, *, iec=False):
    """Размер в привычной компактной записи или в единицах IEC."""
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB") if iec else "BKMGTP"
    for i, unit in enumerate(units):
        if n < 1024 or i == len(units) - 1:
            value = f"{n:.0f}" if i < 2 else f"{n:.1f}"
            return f"{value} {unit}" if iec else value + unit
        n /= 1024
