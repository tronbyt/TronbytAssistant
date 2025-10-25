from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Mapping
from typing import Any

import aiofiles
import aiohttp
import voluptuous as vol
import yaml

from homeassistant import config_entries
from homeassistant.components.hassio import AddonManager, AddonState
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .addon import get_addon_manager
from .const import (
    DOMAIN,
    CONF_DEVICE,
    CONF_TOKEN,
    CONF_ID,
    CONF_PORT,
    CONF_HOST,
    CONF_NAME,
    CONF_EXTERNALADDON,
    CONF_API_URL,
    CONF_TRONBYT,
    ATTR_CONTENT,
    ATTR_CONTENT_ID,
    ATTR_DEVICENANME,
    ATTR_CONT_TYPE,
    ATTR_CUSTOM_CONT,
    ATTR_TEXT_TYPE,
    ATTR_FONT,
    ATTR_COLOR,
    ATTR_TITLE_CONTENT,
    ATTR_TITLE_COLOR,
    ATTR_TITLE_FONT,
    ATTR_ARGS,
    ATTR_PUBLISH_TYPE,
    ATTR_LANG,
    ADDON_MIN_VERSION,
    DEFAULT_API_URL,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_EXTERNAL_ADDON,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SWITCH]

DATA_CONFIG = "config"
DATA_OPTIONAL_SERVICES = "optional_services"
DATA_OPTIONAL_REGISTERED = "optional_registered"
DATA_SERVICES_REGISTERED = "services_registered"

DEFAULT_TITLE = ""
DEFAULT_TITLE_COLOR = ""
DEFAULT_TITLE_FONT = ""
DEFAULT_ARGS = ""
DEFAULT_CONTENT_ID = ""
DEFAULT_LANG = "en"

TIDBYT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME): cv.string,
        vol.Required(CONF_ID): cv.string,
        vol.Required(CONF_TOKEN): cv.string,
        vol.Optional(CONF_API_URL): cv.string,
        vol.Optional(CONF_TRONBYT): cv.boolean,
    }
)
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_DEVICE): vol.All(cv.ensure_list, [TIDBYT_SCHEMA]),
                vol.Optional(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT): cv.string,
                vol.Optional(CONF_EXTERNALADDON): cv.boolean,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def getdevicename(endpoint: str, deviceid: str, token: str) -> str | None:
    url = f"{endpoint}/v0/devices/{deviceid}"
    header = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=header) as response:
            if response.status != 200:
                _LOGGER.warning(
                    "Unable to retrieve device name from %s for %s (status: %s)",
                    endpoint,
                    deviceid,
                    response.status,
                )
                return None
            data = await response.json()
    return data.get("displayName")


@callback
def _get_addon_manager(hass: HomeAssistant) -> AddonManager:
    addon_manager: AddonManager = get_addon_manager(hass)
    if addon_manager.task_in_progress():
        raise ConfigEntryNotReady
    return addon_manager


def is_min_version(version1: str, version2: str) -> bool:
    v1_parts = list(map(int, version1.split(".")))
    v2_parts = list(map(int, version2.split(".")))

    max_length = max(len(v1_parts), len(v2_parts))
    v1_parts.extend([0] * (max_length - len(v1_parts)))
    v2_parts.extend([0] * (max_length - len(v2_parts)))

    for v1, v2 in zip(v1_parts, v2_parts):
        if v1 > v2:
            return True
        if v1 < v2:
            return False

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up TidbytAssistant from YAML."""
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
    """Set up TidbytAssistant from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    conf = _clone_config(entry.data)
    hass.data[DOMAIN][DATA_CONFIG] = conf

    await _async_register_services(hass)

    has_tidbyt = await _async_process_configuration(hass, conf)
    _async_update_optional_services(hass, has_tidbyt)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    data = hass.data.get(DOMAIN)
    if data is not None:
        data.pop(DATA_CONFIG, None)
        if data.get(DATA_OPTIONAL_REGISTERED):
            _async_remove_optional_services(hass)
        if data.get(DATA_SERVICES_REGISTERED):
            _async_remove_services(hass)

    return True


def _clone_config(value: Any) -> Any:
    """Clone Home Assistant entry data into mutable structures."""
    if isinstance(value, Mapping):
        return {key: _clone_config(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_clone_config(item) for item in value]
    return value


async def _async_process_configuration(
    hass: HomeAssistant, conf: dict[str, Any]
) -> bool:
    """Prepare runtime data, verify connectivity and update service selectors."""
    devices = conf.get(CONF_DEVICE, [])
    if not devices:
        raise HomeAssistantError("At least one Tidbyt device must be configured.")

    host = conf.get(CONF_HOST, DEFAULT_HOST)
    port = conf.get(CONF_PORT, DEFAULT_PORT)
    external_addon = conf.get(CONF_EXTERNALADDON, DEFAULT_EXTERNAL_ADDON)
    url = f"http://{host}:{port}"

    has_tidbyt = False
    devicelist: list[str] = []

    for device in devices:
        if not device.get(CONF_TRONBYT, False):
            has_tidbyt = True

        dev_name = device.get(CONF_NAME)
        if not dev_name:
            retrievedname = await getdevicename(
                device.get(CONF_API_URL, DEFAULT_API_URL),
                device[CONF_ID],
                device[CONF_TOKEN],
            )
            if retrievedname:
                dev_name = retrievedname
            else:
                dev_name = device[CONF_ID]
            device[CONF_NAME] = dev_name
        devicelist.append(dev_name)

    if has_tidbyt:
        if not external_addon:
            addon_manager = _get_addon_manager(hass)
            addon_info = await addon_manager.async_get_addon_info()
            addon_state = addon_info.state
            addon_current_ver = addon_info.version
            if addon_state == AddonState.NOT_INSTALLED:
                _LOGGER.error(
                    "The add-on is not installed. Make sure it is installed and try again."
                )
                raise ConfigEntryNotReady
            if not is_min_version(addon_current_ver, ADDON_MIN_VERSION):
                _LOGGER.error(
                    "The minimum required add-on version is %s but the currently installed version is %s. Please update the add-on to the latest version.",
                    ADDON_MIN_VERSION,
                    addon_current_ver,
                )
                raise ConfigEntryNotReady
        else:
            timeout = time.time() + 60
            while True:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"{url}/apps") as response:
                            if response.status == 200:
                                break
                except aiohttp.ClientError:
                    pass
                if time.time() > timeout:
                    _LOGGER.error(
                        "Connection to add-on timed out after 60 seconds. Make sure it is installed or running and try again."
                    )
                    raise ConfigEntryNotReady
                await asyncio.sleep(5)

    await _async_update_services_yaml(hass, devicelist, has_tidbyt, url)

    return has_tidbyt


async def _async_update_services_yaml(
    hass: HomeAssistant, devicelist: list[str], has_tidbyt: bool, url: str
) -> None:
    """Update services.yaml selectors based on current configuration."""
    config_dir = hass.config.path()
    yaml_path = os.path.join(config_dir, "custom_components", DOMAIN, "services.yaml")

    try:
        async with aiofiles.open(yaml_path) as file:
            content = await file.read()
    except FileNotFoundError as exc:
        raise HomeAssistantError(
            f"services.yaml not found for {DOMAIN} integration."
        ) from exc

    services_config = yaml.safe_load(content) or {}

    device_name_options = [{"label": name, "value": name} for name in devicelist]

    for service in services_config.values():
        fields = service.get("fields")
        if not fields:
            continue
        devicename_field = fields.get(ATTR_DEVICENANME)
        if devicename_field and "selector" in devicename_field:
            selector = devicename_field["selector"].get("select")
            if selector is not None:
                selector["options"] = device_name_options

    if has_tidbyt:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}/apps") as response:
                if response.status != 200:
                    error = await response.text()
                    _LOGGER.error("%s", error)
                    raise HomeAssistantError(error)
                data = await response.json()
        content_options = [
            {"label": item["label"], "value": item["value"]} for item in data
        ]
        push_fields = services_config.get("push", {}).get("fields", {})
        content_field = push_fields.get(ATTR_CONTENT)
        if content_field and "selector" in content_field:
            selector = content_field["selector"].get("select")
            if selector is not None:
                selector["options"] = content_options

    async with aiofiles.open(yaml_path, "w") as file:
        await file.write(
            yaml.dump(services_config, default_flow_style=False, sort_keys=False)
        )


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services once."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(DATA_SERVICES_REGISTERED):
        return

    def _get_config() -> dict[str, Any]:
        conf = hass.data.get(DOMAIN, {}).get(DATA_CONFIG)
        if not conf:
            raise HomeAssistantError("TidbytAssistant configuration is not available.")
        return conf

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

        host = conf.get(CONF_HOST, DEFAULT_HOST)
        port = conf.get(CONF_PORT, DEFAULT_PORT)
        url = f"http://{host}:{port}/push"

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
                    key, value = pair.split("=")
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
            for item in conf[CONF_DEVICE]:
                if item[CONF_NAME] != device:
                    continue

                token = item[CONF_TOKEN]
                deviceid = item[CONF_ID]
                is_tronbyt = item.get(CONF_TRONBYT, False)
                if is_tronbyt:
                    api_url = f"{item.get(CONF_API_URL, DEFAULT_API_URL)}/v0/devices/{deviceid}/push_app"
                    body = {
                        "config": arguments,
                        "app_id": content,
                        "installationID": contentid,
                    }
                    await request("POST", api_url, body, headers=tronbyt_headers(token))
                else:
                    todo: dict[str, Any] = {
                        "content": content,
                        "contentid": contentid,
                        "contenttype": contenttype,
                        "publishtype": publishtype,
                        "token": token,
                        "deviceid": deviceid,
                        "starargs": arguments,
                    }
                    if is_text:
                        todo["texttype"] = texttype
                    if CONF_API_URL in item:
                        todo["base_url"] = item[CONF_API_URL]
                    await request("POST", url, todo)

    async def pixlet_push(call: ServiceCall) -> None:
        await handle_push_or_text(call, is_text=False)

    async def pixlet_text(call: ServiceCall) -> None:
        await handle_push_or_text(call, is_text=True)

    async def pixlet_delete(call: ServiceCall) -> None:
        conf = _get_config()

        contentid = call.data.get(ATTR_CONTENT_ID)
        if not validateid(contentid):
            _LOGGER.error("Content ID must contain characters A-Z, a-z or 0-9")
            raise HomeAssistantError(
                "Content ID must contain characters A-Z, a-z or 0-9"
            )

        devicename = call.data.get(ATTR_DEVICENANME)
        for device in devicename:
            for item in conf[CONF_DEVICE]:
                if item[CONF_NAME] != device:
                    continue

                token = item[CONF_TOKEN]
                deviceid = item[CONF_ID]
                base_url = item.get(CONF_API_URL, DEFAULT_API_URL)

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

        contentid = call.data.get(ATTR_CONTENT_ID)
        if not validateid(contentid):
            _LOGGER.error("Content ID must contain characters A-Z, a-z or 0-9")
            raise HomeAssistantError(
                "Content ID must contain characters A-Z, a-z or 0-9"
            )

        devicename = call.data.get(ATTR_DEVICENANME)
        for device in devicename:
            for item in conf[CONF_DEVICE]:
                if item[CONF_NAME] != device:
                    continue
                if not item.get(CONF_TRONBYT, False):
                    raise HomeAssistantError(
                        f"{device} is not configured as a Tronbyt device."
                    )

                token = item[CONF_TOKEN]
                deviceid = item[CONF_ID]
                base_url = item.get(CONF_API_URL, DEFAULT_API_URL)

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
                await request(
                    "PATCH", endpoint, payload, headers=tronbyt_headers(token)
                )

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

    data[DATA_OPTIONAL_SERVICES] = {
        "enable_app": pixlet_enable,
        "disable_app": pixlet_disable,
        "pin_app": pixlet_pin,
        "unpin_app": pixlet_unpin,
    }
    data[DATA_SERVICES_REGISTERED] = True


def _async_update_optional_services(hass: HomeAssistant, has_tidbyt: bool) -> None:
    """Register or remove Tronbyt-only services based on configuration."""
    data = hass.data.setdefault(DOMAIN, {})
    optional = data.get(DATA_OPTIONAL_SERVICES) or {}
    if has_tidbyt:
        if data.get(DATA_OPTIONAL_REGISTERED):
            _async_remove_optional_services(hass)
        return

    if data.get(DATA_OPTIONAL_REGISTERED):
        return

    for name, handler in optional.items():
        hass.services.async_register(DOMAIN, name, handler)
    data[DATA_OPTIONAL_REGISTERED] = True


def _async_remove_optional_services(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    optional = data.get(DATA_OPTIONAL_SERVICES) or {}
    for name in optional:
        hass.services.async_remove(DOMAIN, name)
    data[DATA_OPTIONAL_REGISTERED] = False


def _async_remove_services(hass: HomeAssistant) -> None:
    """Remove all services for the domain."""
    hass.services.async_remove(DOMAIN, "push")
    hass.services.async_remove(DOMAIN, "text")
    hass.services.async_remove(DOMAIN, "delete")
    _async_remove_optional_services(hass)
    hass.data.setdefault(DOMAIN, {})[DATA_SERVICES_REGISTERED] = False
