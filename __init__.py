"""The MythTV integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import API, CONF_HOST, CONF_PORT, CONF_RECORDED_COUNT, CONF_UPCOMING_COUNT, COORDINATOR, DEFAULT_PORT, DEFAULT_RECORDED_COUNT, DEFAULT_UPCOMING_COUNT, DOMAIN
from .coordinator import MythTVDataUpdateCoordinator
from .mythtv_api import MythTVAPI

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MythTV from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    upcoming_count = entry.data.get(CONF_UPCOMING_COUNT, DEFAULT_UPCOMING_COUNT)
    recorded_count = entry.data.get(CONF_RECORDED_COUNT, DEFAULT_RECORDED_COUNT)

    api = MythTVAPI(host=host, port=port)
    coordinator = MythTVDataUpdateCoordinator(
        hass,
        api=api,
        upcoming_count=upcoming_count,
        recorded_count=recorded_count,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        API: api,
        COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data[API].close()
    return unload_ok
