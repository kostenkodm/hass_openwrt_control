# Нативный контроллер Podkop 0.7.23

Экспериментальный пакет `hass-openwrt-vpn-controller` версии 0.2.0.

- `files/usr/sbin/vpn-controller.uc` — ограниченный объект ubus `vpn.controller`, очередь запросов, отдельный автономный worker.
- `files/usr/share/vpn-controller/core.uc` — независимые политики секций, Manual/Auto, приоритет/качество, удержание, история и дедупликация.
- `files/usr/share/vpn-controller/platform.uc` — настоящее UCI, привязанные HTTPS-пробы, применение и откат.
- `files/usr/libexec/vpn-controller-podkop-render` — адаптер штатного генератора. Не выполняет `podkop reload`, не изменяет nft или rule sets.
- `src/io.c` — атомарная запись, fsync и запуск фиксированных argv с ограничением времени; в RPC не экспортируется.
- `rpcd-acl` — права только на ограниченные методы контроллера.
- `Makefile` — пакет для SDK OpenWrt. Никаких postinst, которые включают управление или меняют сеть.

Установка HACS доставляет только интеграцию HA. Контроллер устанавливается на OpenWrt отдельно после проверки пакета. [Инструкция, ограничения и приёмка](../docs/podkop-controller.ru.md).
