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
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        if self.resource_group == "vpns":
            attrs.update({"approved": self.resource.get("approved") is True,
                          "protocol": self.resource.get("protocol"),
                          "device": self.resource.get("device")})
        return attrs

    @property
    def is_on(self):
        if self.key == "controller_available":
            return self.coordinator.last_update_success
        return self.resource.get(self.key)


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(coordinator):
        yield ControllerBinarySensor(coordinator, "controller", "controller", "controller_available")
        for vpn, meta in coordinator.data["vpns"].items():
            if "up" in meta:
                yield ControllerBinarySensor(coordinator, "vpns", vpn, "up")
            for key in ("available", "http_test"):
                yield ControllerBinarySensor(coordinator, "vpns", vpn, key)
        for sid in coordinator.data["sections"]:
            yield ControllerBinarySensor(coordinator, "sections", sid, "all_unavailable")
    install_entities(hass, entry, async_add_entities, factory)
