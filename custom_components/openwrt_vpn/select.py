"""Desired section policy; actual assignment is a separate sensor."""
from copy import deepcopy

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .entity import ControllerEntity, install_entities


class SectionSelect(ControllerEntity, SelectEntity):
    def __init__(self, coordinator, sid):
        super().__init__(coordinator, "sections", sid, "policy")

    @property
    def approved_vpns(self):
        return [v for v, data in self.coordinator.data["vpns"].items() if data.get("approved") is True]

    @property
    def auto_ready(self):
        policy = self.resource.get("policy", {})
        candidates = policy.get("candidates", [])
        approved = self.approved_vpns
        return (policy.get("vpn") in approved
                and all(v in approved for v in candidates))

    @property
    def options(self):
        options = (["Auto"] if self.auto_ready else []) + self.approved_vpns
        # Discovery describes the existing policy even before local approval.
        # Keeping it visible does not authorize a new assignment.
        current = self.current_option
        if current is not None and current not in options:
            options.insert(0, current)
        return options

    @property
    def extra_state_attributes(self):
        return {**super().extra_state_attributes,
                "approved_vpns": self.approved_vpns, "auto_ready": self.auto_ready,
                "policy_mode": self.resource.get("policy", {}).get("mode")}

    @property
    def current_option(self):
        policy = self.resource.get("policy", {})
        return "Auto" if policy.get("mode") == "auto" else policy.get("vpn")

    async def async_select_option(self, option):
        if option == self.current_option:
            return
        if (option == "Auto" and not self.auto_ready
                or option != "Auto" and option not in self.approved_vpns):
            raise HomeAssistantError("VPN and policy candidates must be approved locally on OpenWrt")
        if option == "Auto":
            policy = deepcopy(self.resource["policy"])
            policy["mode"] = "auto"
            if not policy.get("candidates"):
                policy["candidates"] = self.approved_vpns
            await self.coordinator.command("set_policy", {"section_id": self.resource_id, "policy": policy})
        else:
            await self.coordinator.command("assign_vpn", {"section_id": self.resource_id, "vpn": option})


async def async_setup_entry(hass, entry, async_add_entities):
    install_entities(hass, entry, async_add_entities,
                     lambda c: [SectionSelect(c, sid) for sid in c.data["sections"]])
