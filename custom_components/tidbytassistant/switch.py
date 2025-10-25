import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.components.switch import SwitchEntity
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
        _LOGGER.debug("TidbytAssistant configuration not available for switch setup.")
        return

    entities = [TidbytSwitch(tidbyt) for tidbyt in conf.get(CONF_DEVICE, [])]
    if entities:
        async_add_entities(entities)


class TidbytSwitch(SwitchEntity):
    def __init__(self, tidbyt: dict[str, Any]) -> None:
        self._name = tidbyt[CONF_NAME]
        self._deviceid = tidbyt[CONF_ID]
        self._token = tidbyt[CONF_TOKEN]

        self._attr_unique_id = f"tidbytautodim{self._deviceid}"

        self._url = (
            f"{tidbyt.get(CONF_API_URL, DEFAULT_API_URL)}/v0/devices/{self._deviceid}"
        )
        self._header = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._is_on: bool | None = None

    @property
    def name(self) -> str:
        id_components = self._deviceid.split("-")
        if len(id_components) > 3:
            return f"{self._name} {id_components[3].capitalize()} AutoDim"
        return f"{self._name} AutoDim"

    @property
    def icon(self) -> str:
        return "mdi:brightness-auto"

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        payload = {"autoDim": True}
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                self._url, headers=self._header, json=payload
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)

    async def async_turn_off(self, **kwargs: Any) -> None:
        payload = {"autoDim": False}
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                self._url, headers=self._header, json=payload
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)

    async def async_update(self) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.get(self._url, headers=self._header) as response:
                status = f"{response.status}"
                if status != "200":
                    error = await response.text()
                    _LOGGER.error("%s", error)
                else:
                    data = await response.json()
                    self._is_on = data.get("autoDim")

    async def async_poll_device(self) -> None:
        while True:
            await self.async_update()
            await asyncio.sleep(30)
