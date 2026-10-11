"""Controller diagnostics and locally permitted outgoing VPN restarts."""
from homeassistant.components.button import ButtonEntity

from .entity import ControllerEntity, install_entities


class DiagnoseButton(ControllerEntity, ButtonEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "controller", "controller", "diagnose")

    async def async_press(self):
        await self.coordinator.command("diagnose", {})


class RestartVPNButton(ControllerEntity, ButtonEntity):
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator, vpn):
        super().__init__(coordinator, "vpns", vpn, "restart_vpn")

    @property
    def available(self):
        return (super().available
                and self.coordinator.capabilities.get("vpn_restart") is True
                and (self.coordinator.capabilities.get("simulated") is True
                     or self.coordinator.data.get("run_mode") == "control")
                and self.resource.get("approved") is True
                and self.resource.get("restart_allowed") is True
                and self.resource_id not in self.coordinator.capabilities.get("protected_interfaces", ())
                and not self.coordinator.data.get("recovery_required", False))

    async def async_press(self):
        await self.coordinator.command("restart_vpn", {"vpn": self.resource_id})


def entities(coordinator):
    yield DiagnoseButton(coordinator)
    protected = coordinator.capabilities.get("protected_interfaces", ())
    for vpn, meta in coordinator.data.get("vpns", {}).items():
        if meta.get("approved") is True and vpn not in protected:
            yield RestartVPNButton(coordinator, vpn)


async def async_setup_entry(hass, entry, async_add_entities):
    install_entities(hass, entry, async_add_entities, entities)
