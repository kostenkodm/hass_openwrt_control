# Ограниченный протокол прототипа

HTTPS POST /ubus, JSON-RPC 2.0, проверка CA и имени сервера; redirects запрещены.

~~~json
{"jsonrpc":"2.0","id":1,"method":"call","params":["SESSION","vpn.controller","status",{}]}
~~~

Ответ ubus: result=[0,payload]. Код 6 — отказ авторизации/доступа. Прикладная ошибка: result=[0,{"ok":false,"error":{"code":"conflict"}}]. Неуспешный HTTP, некорректный JSON, несовпадающий id и слишком большой ответ считаются ошибками протокола.

session.login получает username/password, возвращает ubus_rpc_session и timeout. Клиент обновляет сессию перед истечением и после отказа чтения; write автоматически не воспроизводится.

| Метод vpn.controller | Параметры кроме request_id/expected_revision | Доступ |
|---|---|---|
| capabilities, status, sections, vpns | нет | read |
| history | after: целочисленный курсор | read |
| operation | request_id | read |
| set_automation | enabled: bool | write |
| configure | run_mode, probe_interval, failure_cycles, quorum, min_hold | write |
| set_policy | section_id, policy | write |
| assign_vpn | section_id, vpn | write |
| diagnose | нет | write |

Все write требуют request_id и expected_revision. Лишние ключи отклоняются. Policy: mode (manual/auto), vpn, candidates (упорядоченные уникальные id), algorithm (priority/quality), return_policy (after_hold/sticky), quality_margin, preferences (VPN → -10..10).

Desired policy, applied_vpn и proposed_vpn разделены. completed в observe подтверждает сохранение политики, не сетевое применение. Все применения прототипа смоделированы.

Качество: 0.7 × успешность за последние 10 циклов + 0.2 × доля успешных циклов + 0.1 × 100/(1+latency_ms/100) + предпочтение. Переключение по качеству требует преимущества quality_margin и выдержанного min_hold. Подтверждённый отказ текущего кандидата допускает аварийное переключение до окончания удержания.

Нет универсальных uci.get/set, file.exec, rc.init, service.*, network.interface.* и system.reboot. inbound_vpn отсутствует среди исходящих ресурсов и отклоняется при назначении. Создание и удаление секций через RPC отсутствует.

Отдельный /_lab — локальная инъекция отказов с другим случайным lab_token, не часть интерфейса HA. Реальная сторона rpcd/ucode ещё не реализована; инъекция ubus_rpc_session шлюзом uhttpd будет проверяться при разработке нативного адаптера.
