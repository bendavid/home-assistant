"""Support for interface with an LG webOS Smart TV."""
from functools import wraps
import asyncio
from datetime import timedelta
import logging
from urllib.parse import urlparse
from typing import Dict
from websockets.exceptions import ConnectionClosed

from pylgtv import WebOsClient
from pylgtv import PyLGTVPairException, PyLGTVCmdException

import voluptuous as vol

from homeassistant import util
from homeassistant.components.media_player import MediaPlayerDevice, PLATFORM_SCHEMA
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_CHANNEL,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP,
    SUPPORT_COMMAND,
)
from homeassistant.const import (
    CONF_CUSTOMIZE,
    CONF_FILENAME,
    CONF_HOST,
    CONF_NAME,
    CONF_TIMEOUT,
    STATE_OFF,
    STATE_PAUSED,
    STATE_PLAYING,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

_CONFIGURING: Dict[str, str] = {}
_LOGGER = logging.getLogger(__name__)

CONF_SOURCES = "sources"
CONF_ON_ACTION = "turn_on_action"

DEFAULT_NAME = "LG webOS Smart TV"
LIVETV_APP_ID = "com.webos.app.livetv"

WEBOSTV_CONFIG_FILE = "webostv.conf"

SUPPORT_WEBOSTV = (
    SUPPORT_TURN_OFF
    | SUPPORT_NEXT_TRACK
    | SUPPORT_PAUSE
    | SUPPORT_PREVIOUS_TRACK
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_STEP
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_PLAY_MEDIA
    | SUPPORT_PLAY
    | SUPPORT_COMMAND
)

MIN_TIME_BETWEEN_SCANS = timedelta(seconds=10)
MIN_TIME_BETWEEN_FORCED_SCANS = timedelta(seconds=1)

CUSTOMIZE_SCHEMA = vol.Schema(
    {vol.Optional(CONF_SOURCES): vol.All(cv.ensure_list, [cv.string])}
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_CUSTOMIZE, default={}): CUSTOMIZE_SCHEMA,
        vol.Optional(CONF_FILENAME, default=WEBOSTV_CONFIG_FILE): cv.string,
        vol.Optional(CONF_HOST): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_ON_ACTION): cv.SCRIPT_SCHEMA,
        vol.Optional(CONF_TIMEOUT, default=1): cv.positive_int,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the LG WebOS TV platform."""
    if discovery_info is not None:
        host = urlparse(discovery_info[1]).hostname
    else:
        host = config.get(CONF_HOST)

    if host is None:
        _LOGGER.error("No TV found in configuration file or with discovery")
        return False

    # Only act if we are not already configuring this host
    if host in _CONFIGURING:
        return

    name = config.get(CONF_NAME)
    customize = config.get(CONF_CUSTOMIZE)
    timeout = config.get(CONF_TIMEOUT)
    turn_on_action = config.get(CONF_ON_ACTION)

    config = hass.config.path(config.get(CONF_FILENAME))

    await async_setup_tv(
        host, name, customize, config, timeout, hass, async_add_entities, turn_on_action
    )


async def async_setup_tv(
    host, name, customize, config, timeout, hass, async_add_entities, turn_on_action
):
    """Set up a LG WebOS TV based on host parameter."""

    # client = WebOsClient(host, config, timeout)
    device = LgWebOSDevice(host, name, customize, config, timeout, hass, turn_on_action)

    if not device._client.is_registered():
        _LOGGER.warning("Not Paired")
        if host in _CONFIGURING:
            # Try to pair.
            try:
                await device._client.connect()
                await device._client.disconnect()
            except PyLGTVPairException:
                _LOGGER.warning("Connected to LG webOS TV %s but not paired", host)
                return
            except (
                OSError,
                ConnectionClosed,
                ConnectionRefusedError,
                asyncio.TimeoutError,
                asyncio.CancelledError,
                PyLGTVCmdException,
            ):
                _LOGGER.error("Unable to connect to host %s", host)
                return
        else:
            # Not registered, request configuration.
            _LOGGER.warning("LG webOS TV %s needs to be paired", host)
            await async_request_configuration(
                host,
                name,
                customize,
                config,
                timeout,
                hass,
                async_add_entities,
                turn_on_action,
            )
            return

    # If we came here and configuring this host, mark as done.
    if device._client.is_registered() and host in _CONFIGURING:
        request_id = _CONFIGURING.pop(host)
        configurator = hass.components.configurator
        configurator.async_request_done(request_id)

    device.setup()
    async_add_entities([device], update_before_add=True)


async def async_request_configuration(
    host, name, customize, config, timeout, hass, add_entities, turn_on_action
):
    """Request configuration steps from the user."""
    configurator = hass.components.configurator

    _LOGGER.warning("request configuration")

    # We got an error if this method is called while we are configuring
    if host in _CONFIGURING:
        _LOGGER.warning("host in configuring")
        await configurator.async_notify_errors(
            _CONFIGURING[host], "Failed to pair, please try again."
        )
        return

    async def lgtv_configuration_callback(data):
        """Handle actions when configuration callback is called."""
        await async_setup_tv(
            host, name, customize, config, timeout, hass, add_entities, turn_on_action
        )

    _LOGGER.warning("adding host to configuring")
    _CONFIGURING[host] = configurator.async_request_config(
        name,
        lgtv_configuration_callback,
        description="Click start and accept the pairing request on your TV.",
        description_image="/static/images/config_webos.png",
        submit_caption="Start pairing request",
    )


def cmd(func):
    """Catch command exceptions."""

    @wraps(func)
    async def wrapper(obj, *args, **kwargs):
        """Wrap all command methods."""
        try:
            await func(obj, *args, **kwargs)
        except (
            asyncio.TimeoutError,
            asyncio.CancelledError,
            PyLGTVCmdException,
        ) as exc:
            # If TV is off, we expect calls to fail.
            if obj.state == STATE_OFF:
                log_function = _LOGGER.info
            else:
                log_function = _LOGGER.error
            log_function(
                "Error calling %s on entity %s: %r", func.__name__, obj.entity_id, exc
            )

    return wrapper


class LgWebOSDevice(MediaPlayerDevice):
    """Representation of a LG WebOS TV."""

    def __init__(self, host, name, customize, config, timeout, hass, on_action):
        """Initialize the webos device."""
        self.hass = hass

        self._client = WebOsClient(host, config, timeout)
        self._on_script = Script(hass, on_action) if on_action else None
        self._customize = customize

        self._name = name
        # Assume that the TV is not muted
        self._muted = False
        # Assume that the TV is in Play mode
        self._playing = True
        self._volume = 0
        self._current_source = None
        self._current_source_id = None
        self._state = None
        self._source_list = {}
        self._app_list = {}
        self._input_list = {}
        self._channel = None
        self._last_icon = None

    @property
    def should_poll(self):
        """Only poll for state when client is not connected."""
        return not self._client.is_connected()

    def setup(self):
        """Listen for Home Assistant stop event."""

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.disconnect)

    async def disconnect(self, event):
        """Disconnect from TV."""
        await self._client.disconnect()

    async def async_subscribe_input_callback(self, current_input):
        """Handle subscribed updates to current input."""
        self._current_source_id = current_input

        if self._current_source_id == "":
            self._state = STATE_OFF
        else:
            self._state = STATE_PLAYING

        self.update_sources()

        if self.entity_id is not None:
            self.async_schedule_update_ha_state(False)

    async def async_subscribe_muted_callback(self, muted):
        """Handle subscribed updates to mute status."""
        self._muted = muted

        if self.entity_id is not None:
            self.async_schedule_update_ha_state(False)

    async def async_subscribe_volume_callback(self, volume):
        """Handle subscribed updates to volume status."""
        self._volume = volume
        if self.entity_id is not None:
            self.async_schedule_update_ha_state(False)

    async def async_subscribe_current_channel_callback(self, channel):
        """Handle subscribed updates to current channel."""
        self._channel = channel
        if self.entity_id is not None:
            self.async_schedule_update_ha_state(False)

    async def async_subscribe_apps_callback(self, apps):
        """Handle subscribed updates to apps list."""
        self._app_list = {}
        for app in apps:
            self._app_list[app["id"]] = app

        self.update_sources()

        if self.entity_id is not None:
            self.async_schedule_update_ha_state(True)

    async def async_subscribe_inputs_callback(self, inputs):
        """Handle subscribed updates to inputs list."""
        self._input_list = {}
        for extinput in inputs:
            self._input_list[extinput["label"]] = extinput

        self.update_sources()

        if self.entity_id is not None:
            self.async_schedule_update_ha_state(True)

    def update_sources(self):
        """Update list of sources from current source, apps, inputs and configured list."""
        self._source_list = {}
        conf_sources = self._customize.get(CONF_SOURCES, [])

        for app in self._app_list.values():
            if app["id"] == self._current_source_id:
                self._current_source = app["title"]
                self._source_list[app["title"]] = app
            elif (
                not conf_sources
                or app["id"] in conf_sources
                or any(word in app["title"] for word in conf_sources)
                or any(word in app["id"] for word in conf_sources)
            ):
                self._source_list[app["title"]] = app

        for source in self._input_list.values():
            if source["appId"] == self._current_source_id:
                self._current_source = source["label"]
                self._source_list[source["label"]] = source
            elif (
                not conf_sources
                or source["label"] in conf_sources
                or any(source["label"].find(word) != -1 for word in conf_sources)
            ):
                self._source_list[source["label"]] = source

    @util.Throttle(MIN_TIME_BETWEEN_SCANS, MIN_TIME_BETWEEN_FORCED_SCANS)
    async def async_update(self):
        """Connect and initialize state and update subscriptions."""

        if not self._client.is_connected():
            try:
                await self._client.connect()

                # manually get state
                results = await asyncio.gather(
                    self._client.get_current_app(),
                    self._client.get_muted(),
                    self._client.get_volume(),
                    self._client.get_current_channel(),
                    self._client.get_apps(),
                    self._client.get_inputs(),
                )

                self._current_source_id = results[0]

                if self._current_source_id == "":
                    self._state = STATE_OFF
                else:
                    self._state = STATE_PLAYING

                self._muted = results[1]
                self._volume = results[2]
                self._channel = results[3]

                self._app_list = {}
                for app in results[4]:
                    self._app_list[app["id"]] = app

                self._input_list = {}
                for extinput in results[5]:
                    self._input_list[extinput["label"]] = extinput

                self.update_sources()

                # subscribe to updates
                await self._client.subscribe_current_app(
                    self.async_subscribe_input_callback
                )
                await self._client.subscribe_muted(self.async_subscribe_muted_callback)
                await self._client.subscribe_volume(
                    self.async_subscribe_volume_callback
                )
                await self._client.subscribe_current_channel(
                    self.async_subscribe_current_channel_callback
                )
                await self._client.subscribe_apps(self.async_subscribe_apps_callback)
                await self._client.subscribe_inputs(
                    self.async_subscribe_inputs_callback
                )
            except (
                OSError,
                ConnectionClosed,
                ConnectionRefusedError,
                asyncio.TimeoutError,
                asyncio.CancelledError,
                PyLGTVPairException,
                PyLGTVCmdException,
            ):
                if self._client.is_connected():
                    await self._client.disconnect()
                self._state = STATE_OFF
                self._current_source = None
                self._current_source_id = None
                self._channel = None

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume / 100.0

    @property
    def source(self):
        """Return the current input source."""
        return self._current_source

    @property
    def source_list(self):
        """List of available input sources."""
        return sorted(self._source_list.keys())

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MEDIA_TYPE_CHANNEL

    @property
    def media_title(self):
        """Title of current playing media."""
        if (self._channel is not None) and ("channelName" in self._channel):
            return self._channel["channelName"]
        return None

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        if self._current_source_id in self._app_list:
            icon = self._app_list[self._current_source_id]["largeIcon"]
            if not icon.startswith("http"):
                icon = self._app_list[self._current_source_id]["icon"]

            # 'icon' holds a URL with a transient key. Avoid unnecessary
            # updates by returning the same URL until the image changes.
            if self._last_icon and (
                icon.split("/")[-1] == self._last_icon.split("/")[-1]
            ):
                return self._last_icon
            self._last_icon = icon
            return icon
        return None

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        if self._on_script:
            return SUPPORT_WEBOSTV | SUPPORT_TURN_ON
        return SUPPORT_WEBOSTV

    @cmd
    async def async_turn_off(self):
        """Turn off media player."""
        try:
            await self._client.power_off()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

        self._state = STATE_OFF

    def async_turn_on(self):
        """Turn on the media player."""
        if self._on_script:
            return self._on_script.async_run()

    @cmd
    async def async_volume_up(self):
        """Volume up the media player."""
        await self._client.volume_up()

    @cmd
    async def async_volume_down(self):
        """Volume down media player."""
        await self._client.volume_down()

    @cmd
    def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        tv_volume = volume * 100
        return self._client.set_volume(tv_volume)

    @cmd
    def async_mute_volume(self, mute):
        """Send mute command."""
        self._muted = mute
        return self._client.set_mute(mute)

    @cmd
    def async_media_play_pause(self):
        """Simulate play pause media player."""
        if self._playing:
            return self.media_pause()
        else:
            return self.media_play()

    @cmd
    async def async_select_source(self, source):
        """Select input source."""
        source_dict = self._source_list.get(source)
        if source_dict is None:
            _LOGGER.warning("Source %s not found for %s", source, self.name)
            return
        self._current_source_id = source_dict["id"]
        if source_dict.get("title"):
            self._current_source = source_dict["title"]
            await self._client.launch_app(source_dict["id"])
        elif source_dict.get("label"):
            self._current_source = source_dict["label"]
            await self._client.set_input(source_dict["id"])

    @cmd
    async def async_play_media(self, media_type, media_id, **kwargs):
        """Play a piece of media."""
        _LOGGER.debug("Call play media type <%s>, Id <%s>", media_type, media_id)

        if media_type == MEDIA_TYPE_CHANNEL:
            _LOGGER.debug("Searching channel...")
            partial_match_channel_id = None
            perfect_match_channel_id = None

            for channel in self._client.get_channels():
                if media_id == channel["channelNumber"]:
                    perfect_match_channel_id = channel["channelId"]
                    continue

                if media_id.lower() == channel["channelName"].lower():
                    perfect_match_channel_id = channel["channelId"]
                    continue

                if media_id.lower() in channel["channelName"].lower():
                    partial_match_channel_id = channel["channelId"]

            if perfect_match_channel_id is not None:
                _LOGGER.info(
                    "Switching to channel <%s> with perfect match",
                    perfect_match_channel_id,
                )
                await self._client.set_channel(perfect_match_channel_id)
            elif partial_match_channel_id is not None:
                _LOGGER.info(
                    "Switching to channel <%s> with partial match",
                    partial_match_channel_id,
                )
                await self._client.set_channel(partial_match_channel_id)

    @cmd
    def async_media_play(self):
        """Send play command."""
        self._playing = True
        self._state = STATE_PLAYING
        return self._client.play()

    @cmd
    def async_media_pause(self):
        """Send media pause command to media player."""
        self._playing = False
        self._state = STATE_PAUSED
        return self._client.pause()

    @cmd
    def async_media_next_track(self):
        """Send next track command."""
        current_input = self._client.get_input()
        if current_input == LIVETV_APP_ID:
            return self._client.channel_up()
        else:
            return self._client.fast_forward()

    @cmd
    def async_media_previous_track(self):
        """Send the previous track command."""
        current_input = self._client.get_input()
        if current_input == LIVETV_APP_ID:
            return self._client.channel_down()
        else:
            return self._client.rewind()

    @cmd
    def async_command(self, command, command_type=None, command_data=None):
        """Send generic command or button press."""
        if command_type == "button":
            return self._client.button(command)
        else:
            return self._client.request(command)
