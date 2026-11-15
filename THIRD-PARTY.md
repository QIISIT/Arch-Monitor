# Сторонние компоненты Arch Monitor

[LICENSE.md](LICENSE.md) относится к собственному коду Arch Monitor.
Лицензии зависимостей сохраняют силу. Установщик содержит исходники приложения,
тесты и документацию; зависимости он устанавливает отдельными пакетами Arch Linux.

| Компонент | Лицензирование | Источник |
|---|---|---|
| PyQt6 | GNU GPL v3 либо Riverbank Commercial License; варианта LGPL нет | [Riverbank](https://www.riverbankcomputing.com/software), [License FAQ](https://riverbankcomputing.com/commercial/license-faq) |
| Qt 6: Core, Gui, Widgets, Network; Qt SVG | LGPL v3, альтернативные GPL либо коммерческие условия соответствующего модуля | [Qt Licensing](https://doc.qt.io/qt-6/licensing.html), [Qt SVG](https://doc.qt.io/qt-6/qtsvg-index.html) |
| psutil | BSD 3-Clause | [Текст лицензии psutil](https://github.com/giampaolo/psutil/blob/master/LICENSE) |

## Совместимость перед релизом

PolyForm Noncommercial ограничивает коммерческое использование и не является
GPL-совместимой лицензией. По [официальному FAQ Riverbank, вопросы 1 и 11](https://riverbankcomputing.com/commercial/license-faq),
распространение приложения под GPL-несовместимой лицензией требует коммерческой
лицензии PyQt. Использование уже установленного системного PyQt само по себе
не отменяет это требование; для такого варианта Riverbank также указывает условия
по версии PyQt и её проверке при запуске.

До выпуска Arch Monitor под PolyForm нужно выбрать подходящий вариант:
перейти на подходящие LGPL-модули PySide6/Qt, выполнить условия коммерческой
лицензии PyQt либо использовать для приложения GPL-совместимую лицензию.
Текущая публикация исходников не означает, что этот вопрос уже решён.

MangoHud, Reflector, драйверы и системные утилиты в установщик не включаются.
Они вызываются как внешние программы и распространяются отдельно на своих условиях.
Шрифты AutoQ не копируются: приложение использует системные шрифты.
