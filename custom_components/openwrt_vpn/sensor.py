"""Controller, per-section and per-VPN state."""
from datetime import datetime

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass

from .entity import ControllerEntity, install_entities

SECTION_KEYS = ("applied_vpn", "proposed_vpn", "application_state", "reason", "last_switch")
VPN_KEYS = ("latency_ms", "success_percent", "last_handshake", "rx_bytes", "tx_bytes", "external_ip")


class ControllerSensor(ControllerEntity, SensorEntity):
    def __init__(self, coordinator, group, resource_id, key):
        super().__init__(coordinator, group, resource_id, key)
        if key == "run_mode":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["observe", "control"]
        elif key == "application_state":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["simulated", "pending", "pending_observe", "automation_paused",
                                  "rolled_back", "recovery_required"]
        elif key == "latency_ms":
            self._attr_native_unit_of_measurement = "ms"
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif key == "success_percent":
            self._attr_native_unit_of_measurement = "%"
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif key in ("last_switch", "last_handshake"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif key in ("rx_bytes", "tx_bytes"):
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_native_unit_of_measurement = "B"
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self):
        if self.key == "history":
            return len(self.coordinator.events)
        value = self.resource.get(self.key)
        if self.key in ("last_switch", "last_handshake") and value:
            return datetime.fromisoformat(value)
        return value

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        if self.key == "history":
            attrs["events"] = self.coordinator.events
        if self.key in ("rx_bytes", "tx_bytes", "last_handshake"):
            attrs["supported"] = not self.coordinator.capabilities.get("simulated")
        return attrs


async def async_setup_entry(hass, entry, async_add_entities):
    def factory(coordinator):
        for key in ("podkop_status", "sing_box_status", "run_mode", "history"):
            yield ControllerSensor(coordinator, "controller", "controller", key)
        for sid in coordinator.data["sections"]:
            for key in SECTION_KEYS:
                yield ControllerSensor(coordinator, "sections", sid, key)
        for vpn in coordinator.data["vpns"]:
            for key in VPN_KEYS:
                yield ControllerSensor(coordinator, "vpns", vpn, key)
    install_entities(hass, entry, async_add_entities, factory)
