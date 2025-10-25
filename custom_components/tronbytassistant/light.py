from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DATA_CONFIG
from .const import (
    CONF_API_URL,
    CONF_DEVICE,
    CONF_ID,
    CONF_NAME,
    CONF_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_SCALE = (1, 100)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tronbyt brightness entities from a config entry."""
    conf = hass.data.get(DOMAIN, {}).get(DATA_CONFIG)
    if not conf:
        _LOGGER.debug("TronbytAssistant configuration missing; skipping light setup.")
        return

    entities = [TronbytLight(device) for device in conf.get(CONF_DEVICE, [])]
    if entities:
        async_add_entities(entities)


class TronbytLight(LightEntity):
    """Brightness entity backed by the Tronbyt device API."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, device: dict[str, Any]) -> None:
        self._name = device[CONF_NAME]
        self._deviceid = device[CONF_ID]
        self._token = device[CONF_TOKEN]
        self._url = f"{device.get(CONF_API_URL)}/v0/devices/{self._deviceid}"
        self._header = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._brightness: int | None = None
        self._is_on = True

    @property
    def name(self) -> str:
        return f"{self._name} Brightness"

    @property
    def unique_id(self) -> str:
        return f"tronbytlight-{self._deviceid}"

    @property
    def brightness(self) -> int | None:
        return self._brightness

    @property
    def icon(self) -> str:
        return "mdi:television-ambient-light"

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            brightness = round((kwargs[ATTR_BRIGHTNESS] / 255) * 100)
        else:
            brightness = self._brightness or BRIGHTNESS_SCALE[1]

        payload = {"brightness": int(brightness)}
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                self._url, headers=self._header, json=payload
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)
                else:
                    self._brightness = brightness
                    self._is_on = brightness >= BRIGHTNESS_SCALE[0]

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Tronbyt displays do not support turning fully off via this endpoint."""

    async def async_update(self) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.get(self._url, headers=self._header) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)
                    return
                data = await response.json()
                percent = data.get("brightness", 0)
                self._is_on = percent >= BRIGHTNESS_SCALE[0]
                self._brightness = round((percent * 0.01) * 255)

    async def async_poll_device(self) -> None:
        while True:
            await self.async_update()
            await asyncio.sleep(30)
