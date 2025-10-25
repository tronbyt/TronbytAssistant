from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import aiofiles
import aiohttp
import voluptuous as vol
import yaml

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_TOKEN,
    ATTR_ARGS,
    ATTR_COLOR,
    ATTR_CONTENT,
    ATTR_CONTENT_ID,
    ATTR_CONT_TYPE,
    ATTR_CUSTOM_CONT,
    ATTR_DEVICENANME,
    ATTR_FONT,
    ATTR_LANG,
    ATTR_PUBLISH_TYPE,
    ATTR_TEXT_TYPE,
    ATTR_TITLE_COLOR,
    ATTR_TITLE_CONTENT,
    ATTR_TITLE_FONT,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SWITCH]

DATA_CONFIG = "config"
DATA_SERVICES_REGISTERED = "services_registered"
DATA_DEVICES = "devices"

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
    hass.data[DOMAIN][DATA_CONFIG] = conf

    await _async_register_services(hass)
    await _async_prepare_devices(hass, conf)
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
        data.pop(DATA_DEVICES, None)
        if data.get(DATA_SERVICES_REGISTERED):
            _async_remove_services(hass)

    return True


async def _async_prepare_devices(hass: HomeAssistant, conf: dict[str, Any]) -> None:
    """Fetch devices from Tronbyt and update services.yaml selectors."""
    api_url = conf[CONF_API_URL]
    token = conf[CONF_TOKEN]

    devices = await _async_fetch_devices(api_url, token)
    if not devices:
        raise HomeAssistantError(
            "No Tronbyt devices were returned by the server. Verify your API key."
        )

    hass.data[DOMAIN][DATA_DEVICES] = devices
    await _async_update_services_yaml(hass, [device["name"] for device in devices])


async def _async_fetch_devices(api_url: str, token: str) -> list[dict[str, Any]]:
    """Fetch devices available to the provided Tronbyt user token."""
    endpoint = f"{api_url}/v0/devices"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(endpoint, headers=headers) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("Failed to fetch devices: %s", error)
                    raise HomeAssistantError("Failed to fetch devices from Tronbyt.")
                payload = await response.json()
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Error connecting to Tronbyt at {endpoint}: {err}"
            ) from err

    devices: list[dict[str, Any]] = []
    for item in payload.get("devices", []):
        device_id = item.get("id")
        if not device_id:
            continue

        name = item.get("displayName") or device_id
        devices.append(
            {
                "id": device_id,
                "name": name,
                "brightness": item.get("brightness"),
                "autoDim": item.get("autoDim"),
            }
        )

    return devices


async def _async_update_services_yaml(
    hass: HomeAssistant, devicenames: list[str]
) -> None:
    """Update services.yaml selectors based on current configuration."""
    config_dir = hass.config.path()
    yaml_path = os.path.join(
        config_dir,
        "custom_components",
        DOMAIN,
        "services.yaml",
    )

    try:
        async with aiofiles.open(yaml_path) as file:
            content = await file.read()
    except FileNotFoundError as exc:
        raise HomeAssistantError(
            f"services.yaml not found for {DOMAIN} integration."
        ) from exc

    services_config = yaml.safe_load(content) or {}
    device_name_options = [{"label": name, "value": name} for name in devicenames]

    for service in services_config.values():
        fields = service.get("fields")
        if not fields:
            continue
        devicename_field = fields.get(ATTR_DEVICENANME)
        if not devicename_field:
            continue
        selector = devicename_field.get("selector", {}).get("select")
        if selector is not None:
            selector["options"] = device_name_options

    async with aiofiles.open(yaml_path, "w") as file:
        await file.write(
            yaml.dump(services_config, default_flow_style=False, sort_keys=False)
        )


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register the Tronbyt service handlers once."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(DATA_SERVICES_REGISTERED):
        return

    def _get_config() -> dict[str, Any]:
        conf = hass.data.get(DOMAIN, {}).get(DATA_CONFIG)
        if not conf:
            raise HomeAssistantError("TronbytAssistant configuration is not available.")
        return conf

    def _get_device_lookup() -> dict[str, dict[str, Any]]:
        devices = hass.data.get(DOMAIN, {}).get(DATA_DEVICES)
        if not devices:
            raise HomeAssistantError(
                "No Tronbyt devices are loaded. Reload the integration."
            )
        return {device["name"]: device for device in devices}

    def validateid(input_value: str) -> bool:
        """Check if the string contains only A-Z, a-z, and 0-9."""
        pattern = r"^[A-Za-z0-9]+$"
        return bool(re.match(pattern, input_value))

    async def getinstalledapps(
        endpoint: str, deviceid: str, token: str, only_pushed: bool = True
    ) -> list[str]:
        url = f"{endpoint}/v0/devices/{deviceid}/installations"
        header = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with aiohttp.ClientSession() as session:
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
        headers: dict[str, str] | None = None,
    ) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, webhook_url, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)
                    raise HomeAssistantError(error)

    def tronbyt_headers(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def handle_push_or_text(call: ServiceCall, is_text: bool) -> None:
        conf = _get_config()
        device_lookup = _get_device_lookup()

        base_url = conf[CONF_API_URL]
        token = conf[CONF_TOKEN]

        contentid = call.data.get(ATTR_CONTENT_ID, DEFAULT_CONTENT_ID)
        publishtype = call.data.get(ATTR_PUBLISH_TYPE)
        devicename = call.data.get(ATTR_DEVICENANME)

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

        for device in devicename:
            info = device_lookup.get(device)
            if info is None:
                raise HomeAssistantError(f"{device} is not a known Tronbyt device.")

            deviceid = info["id"]
            api_url = f"{base_url}/v0/devices/{deviceid}/push_app"
            body = {
                "config": arguments,
                "app_id": content,
                "installationID": contentid,
            }
            if publishtype:
                body["publish"] = publishtype
            await request("POST", api_url, body, headers=tronbyt_headers(token))

    async def pixlet_push(call: ServiceCall) -> None:
        await handle_push_or_text(call, is_text=False)

    async def pixlet_text(call: ServiceCall) -> None:
        await handle_push_or_text(call, is_text=True)

    async def pixlet_delete(call: ServiceCall) -> None:
        conf = _get_config()
        device_lookup = _get_device_lookup()

        contentid = call.data.get(ATTR_CONTENT_ID)
        if not validateid(contentid):
            _LOGGER.error("Content ID must contain characters A-Z, a-z or 0-9")
            raise HomeAssistantError(
                "Content ID must contain characters A-Z, a-z or 0-9"
            )

        base_url = conf[CONF_API_URL]
        token = conf[CONF_TOKEN]
        devicename = call.data.get(ATTR_DEVICENANME)
        for device in devicename:
            info = device_lookup.get(device)
            if info is None:
                raise HomeAssistantError(f"{device} is not a known Tronbyt device.")

            deviceid = info["id"]

            validids = await getinstalledapps(base_url, deviceid, token)
            if contentid not in validids:
                _LOGGER.error(
                    "The Content ID you entered is not an installed app on %s. Currently installed apps are: %s",
                    device,
                    validids,
                )
                raise HomeAssistantError(
                    f"The Content ID you entered is not an installed app on {device}. Currently installed apps are: {validids}"
                )

            url = f"{base_url}/v0/devices/{deviceid}/installations/{contentid}"
            await request("DELETE", url, {}, headers=tronbyt_headers(token))

    async def handle_installation_update(
        call: ServiceCall, payload: dict[str, Any]
    ) -> None:
        conf = _get_config()
        device_lookup = _get_device_lookup()

        contentid = call.data.get(ATTR_CONTENT_ID)
        if not validateid(contentid):
            _LOGGER.error("Content ID must contain characters A-Z, a-z or 0-9")
            raise HomeAssistantError(
                "Content ID must contain characters A-Z, a-z or 0-9"
            )

        base_url = conf[CONF_API_URL]
        token = conf[CONF_TOKEN]
        devicename = call.data.get(ATTR_DEVICENANME)
        for device in devicename:
            info = device_lookup.get(device)
            if info is None:
                raise HomeAssistantError(f"{device} is not a known Tronbyt device.")

            deviceid = info["id"]

            validids = await getinstalledapps(
                base_url, deviceid, token, only_pushed=False
            )
            if contentid not in validids:
                _LOGGER.error(
                    "The Content ID you entered is not an installed app on %s. Currently installed apps are: %s",
                    device,
                    validids,
                )
                raise HomeAssistantError(
                    f"The Content ID you entered is not an installed app on {device}. Currently installed apps are: {validids}"
                )

            endpoint = f"{base_url}/v0/devices/{deviceid}/installations/{contentid}"
            await request("PATCH", endpoint, payload, headers=tronbyt_headers(token))

    async def pixlet_enable(call: ServiceCall) -> None:
        await handle_installation_update(call, {"set_enabled": True})

    async def pixlet_disable(call: ServiceCall) -> None:
        await handle_installation_update(call, {"set_enabled": False})

    async def pixlet_pin(call: ServiceCall) -> None:
        await handle_installation_update(call, {"set_pinned": True})

    async def pixlet_unpin(call: ServiceCall) -> None:
        await handle_installation_update(call, {"set_pinned": False})

    hass.services.async_register(DOMAIN, "push", pixlet_push)
    hass.services.async_register(DOMAIN, "text", pixlet_text)
    hass.services.async_register(DOMAIN, "delete", pixlet_delete)
    hass.services.async_register(DOMAIN, "enable_app", pixlet_enable)
    hass.services.async_register(DOMAIN, "disable_app", pixlet_disable)
    hass.services.async_register(DOMAIN, "pin_app", pixlet_pin)
    hass.services.async_register(DOMAIN, "unpin_app", pixlet_unpin)

    data[DATA_SERVICES_REGISTERED] = True


def _async_remove_services(hass: HomeAssistant) -> None:
    """Remove domain services."""
    for service in (
        "push",
        "text",
        "delete",
        "enable_app",
        "disable_app",
        "pin_app",
        "unpin_app",
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
