# Сторонние компоненты Arch Monitor

[LICENSE.md](LICENSE.md) (GNU GPL v3.0, GPL-3.0-only) относится к собственному коду Arch Monitor.
Лицензии зависимостей сохраняют силу. Установщик содержит исходники приложения,
тесты и документацию; зависимости он устанавливает отдельными пакетами Arch Linux.

| Компонент | Лицензирование | Источник |
|---|---|---|
| PyQt6 | GNU GPL v3 либо Riverbank Commercial License; варианта LGPL нет | [Riverbank](https://www.riverbankcomputing.com/software), [License FAQ](https://riverbankcomputing.com/commercial/license-faq) |
| Qt 6: Core, Gui, Widgets, Network; Qt SVG | LGPL v3, альтернативные GPL либо коммерческие условия соответствующего модуля | [Qt Licensing](https://doc.qt.io/qt-6/licensing.html), [Qt SVG](https://doc.qt.io/qt-6/qtsvg-index.html) |
| psutil | BSD 3-Clause | [Текст лицензии psutil](https://github.com/giampaolo/psutil/blob/master/LICENSE) |

Приложение использует GPL-версию PyQt6. Лицензия GNU GPL v3.0 выбрана для
Arch Monitor с учётом этой зависимости; переход на другую библиотеку интерфейса
не требуется. Условия GPL/LGPL и уведомления сторонних компонентов сохраняют силу.

MangoHud, Reflector, драйверы и системные утилиты в установщик не включаются.
Они вызываются как внешние программы и распространяются отдельно на своих условиях.
Шрифты AutoQ не копируются: приложение использует системные шрифты.
