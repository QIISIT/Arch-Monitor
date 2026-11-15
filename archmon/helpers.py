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


def human_bytes(n):
    """2048 -> '2K', 5368709120 -> '5.0G'."""
    for unit in "BKMGT":
        if n < 1024:
            return f"{n:.0f}{unit}" if unit in "BK" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


_INTERPRETERS = {"python", "python3", "bash", "sh", "zsh", "node", "java", "wine", "env", "sudo"}


def program_initial(command):
    """Первая буква программы из командной строки: «/usr/bin/kitty +kitten…» -> «K», «python3 -m archmon» -> «A»."""
    words = [w for w in command.split() if not w.startswith("-")]
    if not words:
        return "?"
    first = words[0]
    name = first.strip("[]").split("/")[0] if first.startswith("[") else first.rsplit("/", 1)[-1]   # [kworker/0:1] -> kworker
    if name in _INTERPRETERS and len(words) > 1:
        name = words[-1].rsplit("/", 1)[-1]
    return (name[:1] or "?").upper()
