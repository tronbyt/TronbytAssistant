from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DATA_CONFIG, DATA_DEVICES
from .const import CONF_API_URL, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tronbyt night mode switches from a config entry."""
    conf = hass.data.get(DOMAIN, {}).get(DATA_CONFIG)
    if not conf:
        _LOGGER.debug("TronbytAssistant configuration missing; skipping switch setup.")
        return

    devices = hass.data.get(DOMAIN, {}).get(DATA_DEVICES, [])
    if not devices:
        _LOGGER.debug("No Tronbyt devices available; skipping switch entity creation.")
        return

    api_url = conf[CONF_API_URL]
    token = conf[CONF_TOKEN]
    entities = [TronbytAutoDimSwitch(device, api_url, token) for device in devices]
    if entities:
        async_add_entities(entities)


class TronbytAutoDimSwitch(SwitchEntity):
    """Expose the Tronbyt auto-dim flag as a switch."""

    def __init__(self, device: dict[str, Any], api_url: str, token: str) -> None:
        self._deviceid = device["id"]
        self._name = device["name"]
        self._base_url = api_url
        self._token = token
        self._url = f"{self._base_url}/v0/devices/{self._deviceid}"
        self._header = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._is_on: bool | None = device.get("autoDim")

    @property
    def name(self) -> str:
        return f"{self._name} AutoDim"

    @property
    def unique_id(self) -> str:
        return f"tronbytautodim-{self._deviceid}"

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._deviceid)},
            "name": self._name,
            "manufacturer": "Tronbyt",
            "model": "Display",
        }

    @property
    def icon(self) -> str:
        return "mdi:brightness-auto"

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_autodim(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_autodim(False)

    async def async_update(self) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.get(self._url, headers=self._header) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)
                    return
                data = await response.json()
                self._name = data.get("displayName", self._name)
                self._is_on = data.get("autoDim")

    async def _async_set_autodim(self, enabled: bool) -> None:
        payload = {"autoDim": enabled}
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                self._url, headers=self._header, json=payload
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)

    async def async_poll_device(self) -> None:
        while True:
            await self.async_update()
            await asyncio.sleep(30)
