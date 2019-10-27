"""Support for LG WebOS TV notification service."""
import logging
import asyncio
from websockets.exceptions import ConnectionClosed

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.notify import (
    ATTR_DATA,
    BaseNotificationService,
    PLATFORM_SCHEMA,
)
from homeassistant.const import (
    CONF_FILENAME,
    CONF_HOST,
    CONF_ICON,
    EVENT_HOMEASSISTANT_STOP,
)

_LOGGER = logging.getLogger(__name__)

WEBOSTV_CONFIG_FILE = "webostv.conf"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_FILENAME, default=WEBOSTV_CONFIG_FILE): cv.string,
        vol.Optional(CONF_ICON): cv.string,
    }
)


async def async_get_service(hass, config, discovery_info=None):
    """Return the notify service."""
    from pylgtv import WebOsClient
    from pylgtv import PyLGTVPairException

    path = hass.config.path(config.get(CONF_FILENAME))
    client = WebOsClient(config.get(CONF_HOST), key_file_path=path, timeout_connect=8)

    if not client.is_registered():
        try:
            await client.connect()
            await client.disconnect()
        except PyLGTVPairException:
            _LOGGER.error("Pairing with TV failed")
            return None
        except OSError:
            _LOGGER.error("TV unreachable")
            return None

    svc = LgWebOSNotificationService(hass, client, config.get(CONF_ICON))
    svc.setup()
    return svc


class LgWebOSNotificationService(BaseNotificationService):
    """Implement the notification service for LG WebOS TV."""

    def __init__(self, hass, client, icon_path):
        """Initialize the service."""
        self.hass = hass
        self._client = client
        self._icon_path = icon_path

    def setup(self):
        """Listen for Home Assistant stop event."""

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.disconnect)

    async def disconnect(self, event):
        """Disconnect from TV."""
        await self._client.disconnect()

    async def async_send_message(self, message="", **kwargs):
        """Send a message to the tv."""
        from pylgtv import PyLGTVPairException, PyLGTVCmdException

        try:
            if not self._client.is_connected():
                await self._client.connect()

            data = kwargs.get(ATTR_DATA)
            icon_path = (
                data.get(CONF_ICON, self._icon_path) if data else self._icon_path
            )
            await self._client.send_message(message, icon_path=icon_path)
        except PyLGTVPairException:
            _LOGGER.error("Pairing with TV failed")
        except FileNotFoundError:
            _LOGGER.error("Icon %s not found", icon_path)
        except (
            OSError,
            ConnectionClosed,
            ConnectionRefusedError,
            asyncio.TimeoutError,
            asyncio.CancelledError,
            PyLGTVCmdException,
        ):
            _LOGGER.error("TV unreachable")
