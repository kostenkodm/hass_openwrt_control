# Уточнение аудита: установленная версия Podkop 0.7.23
Дата: 11 октября 2026.

Пользователь подтвердил podkop-0.7.23-r1 и sing-box-1.12.17-r1. Дополнительно исследован upstream tag [0.7.23](https://github.com/itdoginfo/podkop/releases/tag/0.7.23), commit `c2ce4c32c72169272f1149961e9663755c8d4c9c`. Это уточняет [аудит main](reference-audit.ru.md), не подменяя проверку установленного пакета на устройстве.

## Подтверждённые свойства релиза

1. [reload](https://github.com/itdoginfo/podkop/blob/c2ce4c32c72169272f1149961e9663755c8d4c9c/podkop/files/usr/bin/podkop#L204) вызывает stop_main и start_main. stop_main удаляет nft-таблицу Podkop, его ip rule/route и останавливает sing-box. Значит, выявленный риск прерывания перехвата относится также к этому релизу. Отсутствие утечек на целевом роутере не проверено.
2. start/stop, используемые restart, затрагивают DHCP/DNS при dont_touch_dhcp=0; start_main может менять UCI sing-box. Релиз не содержит публичного узкого API только для смены bind_interface без этих lifecycle-эффектов.
3. [sing_box_save_config](https://github.com/itdoginfo/podkop/blob/c2ce4c32c72169272f1149961e9663755c8d4c9c/podkop/files/usr/bin/podkop#L1274) проверяет временный JSON перед заменой файла, но при reload эта стадия идёт после остановки runtime. Готового транзакционного rollback нет.
4. [VPN outbound](https://github.com/itdoginfo/podkop/blob/c2ce4c32c72169272f1149961e9663755c8d4c9c/podkop/files/usr/lib/sing_box_config_manager.sh#L914) — type=direct с bind_interface из option interface; tag формируется как section-out. Контроллер должен управлять только действительными VPN-секциями и проверять соответствие kernel device.
5. [check_proxy](https://github.com/itdoginfo/podkop/blob/c2ce4c32c72169272f1149961e9663755c8d4c9c/podkop/files/usr/bin/podkop#L1653) не принимает идентификатор секции. Эта проверка не заменяет независимые испытания трафика каждой секции.
6. [constants.sh](https://github.com/itdoginfo/podkop/blob/c2ce4c32c72169272f1149961e9663755c8d4c9c/podkop/files/usr/lib/constants.sh#L27) задаёт SB_REQUIRED_VERSION=1.12.0. Подтверждённый sing-box 1.12.17 выше этого минимума. Это проверка порога Podkop, а не утверждение полной совместимости будущего контроллера.

## Сравнение с исходным снимком main

Изначальный снимок main: `da8bd40983aaab4d29614d38c8d6214d0a217e3e`.

| Файл | Сравнение SHA-256 |
|---|---|
| etc/init.d/podkop | Совпадает |
| usr/lib/helpers.sh | Совпадает |
| usr/bin/podkop | Отличается; критические lifecycle-функции прочитаны отдельно |
| usr/lib/sing_box_config_manager.sh | Отличается; создание interface-outbound проверено отдельно |
| usr/lib/constants.sh | Отличается; минимальная версия sing-box проверена отдельно |

Полное совпадение main с релизом не предполагается. Код адаптера и фикстуры базировать на 0.7.23; совместимость с другими версиями объявлять после тестов.

## Решение

Предлагаемая архитектура сохраняется. Первым этапом идёт локальная реализация наблюдения, probes, политик и HA-клиента. Автоматическое применение требует подтверждённого безопасного Podkop adapter и fail-closed data plane. Простую последовательность uci commit → podkop reload как завершённое решение не использовать.

Проверка выполнялась только на локальной копии исходников. Код пакетов на целевом роутере, firewall и службы не изменялись. Никакие новые коммиты не создавались и не публиковались.
