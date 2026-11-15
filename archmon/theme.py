"""Цветовые темы. Переключаются на лету из выпадающего списка в окне.

Чтобы добавить свою тему, скопируй любую строку Theme(...) в THEMES и поменяй цвета.
Остальной код берёт цвета из объекта T (например, T.accent), поэтому после смены темы
достаточно перерисовать окно.
"""
from dataclasses import asdict, dataclass
from types import SimpleNamespace

from . import config as C


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str       # главный цвет: заполнение полос, рамка в фокусе, плашки клавиш
    bg: str           # фон окна
    card: str         # фон карточек и таблицы
    line: str         # линии и пустая часть полос
    text: str         # основной текст
    dim: str          # приглушённый текст
    amber: str        # предупреждение
    red: str          # опасность
    selection: str    # выделенная строка таблицы


THEMES = {t.name: t for t in [
    Theme("Graphite",   "#38BDF8", "#0F1113", "#171A1E", "#262B31", "#ECEFF3", "#9AA3AE", "#F5A524", "#F59E9E", "#1B3140"),
    Theme("Arch",       "#1793D1", "#0d1218", "#141b23", "#232d39", "#d5dde6", "#7d8a98", "#e5c07b", "#e5646f", "#1b4a6b"),
    Theme("Nord",       "#88c0d0", "#242933", "#2e3440", "#3b4252", "#d8dee9", "#7b88a1", "#ebcb8b", "#bf616a", "#434c5e"),
    Theme("Gruvbox",    "#83a598", "#1d2021", "#282828", "#3c3836", "#ebdbb2", "#928374", "#fabd2f", "#fb4934", "#504945"),
    Theme("Catppuccin", "#89b4fa", "#11111b", "#1e1e2e", "#313244", "#cdd6f4", "#7f849c", "#f9e2af", "#f38ba8", "#45475a"),
    Theme("Dracula",    "#bd93f9", "#1e1f29", "#282a36", "#44475a", "#f8f8f2", "#6272a4", "#ffb86c", "#ff5555", "#3b3d52"),
]}

T = SimpleNamespace()   # текущая тема: T.accent, T.bg, ... плюс T.side и T.raised (считаются сами)


def mix(a, b, t):
    """Цвет между a и b: t=0 даёт a, t=1 даёт b (оба в виде #rrggbb)."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def set_theme(name):
    """Сделать тему текущей (если имя неизвестно, берётся тема по умолчанию)."""
    theme = THEMES.get(name) or THEMES[C.DEFAULT_THEME]
    T.__dict__.update(asdict(theme))
    T.side = mix(theme.bg, theme.card, 0.5)      # фон бокового меню
    T.raised = mix(theme.card, theme.line, 0.5)  # кнопки внутри карточек, наведение в меню


set_theme(C.DEFAULT_THEME)
