# Аудит референсов и Podkop
Дата: 11 октября 2026. Этап 1 завершён по указанным ниже снимкам исходников. Проверок на целевом роутере не проводилось. Результат локальный; новые коммиты не создавались и не публиковались.


## Исследованные версии

| Проект | Commit | Роль |
|---|---|---|
| kostenkodm/hass_openwrt_reboot | `6cfe0f15143fad2cef6107d9bc3cb4635a959fc3` | Референс HA, исходный проект не изменён |
| itdoginfo/podkop | `da8bd40983aaab4d29614d38c8d6214d0a217e3e` | UCI, генерация sing-box, применение и маршрутизация |
| FUjr/homeassistant-openwrt-ubus | `adaebdf2d44cda7195638dbf70f8ae43b774dd6f` | Асинхронный ubus-клиент и общие данные |

Первоначальный аудит относится к main. Затем пользователь подтвердил Podkop 0.7.23 и sing-box 1.12.17; отдельно исследован tag 0.7.23 (c2ce4c32c72169272f1149961e9663755c8d4c9c). [Проверка установленной версии](podkop-0.7.23-audit.ru.md) подтверждает ключевые выводы о lifecycle. Ссылки ниже сохраняют исходный снимок main.

## 1. HA-референс kostenkodm

Полезны структура custom_components, Config Flow, русская и английская локализации, регистрация устройств, async_forward_entry_setups и async_unload_platforms.

Проверенные проблемы:
- [button.py](https://github.com/kostenkodm/hass_openwrt_reboot/blob/6cfe0f15143fad2cef6107d9bc3cb4635a959fc3/custom_components/openwrt_reboot/button.py) выполняет синхронные Paramiko connect/exec_command непосредственно из async-функции. Это блокирует event loop. AutoAddPolicy принимает неизвестный ключ сервера; код не проверяет exit status и сообщает об успехе сразу после отправки.
- [config_flow.py](https://github.com/kostenkodm/hass_openwrt_reboot/blob/6cfe0f15143fad2cef6107d9bc3cb4635a959fc3/custom_components/openwrt_reboot/config_flow.py) хранит выбранный auth_method в экземпляре flow, но не добавляет его в данные entry. button.py читает его из entry; путь приватного ключа получается несогласованным.
- [manifest.json](https://github.com/kostenkodm/hass_openwrt_reboot/blob/6cfe0f15143fad2cef6107d9bc3cb4635a959fc3/custom_components/openwrt_reboot/manifest.json) объявляет asyncssh и zeroconf, тогда как button.py импортирует paramiko. iot_class local_push не подтверждён реализацией push-обмена.
- Нет проверки соединения в flow, Options Flow, общего координатора, типизированных ошибок и подтверждённого состояния выполнения команды.

Новую интеграцию реализовать отдельно, с доменом openwrt_vpn_manager. Полномочия reboot/Wi-Fi/DNS и SSH-кнопки не переносить. Исходный репозиторий остаётся неизменным.

## 2. FUjr

Подробные результаты по файлам и функциям приведены в [дополнении](transport-ubus-addendum.md#2-проверенный-референс).

Переиспользовать решения: общий aiohttp-клиент, reconnect lock, общий менеджер данных на config entry, кеширование и координаторы. Собственная реализация должна исправить сопоставление batch по позициям вместо id, знак запаса перед истечением сессии, смешение HTTP-ошибки с успешным пустым ответом, логирование токенов и небезопасные повторы мутаций.

uci_get повторно разбирает уже снятую JSON-RPC-оболочку; uci_set_commit не является транзакцией и позволяет последующий restart произвольных служб. HA-сервисы выбирают первый менеджер роутера. Эти механизмы не переносить.

TLS verification и HTTPS в референсе отключены по умолчанию; ACL из README шире требуемой. В новом проекте HTTPS обязателен, проверка имени и CA обязательна, а права HA ограничиваются объектом vpn.controller. Не наследовать полный доступ UCI, file.exec, rc.init, network.interface.*.

## 3. UCI-модель Podkop

[Конфигурация](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/etc/config/podkop) содержит отдельные settings и section. Управлять только section с connection_type=vpn. Внутри Podkop разрешена запись только option interface выбранных VPN-секций; настройки контроллера хранятся отдельно. proxy, block, exclusion, общие настройки и source_network_interfaces сохраняются.

[configure_outbound_handler](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/usr/bin/podkop#L749) передаёт interface в sing_box_cm_add_interface_outbound. [Генератор](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/usr/lib/sing_box_config_manager.sh#L914) создаёт outbound type=direct с bind_interface. Здесь direct обозначает исходящий сокет через указанный VPN-интерфейс; это само по себе не означает прямой WAN.

[helpers.sh](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/usr/lib/helpers.sh#L93) формирует tag как section-out. [LuCI](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/luci-app-podkop/htdocs/luci-static/resources/view/podkop/section.js#L270) выбирает DeviceSelect, не логическое имя сети. Контроллеру нужны раздельные поля network_id и device_name; совпадение имён не предполагать. Метаданные netifd сопоставлять с устройствами, кандидатами считать обнаруженные и явно разрешённые пользователем исходящие VPN. inbound_vpn исключается безусловно.

Названные UCI-секции адресуются по действительному id. Переименование не считать автоматически безопасным переносом политики: исчезнувший id помечается отсутствующим, новый обнаруживается без автоматического разрешения записи. Анонимные секции не адресовать через изменяемый порядковый индекс; до решения устойчивой идентификации показывать только в наблюдении.

## 4. Применение имеет существенные побочные эффекты

[init.d/podkop](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/etc/init.d/podkop#L30) вызывает /usr/bin/podkop reload. В [основном скрипте](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/usr/bin/podkop#L144):
- reload выполняет stop_main, затем start_main;
- stop_main удаляет таблицу nftables Podkop, ip rule/route и останавливает sing-box;
- start_main создаёт правила заново, вызывает sing_box_configure_service, генерирует JSON и запускает sing-box;
- start/stop, используемые restart, дополнительно вызывают настройку/восстановление DHCP/DNS при dont_touch_dhcp=0;
- sing_box_configure_service может записывать UCI sing-box, изменяя enabled/user/conffile;
- start_main также выполняет настройку времени и может менять bridge netfilter sysctl.

Это не узкая операция смены interface. Между удалением и восстановлением перехвата требуется доказать отсутствие обхода VPN. Утечка в конкретной конфигурации не воспроизведена: вывод о риске основан на порядке операций, а не на испытании целевом роутере.

[sing_box_save_config](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/usr/bin/podkop#L1292) генерирует временный JSON, выполняет sing-box check и заменяет файл. Проверка происходит после stop_main при reload: ошибка генерации может оставить остановленный runtime. Готовой транзакции UCI+runtime и отката в исследованном пути нет.

config.change trigger запускает restart. Не использовать uci.apply/reload_config вслепую: это может запустить широкий lifecycle через триггеры. Штатный reload не объявляется подходящим по одному названию.

## 5. Проверки и fail-closed

В [sing_box_configure_route](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/usr/bin/podkop#L830) существуют общий direct outbound/final и исключающие правила. Они нужны обычному трафику Podkop, поэтому запретить весь WAN или считать все direct-outbound утечкой неправильно. Требование fail-closed относится к трафику, выбранному управляемой VPN-секцией.

[check_proxy](https://github.com/itdoginfo/podkop/blob/da8bd40983aaab4d29614d38c8d6214d0a217e3e/podkop/files/usr/bin/podkop#L1671) получает внешний IP без аргумента конкретной секции. Специальный диагностический домен маршрутизируется через первый outbound. Такой тест не доказывает выход каждой секции.

clash_api get_proxy_latency принимает конкретный tag, но даёт лишь задержку HTTP-теста. set_group_proxy работает с существующими selector-группами; VPN-секция генерируется как direct с bind_interface, поэтому этим API нельзя просто сменить её интерфейс. Перевод VPN-секций в proxy-selector изменил бы модель ТЗ и не выбран.

mixed_proxy может направлять тесты в section-out, но его включение меняет дополнительные параметры Podkop, а listen address обычно LAN. Без отдельного решения не включать скрытые прокси для диагностики.

get_status отражает boot enable, а get_sing_box_status использует pgrep; это вспомогательные сигналы, не доказательство рабочего data plane. Проверять процесс, активный config/tag и трафик.

Два отдельных результата:
1. VPN probe: HTTP/HTTPS/TCP/ICMP с жёсткой привязкой к device, без fallback; внешний IP с известным уровнем достоверности. DNS имеет собственный путь и проверяется отдельно.
2. Section probe: трафик через фактические правила конкретной секции, с подтверждением выбранного outbound/выхода. Одного bind_interface в JSON недостаточно.

До испытаний с внешним контрольным узлом, WAN packet capture, TCP/UDP, IPv4/IPv6, остановкой VPN/sing-box и reload публиковать fail_closed_verified=false. Не обещать исправить утечки одним rollback.

## 6. Предложение по реализации

Локальный daemon под procd публикует ограниченный объект vpn.controller, использует rpcd session/ACL через uhttpd. Предпочтительный runtime — ucode с ubus/uloop/uci: он подходит OpenWrt и не требует Python на роутере. Поддержка регистрации ubus и запуска процессов подтверждена документацией ucode; наличие пакетов и точные API целевого SDK требуют сборочного прототипа. Это проектное решение, не готовый пакет.

HA — асинхронный Python-клиент HTTPS, DataUpdateCoordinator, ConfigEntry.runtime_data, Config Flow/Options Flow, стабильные идентификаторы controller_id/section_id/vpn_id, все сущности из полного ТЗ. Автоматика и журнал живут на роутере.

Первый работающий этап контроллера: наблюдение, discovery, probes, политики, история и расчёт предлагаемого назначения. Запись в рабочую сеть не выполнять до решения двух задач: безопасного Podkop apply и доказанного fail-closed. Эти возможности показывать как неподдержанные, а не возвращать фиктивный успех.

Для записи исследовать версионированное расширение штатного Podkop: dry-render/validate до остановки, apply только runtime конфигурации без удаления перехвата и изменения DNS/DHCP, локальный rollback. Это требуемая разработка; в исследованном CLI такого API нет. Сгенерированный config.json контроллер вручную не редактирует. Если необходим traffic guard, подготовить отдельный проект и тесты; изменение рабочего firewall требует отдельного разрешения по ТЗ.

## 7. Следующие проверки

- На локальном Linux/OpenWrt стенде воспроизвести полный жизненный цикл и перехват Podkop, включая трафик источника inbound_vpn и административный доступ.
- Создать runtime-прототип ucode, проверить отрицательные ACL и запрет инъекций. Linux-стенд пока не запущен; наличие wsl.exe не подтверждает наличие установленного дистрибутива.
- Уточнить UCI concurrency: наш lock не блокирует LuCI. Нужны независимый cursor/staging, контроль всей конфигурации перед записью и применение/откат только собственных полей с обнаружением внешних изменений.
- Принять модель API/состояний из [проекта архитектуры](architecture.ru.md), затем перейти к коду и тестам.

## Источники платформенных API

- [ucode ubus](https://ucode-lang.org/module-ubus.connection.html) и [uloop](https://ucode-lang.org/module-uloop.html).
- [uhttpd проверяет session.access](https://lxr.openwrt.org/source/uhttpd/ubus.c).
- [HA: получение данных и координатор](https://developers.home-assistant.io/docs/integration_fetching_data/).
- [HA: ConfigEntry.runtime_data](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data/).
- [sing-box: bind_interface](https://sing-box.sagernet.org/configuration/shared/dial/).

Код из MIT/GPL-референсов не копировался в реализацию. Лицензирование возможных производных изменений Podkop (GPL-2.0-or-later) и FUjr (GPL-3.0) учитывается отдельно при появлении такого кода.
