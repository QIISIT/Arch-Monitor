"""Колонки таблицы процессов. Чтобы добавить, убрать или переименовать колонку, правь только этот файл.

Поля Column:
  title    заголовок
  width    ширина в пикселях (None: колонка растягивается на остаток)
  key      имя поля из system.Proc, по нему идёт сортировка
  numeric  число: выравнивается вправо, при первом клике сортируется по убыванию
  fmt      как превратить значение поля в текст
"""
from dataclasses import dataclass
from typing import Callable, Optional

from .helpers import human_bytes


@dataclass(frozen=True)
class Column:
    title: str
    width: Optional[int]
    key: str
    numeric: bool
    fmt: Callable


COLUMNS = [
    Column("PID", 70, "pid", True, str),
    Column("User", 110, "user", False, str),
    Column("CPU %", 80, "cpu", True, lambda v: f"{v:.1f}"),
    Column("Mem %", 80, "mem_percent", True, lambda v: f"{v:.1f}"),
    Column("Memory", 90, "rss", True, human_bytes),
    Column("Command", None, "command", False, str),
]
