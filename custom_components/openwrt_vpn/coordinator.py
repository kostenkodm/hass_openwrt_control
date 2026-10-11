"""Aggregate snapshots, cursor-based history and one event per outage transition."""
import asyncio
from datetime import timedelta
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, ControllerError, validate_snapshot
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ControllerCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client, capabilities):
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(seconds=entry.options.get("poll_interval", 30)))
        self.client, self.capabilities = client, capabilities
        self.controller_id = capabilities["controller_id"]
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_cursor")
        self.cursor = None
        self.events = []
        self.connection_lost = False
        self.command_lock = asyncio.Lock()

    async def load_cursor(self):
        stored = await self.store.async_load()
        if isinstance(stored, dict) and type(stored.get("cursor")) is int:
            self.cursor = stored["cursor"]

    def fire(self, kind, **context):
        self.hass.bus.async_fire(f"{DOMAIN}_event", {
            "controller_id": self.controller_id, "type": kind, **context,
        })

    async def _async_update_data(self):
        try:
            snapshot = validate_snapshot(await self.client.read("status"), self.controller_id)
            if self.cursor is None:
                self.cursor = snapshot["latest_event_id"]
                await self.store.async_save({"cursor": self.cursor})
            history = await self.client.read("history", {"after": self.cursor})
            if not isinstance(history, dict) or type(history.get("cursor")) is not int:
                raise ControllerError("Invalid event history")
            events = history.get("events")
            if not isinstance(events, list) or len(events) > 200:
                raise ControllerError("Invalid event history")
            if history.get("gap"):
                self.fire("history_gap")
            for event in events:
                if not isinstance(event, dict) or type(event.get("event_id")) is not int:
                    raise ControllerError("Invalid event")
                if event["event_id"] <= self.cursor:
                    continue
                allowed = {"event_id", "time", "section_id", "vpn", "previous", "request_id", "simulated", "code"}
                self.fire(event.get("type", "unknown"),
                          **{k: v for k, v in event.items() if k in allowed})
            self.events = (self.events + events)[-20:]
            if history["cursor"] != self.cursor:
                self.cursor = history["cursor"]
                await self.store.async_save({"cursor": self.cursor})
            if self.connection_lost:
                self.fire("controller_restored")
                self.connection_lost = False
            return snapshot
        except AuthenticationError as err:
            self._lost()
            raise ConfigEntryAuthFailed("RPC authentication failed") from err
        except ControllerError as err:
            self._lost()
            raise UpdateFailed(str(err)) from err

    def _lost(self):
        if not self.connection_lost:
            self.fire("controller_lost")
            self.connection_lost = True

    async def command(self, method, values):
        if not (self.capabilities.get("simulated") is True
                and self.capabilities.get("simulation_control") is True):
            raise HomeAssistantError("This prototype permits commands only to the local simulator")
        async with self.command_lock:
            await self.async_refresh()
            if not self.last_update_success:
                raise HomeAssistantError("Controller state is unavailable; write was not sent")
            try:
                result = await self.client.mutate(method, values, self.data["revision"])
                if not isinstance(result, dict) or result.get("status") != "completed":
                    raise HomeAssistantError("Application failed or recovery is required; inspect history")
                return result
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed("RPC authentication failed") from err
            except ControllerError as err:
                raise HomeAssistantError(str(err)) from err
            finally:
                # Request-refresh can debounce; commands need the actual fresh snapshot.
                await self.async_refresh()
