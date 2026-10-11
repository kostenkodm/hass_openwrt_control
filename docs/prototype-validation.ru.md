# Проверка прототипа 0.1.0

Дата: 11 октября 2026. Локальный WSL Ubuntu-26.04, x86_64.

Результат: **70 теста прошли**, ошибок и провалов нет. Ruff check прошёл.

Python: 3.14.4.

| Компонент | Версия |
|---|---|
| homeassistant | 2026.10.1 |
| aiohttp | 3.14.4 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |
| cryptography | 50.0.1 |
| ruff | 0.17.0 |

| Набор тестов | Количество |
|---|---|
| test_api | 19 |
| test_demo | 5 |
| test_engine | 25 |
| test_homeassistant | 11 |
| test_packaging | 1 |
| test_protocol_errors | 9 |


Сквозные HA-тесты используют настоящий Core, Config Flow, Options Flow, реестры, сервисы и пять платформ; Home Assistant не подменяется моками. Сервер — настоящий локальный HTTPS с тестовым CA.

Проверены встроенный демонстрационный Config Flow без ввода реквизитов, сценарии через Options Flow, verified loopback TLS, сохранение политик при reload, закрытие listener при unload, изолированный запуск HACS-каталога без tools/simulator и 52 сущности для трёх секций и трёх VPN, независимость двух контроллеров, добавление/удаление ресурсов, команды и их последовательность, настройки, потеря/восстановление связи, редактирование политик, исключение секретов из диагностики, сохранение курсора после reload.

Проверены модель отказов, ручные политики, наблюдение, групповые переключения, откат/конфликт/рестарт, гистерезис, сохранение последнего назначения, запрет inbound_vpn, строгий TLS (CA и hostname), отказы generic RPC, отсутствие автоматического повтора записи, неизвестный исход, ошибки HTTP/JSON-RPC, redirects и ограничение размера ответа.

Отдельно выполнена демонстрация шести сценариев через HTTPS RPC: outputs/prototype/demo.html и demo.json.

Это подтверждает локальную модель и HA-интеграцию. Загрузка опубликованного репозитория самим HACS и установка в HAOS пользователя не выполнялись. Официальный валидатор HACS запускается отдельно после публикации; актуальный результат доступен в [GitHub Actions](https://github.com/kostenkodm/hass_openwrt_control/actions/workflows/validate.yaml). Этот документ описывает локальный прогон, а не результат HACS. Встроенная демонстрация останавливается вместе с HA; автономность production-контроллера остаётся отдельным требованием. Реальный OpenWrt/Podkop, egress, отсутствие утечек IPv4/IPv6, фактическая защита inbound_vpn, rpcd ACL на устройстве и отказоустойчивость flash не испытаны. Нативный OpenWrt-контроллер ещё не реализован.

Первичные API-референсы: [Config Flow](https://developers.home-assistant.io/docs/core/integration/config_flow/), [DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/), [runtime_data](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data/).
