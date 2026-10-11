"""Global automation only; never stops VPNs or Podkop."""
from homeassistant.components.switch import SwitchEntity

from .entity import ControllerEntity


class AutomationSwitch(ControllerEntity, SwitchEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "controller", "controller", "automation")

    @property
    def is_on(self):
        return self.resource["automation"]

    async def async_turn_on(self, **kwargs):
        await self.coordinator.command("set_automation", {"enabled": True})

    async def async_turn_off(self, **kwargs):
        await self.coordinator.command("set_automation", {"enabled": False})


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AutomationSwitch(entry.runtime_data)])
