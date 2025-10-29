from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_API_URL, CONF_TOKEN, CONF_VERIFY_SSL, DOMAIN

USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_URL): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


class TronbytAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TronbytAssistant."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                api_url = _normalize_base_url(user_input[CONF_API_URL])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                token = user_input[CONF_TOKEN]
                verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
                try:
                    devices = await self._async_fetch_devices(
                        api_url, token, verify_ssl
                    )
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidAuth:
                    errors["base"] = "invalid_api_key"
                except NoDevicesFound:
                    errors["base"] = "no_devices_found"
                else:
                    await self.async_set_unique_id(DOMAIN)
                    self._abort_if_unique_id_configured()
                    parsed = urlparse(api_url)
                    title = parsed.hostname or parsed.netloc or api_url
                    if not title and devices:
                        title = devices[0]["name"]
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_API_URL: api_url,
                            CONF_TOKEN: token,
                            CONF_VERIFY_SSL: verify_ssl,
                        },
                    )

        schema = self.add_suggested_values_to_schema(USER_DATA_SCHEMA, user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_import(self, user_input: dict[str, Any]):
        try:
            api_url = _normalize_base_url(user_input.get(CONF_API_URL))
        except ValueError:
            return self.async_abort(reason="invalid_import")

        token = user_input.get(CONF_TOKEN)
        if not token:
            return self.async_abort(reason="invalid_import")

        verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

        try:
            await self._async_fetch_devices(api_url, token, verify_ssl)
        except InvalidAuth:
            return self.async_abort(reason="invalid_api_key")
        except NoDevicesFound:
            return self.async_abort(reason="no_devices_found")
        except HomeAssistantError:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=urlparse(api_url).hostname or urlparse(api_url).netloc or api_url,
            data={
                CONF_API_URL: api_url,
                CONF_TOKEN: token,
                CONF_VERIFY_SSL: verify_ssl,
            },
        )

    async def _async_fetch_devices(
        self, api_url: str, token: str, verify_ssl: bool
    ) -> list[dict[str, Any]]:
        endpoint = f"{api_url}/v0/devices"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        try:
            async with session.get(endpoint, headers=headers) as response:
                if response.status == 401:
                    raise InvalidAuth
                if response.status != 200:
                    raise CannotConnect
                payload = await response.json()
        except aiohttp.ClientError as err:
            raise CannotConnect from err

        devices = payload.get("devices") or []
        if not devices:
            raise NoDevicesFound

        normalized: list[dict[str, Any]] = []
        for item in devices:
            device_id = item.get("id")
            if not device_id:
                continue
            name = item.get("displayName") or device_id
            normalized.append({"id": device_id, "name": name})

        if not normalized:
            raise NoDevicesFound

        return normalized

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return TronbytAssistantOptionsFlow(config_entry)


class TronbytAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_abort(reason="not_supported")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class NoDevicesFound(HomeAssistantError):
    """Error to indicate no devices were returned."""


def _normalize_base_url(url: str) -> str:
    if not url:
        raise ValueError
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError
    path = parsed.path.rstrip("/")
    normalized = f"{parsed.scheme}://{parsed.netloc}"
    if path:
        normalized += path
    return normalized
