"""Desired section policy; actual assignment is a separate sensor."""
from copy import deepcopy

from homeassistant.components.select import SelectEntity

from .entity import ControllerEntity, install_entities


class SectionSelect(ControllerEntity, SelectEntity):
    def __init__(self, coordinator, sid):
        super().__init__(coordinator, "sections", sid, "policy")

    @property
    def options(self):
        return ["Auto"] + [v for v, data in self.coordinator.data["vpns"].items() if data.get("approved")]

    @property
    def current_option(self):
        policy = self.resource.get("policy", {})
        return "Auto" if policy.get("mode") == "auto" else policy.get("vpn")

    async def async_select_option(self, option):
        if option == "Auto":
            policy = deepcopy(self.resource["policy"])
            policy["mode"] = "auto"
            await self.coordinator.command("set_policy", {"section_id": self.resource_id, "policy": policy})
        else:
            await self.coordinator.command("assign_vpn", {"section_id": self.resource_id, "vpn": option})


async def async_setup_entry(hass, entry, async_add_entities):
    install_entities(hass, entry, async_add_entities,
                     lambda c: [SectionSelect(c, sid) for sid in c.data["sections"]])
