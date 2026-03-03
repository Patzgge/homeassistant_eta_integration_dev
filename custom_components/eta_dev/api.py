"""
API Client for ETA Heating Systems.
This class handles communication with the ETA REST API,
parses XML responses, and prepares data for Home Assistant.
"""

import logging
import xmltodict
from aiohttp import ClientSession
from typing import Any, Dict, List, Tuple, Optional

_LOGGER = logging.getLogger(__name__)

class EtaAPI:
    def __init__(self, session: ClientSession, host: str, port: int):
        """
        Initialize the API client.
        
        :param session: aiohttp ClientSession for async requests
        :param host: IP address of the ETA system
        :param port: Port of the REST API (default 8080)
        """
        self._session = session
        self._host = host
        self._port = port

        # Units that identify a sensor as a numeric (float) value
        self._float_sensor_units = [
            "%", "A", "Hz", "Ohm", "Pa", "U/min", "V", "W", "W/m²", 
            "bar", "kW", "kWh", "kg", "l", "l/min", "mV", "m²", "s", "°C", "%rH"
        ]

    def build_uri(self, suffix: str) -> str:
        """Construct the full URI for an API endpoint."""
        return f"http://{self._host}:{self._port}{suffix}"

    async def get_request(self, suffix: str):
        """Perform an asynchronous GET request."""
        url = self.build_uri(suffix)
        return await self._session.get(url)

    async def does_endpoint_exists(self) -> bool:
        """Check if the API is reachable (connectivity test)."""
        try:
            resp = await self.get_request("/user/menu")
            return resp.status == 200
        except Exception as err:
            _LOGGER.error("Connectivity test failed for ETA system: %s", err)
            return False

    def evaluate_xml_dict(self, xml_dict: Any, uri_dict: Dict[str, str], prefix: str = ""):
        """
        Recursively traverse the XML menu structure.
        Extracts all endpoints and their corresponding URIs.
        """
        if isinstance(xml_dict, list):
            for child in xml_dict:
                self.evaluate_xml_dict(child, uri_dict, prefix)
        else:
            name = xml_dict.get("@name", "unknown")
            uri = xml_dict.get("@uri")
            new_prefix = f"{prefix}_{name}" if prefix else name
            
            if "object" in xml_dict:
                # Menus can contain sub-objects (recursion)
                uri_dict[new_prefix] = uri
                self.evaluate_xml_dict(xml_dict["object"], uri_dict, new_prefix)
            else:
                # Leaf node (actual data endpoint)
                uri_dict[new_prefix] = uri

    async def _parse_data(self, data: Dict[str, Any]) -> Tuple[Any, str]:
        """
        Extract value and unit from an ETA data point.
        Automatically distinguishes between numeric values and text statuses.
        """
        unit = data.get("@unit", "")
        
        # Check if the unit is in the known list of numeric units
        if unit in self._float_sensor_units:
            try:
                scale_factor = int(data.get("@scaleFactor", 1))
                decimal_places = int(data.get("@decPlaces", 0))
                raw_value = float(data.get("#text", 0))
                
                value = round(raw_value / scale_factor, decimal_places)
                return value, unit
            except (ValueError, TypeError):
                _LOGGER.warning("Could not parse numeric value for data: %s", data)
        
        # Fallback: Return the text representation (e.g., "Heating", "Ready")
        # The '@strValue' attribute contains the human-readable status from the ETA system
        value = data.get("@strValue", "Unknown")
        return value, unit

    async def get_data(self, uri: str) -> Tuple[Optional[Any], Optional[str]]:
        """Fetch current data for a specific URI."""
        try:
            resp = await self.get_request(f"/user/var/{uri}")
            text = await resp.text()
            data = xmltodict.parse(text)["eta"]["value"]
            return await self._parse_data(data)
        except Exception as err:
            _LOGGER.debug("Error fetching data for URI %s: %s", uri, err)
            return None, None

    async def get_raw_sensor_dict(self) -> Any:
        """Fetch the complete menu structure from the ETA system."""
        resp = await self.get_request("/user/menu/")
        text = await resp.text()
        return xmltodict.parse(text)["eta"]["menu"]["fub"]

    async def get_sensors_dict(self) -> Dict[str, str]:
        """Create a flat dictionary of all available URIs from the menu."""
        raw_dict = await self.get_raw_sensor_dict()
        uri_dict = {}
        self.evaluate_xml_dict(raw_dict, uri_dict)
        return uri_dict

    async def get_all_sensors(self) -> Dict[str, Dict[str, Tuple[str, Any, str]]]:
        """
        Categorize all available sensors into numeric and text values.
        Enables reading statuses like 'Boiler is heating'.
        """
        sensor_dict = await self.get_sensors_dict()
        results = {"numeric": {}, "text": {}}
        
        for key, uri in sensor_dict.items():
            value, unit = await self.get_data(uri)
            if value is None:
                continue
                
            cleaned_key = key.lower().replace(" ", "_")
            
            # Categorize based on detected unit
            if unit in self._float_sensor_units:
                results["numeric"][cleaned_key] = (uri, value, unit)
            else:
                results["text"][cleaned_key] = (uri, value, unit)
                
        return results

    async def get_float_sensors(self) -> Dict[str, Tuple[str, float, str]]:
        """
        Helper method to return only numeric sensors.
        Maintains backward compatibility with existing config flow.
        """
        all_sensors = await self.get_all_sensors()
        return all_sensors["numeric"]
