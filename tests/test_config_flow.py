from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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
    assert result["errors"]["base"] == "invalid_auth"


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
    assert result["errors"]["base"] == "no_devices"


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
