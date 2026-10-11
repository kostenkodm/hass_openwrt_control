"""Shared resource identities and discovery lifecycle."""
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class ControllerEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, group, resource_id, key):
        super().__init__(coordinator)
        self.resource_group, self.resource_id, self.key = group, resource_id, key
        self._attr_unique_id = f"{coordinator.controller_id}:{group}:{resource_id}:{key}"
        self._attr_translation_key = key
        if group != "controller":
            self._attr_translation_placeholders = {"resource": resource_id}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.controller_id)},
            name="OpenWrt VPN — Demo" if coordinator.config_entry.data.get("demo") else "OpenWrt VPN Controller",
            manufacturer="hass_openwrt_control",
            model="Local simulator" if coordinator.capabilities.get("simulated") else "OpenWrt VPN Controller",
            sw_version="prototype 0.1.0",
        )

    @property
    def resource(self):
        if self.resource_group == "controller":
            return self.coordinator.data
        return self.coordinator.data.get(self.resource_group, {}).get(self.resource_id, {})

    @property
    def available(self):
        return super().available and bool(self.resource)

    @property
    def extra_state_attributes(self):
        return {"simulated": self.coordinator.capabilities.get("simulated", False),
                "resource_id": self.resource_id}


def install_entities(hass, entry, async_add_entities, factory):
    coordinator = entry.runtime_data
    known = {}

    def update():
        current = {entity.unique_id: entity for entity in factory(coordinator)}
        new = [entity for key, entity in current.items() if key not in known]
        if new:
            async_add_entities(new)
        registry = er.async_get(hass)
        for key in set(known) - set(current):
            entity = known[key]
            registered = registry.async_get_entity_id(entity.platform.domain, DOMAIN, key) if entity.platform else None
            if registered:
                registry.async_remove(registered)
            else:
                hass.async_create_task(entity.async_remove())
            del known[key]
        known.update({entity.unique_id: entity for entity in new})

    update()
    entry.async_on_unload(coordinator.async_add_listener(update))
