"""Tests for HomematicIP Cloud weather."""
from homeassistant.components.weather import (
    ATTR_WEATHER_ATTRIBUTION,
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_WIND_BEARING,
    ATTR_WEATHER_WIND_SPEED,
)

from .helper import async_manipulate_test_data, get_and_check_entity_basics


async def test_hmip_weather_sensor(hass, default_mock_hap):
    """Test HomematicipWeatherSensor."""
    entity_id = "weather.weather_sensor_plus"
    entity_name = "Weather Sensor – plus"
    device_model = "HmIP-SWO-PL"

    ha_state, hmip_device = get_and_check_entity_basics(
        hass, default_mock_hap, entity_id, entity_name, device_model
    )

    assert ha_state.state == ""
    assert ha_state.attributes[ATTR_WEATHER_TEMPERATURE] == 4.3
    assert ha_state.attributes[ATTR_WEATHER_HUMIDITY] == 97
    assert ha_state.attributes[ATTR_WEATHER_WIND_SPEED] == 15.0
    assert ha_state.attributes[ATTR_WEATHER_ATTRIBUTION] == "Powered by Homematic IP"

    await async_manipulate_test_data(hass, hmip_device, "actualTemperature", 12.1)
    ha_state = hass.states.get(entity_id)
    assert ha_state.attributes[ATTR_WEATHER_TEMPERATURE] == 12.1


async def test_hmip_weather_sensor_pro(hass, default_mock_hap):
    """Test HomematicipWeatherSensorPro."""
    entity_id = "weather.wettersensor_pro"
    entity_name = "Wettersensor - pro"
    device_model = "HmIP-SWO-PR"

    ha_state, hmip_device = get_and_check_entity_basics(
        hass, default_mock_hap, entity_id, entity_name, device_model
    )

    assert ha_state.state == "sunny"
    assert ha_state.attributes[ATTR_WEATHER_TEMPERATURE] == 15.4
    assert ha_state.attributes[ATTR_WEATHER_HUMIDITY] == 65
    assert ha_state.attributes[ATTR_WEATHER_WIND_SPEED] == 2.6
    assert ha_state.attributes[ATTR_WEATHER_WIND_BEARING] == 295.0
    assert ha_state.attributes[ATTR_WEATHER_ATTRIBUTION] == "Powered by Homematic IP"

    await async_manipulate_test_data(hass, hmip_device, "actualTemperature", 12.1)
    ha_state = hass.states.get(entity_id)
    assert ha_state.attributes[ATTR_WEATHER_TEMPERATURE] == 12.1


async def test_hmip_home_weather(hass, default_mock_hap):
    """Test HomematicipHomeWeather."""
    entity_id = "weather.weather_1010_wien_osterreich"
    entity_name = "Weather 1010  Wien, Österreich"
    device_model = None

    ha_state, hmip_device = get_and_check_entity_basics(
        hass, default_mock_hap, entity_id, entity_name, device_model
    )
    assert hmip_device
    assert ha_state.state == "partlycloudy"
    assert ha_state.attributes[ATTR_WEATHER_TEMPERATURE] == 16.6
    assert ha_state.attributes[ATTR_WEATHER_HUMIDITY] == 54
    assert ha_state.attributes[ATTR_WEATHER_WIND_SPEED] == 8.6
    assert ha_state.attributes[ATTR_WEATHER_WIND_BEARING] == 294
    assert ha_state.attributes[ATTR_WEATHER_ATTRIBUTION] == "Powered by Homematic IP"

    await async_manipulate_test_data(
        hass,
        default_mock_hap.home.weather,
        "temperature",
        28.3,
        fire_device=default_mock_hap.home,
    )

    ha_state = hass.states.get(entity_id)
    assert ha_state.attributes[ATTR_WEATHER_TEMPERATURE] == 28.3
