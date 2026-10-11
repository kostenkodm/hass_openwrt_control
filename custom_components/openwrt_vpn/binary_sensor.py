"""Availability separates unavailable, unknown and connection loss."""
from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import ControllerEntity, install_entities


class ControllerBinarySensor(ControllerEntity, BinarySensorEntity):
    def __init__(self, coordinator, group, resource_id, key):
        super().__init__(coordinator, group, resource_id, key)

    @property
    def available(self):
        if self.key == "controller_available":
            return True
        return super().available

    @property
    def is_on(self):
        if self.key == "controller_available":
            return self.coordinator.last_update_success
        return self.resource.get(self.key)


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(coordinator):
        yield ControllerBinarySensor(coordinator, "controller", "controller", "controller_available")
        for vpn in coordinator.data["vpns"]:
            for key in ("available", "http_test"):
                yield ControllerBinarySensor(coordinator, "vpns", vpn, key)
        for sid in coordinator.data["sections"]:
            yield ControllerBinarySensor(coordinator, "sections", sid, "all_unavailable")
    install_entities(hass, entry, async_add_entities, factory)
