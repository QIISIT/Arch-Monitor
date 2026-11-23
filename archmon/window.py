"""Главное окно. Файл читается сверху вниз:

  1. __init__          собирает окно из частей
  2. _build_*          каждая часть интерфейса в своём методе
  3. tick / update_*   периодическое обновление данных
  4. темы, трей, поиск, сортировка, завершение процесса, горячие клавиши
"""
import platform
import signal
from operator import attrgetter
from typing import NamedTuple

from PyQt6.QtCore import QEvent, QSettings, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QStackedWidget, QSystemTrayIcon,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import classify
from . import config as C
from . import system
from .columns import COLUMNS
from .details import ProcessDialog
from . import disks
from .disks_page import DisksPage, rate_text
from .fans import read_fans
from .fans_page import FansPage
from .gpu import Gpu
from .gpu_poll import GpuPoller
from .mangohud_dialog import MangoHudDialog
from . import reflector
from .reflector_button import ReflectorPage
from .helpers import human_bytes
from .style import build_qss
from .theme import THEMES, T, set_theme
from .tray import TrayIcon
from .tree import tree_nodes, visible_nodes
from .widgets import (ALIGN_LEFT, ALIGN_RIGHT, GpuSection, HintButton, Meter, Metric, NavButton,
                      dim_label, divider, logo_pixmap, make_section)

PID_COL = next(i for i, c in enumerate(COLUMNS) if c.key == "pid")   # колонка с PID (нужна для выделения)
SEARCH_COLS = [i for i, c in enumerate(COLUMNS) if c.key in C.SEARCH_KEYS]
CMD_COL = next(i for i, c in enumerate(COLUMNS) if c.key == "command")   # колонка со стрелками дерева
CELL_PADDING = 8   # отступ текста внутри ячейки, px (см. QTableWidget::item в style.py)


class Row(NamedTuple):
    """Одна строка таблицы."""
    proc: object
    prefix: str = ""      # линии дерева и стрелка перед командой
    suffix: str = ""      # « (+12)» у свёрнутой ветки
    node: object = None   # TreeNode в режиме дерева, иначе None


# Пункты бокового меню: (подпись, номер страницы, показывать ли сводку, значок — контур SVG 24×24)
NAV_ITEMS = [
    ("Overview", 0, True, "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"),
    ("Processes", 0, False, "M4 6h16M4 12h16M4 18h10"),
    ("GPU", 1, False, "M3 7h18v10H3zM7 7v10M3 11h4M3 14h4"),
    ("Disks", 6, False, "M3 13h18M5 5h14l2 8v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5zM7 16h.01M11 16h.01"),
    ("Fans", 2, False, "M12 10a2 2 0 1 0 0 4a2 2 0 1 0 0-4M12 10c0-4 1-7 4-7s2 4-2 7M14 12c4 0 7 1 7 4s-4 2-7-2"
                       "M12 14c0 4-1 7-4 7s-2-4 2-7M10 12c-4 0-7-1-7-4s4-2 7 2"),
    ("MangoHud", 3, False, "M3 5h18v12H3zM8 21h8M12 17v4"),
    ("Reflector", 4, False, "M21 12a9 9 0 1 1-3-6.7M21 3v6h-6"),
    ("Settings", 5, False, "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12h2M3 12h2M12 3v2M12 19v2"),
]
NAV_INDEX = {item[0]: i for i, item in enumerate(NAV_ITEMS)}


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(C.APP_NAME)
        self.resize(*C.WINDOW_SIZE)

        # Сохранённые настройки (~/.config/archmon/archmon.conf)
        self.settings = QSettings(C.DESKTOP_ID, C.DESKTOP_ID)
        set_theme(self.settings.value("ui_theme", C.DEFAULT_THEME, type=str))
        self.tree_mode = self.settings.value("tree", False, type=bool)
        self.apps_first = self.settings.value("apps_first", C.APPS_FIRST_DEFAULT, type=bool)
        self.close_to_tray = self.settings.value("close_to_tray", C.CLOSE_TO_TRAY, type=bool)
        self.refresh_ms = self.settings.value("refresh_ms", C.REFRESH_MS, type=int)

        self.selected_pid = None
        self.selected_started = None
        self.sort_index = next(i for i, c in enumerate(COLUMNS) if c.key == C.DEFAULT_SORT_KEY)
        self.sort_desc = C.DEFAULT_SORT_DESC
        self._quitting = False
        self._frozen = False   # True, пока окно «заморожено»
        self._paused = False   # ручная пауза (клик по плашке Ctrl Pause)
        self._search_lock = False   # True: после поиска найденная строка держится на месте, пока не начнёшь листать сама
        self._programmatic = False  # True, пока выделение меняет сама программа (а не ты мышью или стрелками)
        self._sep_row = -1          # номер строки-разделителя «System processes» или -1
        self.expanded = set()       # PID раскрытых веток дерева (по умолчанию всё свёрнуто)
        self._nodes, self._node_by_pid = [], {}   # все узлы дерева с прошлой перерисовки
        self._display = []          # что показано в таблице: Row или None (разделитель)
        self._skip_release = False  # пропустить отпускание кнопки после двойного клика по стрелке
        self._tray_hint_shown = False
        self._tasks_text, self._uptime_text, self._battery_text = "", "", ""
        self.nav_index = 0
        self.gpus = []
        self.io = disks.IoSampler()   # скорости дисков: опрашивается на каждом шаге

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(22, 18, 22, 14)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())
        self.pages = QStackedWidget()
        for page in (self._build_overview_page(), self._build_gpu_page(), self._build_fans_page(),
                     self._build_mangohud_page(), self._build_reflector_page(), self._build_settings_page(),
                     self._build_disks_page()):
            self.pages.addWidget(page)
        layout.addWidget(self.pages, 1)
        layout.addWidget(divider())
        layout.addLayout(self._build_footer())
        root.addWidget(main, 1)
        self.go_to(0)

        self.tray = TrayIcon(self) if C.TRAY_ENABLED and QSystemTrayIcon.isSystemTrayAvailable() else None
        self._setup_shortcuts()
        self._apply_style()
        self.gpu_poller = GpuPoller(self)
        self.gpu_poller.ready.connect(self._receive_gpus)
        QTimer.singleShot(0, self.gpu_poller.request)
        system.prime_counters()
        self.timer = QTimer(self, interval=self.refresh_ms, timeout=self.tick)
        self.timer.start()
        QTimer.singleShot(400, self.tick)   # первое обновление не ждёт целый интервал
        self.freeze_timer = QTimer(self, interval=100, timeout=self._poll_freeze)   # следит за клавишей Ctrl
        self.freeze_timer.start()

    # ── 2. Построение интерфейса ────────────────────────────────────────────
    def _build_sidebar(self):
        """Боковое меню: логотип, разделы, сведения о системе внизу."""
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(C.SIDEBAR_WIDTH)
        box = QVBoxLayout(side)
        box.setContentsMargins(0, 20, 0, 16)
        box.setSpacing(2)

        brand = QHBoxLayout()
        brand.setContentsMargins(20, 0, 10, 14)
        brand.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(30, 30)
        self.logo.setPixmap(logo_pixmap())
        name = QLabel(C.APP_NAME)
        name.setObjectName("brand")
        brand.addWidget(self.logo)
        brand.addWidget(name)
        brand.addStretch()
        box.addLayout(brand)

        self.nav_buttons = []
        for i, (label, _page, _summary, icon) in enumerate(NAV_ITEMS):
            group = {"Overview": "MONITOR", "MangoHud": "TOOLS"}.get(label)
            if group:
                heading = QLabel(group)
                heading.setObjectName("navGroup")
                box.addSpacing(8)
                box.addWidget(heading)
            button = NavButton(label, icon)
            if label == "GPU":
                button.setVisible(False)   # появится после успешного фонового опроса
            button.clicked.connect(lambda _checked=False, n=i: self.go_to(n))
            self.nav_buttons.append((i, button))
            box.addWidget(button)
        box.addStretch()

        host = QLabel(platform.node())
        host.setObjectName("strong")
        self.side_reflector = dim_label("")
        info = QVBoxLayout()
        info.setContentsMargins(20, 12, 12, 0)
        info.setSpacing(2)
        info.addWidget(host)
        info.addWidget(dim_label(f"Linux {platform.release()}"))
        info.addWidget(self.side_reflector)
        box.addWidget(divider())
        box.addLayout(info)
        self._update_side_reflector()
        return side

    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = QLabel("Overview")
        self.page_title.setObjectName("title")
        self.info_label = dim_label("")
        titles.addWidget(self.page_title)
        titles.addWidget(self.info_label)
        row.addLayout(titles, 1)
        row.addWidget(dim_label("Theme"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES))
        self.theme_combo.setCurrentText(T.name)
        self.theme_combo.setToolTip("Color theme")
        self.theme_combo.currentTextChanged.connect(self.apply_theme)
        row.addWidget(self.theme_combo)
        return row

    def _build_overview_page(self):
        """Сводка Overview и общая таблица процессов."""
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.summary = QWidget()
        summary = QVBoxLayout(self.summary)
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(10)
        self.cpu_threads = system.cpu_count()
        summary.addWidget(self._build_metrics())
        summary.addWidget(self._build_cpu_threads())
        summary.addWidget(self._build_sensors())
        box.addWidget(self.summary)
        box.addWidget(self._build_process_panel(), 1)
        return page

    def _build_metrics(self):
        section = make_section()
        row = QHBoxLayout(section)
        row.setContentsMargins(0, 12, 0, 6)
        row.setSpacing(16)
        self.cpu_metric = Metric("CPU")
        self.mem_metric = Metric("MEMORY")
        self.gpu_metric = Metric("GPU")
        self.vram_metric = Metric("VRAM")
        self.disk_metric = Metric("DISK /", last=True)
        for metric in (self.cpu_metric, self.mem_metric, self.gpu_metric, self.vram_metric, self.disk_metric):
            row.addWidget(metric, 1)
        self.gpu_metric.hide()
        self.vram_metric.hide()
        return section

    def _build_cpu_threads(self):
        section = make_section()
        box = QVBoxLayout(section)
        box.setContentsMargins(0, 10, 0, 4)
        box.setSpacing(7)
        head = QHBoxLayout()
        title = QLabel("CPU threads")
        title.setObjectName("strong")
        self.load_label = dim_label("")
        head.addWidget(title)
        head.addWidget(dim_label(f"{self.cpu_threads} logical CPUs"))
        head.addStretch()
        head.addWidget(self.load_label)
        box.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        columns = max(1, min(C.CPU_THREAD_COLUMNS, self.cpu_threads))
        self.core_meters = []
        for i in range(self.cpu_threads):
            meter = Meter(f"{i + 1:02}", lw=23, tw=30, compact=True)
            meter.setToolTip(f"Logical CPU {i}")
            self.core_meters.append(meter)
            grid.addWidget(meter, i // columns, i % columns)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        box.addLayout(grid)
        return section

    def _build_sensors(self):
        self.sensor_section = make_section()
        row = QHBoxLayout(self.sensor_section)
        row.setContentsMargins(0, 8, 0, 4)
        row.setSpacing(8)
        self.gpu_summary = QWidget()
        gpu = QHBoxLayout(self.gpu_summary)
        gpu.setContentsMargins(0, 0, 0, 0)
        gpu.setSpacing(8)
        self.gpu_name = QLabel("GPU")
        self.gpu_name.setObjectName("strong")
        self.gpu_name.setTextFormat(Qt.TextFormat.PlainText)
        self.gpu_name.setMaximumWidth(280)
        gpu.addWidget(self.gpu_name, 2)
        self.gpu_stats = {}
        for key, caption in (("Core clock", "Core"), ("Memory clock", "Memory"),
                             ("Power", "Power"), ("Fan", "GPU fan")):
            value = QLabel("—")
            value.setObjectName("strong")
            gpu.addWidget(dim_label(caption))
            gpu.addWidget(value)
            gpu.addStretch(1)
            self.gpu_stats[key] = value

        self.fans_label = dim_label("")
        self.fans_label.hide()
        row.addWidget(self.gpu_summary, 1)
        row.addWidget(self.fans_label)
        self.gpu_summary.hide()
        self.sensor_section.hide()
        return self.sensor_section

    def _build_process_panel(self):
        panel = make_section()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 8, 0, 0)
        box.setSpacing(8)
        box.addLayout(self._build_toolbar())
        box.addWidget(self._build_table(), 1)
        return panel

    def _build_gpu_page(self):
        """Раздел GPU: отдельная секция для каждой видеокарты (полосы загрузки, памяти, частот и т. д.)."""
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        self.gpu_sections = {}
        self.gpu_layout = box
        self.gpu_empty = dim_label("Waiting for GPU data…")
        box.addWidget(self.gpu_empty)
        box.addStretch()
        return page

    def _build_disks_page(self):
        self.disks_page = DisksPage(self.io)
        return self.disks_page

    def _build_fans_page(self):
        self.fans_page = FansPage(lambda text: self.status.setText(text))
        return self.fans_page

    def _build_mangohud_page(self):
        self.mango = MangoHudDialog(self, embedded=True, gpus=[])   # общий фоновый опрос GPU
        return self.mango

    def _build_reflector_page(self):
        self.reflector_page = ReflectorPage(self._report_reflector)
        self.reflector_button = self.reflector_page.button
        return self.reflector_page

    def _build_settings_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        section = make_section()
        form = QGridLayout(section)
        form.setContentsMargins(0, 16, 0, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)

        tray_box = QCheckBox("Close button hides the window to the tray")
        tray_box.setChecked(self.close_to_tray)
        tray_box.toggled.connect(self.set_close_to_tray)
        refresh = QSpinBox()
        refresh.setRange(500, 10000)
        refresh.setSingleStep(250)
        refresh.setSuffix(" ms")
        refresh.setValue(self.refresh_ms)
        refresh.valueChanged.connect(self.set_refresh_ms)

        form.addWidget(dim_label("Tray"), 0, 0)
        form.addWidget(tray_box, 0, 1)
        form.addWidget(dim_label("Update every"), 1, 0)
        form.addWidget(refresh, 1, 1, Qt.AlignmentFlag.AlignLeft)
        form.addWidget(dim_label("Colors and everything else"), 2, 0)
        form.addWidget(QLabel("Theme menu at the top right · ~/.local/share/archmon/archmon/config.py"), 2, 1)
        form.setColumnStretch(1, 1)
        outer.addWidget(section)
        outer.addStretch()
        return page

    def go_to(self, n):
        """Открыть раздел бокового меню номер n (по списку NAV_ITEMS)."""
        label, page, show_summary, _icon = NAV_ITEMS[n]
        self.nav_index = n
        self.pages.setCurrentIndex(page)
        self.summary.setVisible(show_summary)
        self.process_heading.setVisible(show_summary)
        self.page_title.setText(label)
        for i, button in self.nav_buttons:
            button.setChecked(i == n)
        if label == "Reflector":
            self.reflector_page.refresh()
        elif label == "Fans":
            self.fans_page.refresh(full=True)
        elif label == "Disks":
            self.disks_page.refresh()

    def _show_processes(self):
        """Поиск и фильтр работают в таблице: если открыт другой раздел, переходим к процессам."""
        if self.pages.currentIndex() != 0:
            self.go_to(NAV_INDEX["Processes"])

    def _build_toolbar(self):
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search  F3")
        self.search_box.textChanged.connect(lambda: self.find_match(1, include_current=True))
        self.search_box.returnPressed.connect(lambda: self.find_match(1))

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter  F4")
        self.filter_box.textChanged.connect(self.refresh_table)

        self.tree_button = QPushButton("Tree")
        self.tree_button.setCheckable(True)
        self.tree_button.setChecked(self.tree_mode)
        self.tree_button.toggled.connect(self.set_tree_mode)

        self.expand_button, self.collapse_button = QPushButton("Expand all"), QPushButton("Collapse all")
        self.expand_button.clicked.connect(self.expand_all)
        self.collapse_button.clicked.connect(self.collapse_all)

        self.apps_button = QPushButton("Apps first")
        self.apps_button.setCheckable(True)
        self.apps_button.setChecked(self.apps_first)
        self.apps_button.setToolTip("Show running applications first, system processes below")
        self.apps_button.toggled.connect(self.set_apps_first)

        details_button = QPushButton("Details")
        end_button, kill_button = QPushButton("End process"), QPushButton("Force kill")
        end_button.setObjectName("danger")
        kill_button.setObjectName("danger")
        details_button.clicked.connect(lambda: self.open_details())
        end_button.clicked.connect(lambda: self.end_process(signal.SIGTERM))
        kill_button.clicked.connect(lambda: self.end_process(signal.SIGKILL))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.process_heading = QLabel("Processes")
        self.process_heading.setObjectName("sectionTitle")
        row.addWidget(self.process_heading)
        row.addSpacing(6)
        row.addWidget(self.search_box, 3)
        row.addWidget(self.filter_box, 2)
        for button in (self.apps_button, self.tree_button, details_button, end_button, kill_button):
            row.addWidget(button)

        self.tree_tools = QWidget()
        tree_tools = QHBoxLayout(self.tree_tools)
        tree_tools.setContentsMargins(0, 0, 0, 0)
        tree_tools.addWidget(self.expand_button)
        tree_tools.addWidget(self.collapse_button)
        tree_tools.addStretch()
        self.tree_tools.setVisible(self.tree_mode)

        toolbar = QVBoxLayout()
        toolbar.setSpacing(6)
        toolbar.addLayout(row)
        toolbar.addWidget(self.tree_tools)
        return toolbar

    def _build_table(self):
        table = QTableWidget(0, len(COLUMNS))
        table.setHorizontalHeaderLabels([c.title for c in COLUMNS])
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(C.TABLE_ROW_HEIGHT)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        font = QFont()
        font.setFamilies(C.MONO_FONTS)
        font.setPointSize(C.TABLE_FONT_SIZE)
        table.setFont(font)

        header = table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self.sort_index, self._sort_order())
        header.setStretchLastSection(True)
        header.setDefaultAlignment(ALIGN_LEFT)
        for i, column in enumerate(COLUMNS):
            if column.width:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                table.setColumnWidth(i, column.width)
        header.sectionClicked.connect(self.on_header_clicked)
        table.itemSelectionChanged.connect(self.on_selection_changed)
        table.viewport().installEventFilter(self)                          # ловим колесо и клики мыши
        table.verticalScrollBar().sliderPressed.connect(self._release_lock)  # и перетаскивание ползунка
        table.itemDoubleClicked.connect(lambda item: self.open_details(int(table.item(item.row(), PID_COL).text())))
        self.table = table
        return table

    def _build_footer(self):
        """Плашки с клавишами. На них можно кликать мышью: каждая выполняет то же, что и клавиша."""
        hints = [
            ("F3", "Search", self._on_search_key, "Search in the list"),
            ("F4", "Filter", self._focus_filter, "Show only matching processes"),
            ("F5", "Tree", self.tree_button.toggle, "Tree view on/off"),
            ("Enter", "Details", self.open_details, "Details of the selected process"),
            ("F9", "End", lambda: self.end_process(signal.SIGTERM), "End the selected process"),
            ("F10", "Quit", self.quit_app, "Quit the app"),
            ("Ctrl", "Pause", self.toggle_pause, "Hold Ctrl to freeze the window, or click to pause until clicked again"),
        ]
        row = QHBoxLayout()
        row.setSpacing(14)
        self.hint_buttons = []
        for key, name, action, tip in hints:
            button = HintButton(key, name, tip)
            button.clicked.connect(lambda _checked=False, run=action: run())   # clicked передаёт лишний аргумент: отбрасываем
            self.hint_buttons.append(button)
            row.addWidget(button)
        self.pause_hint = self.hint_buttons[-1]
        self.status = dim_label("")   # сюда попадают сообщения («Sent SIGTERM…», «No match…»)
        row.addStretch()
        row.addWidget(self.status)
        return row

    def _update_hints(self):
        """Перекрасить плашки в цвета текущей темы."""
        for button in self.hint_buttons:
            button.refresh()

    def _setup_shortcuts(self):
        def bind(key, action):
            QShortcut(QKeySequence(key), self, activated=action)

        bind("F3", self._on_search_key)
        bind("Ctrl+F", self._on_search_key)
        bind("Shift+F3", lambda: self.find_match(-1))
        bind("F4", self._focus_filter)
        bind("F5", self.tree_button.toggle)
        bind("Right", lambda: self.table.hasFocus() and self._expand_selected())
        bind("Left", lambda: self.table.hasFocus() and self._collapse_selected())
        bind("Return", lambda: self.table.hasFocus() and self.open_details())
        bind("Enter", lambda: self.table.hasFocus() and self.open_details())
        bind("F9", lambda: self.end_process(signal.SIGTERM))
        bind("Delete", lambda: self.table.hasFocus() and self.end_process(signal.SIGTERM))
        bind("F10", self.quit_app)
        bind("Ctrl+Q", self.quit_app)
        bind("Esc", self._on_escape)

    # ── 3. Периодическое обновление ─────────────────────────────────────────
    def tick(self):
        if self._frozen:
            return   # Ctrl зажат: ничего не обновляем
        cpu = self.update_cpu()
        mem = self.update_system()
        self.update_disks()
        gpus = self.update_gpus()
        if self.isVisible():
            page = self.pages.currentIndex()
            if page == 0:
                self.refresh_table()   # таблица процессов самая тяжёлая часть: обновляем, только когда её видно
            elif NAV_ITEMS[self.nav_index][0] == "Fans":
                self.fans_page.refresh()
            elif NAV_ITEMS[self.nav_index][0] == "Disks":
                self.disks_page.refresh()
        if self.tray is not None:
            self._update_tray(cpu, mem, gpus)

    def update_cpu(self):
        """Шкалы потоков и сводка CPU; возвращает среднюю загрузку."""
        percents = system.cpu_percents()
        for meter, percent in zip(self.core_meters, percents):
            meter.set(percent)
        avg = sum(percents) / len(percents) if percents else 0.0
        self.cpu_metric.set(avg, f"{avg:.0f}%")
        return avg

    def update_system(self):
        """Память, нагрузка, температура процессора, вентиляторы, батарея. Возвращает % памяти."""
        mem, swap = system.memory(), system.swap()
        self.mem_metric.set(mem.percent, human_bytes(mem.used, iec=True), f"of {human_bytes(mem.total, iec=True)}")
        self.mem_metric.setToolTip(f"Swap: {human_bytes(swap.used)} / {human_bytes(swap.total)}")

        l1, l5, l15 = system.load_average()
        self.load_label.setText(f"Load average  {l1:.2f}")
        self.load_label.setToolTip(f"1 / 5 / 15 min: {l1:.2f}  {l5:.2f}  {l15:.2f}")

        temp = system.cpu_temperature()
        cpu_detail = f"{self.cpu_threads} threads"
        if temp is not None:
            cpu_detail += f" · {temp:.0f} °C"
        self.cpu_metric.set_detail(cpu_detail)

        board_fans = [f for f in read_fans() if f.rpm]
        self.fans_label.setVisible(bool(board_fans))
        if board_fans:
            self.fans_label.setText(f"Case fans  ·  up to {max(f.rpm for f in board_fans):.0f} RPM")
            self.fans_label.setToolTip("\n".join(f"{f.label}: {f.rpm:.0f} RPM" for f in board_fans))

        self.sensor_section.setVisible(not self.gpu_summary.isHidden() or bool(board_fans))

        battery = system.battery()
        self._battery_text = f"bat {battery[0]:.0f}%" + (" AC" if battery[1] else "") if battery else ""
        self._uptime_text = f"up {system.uptime_text()}"
        self._update_info()
        return mem.percent

    def update_gpus(self):
        """Сводка первой видеокарты и данные для раздела GPU. Возвращает список Gpu."""
        self.gpu_poller.request()
        self._show_gpus()
        return self.gpus

    def _receive_gpus(self, gpus):
        devices = [(g.id, g.name, g.pci) for g in gpus]
        previous = [(g.id, g.name, g.pci) for g in self.gpus]
        self.gpus = gpus
        if devices and devices != previous:
            self.mango.set_gpus(gpus)
        if not self._frozen:
            self._show_gpus()

    def _show_gpus(self):
        gpus = self.gpus
        for gpu in gpus:
            if gpu.id not in self.gpu_sections:
                section = GpuSection(f"GPU {len(self.gpu_sections)}")
                self.gpu_sections[gpu.id] = section
                self.gpu_layout.insertWidget(self.gpu_layout.count() - 1, section)
            section = self.gpu_sections[gpu.id]
            section.setToolTip("")
            section.show_gpu(gpu)
        present = {g.id for g in gpus}
        for gpu_id, section in self.gpu_sections.items():
            if gpu_id not in present:
                section.show_gpu(Gpu(gpu_id, "Data unavailable", 0, "—"))
                section.setToolTip("GPU query failed or the device is unavailable. Retrying automatically.")
        known = bool(self.gpu_sections)
        self.gpu_empty.setVisible(not known)
        self.gpu_empty.setText("No GPU data yet. Retrying automatically.")
        for index, button in self.nav_buttons:
            if index == NAV_INDEX["GPU"]:
                button.setVisible(known)
        for widget in (self.gpu_metric, self.vram_metric, self.gpu_summary):
            widget.setVisible(known)
        self.sensor_section.setVisible(known or not self.fans_label.isHidden())
        if gpus:
            g = gpus[0]
            self.gpu_name.setText(g.name)
            self.gpu_name.setToolTip(g.name)
            gpu_detail = f"Temperature  {g.temp:.0f} °C" if g.temp is not None else "GPU load"
            self.gpu_metric.set(g.util, g.util_text, gpu_detail)
            if g.vram_total and g.vram_used is not None:
                self.vram_metric.set(g.vram_used / g.vram_total * 100, human_bytes(g.vram_used, iec=True), f"of {human_bytes(g.vram_total, iec=True)}")
            else:
                self.vram_metric.set(0, "—", "unavailable")
            stats = {
                "Core clock": f"{g.core_clk:.0f} MHz" if g.core_clk is not None else "—",
                "Memory clock": f"{g.mem_clk:.0f} MHz" if g.mem_clk is not None else "—",
                "Power": (f"{g.power:.0f} / {g.power_max:.0f} W" if g.power_max else f"{g.power:.0f} W") if g.power is not None else "—",
                "Fan": f"{g.fan:.0f}%" if g.fan is not None else "—",
            }
            for key, value in stats.items():
                self.gpu_stats[key].setText(value)
        elif known:
            for metric in (self.gpu_metric, self.vram_metric):
                metric.set(0, "—", "unavailable")
            for value in self.gpu_stats.values():
                value.setText("—")

    def update_disks(self):
        """Скорости всех дисков (нужны и главной, и разделу Disks) и заполненность «/»."""
        rates = self.io.sample()
        usage = disks.root_usage()
        if usage is not None:
            self.disk_metric.set(usage.percent, human_bytes(usage.used, iec=True), f"of {human_bytes(usage.total, iec=True)}")
        # счётчики psutil включают и диски, и их разделы: берём только целые диски, чтобы не считать дважды
        whole = {d.name for d in disks.physical_disks()}
        read = sum(r.read for n, r in rates.items() if n in whole)
        write = sum(r.write for n, r in rates.items() if n in whole)
        self.disk_metric.setToolTip(f"All disks: read {rate_text(read)} · write {rate_text(write)}")

    def _update_info(self):
        self.info_label.setText(" · ".join(t for t in (self._uptime_text, self._tasks_text, self._battery_text) if t))

    def refresh_table(self):
        result = system.list_processes(self.filter_box.text())
        key = COLUMNS[self.sort_index].key
        procs = result.procs
        if self.apps_first:   # приложения выше, системные ниже (внутри групп порядок сортировки сохраняется)
            apps = [p for p in procs if classify.is_app(p)]
            others = [p for p in procs if not classify.is_app(p)]
            groups = [apps, others]
        else:
            others, groups = procs, [procs]

        self._nodes, entries, sep_at = [], [], -1
        for group in groups:
            if group and entries:
                sep_at = len(entries)   # разделитель перед второй группой
            entries += self._group_rows(group, key)
        self._node_by_pid = {n.proc.pid: n for n in self._nodes}
        if self.tree_mode and not self.filter_box.text().strip():
            self.expanded &= set(self._node_by_pid)   # забываем завершившиеся процессы

        rows = entries[:C.MAX_ROWS]
        sep_at = sep_at if 0 <= sep_at < len(rows) else -1
        display = rows[:sep_at] + [None] + rows[sep_at:] if sep_at >= 0 else rows   # None = строка-разделитель
        self._display = display
        self._tasks_text = f"{result.total} tasks · {result.running} running"
        self._update_info()

        table = self.table
        pin_offset = self._selected_offset() if self._search_lock else None   # держим строку только после поиска
        table.blockSignals(True)   # чтобы перерисовка не сбивала выбранный процесс
        table.clearSpans()
        table.setRowCount(len(display))
        selected_row = -1
        for r, entry in enumerate(display):
            if entry is None:
                self._fill_separator(r, len(others))
                continue
            for c, column in enumerate(COLUMNS):
                text = column.fmt(getattr(entry.proc, column.key))
                if column.key == "command":
                    text = entry.prefix + text + entry.suffix   # линии и стрелка дерева (вне дерева пусто)
                item = QTableWidgetItem(text)
                item.setTextAlignment(ALIGN_RIGHT if column.numeric else ALIGN_LEFT)
                color = self._cell_color(column.key, entry.proc)
                if color:
                    item.setForeground(QColor(color))
                table.setItem(r, c, item)
            if (entry.proc.pid, entry.proc.started) == (self.selected_pid, self.selected_started):
                selected_row = r
        self._sep_row = sep_at
        if selected_row >= 0:
            table.selectRow(selected_row)
            if pin_offset is not None:   # строка была на экране: оставляем её на том же месте, куда бы она ни переехала
                table.doItemsLayout()
                table.verticalScrollBar().setValue(max(0, selected_row * C.TABLE_ROW_HEIGHT - pin_offset))
                table.scrollToItem(table.item(selected_row, PID_COL))   # страховка: строка точно видна
        else:
            table.clearSelection()
            self.selected_pid = self.selected_started = None
        table.blockSignals(False)

    def _group_rows(self, group, key):
        """Строки одной группы процессов: плоским списком или деревом со свёрнутыми ветками."""
        if not self.tree_mode:
            return [Row(p) for p in sorted(group, key=attrgetter(key), reverse=self.sort_desc)]
        nodes = tree_nodes(group, key, self.sort_desc)
        self._nodes += nodes
        show_all = bool(self.filter_box.text().strip())   # при фильтре раскрываем всё, чтобы найденное было видно
        rows = []
        for node in visible_nodes(nodes, self.expanded, show_all):
            if not node.has_children:
                rows.append(Row(node.proc, node.prefix + "  ", "", node))
            elif show_all or node.proc.pid in self.expanded:
                rows.append(Row(node.proc, node.prefix + "\u25be ", "", node))               # ▾ раскрыто
            else:
                rows.append(Row(node.proc, node.prefix + "\u25b8 ", f"  (+{node.descendants})", node))   # ▸ свёрнуто
        return rows

    def _fill_separator(self, row, count):
        """Строка-разделитель между приложениями и системными процессами (не выделяется)."""
        for c in range(1, len(COLUMNS)):
            self.table.takeItem(row, c)   # убираем остатки прошлой перерисовки
        item = QTableWidgetItem(f"System processes  ({count})")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor(T.dim))
        item.setTextAlignment(ALIGN_LEFT)
        self.table.setItem(row, 0, item)
        self.table.setSpan(row, 0, 1, len(COLUMNS))

    def _row_of_pid(self, pid):
        """Номер строки таблицы с этим PID или -1."""
        if pid is None:
            return -1
        return next((r for r in range(self.table.rowCount())
                     if r != self._sep_row and self.table.item(r, PID_COL).text() == str(pid)), -1)

    def _selected_offset(self):
        """Отступ выделенной строки от верха видимой области, px; None, если её сейчас не видно."""
        row = self._row_of_pid(self.selected_pid)
        if row < 0:
            return None
        rect = self.table.visualItemRect(self.table.item(row, PID_COL))
        return rect.top() if rect.top() >= 0 and rect.bottom() <= self.table.viewport().height() else None

    @staticmethod
    def _cell_color(key, proc):
        """Цвет текста ячейки или None (обычный). Здесь правила подсветки таблицы."""
        if key == "user" and proc.user == "root":
            return T.amber
        if key == "cpu":
            if proc.cpu >= C.CPU_RED_AT:
                return T.red
            if proc.cpu >= C.CPU_AMBER_AT:
                return T.amber
        if key == "command":
            return T.accent if proc.user == "root" else T.text
        return None

    # ── 4a. Темы, трей, режимы ──────────────────────────────────────────────
    def _apply_style(self):
        QApplication.instance().setStyleSheet(build_qss())

    def apply_theme(self, name):
        set_theme(name)
        self.settings.setValue("ui_theme", T.name)
        self._apply_style()
        self._update_hints()
        self.logo.setPixmap(logo_pixmap())
        for _i, button in self.nav_buttons:
            button.refresh()
        for meter in self.findChildren(Meter):
            meter.update()
        self.refresh_table()

    def set_tree_mode(self, on):
        self.tree_mode = on
        self.settings.setValue("tree", on)
        self.tree_tools.setVisible(on)
        self.refresh_table()

    # ── Раскрытие и сворачивание веток дерева ───────────────────────────────
    def toggle_node(self, pid):
        node = self._node_by_pid.get(pid)
        if node is None or not node.has_children:
            return
        if pid in self.expanded:
            self.expanded.discard(pid)
        else:
            self.expanded.add(pid)
        self.refresh_table()

    def expand_all(self):
        self.expanded = {n.proc.pid for n in self._nodes if n.has_children}
        self.refresh_table()

    def collapse_all(self):
        self.expanded.clear()
        self.refresh_table()

    def _expand_selected(self):
        """Клавиша →: раскрыть выбранную ветку."""
        node = self._node_by_pid.get(self.selected_pid)
        if self.tree_mode and node is not None and node.has_children and self.selected_pid not in self.expanded:
            self.expanded.add(self.selected_pid)
            self.refresh_table()

    def _collapse_selected(self):
        """Клавиша ←: свернуть выбранную ветку, а если она уже свёрнута, перейти к родителю."""
        node = self._node_by_pid.get(self.selected_pid)
        if not self.tree_mode or node is None:
            return
        if self.selected_pid in self.expanded:
            self.expanded.discard(self.selected_pid)
            self.refresh_table()
        elif node.parent_pid is not None:
            self.selected_pid = node.parent_pid
            self.refresh_table()
            self._select_row_of(self.selected_pid)

    def _select_row_of(self, pid):
        """Выделить строку с этим PID и прокрутить к ней (выделение делает программа, а не ты)."""
        row = self._row_of_pid(pid)
        if row < 0:
            return False
        self._programmatic = True
        self.table.selectRow(row)
        self._programmatic = False
        self.table.scrollToItem(self.table.item(row, PID_COL))
        return True

    def _arrow_row(self, event):
        """Номер строки, если клик попал точно в стрелку ветки (▸ или ▾), иначе -1."""
        pos, table = event.position().toPoint(), self.table
        row, col = table.rowAt(pos.y()), table.columnAt(pos.x())
        if row < 0 or col != CMD_COL or row >= len(self._display):
            return -1
        entry = self._display[row]
        if entry is None or entry.node is None or not entry.node.has_children:
            return -1
        metrics = table.fontMetrics()
        x = pos.x() - table.columnViewportPosition(col) - CELL_PADDING   # от начала текста в ячейке
        reach = metrics.horizontalAdvance(entry.prefix)                  # конец стрелки
        return row if reach - metrics.horizontalAdvance("\u25b8 ") - 3 <= x <= reach + 3 else -1

    def set_apps_first(self, on):
        self.apps_first = on
        self.settings.setValue("apps_first", on)
        self.refresh_table()

    def set_close_to_tray(self, on):
        self.close_to_tray = on
        self.settings.setValue("close_to_tray", on)

    def set_refresh_ms(self, ms):
        self.refresh_ms = ms
        self.settings.setValue("refresh_ms", ms)
        self.timer.setInterval(ms)

    def _update_side_reflector(self):
        info = reflector.mirror_info()
        self.side_reflector.setText(f"Reflector · {info.servers} mirrors" if info else "")

    def _update_tray(self, cpu, mem, gpus):
        levels = [cpu, mem, max((g.util for g in gpus), default=0.0)]
        lines = [C.APP_NAME, f"CPU {cpu:.0f}%   Mem {mem:.0f}%"]
        for n, g in enumerate(gpus):
            temp = f"   {g.temp:.0f}\u00b0C" if g.temp is not None else ""
            lines.append(f"GPU {n}: {g.util_text}{temp}")
        self.tray.set_status(levels, "\n".join(lines))

    def show_window(self):
        """Показать окно поверх остальных (из трея, при повторном запуске)."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show_window()

    def quit_app(self):
        self._quitting = True
        QApplication.quit()

    def closeEvent(self, event):
        """Крестик окна прячет программу в трей; полностью закрывают F10, Ctrl+Q или меню трея."""
        if self.tray is not None and self.close_to_tray and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(C.APP_NAME, "Still running in the tray. Quit with F10 or the tray menu.",
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
        else:
            self.gpu_poller.shutdown()
            event.accept()

    # ── 4b. Действия пользователя ───────────────────────────────────────────
    def _sort_order(self):
        return Qt.SortOrder.DescendingOrder if self.sort_desc else Qt.SortOrder.AscendingOrder

    def on_header_clicked(self, index):
        if index == self.sort_index:
            self.sort_desc = not self.sort_desc             # повторный клик: развернуть порядок
        else:
            self.sort_index = index
            self.sort_desc = COLUMNS[index].numeric         # числа сначала по убыванию, текст по алфавиту
        self.table.horizontalHeader().setSortIndicator(index, self._sort_order())
        self.refresh_table()

    def on_selection_changed(self):
        if not self._programmatic:
            self._search_lock = False   # выбрала сама (мышью или стрелками): держать строку больше не нужно
        rows = self.table.selectionModel().selectedRows()
        self.selected_pid = self.selected_started = None
        if rows and rows[0].row() < len(self._display):
            entry = self._display[rows[0].row()]
            if entry is not None:
                self.selected_pid = entry.proc.pid
                self.selected_started = entry.proc.started

    def _release_lock(self):
        self._search_lock = False

    def eventFilter(self, obj, event):
        """Колесо или клик мыши по таблице снимают «магнит» поиска: дальше листаешь свободно."""
        if obj is self.table.viewport():
            kind = event.type()
            if kind in (QEvent.Type.Wheel, QEvent.Type.MouseButtonPress):
                self._search_lock = False
            if self.tree_mode and kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick) \
                    and event.button() == Qt.MouseButton.LeftButton:
                row = self._arrow_row(event)
                if kind == QEvent.Type.MouseButtonDblClick and row >= 0:
                    self._skip_release = True   # двойной клик по стрелке не открывает сведения
                    return True
                if kind == QEvent.Type.MouseButtonRelease:
                    if self._skip_release:
                        self._skip_release = False
                    elif row >= 0:
                        self.toggle_node(self._display[row].proc.pid)
        return super().eventFilter(obj, event)

    def open_details(self, pid=None):
        pid = pid if pid is not None else self.selected_pid
        if pid is None:
            self.status.setText("Select a process first.")
            return
        ProcessDialog(pid, self).show()

    def _report_reflector(self, text):
        """Сообщения кнопки Reflector: в строку статуса, а если окно спрятано в трей, ещё и уведомлением."""
        self.status.setText(text)
        if not text.endswith("…"):
            self._update_side_reflector()
            if self.tray is not None and not self.isVisible():
                self.tray.showMessage(C.APP_NAME, text, QSystemTrayIcon.MessageIcon.Information, 5000)

    def open_mangohud(self):
        self.go_to(NAV_INDEX["MangoHud"])

    def end_process(self, sig):
        rows = self.table.selectionModel().selectedRows()
        entry = self._display[rows[0].row()] if rows and rows[0].row() < len(self._display) else None
        if (entry is None or self.selected_pid is None
                or (entry.proc.pid, entry.proc.started) != (self.selected_pid, self.selected_started)):
            self.status.setText("Select a process first.")
            return
        self.status.setText(system.send_signal(self.selected_pid, sig, self.selected_started))

    def find_match(self, step=1, include_current=False):
        """Выделить следующую (step=1) или предыдущую (step=-1) строку, подходящую под поиск.

        include_current=True: начать с текущей строки (нужно при наборе текста).
        """
        query = self.search_box.text().lower().strip()
        table = self.table
        count = table.rowCount()
        if not query:
            self._search_lock = False
        if not query or not count:
            return
        current = self._row_of_pid(self.selected_pid)
        if current < 0:
            start = 0 if step > 0 else count - 1
        else:
            start = current if include_current else current + step
        for k in range(count):
            r = (start + step * k) % count
            if r == self._sep_row:
                continue
            text = " ".join(table.item(r, c).text() for c in SEARCH_COLS).lower()
            if query in text:
                self._programmatic = True
                table.selectRow(r)
                self._programmatic = False
                table.scrollToItem(table.item(r, PID_COL))
                self._search_lock = True   # держим найденную строку на месте, пока не начнёшь листать сама
                self.status.setText("")
                return
        if self.tree_mode and (not include_current or len(query) >= 3) and self._reveal_hidden_match(query):
            return
        self.status.setText(f'No match for "{query}".')

    def _reveal_hidden_match(self, query):
        """Поиск по свёрнутым веткам: раскрывает родителей найденного процесса и выделяет его."""
        for node in self._nodes:
            proc = node.proc
            if self._row_of_pid(proc.pid) >= 0:
                continue   # эта строка и так видна: по ней уже искали
            if query in " ".join(str(getattr(proc, k)) for k in C.SEARCH_KEYS).lower():
                parent = node.parent_pid
                while parent is not None:
                    self.expanded.add(parent)
                    parent = getattr(self._node_by_pid.get(parent), "parent_pid", None)
                self.selected_pid = proc.pid
                self.refresh_table()
                if self._select_row_of(proc.pid):
                    self._search_lock = True
                    self.status.setText("")
                    return True
        return False

    def _on_search_key(self):
        """F3: из таблицы переходит в поиск, внутри поиска ищет следующее."""
        self._show_processes()
        if self.search_box.hasFocus():
            self.find_match(1)
        else:
            self.search_box.setFocus()
            self.search_box.selectAll()

    def _poll_freeze(self):
        """Окно замирает, пока зажат Ctrl (как в диспетчере задач Windows) или включена ручная пауза."""
        held = self.isActiveWindow() and bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        frozen = held or self._paused
        if frozen == self._frozen:
            return
        self._frozen = frozen
        if frozen:
            self.status.setText("Paused: click Pause to resume" if self._paused else "Paused: release Ctrl to resume")
        else:
            self.status.setText("")
            self.tick()   # сразу догоняем, не дожидаясь следующего интервала

    def toggle_pause(self):
        """Ручная пауза: обновление стоит, пока не нажмёшь ещё раз."""
        self._paused = not self._paused
        self.pause_hint.set_active(self._paused)
        self._poll_freeze()

    def _focus_filter(self):
        self._show_processes()
        self.filter_box.setFocus()
        self.filter_box.selectAll()

    def _on_escape(self):
        for box in (self.search_box, self.filter_box):
            if box.hasFocus():
                box.clear()
        self.table.setFocus()
