import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_API_URL,
    CONF_DEVICE,
    CONF_ID,
    CONF_NAME,
    CONF_TOKEN,
    DEFAULT_API_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_SCALE = (1, 100)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Deprecated YAML setup path."""
    if discovery_info is None:
        return

    await _async_add_entities(hass, add_entities)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    await _async_add_entities(hass, async_add_entities)


async def _async_add_entities(
    hass: HomeAssistant, async_add_entities: AddEntitiesCallback
) -> None:
    conf = hass.data.get(DOMAIN, {}).get("config")
    if not conf:
        _LOGGER.debug("TidbytAssistant configuration not available for light setup.")
        return

    entities = [TidbytLight(tidbyt) for tidbyt in conf.get(CONF_DEVICE, [])]
    if entities:
        async_add_entities(entities)


class TidbytLight(LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, tidbyt: dict[str, Any]) -> None:
        self._name = tidbyt[CONF_NAME]
        self._deviceid = tidbyt[CONF_ID]
        self._token = tidbyt[CONF_TOKEN]
        self._is_on = True
        self._url = (
            f"{tidbyt.get(CONF_API_URL, DEFAULT_API_URL)}/v0/devices/{self._deviceid}"
        )
        self._header = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._brightness: int | None = None

    @property
    def name(self) -> str:
        id_components = self._deviceid.split("-")
        if len(id_components) > 3:
            return f"{self._name} {id_components[3].capitalize()} Brightness"
        return f"{self._name} Brightness"

    @property
    def unique_id(self) -> str:
        return f"tidbytlight-{self._deviceid}"

    @property
    def brightness(self) -> int | None:
        return self._brightness

    @property
    def icon(self) -> str:
        return "mdi:television-ambient-light"

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        if ATTR_BRIGHTNESS in kwargs:
            brightness = round((kwargs[ATTR_BRIGHTNESS] / 255) * 100)
        else:
            brightness = self._brightness or BRIGHTNESS_SCALE[1]

        payload = {"brightness": int(brightness)}
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                self._url, headers=self._header, json=payload
            ) as response:
                status = f"{response.status}"
                if status != "200":
                    error = await response.text()
                    _LOGGER.error("%s", error)
                else:
                    self._brightness = brightness

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Tidbyt displays do not support turning off via the brightness entity."""

    async def async_update(self) -> None:
        """Fetch new state data for this light."""
        async with aiohttp.ClientSession() as session:
            async with session.get(self._url, headers=self._header) as response:
                status = f"{response.status}"
                if status != "200":
                    error = await response.text()
                    _LOGGER.error("%s", error)
                else:
                    data = await response.json()
                    self._is_on = data.get("brightness", 0) >= BRIGHTNESS_SCALE[0]
                    self._brightness = round((data.get("brightness", 0) * 0.01) * 255)

    async def async_poll_device(self) -> None:
        while True:
            await self.async_update()
            await asyncio.sleep(30)
