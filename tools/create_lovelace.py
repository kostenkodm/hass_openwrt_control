"""Build a native Lovelace dashboard from the integration's registered entities."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def build_dashboard(entities):
    def ident(group, resource, key):
        suffix = f":{group}:{resource}:{key}"
        return next(e["entity_id"] for e in entities if e["unique_id"].endswith(suffix))

    def row(group, resource, key, name):
        return {"entity": ident(group, resource, key), "name": name}

    def controller(key, name):
        return row("controller", "controller", key, name)
    control_cards = [
        {"type": "markdown", "content": (
            "## OpenWrt VPN — интеграция Home Assistant\n"
            "**Тестовый стенд.** Сущности и управление работают через настоящую интеграцию HA; "
            "роутер, проверки VPN и применение Podkop заменены локальным HTTPS ubus-симулятором.\n\n"
            "**С чего начать:** в карточке **main** выберите `vpn_b`. "
            "В режиме наблюдения изменится заданная политика и предлагаемый VPN; "
            "применённый останется `vpn_a`. Карточки **media** и **custom** не должны измениться.\n\n"
            "Для применения в симуляторе: **[Настройки интеграции](/config/integrations/integration/openwrt_vpn)** "
            "→ Настроить → Общие параметры → режим `control`. "
            "Затем снова выберите VPN либо `Auto`. Для Auto также включите автоматику.\n\n"
            "`inbound_vpn` защищён и отсутствует в списке исходящих VPN. "
            "Секции media/custom приведены для проверки независимости и не обнаружены на реальном роутере."
        )},
        {"type": "entities", "title": "Контроллер", "show_header_toggle": False,
         "entities": [controller(key, name) for key, name in (
             ("controller_available", "Связь с контроллером"),
             ("automation", "Автоматический выбор VPN"),
             ("run_mode", "Режим работы"),
             ("diagnose", "Запросить диагностику"),
         )]},
    ]
    section_cards = []
    section_ids = sorted({e["unique_id"].split(":")[-2] for e in entities
                          if ":sections:" in e["unique_id"]}, key=lambda sid: (sid != "main", sid))
    for sid in section_ids:
        section_cards.append({"type": "entities", "title": f"Секция {sid}", "show_header_toggle": False,
                              "entities": [row("sections", sid, key, name) for key, name in (
                                  ("policy", "Заданная политика / VPN"),
                                  ("applied_vpn", "Применённый VPN"),
                                  ("proposed_vpn", "Предлагаемый VPN"),
                                  ("application_state", "Результат применения"),
                                  ("reason", "Причина решения"),
                                  ("last_switch", "Последнее переключение"),
                                  ("all_unavailable", "Все кандидаты недоступны"),
                              )]})
    vpn_ids = sorted({e["unique_id"].split(":")[-2] for e in entities if ":vpns:" in e["unique_id"]})
    vpn_cards = [{"type": "entities", "title": vpn, "show_header_toggle": False,
                  "entities": [row("vpns", vpn, key, name) for key, name in (
                      ("available", "VPN доступен"), ("latency_ms", "Задержка"),
                      ("success_percent", "Успешные проверки"), ("http_test", "HTTP-проверка"),
                      ("external_ip", "Внешний IP (смоделирован)"),
                      ("restart_vpn", "Перезапустить VPN (в Demo смоделировано)"),
                  )]} for vpn in vpn_ids]
    details = [{"type": "markdown", "content": (
        "## Что проверяет прототип\n"
        "- Политика и фактически назначенный VPN показаны отдельно.\n"
        "- Выбор в одной секции не меняет ручные политики других.\n"
        "- Auto выбирает из кандидатов своей секции; выключение глобальной автоматики сохраняет назначения.\n"
        "- История решений находится в атрибутах сущности «Последние события».\n\n"
        "Демонстрация не проверяет реальный выход. Прототип 0.2.0 имеет отдельный экспериментальный "
        "нативный OpenWrt-контроллер; production-приёмка остаётся отдельным этапом."
    )}, {"type": "entities", "title": "Службы и история", "entities": [
        controller("podkop_status", "Podkop (смоделирован)"),
        controller("sing_box_status", "sing-box (смоделирован)"),
        controller("history", "Последние события — нажмите для атрибутов"),
    ]}]
    return {"title": "OpenWrt VPN", "views": [
        {"title": "Управление", "path": "vpn", "icon": "mdi:vpn", "cards": control_cards + section_cards},
        {"title": "Состояние VPN", "path": "health", "icon": "mdi:heart-pulse", "cards": vpn_cards},
        {"title": "История и ограничения", "path": "details", "icon": "mdi:history", "cards": details},
    ]}


def save_dashboard(entities, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(build_dashboard(entities), allow_unicode=True, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    entity_map = json.loads((ROOT / "work/ha-entity-map.json").read_text())
    save_dashboard(entity_map, ROOT / "examples/lovelace.yaml")
    print("Native Lovelace dashboard generated from registered integration entity IDs.")
