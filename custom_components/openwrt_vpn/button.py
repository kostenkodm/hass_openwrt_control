"""Immediate controller-side diagnosis."""
from homeassistant.components.button import ButtonEntity

from .entity import ControllerEntity


class DiagnoseButton(ControllerEntity, ButtonEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "controller", "controller", "diagnose")

    async def async_press(self):
        await self.coordinator.command("diagnose", {})


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DiagnoseButton(entry.runtime_data)])
