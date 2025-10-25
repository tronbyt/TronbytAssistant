from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_DEVICE,
    CONF_HOST,
    CONF_PORT,
    CONF_EXTERNALADDON,
    CONF_NAME,
    CONF_ID,
    CONF_TOKEN,
    CONF_API_URL,
    CONF_TRONBYT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_EXTERNAL_ADDON,
)


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): str,
        vol.Optional(CONF_EXTERNALADDON, default=DEFAULT_EXTERNAL_ADDON): bool,
    }
)

STEP_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME): str,
        vol.Required(CONF_ID): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_API_URL): str,
        vol.Optional(CONF_TRONBYT, default=False): bool,
    }
)


class TidbytAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TidbytAssistant."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_device()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

    async def async_step_device(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            self._devices.append(user_input)
            return await self.async_step_device_menu()

        return self.async_show_form(
            step_id="device", data_schema=STEP_DEVICE_SCHEMA, errors=errors
        )

    async def async_step_device_menu(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="device_menu",
            menu_options={
                "add_device": "Add another device",
                "finish": "Finish setup",
            },
        )

    async def async_step_add_device(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_device()

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        return await self._async_create_entry()

    async def _async_create_entry(self):
        if not self._devices:
            return await self.async_show_form(
                step_id="device",
                data_schema=STEP_DEVICE_SCHEMA,
                errors={"base": "no_devices"},
            )

        data = dict(self._data)
        data[CONF_DEVICE] = self._devices
        title = _entry_title_from_devices(self._devices)

        return self.async_create_entry(title=title, data=data)

    async def async_step_import(self, user_input: dict[str, Any]):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        data = {
            CONF_HOST: user_input.get(CONF_HOST, DEFAULT_HOST),
            CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
            CONF_EXTERNALADDON: user_input.get(
                CONF_EXTERNALADDON, DEFAULT_EXTERNAL_ADDON
            ),
            CONF_DEVICE: user_input.get(CONF_DEVICE, []),
        }

        if not data[CONF_DEVICE]:
            return self.async_abort(reason="no_devices")

        title = _entry_title_from_devices(data[CONF_DEVICE])
        return self.async_create_entry(title=title, data=data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return TidbytAssistantOptionsFlow(config_entry)


class TidbytAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_abort(reason="not_supported")


def _entry_title_from_devices(devices: list[dict[str, Any]]) -> str:
    if not devices:
        return "TidbytAssistant"
    device = devices[0]
    return device.get(CONF_NAME) or device.get(CONF_ID) or "TidbytAssistant"
