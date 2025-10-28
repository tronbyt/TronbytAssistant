from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_ARGS,
    ATTR_COLOR,
    ATTR_CONTENT,
    ATTR_CONTENT_ID,
    ATTR_CONT_TYPE,
    ATTR_CUSTOM_CONT,
    ATTR_DEVICENANME,
    ATTR_DEVICE_IDS,
    ATTR_FONT,
    ATTR_LANG,
    ATTR_PUBLISH_TYPE,
    ATTR_TEXT_TYPE,
    ATTR_TITLE_COLOR,
    ATTR_TITLE_CONTENT,
    ATTR_TITLE_FONT,
    CONF_API_URL,
    CONF_TOKEN,
    DATA_COORDINATOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.TIME,
    Platform.SELECT,
]

DATA_CONFIG = "config"
DATA_SERVICES_REGISTERED = "services_registered"

DEFAULT_TITLE = ""
DEFAULT_TITLE_COLOR = ""
DEFAULT_TITLE_FONT = ""
DEFAULT_ARGS = ""
DEFAULT_CONTENT_ID = ""
DEFAULT_LANG = "en"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_API_URL): cv.string,
                vol.Required(CONF_TOKEN): cv.string,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Support YAML imports by launching a config flow."""
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN not in config:
        return True

    existing_entries = hass.config_entries.async_entries(DOMAIN)
    if existing_entries:
        hass.async_create_task(
            hass.config_entries.async_reload(existing_entries[0].entry_id)
        )
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data=config[DOMAIN],
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    conf = _clone_config(entry.data)
    try:
        conf[CONF_API_URL] = _normalize_base_url(conf[CONF_API_URL])
    except ValueError as err:
        raise HomeAssistantError(
            "Tronbyt base URL must include the protocol (e.g. https://host)"
        ) from err

    coordinator = TronbytCoordinator(
        hass,
        conf[CONF_API_URL],
        conf[CONF_TOKEN],
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][DATA_CONFIG] = conf
    hass.data[DOMAIN][DATA_COORDINATOR] = coordinator

    await _async_register_services(hass, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integration."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    data = hass.data.get(DOMAIN)
    if data is not None:
        data.pop(DATA_CONFIG, None)
        data.pop(DATA_COORDINATOR, None)
        if data.get(DATA_SERVICES_REGISTERED):
            _async_remove_services(hass)

    return True


async def _async_register_services(
    hass: HomeAssistant, coordinator: "TronbytCoordinator"
) -> None:
    """Register the Tronbyt service handlers once."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(DATA_SERVICES_REGISTERED):
        return

    session = async_get_clientsession(hass)
    device_reg = dr.async_get(hass)

    def _get_device_maps() -> tuple[
        dict[str, dict[str, Any]], dict[str, dict[str, Any]]
    ]:
        devices = coordinator.data or []
        if not devices:
            raise HomeAssistantError(
                "No Tronbyt devices are loaded. Reload the integration."
            )
        return (
            {device["name"]: device for device in devices},
            {device["id"]: device for device in devices},
        )

    def _resolve_devices(call: ServiceCall) -> list[dict[str, Any]]:
        names_map, ids_map = _get_device_maps()
        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()

        raw_ids = call.data.get(ATTR_DEVICE_IDS)
        if raw_ids:
            ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
            for device_id in ids:
                entry = device_reg.async_get(device_id)
                if entry is None:
                    raise HomeAssistantError(
                        f"Device {device_id} is not registered in Home Assistant."
                    )
                matched_id = None
                for domain, identifier in entry.identifiers:
                    if domain == DOMAIN:
                        matched_id = identifier
                        break
                if matched_id is None:
                    raise HomeAssistantError(
                        f"Device {device_id} is not managed by TronbytAssistant."
                    )
                device = ids_map.get(matched_id)
                if device is None:
                    raise HomeAssistantError(
                        f"Tronbyt device with id {matched_id} is not available."
                    )
                if matched_id not in seen:
                    resolved.append(device)
                    seen.add(matched_id)

        raw_names = call.data.get(ATTR_DEVICENANME)
        if raw_names:
            names = raw_names if isinstance(raw_names, list) else [raw_names]
            for name in names:
                device = names_map.get(name)
                if device is None:
                    raise HomeAssistantError(f"{name} is not a known Tronbyt device.")
                if device["id"] not in seen:
                    resolved.append(device)
                    seen.add(device["id"])

        if not resolved:
            raise HomeAssistantError("You must select at least one Tronbyt device.")
        return resolved

    def validateid(input_value: str) -> bool:
        """Check if the string contains only A-Z, a-z, and 0-9."""
        pattern = r"^[A-Za-z0-9]+$"
        return bool(re.match(pattern, input_value))

    async def getinstalledapps(deviceid: str, only_pushed: bool = True) -> list[str]:
        url = f"{coordinator.base_url}/v0/devices/{deviceid}/installations"
        header = {
            "Authorization": f"Bearer {coordinator.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with session.get(url, headers=header) as response:
            if response.status != 200:
                error = await response.text()
                _LOGGER.error("%s", error)
                raise HomeAssistantError(error)
            appids: list[str] = []
            data = await response.json()
            for item in data["installations"]:
                if not only_pushed or item["appID"] == "pushed":
                    appids.append(item["id"])
            return appids

    async def request(
        method: str,
        webhook_url: str,
        payload: dict[str, Any],
    ) -> None:
        headers = tronbyt_headers()
        async with session.request(
            method, webhook_url, json=payload, headers=headers
        ) as response:
            if response.status != 200:
                error = await response.text()
                _LOGGER.error("%s", error)
                raise HomeAssistantError(error)

    def tronbyt_headers() -> dict[str, str]:
        return {
            "Authorization": f"Bearer {coordinator.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def handle_push_or_text(call: ServiceCall, is_text: bool) -> None:
        contentid = call.data.get(ATTR_CONTENT_ID, DEFAULT_CONTENT_ID)
        publishtype = call.data.get(ATTR_PUBLISH_TYPE)
        targets = _resolve_devices(call)

        arguments: dict[str, Any] = {}
        if is_text:
            contenttype = "builtin"
            texttype = call.data.get(ATTR_TEXT_TYPE)
            content = f"text-{texttype}"
            arguments["content"] = call.data.get(ATTR_CONTENT)
            arguments["font"] = call.data.get(ATTR_FONT)
            arguments["color"] = call.data.get(ATTR_COLOR)
            arguments["title"] = call.data.get(ATTR_TITLE_CONTENT, DEFAULT_TITLE)
            arguments["titlecolor"] = call.data.get(
                ATTR_TITLE_COLOR, DEFAULT_TITLE_COLOR
            )
            arguments["titlefont"] = call.data.get(ATTR_TITLE_FONT, DEFAULT_TITLE_FONT)
        else:
            contenttype = call.data.get(ATTR_CONT_TYPE)
            args = call.data.get(ATTR_ARGS, DEFAULT_ARGS)
            if args != "":
                parts = args.split(";")
                for pair in parts:
                    if not pair:
                        continue
                    if "=" not in pair:
                        raise HomeAssistantError(
                            "Arguments must be provided as key=value pairs separated by ';'"
                        )
                    key, value = pair.split("=", maxsplit=1)
                    arguments[key] = value

            match contenttype:
                case "builtin":
                    content = call.data.get(ATTR_CONTENT)
                    arguments["lang"] = call.data.get(ATTR_LANG, DEFAULT_LANG)
                case "custom":
                    content = call.data.get(ATTR_CUSTOM_CONT)
                case _:
                    raise HomeAssistantError(f"Unsupported content type: {contenttype}")

        refresh_needed = False
        for item in targets:
            deviceid = item["id"]
            api_url = f"{coordinator.base_url}/v0/devices/{deviceid}/push_app"
            body = {
                "config": arguments,
                "app_id": content,
                "installationID": contentid,
            }
            if publishtype:
                body["publish"] = publishtype
            await request("POST", api_url, body)
            refresh_needed = True

        if refresh_needed:
            await coordinator.async_request_refresh()

    async def pixlet_push(call: ServiceCall) -> None:
        await handle_push_or_text(call, is_text=False)

    async def pixlet_text(call: ServiceCall) -> None:
        await handle_push_or_text(call, is_text=True)

    async def pixlet_delete(call: ServiceCall) -> None:
        contentid = call.data.get(ATTR_CONTENT_ID)
        if not validateid(contentid):
            _LOGGER.error("Content ID must contain characters A-Z, a-z or 0-9")
            raise HomeAssistantError(
                "Content ID must contain characters A-Z, a-z or 0-9"
            )

        targets = _resolve_devices(call)
        refresh_needed = False
        for item in targets:
            deviceid = item["id"]

            validids = await getinstalledapps(deviceid)
            if contentid not in validids:
                _LOGGER.error(
                    "The Content ID you entered is not an installed app on %s. Currently installed apps are: %s",
                    item["name"],
                    validids,
                )
                raise HomeAssistantError(
                    f"The Content ID you entered is not an installed app on {item['name']}. Currently installed apps are: {validids}"
                )

            url = f"{coordinator.base_url}/v0/devices/{deviceid}/installations/{contentid}"
            await request("DELETE", url, {})
            refresh_needed = True

        if refresh_needed:
            await coordinator.async_request_refresh()

    async def handle_installation_update(
        call: ServiceCall, payload: dict[str, Any]
    ) -> None:
        contentid = call.data.get(ATTR_CONTENT_ID)
        if not validateid(contentid):
            _LOGGER.error("Content ID must contain characters A-Z, a-z or 0-9")
            raise HomeAssistantError(
                "Content ID must contain characters A-Z, a-z or 0-9"
            )

        targets = _resolve_devices(call)
        refresh_needed = False
        for item in targets:
            deviceid = item["id"]

            validids = await getinstalledapps(deviceid, only_pushed=False)
            if contentid not in validids:
                _LOGGER.error(
                    "The Content ID you entered is not an installed app on %s. Currently installed apps are: %s",
                    item["name"],
                    validids,
                )
                raise HomeAssistantError(
                    f"The Content ID you entered is not an installed app on {item['name']}. Currently installed apps are: {validids}"
                )

            endpoint = f"{coordinator.base_url}/v0/devices/{deviceid}/installations/{contentid}"
            await request("PATCH", endpoint, payload)
            refresh_needed = True

        if refresh_needed:
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "push", pixlet_push)
    hass.services.async_register(DOMAIN, "text", pixlet_text)
    hass.services.async_register(DOMAIN, "delete", pixlet_delete)

    data[DATA_SERVICES_REGISTERED] = True


def _async_remove_services(hass: HomeAssistant) -> None:
    """Remove domain services."""
    for service in (
        "push",
        "text",
        "delete",
    ):
        hass.services.async_remove(DOMAIN, service)
    hass.data.setdefault(DOMAIN, {})[DATA_SERVICES_REGISTERED] = False


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


def _clone_config(value: Any) -> Any:
    """Clone Home Assistant entry data into mutable structures."""
    if isinstance(value, Mapping):
        return {key: _clone_config(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_clone_config(item) for item in value]
    return value


class TronbytCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinate Tronbyt device state via a shared API call."""

    def __init__(self, hass: HomeAssistant, base_url: str, token: str) -> None:
        self._base_url = base_url
        self._token = token
        super().__init__(
            hass,
            _LOGGER,
            name="tronbytassistant_devices",
            update_interval=timedelta(seconds=30),
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def token(self) -> str:
        return self._token

    async def _async_update_data(self) -> list[dict[str, Any]]:
        session = async_get_clientsession(self.hass)
        endpoint = f"{self._base_url}/v0/devices"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with session.get(endpoint, headers=headers) as response:
                if response.status == 401:
                    raise UpdateFailed("Invalid Tronbyt API key.")
                if response.status != 200:
                    error = await response.text()
                    raise UpdateFailed(
                        f"Failed to fetch devices ({response.status}): {error}"
                    )
                payload = await response.json()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error connecting to Tronbyt: {err}") from err

        devices: list[dict[str, Any]] = []
        install_tasks = []
        for item in payload.get("devices", []):
            device_id = item.get("id")
            if not device_id:
                continue

            night = item.get("nightMode") or {}
            dim = item.get("dimMode") or {}

            devices.append(
                {
                    "id": device_id,
                    "name": item.get("displayName") or device_id,
                    "type": item.get("type"),
                    "notes": item.get("notes"),
                    "interval": item.get("intervalSec"),
                    "brightness": item.get("brightness"),
                    "night_mode": {
                        "enabled": night.get("enabled"),
                        "app": night.get("app"),
                        "start": night.get("startTime"),
                        "end": night.get("endTime"),
                        "brightness": night.get("brightness"),
                    },
                    "dim_mode": {
                        "start": dim.get("startTime"),
                        "brightness": dim.get("brightness"),
                    },
                    "pinned_app": item.get("pinnedApp"),
                }
            )
            install_tasks.append(self._async_fetch_installations(session, device_id))

        if not devices:
            raise UpdateFailed("No Tronbyt devices were returned by the server.")

        if install_tasks:
            results = await asyncio.gather(*install_tasks, return_exceptions=True)
            for device, result in zip(devices, results):
                if isinstance(result, Exception):
                    _LOGGER.warning(
                        "Failed to fetch installations for %s: %s",
                        device["id"],
                        result,
                    )
                    device["installations"] = []
                else:
                    device["installations"] = result

        return devices

    async def async_patch_device(self, deviceid: str, payload: dict[str, Any]) -> None:
        session = async_get_clientsession(self.hass)
        url = f"{self._base_url}/v0/devices/{deviceid}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with session.patch(url, headers=headers, json=payload) as response:
            if response.status != 200:
                error = await response.text()
                raise HomeAssistantError(f"Failed to update device {deviceid}: {error}")

            device_payload = await response.json()

        install_payload = await self._async_fetch_installations(session, deviceid)

        self._merge_device_update(deviceid, device_payload, install_payload)

        self.async_set_updated_data(self.data)

    async def async_patch_installation(
        self, deviceid: str, installation_id: str, payload: dict[str, Any]
    ) -> None:
        session = async_get_clientsession(self.hass)
        url = f"{self._base_url}/v0/devices/{deviceid}/installations/{installation_id}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with session.patch(url, headers=headers, json=payload) as response:
            if response.status != 200:
                error = await response.text()
                raise HomeAssistantError(
                    f"Failed to update installation {installation_id}: {error}"
                )

            installation_payload = await response.json()

        self._merge_installation_update(deviceid, installation_payload)
        self.async_set_updated_data(self.data)

    async def _async_fetch_installations(
        self, session: aiohttp.ClientSession, deviceid: str
    ) -> list[dict[str, Any]]:
        url = f"{self._base_url}/v0/devices/{deviceid}/installations"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                error = await response.text()
                raise UpdateFailed(
                    f"Failed to fetch installations for {deviceid}: {error}"
                )
            payload = await response.json()
        return payload.get("installations", [])

    def _merge_device_update(
        self,
        deviceid: str,
        device_payload: dict[str, Any],
        installations: list[dict[str, Any]],
    ) -> None:
        if not self.data:
            return

        for idx, device in enumerate(self.data):
            if device.get("id") != deviceid:
                continue

            night = device_payload.get("nightMode") or {}
            dim = device_payload.get("dimMode") or {}

            updated = {
                "id": deviceid,
                "name": device_payload.get("displayName") or deviceid,
                "type": device_payload.get("type"),
                "notes": device_payload.get("notes"),
                "interval": device_payload.get("intervalSec"),
                "brightness": device_payload.get("brightness"),
                "night_mode": {
                    "enabled": night.get("enabled"),
                    "app": night.get("app"),
                    "start": night.get("startTime"),
                    "end": night.get("endTime"),
                    "brightness": night.get("brightness"),
                },
                "dim_mode": {
                    "start": dim.get("startTime"),
                    "brightness": dim.get("brightness"),
                },
                "pinned_app": device_payload.get("pinnedApp"),
                "installations": installations,
            }

            self.data[idx] = updated
            break

    def _merge_installation_update(
        self, deviceid: str, installation_payload: dict[str, Any]
    ) -> None:
        if not self.data:
            return

        install_id = installation_payload.get("id")
        if not install_id:
            return

        for device in self.data:
            if device.get("id") != deviceid:
                continue
            installs = device.setdefault("installations", [])
            for idx, install in enumerate(installs):
                if install.get("id") == install_id:
                    installs[idx] = installation_payload
                    break
            else:
                installs.append(installation_payload)
            break
