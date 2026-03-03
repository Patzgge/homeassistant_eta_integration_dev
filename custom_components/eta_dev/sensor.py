"""
Platform for ETA sensor integration in Home Assistant.
Updated to support both numeric measurements and text-based status messages.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
    ENTITY_ID_FORMAT,
)
from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.const import CONF_HOST, CONF_PORT

from .api import EtaAPI
from .const import DOMAIN, CHOOSEN_ENTITIES, FLOAT_DICT

_LOGGER = logging.getLogger(__name__)

# Polling interval for the sensors
SCAN_INTERVAL = timedelta(minutes=1)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    
    if config_entry.options:
        config.update(config_entry.options)

    chosen_entities = config[CHOOSEN_ENTITIES]
    
    # We use the FLOAT_DICT which contains uri, value, and unit
    sensors = [
        EtaSensor(
            config,
            hass,
            entity_name,
            config[FLOAT_DICT][entity_name][0], # URI
            config[FLOAT_DICT][entity_name][2], # Unit
        )
        for entity_name in chosen_entities
    ]
    
    async_add_entities(sensors, update_before_add=True)

class EtaSensor(SensorEntity):
    """Representation of an ETA Sensor (Numeric or Text)."""

    def __init__(self, config: dict, hass: HomeAssistant, name: str, uri: str, unit: str):
        """Initialize the sensor."""
        self._attr_name = name
        self.uri = uri
        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.session = async_get_clientsession(hass)
        
        # Unique ID using host and entity name
        self._attr_unique_id = f"eta_{self.host}_{name.replace(' ', '_')}"
        
        # Generate entity_id: e.g., sensor.eta_outside_temperature
        cleaned_id = name.lower().replace(" ", "_")
        self.entity_id = generate_entity_id(ENTITY_ID_FORMAT, f"eta_{cleaned_id}", hass=hass)

        # Determine if it's a numeric sensor or a text status
        self._attr_device_class = self.determine_device_class(unit)
        
        if unit and unit.strip():
            self._attr_native_unit_of_measurement = unit
            # For numeric values, we use MEASUREMENT or TOTAL_INCREASING
            if self._attr_device_class == SensorDeviceClass.ENERGY:
                self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            else:
                self._attr_state_class = SensorStateClass.MEASUREMENT
        else:
            # Text/Status sensors have no unit and no state_class
            self._attr_native_unit_of_measurement = None
            self._attr_state_class = None

    async def async_update(self):
        """Fetch new state data from the ETA API."""
        try:
            eta_client = EtaAPI(self.session, self.host, self.port)
            value, _ = await eta_client.get_data(self.uri)
            
            # Update the value without forced float conversion to allow strings
            self._attr_native_value = value
            
        except Exception as err:
            _LOGGER.error("Error updating ETA sensor %s: %s", self._attr_name, err)

    @staticmethod
    def determine_device_class(unit: str) -> SensorDeviceClass | None:
        """Map ETA units to Home Assistant Device Classes."""
        unit_map = {
            "°C": SensorDeviceClass.TEMPERATURE,
            "W": SensorDeviceClass.POWER,
            "kW": SensorDeviceClass.POWER,
            "A": SensorDeviceClass.CURRENT,
            "Hz": SensorDeviceClass.FREQUENCY,
            "Pa": SensorDeviceClass.PRESSURE,
            "bar": SensorDeviceClass.PRESSURE,
            "V": SensorDeviceClass.VOLTAGE,
            "mV": SensorDeviceClass.VOLTAGE,
            "W/m²": SensorDeviceClass.IRRADIANCE,
            "kWh": SensorDeviceClass.ENERGY,
            "kg": SensorDeviceClass.WEIGHT,
            "s": SensorDeviceClass.DURATION,
            "%rH": SensorDeviceClass.HUMIDITY
        }
        return unit_map.get(unit)
