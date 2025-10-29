from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tronbytassistant.config_flow import (
    CannotConnect,
    InvalidAuth,
    NoDevicesFound,
    TronbytAssistantConfigFlow,
    _normalize_base_url,
)
from custom_components.tronbytassistant.const import (
    CONF_API_URL,
    CONF_TOKEN,
    CONF_VERIFY_SSL,
    DOMAIN,
)


def _get_suggested_value(schema: vol.Schema, field: str):
    for key in schema.schema:
        if getattr(key, "schema", None) == field:
            description = getattr(key, "description", None) or {}
            if "suggested_value" in description:
                return description["suggested_value"]
            default = getattr(key, "default", None)
            if default is None:
                return None
            if callable(default):
                return default()
            return default
    raise AssertionError(f"Field {field} not present in schema")


@pytest.mark.asyncio
async def test_user_flow_success(hass):
    """Validate that a user initiated flow succeeds."""
    device_payload = [{"id": "961adee8", "name": "Living Room"}]
    with patch.object(
        TronbytAssistantConfigFlow,
        "_async_fetch_devices",
        AsyncMock(return_value=device_payload),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_API_URL: "https://example.com", CONF_TOKEN: "secret"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "example.com"
    assert result["data"][CONF_TOKEN] == "secret"
    assert result["data"][CONF_VERIFY_SSL] is True


@pytest.mark.asyncio
async def test_user_flow_rejects_bad_url(hass):
    """Ensure invalid URLs surface an error on the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_API_URL: "example.com", CONF_TOKEN: "secret"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_url"

    schema = result["data_schema"]
    assert _get_suggested_value(schema, CONF_API_URL) == "example.com"
    assert _get_suggested_value(schema, CONF_TOKEN) == "secret"
    assert _get_suggested_value(schema, CONF_VERIFY_SSL) is True


@pytest.mark.asyncio
async def test_user_flow_invalid_auth(hass):
    """Ensure authentication errors are reported."""
    with patch.object(
        TronbytAssistantConfigFlow,
        "_async_fetch_devices",
        AsyncMock(side_effect=InvalidAuth),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_API_URL: "https://example.com", CONF_TOKEN: "bad"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_api_key"

    schema = result["data_schema"]
    assert _get_suggested_value(schema, CONF_API_URL) == "https://example.com"
    assert _get_suggested_value(schema, CONF_TOKEN) == "bad"
    assert _get_suggested_value(schema, CONF_VERIFY_SSL) is True


@pytest.mark.asyncio
async def test_user_flow_cannot_connect(hass):
    """Ensure connectivity errors are reported."""
    with patch.object(
        TronbytAssistantConfigFlow,
        "_async_fetch_devices",
        AsyncMock(side_effect=CannotConnect),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_API_URL: "https://example.com", CONF_TOKEN: "token"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"

    schema = result["data_schema"]
    assert _get_suggested_value(schema, CONF_API_URL) == "https://example.com"
    assert _get_suggested_value(schema, CONF_TOKEN) == "token"
    assert _get_suggested_value(schema, CONF_VERIFY_SSL) is True


@pytest.mark.asyncio
async def test_user_flow_no_devices(hass):
    """Ensure the flow stops when no devices are returned."""
    with patch.object(
        TronbytAssistantConfigFlow,
        "_async_fetch_devices",
        AsyncMock(side_effect=NoDevicesFound),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_API_URL: "https://example.com", CONF_TOKEN: "token"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "no_devices_found"

    schema = result["data_schema"]
    assert _get_suggested_value(schema, CONF_API_URL) == "https://example.com"
    assert _get_suggested_value(schema, CONF_TOKEN) == "token"
    assert _get_suggested_value(schema, CONF_VERIFY_SSL) is True


@pytest.mark.asyncio
async def test_import_flow_success(hass):
    """Validate YAML import flow."""
    with patch.object(
        TronbytAssistantConfigFlow,
        "_async_fetch_devices",
        AsyncMock(return_value=[{"id": "961adee8", "name": "Living Room"}]),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={CONF_API_URL: "https://example.com/api/", CONF_TOKEN: "secret"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_URL] == "https://example.com/api"
    assert result["data"][CONF_VERIFY_SSL] is True


@pytest.mark.asyncio
async def test_import_flow_invalid_input(hass):
    """Ensure invalid YAML imports abort with an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={CONF_API_URL: "invalid-url", CONF_TOKEN: "secret"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_import"


def test_config_flow_normalize_base_url():
    """Verify URL normalization mirrors the coordinator helper."""
    assert _normalize_base_url("https://example.com/") == "https://example.com"
    assert (
        _normalize_base_url("https://example.com/base/") == "https://example.com/base"
    )

    with pytest.raises(ValueError):
        _normalize_base_url("")

    with pytest.raises(ValueError):
        _normalize_base_url("example.com")


@pytest.mark.asyncio
async def test_user_flow_preserves_verify_ssl_toggle(hass):
    """Ensure toggled SSL flag persists after an error."""
    with patch.object(
        TronbytAssistantConfigFlow,
        "_async_fetch_devices",
        AsyncMock(side_effect=CannotConnect),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={
                CONF_API_URL: "https://example.com",
                CONF_TOKEN: "secret",
                CONF_VERIFY_SSL: False,
            },
        )

    assert result["errors"]["base"] == "cannot_connect"
    schema = result["data_schema"]
    assert _get_suggested_value(schema, CONF_API_URL) == "https://example.com"
    assert _get_suggested_value(schema, CONF_TOKEN) == "secret"
    assert _get_suggested_value(schema, CONF_VERIFY_SSL) is False
