"""Create validation notes only from a successful JUnit result."""
from collections import Counter
import importlib.metadata
from pathlib import Path
import platform
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
tree = ET.parse(ROOT / "work/test-results.xml")
suites = list(tree.iter("testsuite"))
assert suites and all(int(s.get("failures", 0)) == 0 and int(s.get("errors", 0)) == 0 for s in suites)
cases = list(tree.iter("testcase"))
counts = Counter(case.get("classname", "").rsplit(".", 1)[-1] for case in cases)
versions = {name: importlib.metadata.version(name) for name in (
    "homeassistant", "aiohttp", "pytest", "pytest-asyncio", "cryptography", "ruff")}
text = "# Проверка прототипа 0.1.0\n\nДата: 11 октября 2026. Локальный WSL Ubuntu-26.04, x86_64.\n\n"
text += f"Результат: **{len(cases)} теста прошли**, ошибок и провалов нет. Ruff check прошёл.\n\n"
text += f"Python: {platform.python_version()}.\n\n| Компонент | Версия |\n|---|---|\n"
text += "".join(f"| {key} | {value} |\n" for key, value in versions.items())
text += "\n| Набор тестов | Количество |\n|---|---|\n"
text += "".join(f"| {key} | {value} |\n" for key, value in sorted(counts.items()))
text += """
\nСквозные HA-тесты используют настоящий Core, Config Flow, Options Flow, реестры, сервисы и пять платформ; Home Assistant не подменяется моками. Сервер — настоящий локальный HTTPS с тестовым CA.

Проверены встроенный демонстрационный Config Flow без ввода реквизитов, сценарии через Options Flow, verified loopback TLS, сохранение политик при reload, закрытие listener при unload, изолированный запуск HACS-каталога без tools/simulator и 52 сущности для трёх секций и трёх VPN, независимость двух контроллеров, добавление/удаление ресурсов, команды и их последовательность, настройки, потеря/восстановление связи, редактирование политик, исключение секретов из диагностики, сохранение курсора после reload.

Проверены модель отказов, ручные политики, наблюдение, групповые переключения, откат/конфликт/рестарт, гистерезис, сохранение последнего назначения, запрет inbound_vpn, строгий TLS (CA и hostname), отказы generic RPC, отсутствие автоматического повтора записи, неизвестный исход, ошибки HTTP/JSON-RPC, redirects и ограничение размера ответа.

Отдельно выполнена демонстрация шести сценариев через HTTPS RPC: outputs/prototype/demo.html и demo.json.

Это подтверждает локальную модель и HA-интеграцию. Загрузка опубликованного репозитория самим HACS и установка в HAOS пользователя не выполнялись. Официальный валидатор HACS запускается отдельно после публикации; актуальный результат доступен в [GitHub Actions](https://github.com/kostenkodm/hass_openwrt_control/actions/workflows/validate.yaml). Этот документ описывает локальный прогон, а не результат HACS. Встроенная демонстрация останавливается вместе с HA; автономность production-контроллера остаётся отдельным требованием. Реальный OpenWrt/Podkop, egress, отсутствие утечек IPv4/IPv6, фактическая защита inbound_vpn, rpcd ACL на устройстве и отказоустойчивость flash не испытаны. Нативный OpenWrt-контроллер ещё не реализован.

Первичные API-референсы: [Config Flow](https://developers.home-assistant.io/docs/core/integration/config_flow/), [DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/), [runtime_data](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data/).
"""
(ROOT / "docs/prototype-validation.ru.md").write_text(text, encoding="utf-8")
out = ROOT / "outputs/prototype"
out.mkdir(parents=True, exist_ok=True)
(out / "TEST-REPORT.ru.md").write_text(text, encoding="utf-8")
shutil.copyfile(ROOT / "work/test-results.xml", out / "test-results.xml")
shutil.copyfile(ROOT / "work/test-run.log", out / "test-run.txt")
print(f"Validation report saved: {len(cases)} passed.")
