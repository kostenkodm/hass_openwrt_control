"""UI configuration, reauthentication and router-owned policy options."""
from copy import deepcopy
import json
import ssl
import uuid

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, ControllerError, UbusClient, tls_context
from .const import DOMAIN


def connection_schema(defaults=None):
    defaults = defaults or {}
    return vol.Schema({
        vol.Required("endpoint", default=defaults.get("endpoint", "https://localhost:8443/ubus")): str,
        vol.Required("username", default=defaults.get("username", "hass")): str,
        vol.Required("password"): selector.TextSelector({"type": selector.TextSelectorType.PASSWORD}),
        vol.Optional("ca_pem", default=defaults.get("ca_pem", "")): selector.TextSelector({"multiline": True}),
    })


async def validate_connection(hass, data):
    context = await hass.async_add_executor_job(tls_context, data.get("ca_pem", ""))
    client = UbusClient(async_get_clientsession(hass), data["endpoint"],
                        data["username"], data["password"], context)
    try:
        capabilities = await client.read("capabilities")
        if (not isinstance(capabilities, dict) or capabilities.get("api_version") != 1
                or not isinstance(capabilities.get("controller_id"), str)):
            raise ControllerError("Unsupported controller API")
        return capabilities
    finally:
        await client.close()


class ControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ControllerOptionsFlow()

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return await self.async_step_controller(user_input)
        return self.async_show_menu(step_id="user", menu_options=["demo", "controller"])

    async def async_step_demo(self, user_input=None):
        if any(entry.data.get("demo") is True for entry in self._async_current_entries()):
            return self.async_abort(reason="demo_already_configured")
        if user_input is not None:
            controller_id = str(uuid.uuid4())
            await self.async_set_unique_id(controller_id)
            return self.async_create_entry(title="OpenWrt VPN — Demo", data={"demo": True})
        return self.async_show_form(step_id="demo", data_schema=vol.Schema({}))

    async def async_step_controller(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                capabilities = await validate_connection(self.hass, user_input)
                await self.async_set_unique_id(capabilities["controller_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="OpenWrt VPN Controller", data=user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (ControllerError, ssl.SSLError, ValueError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="controller", data_schema=connection_schema(), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._update_connection("reauth_confirm", self._get_reauth_entry(), user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await self._update_connection("reconfigure", self._get_reconfigure_entry(), user_input)

    async def _update_connection(self, step, entry, user_input):
        if entry.data.get("demo") is True:
            return self.async_abort(reason="demo_no_connection")
        errors = {}
        if user_input is not None:
            try:
                capabilities = await validate_connection(self.hass, user_input)
                await self.async_set_unique_id(capabilities["controller_id"])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (ControllerError, ssl.SSLError, ValueError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id=step, data_schema=connection_schema(entry.data), errors=errors)


class ControllerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        menu = ["general", "section"]
        if self.config_entry.data.get("demo") is True:
            menu.append("demo_scenario")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_demo_scenario(self, user_input=None):
        c = self.config_entry.runtime_data
        if self.config_entry.data.get("demo") is not True or c.demo is None:
            return self.async_abort(reason="demo_unavailable")
        from .demo.runtime import SCENARIOS
        errors = {}
        if user_input is not None:
            try:
                await c.demo.scenario(self.hass, user_input["scenario"])
                await c.async_refresh()
                return self.async_abort(reason="demo_scenario_applied")
            except (HomeAssistantError, ValueError, KeyError, OSError):
                errors["base"] = "command_failed"
        return self.async_show_form(step_id="demo_scenario", errors=errors, data_schema=vol.Schema({
            vol.Required("scenario"): selector.SelectSelector({
                "options": list(SCENARIOS), "translation_key": "demo_scenario"}),
        }))

    async def async_step_general(self, user_input=None):
        c = self.config_entry.runtime_data
        settings = c.data["settings"]
        errors = {}
        if user_input is not None:
            try:
                if user_input["run_mode"] == "control" and not c.capabilities.get("simulation_control"):
                    raise HomeAssistantError("Production control is not available in this prototype")
                await c.command("configure", {k: user_input[k] for k in (
                    "run_mode", "probe_interval", "failure_cycles", "quorum", "min_hold")})
                return self.async_create_entry(title="", data={"poll_interval": user_input["poll_interval"]})
            except (HomeAssistantError, KeyError, ValueError):
                errors["base"] = "command_failed"
        return self.async_show_form(step_id="general", errors=errors, data_schema=vol.Schema({
            vol.Required("run_mode", default=c.data["run_mode"]): vol.In(["observe", "control"]),
            vol.Required("poll_interval", default=self.config_entry.options.get("poll_interval", 30)):
                vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            vol.Required("probe_interval", default=settings["probe_interval"]):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
            vol.Required("failure_cycles", default=settings["failure_cycles"]):
                vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            vol.Required("quorum", default=settings["quorum"]): vol.In([2, 3]),
            vol.Required("min_hold", default=settings["min_hold"]):
                vol.All(vol.Coerce(int), vol.Range(min=0, max=86400)),
        }))

    async def async_step_section(self, user_input=None):
        sections = self.config_entry.runtime_data.data["sections"]
        if user_input is not None and user_input.get("section_id") in sections:
            self.section_id = user_input["section_id"]
            return await self.async_step_section_policy()
        if not sections:
            return self.async_abort(reason="no_sections")
        return self.async_show_form(step_id="section", data_schema=vol.Schema({
            vol.Required("section_id"): vol.In(list(sections)),
        }))

    async def async_step_section_policy(self, user_input=None):
        c = self.config_entry.runtime_data
        section = c.data["sections"].get(self.section_id)
        if section is None:
            return self.async_abort(reason="no_sections")
        policy = deepcopy(section["policy"])
        errors = {}
        if user_input is not None:
            try:
                policy.update({k: user_input[k] for k in (
                    "mode", "vpn", "algorithm", "return_policy", "quality_margin")})
                policy["candidates"] = [s.strip() for s in user_input["candidates"].split(",") if s.strip()]
                policy["preferences"] = json.loads(user_input["preferences"])
                await c.command("set_policy", {"section_id": self.section_id, "policy": policy})
                return self.async_create_entry(title="", data=dict(self.config_entry.options))
            except (ValueError, HomeAssistantError, KeyError):
                errors["base"] = "command_failed"
        return self.async_show_form(step_id="section_policy", errors=errors, data_schema=vol.Schema({
            vol.Required("mode", default=policy["mode"]): vol.In(["manual", "auto"]),
            vol.Required("vpn", default=policy["vpn"]): vol.In(list(c.data["vpns"])),
            vol.Required("candidates", default=", ".join(policy["candidates"])): str,
            vol.Required("algorithm", default=policy["algorithm"]): vol.In(["priority", "quality"]),
            vol.Required("return_policy", default=policy["return_policy"]): vol.In(["after_hold", "sticky"]),
            vol.Required("quality_margin", default=policy["quality_margin"]):
                vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
            vol.Required("preferences", default=json.dumps(policy["preferences"])): str,
        }))
