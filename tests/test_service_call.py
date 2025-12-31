from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.core import HomeAssistant
from custom_components.tronbytassistant.const import (
    DOMAIN,
    CONF_API_URL,
    CONF_TOKEN,
    CONF_VERIFY_SSL,
    ATTR_DEVICENANME,
    ATTR_CONTENT,
    ATTR_CONT_TYPE,
    ATTR_ARGS,
)
from custom_components.tronbytassistant import async_setup_entry

@pytest.fixture
def mock_coordinator():
    with patch("custom_components.tronbytassistant.TronbytCoordinator") as MockCoordinator:
        instance = MockCoordinator.return_value
        instance.base_url = "http://test.com"
        instance.token = "test-token"
        instance.verify_ssl = True
        instance.data = [
            {"id": "device1", "name": "Test Device", "installations": []}
        ]
        instance.async_config_entry_first_refresh = AsyncMock()
        instance.async_request_refresh = AsyncMock()
        yield instance

@pytest.fixture
def mock_session():
    with patch("custom_components.tronbytassistant.async_get_clientsession") as mock_sess:
        session = mock_sess.return_value
        # Mock request context manager
        session.request.return_value.__aenter__.return_value.status = 200
        yield session

@pytest.mark.asyncio
async def test_push_service_arguments_builtin(hass: HomeAssistant, mock_coordinator, mock_session):
    # Setup the integration
    config_entry = AsyncMock()
    config_entry.data = {
        CONF_API_URL: "http://test.com",
        CONF_TOKEN: "test-token",
        CONF_VERIFY_SSL: True
    }
    config_entry.domain = DOMAIN

    # We need to ensure the coordinator used by async_setup_entry is our mock
    # The code instantiates TronbytCoordinator, so our patch in the fixture handles it.

    await async_setup_entry(hass, config_entry)

    # Verify service registration
    assert hass.services.has_service(DOMAIN, "push")

    # Call the service
    data = {
        ATTR_DEVICENANME: "Test Device", # Use name to avoid mocking device registry
        ATTR_CONTENT: "emoji-text",
        ATTR_CONT_TYPE: "builtin",
        ATTR_ARGS: "main_text=Wifey;main_color=#00A500;emoji=🚙"
    }

    await hass.services.async_call(DOMAIN, "push", data, blocking=True)

    # assert request was called
    mock_session.request.assert_called()

    # Check arguments
    # Expected: The "config" dict should contain the parsed arguments
    # Current Bug: "config" will be empty {}

    calls = mock_session.request.call_args_list
    # Find the POST call to push_app
    post_call = next(
        (c for c in calls if "push_app" in c[0][1] and c[0][0] == "POST"),
        None
    )

    assert post_call is not None, "push_app was not called"

    payload = post_call.kwargs.get("json")
    assert payload is not None

    # This assertion should FAIL if the bug is present
    assert payload["config"] == {
        "main_text": "Wifey",
        "main_color": "#00A500",
        "emoji": "🚙"
    }
