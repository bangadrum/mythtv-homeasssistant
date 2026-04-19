"""DataUpdateCoordinator for MythTV."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_RECORDED_COUNT, DEFAULT_SCAN_INTERVAL, DEFAULT_UPCOMING_COUNT, DOMAIN
from .mythtv_api import MythTVAPI, MythTVConnectionError

_LOGGER = logging.getLogger(__name__)


class MythTVDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch all data from MythTV backend in a single coordinated update."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: MythTVAPI,
        upcoming_count: int = DEFAULT_UPCOMING_COUNT,
        recorded_count: int = DEFAULT_RECORDED_COUNT,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.api = api
        self.upcoming_count = upcoming_count
        self.recorded_count = recorded_count
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from MythTV backend."""
        try:
            (
                hostname,
                backend_info,
                backend_status,
                upcoming_raw,
                recorded_raw,
                encoder_raw,
                conflicts_raw,
                schedules_raw,
            ) = await _gather_safe(
                self.api.get_hostname(),
                self.api.get_backend_info(),
                self.api.get_backend_status(),
                self.api.get_upcoming_list(count=self.upcoming_count),
                self.api.get_recorded_list(count=self.recorded_count),
                self.api.get_encoder_list(),
                self.api.get_conflict_list(),
                self.api.get_record_schedule_list(),
            )
        except MythTVConnectionError as err:
            raise UpdateFailed(f"MythTV connection error: {err}") from err

        upcoming_programs: list[dict] = (
            (upcoming_raw or {}).get("ProgramList", {}).get("Programs") or []
        )
        recorded_programs: list[dict] = (
            (recorded_raw or {}).get("ProgramList", {}).get("Programs") or []
        )
        encoders: list[dict] = (
            (encoder_raw or {}).get("EncoderList", {}).get("Encoders") or []
        )
        conflicts: list[dict] = (
            (conflicts_raw or {}).get("ProgramList", {}).get("Programs") or []
        )
        schedules: list[dict] = (
            (schedules_raw or {}).get("RecRuleList", {}).get("RecRules") or []
        )

        currently_recording = self.api.get_currently_recording(upcoming_programs)

        # Encoder summary
        num_encoders = len(encoders)
        num_recording = len(currently_recording)
        num_idle = sum(
            1 for e in encoders if str(e.get("State", "0")) == "0"
        )

        # Storage groups from backend status
        status_info = (backend_status or {}).get("BackendStatus", {})
        storage_groups = (
            status_info.get("StorageGroups", {}).get("GroupInfos") or []
        )

        return {
            "hostname": hostname or "",
            "backend_info": backend_info or {},
            "backend_status": status_info,
            "upcoming_programs": upcoming_programs,
            "upcoming_total": int(
                (upcoming_raw or {}).get("ProgramList", {}).get("TotalAvailable", 0)
            ),
            "currently_recording": currently_recording,
            "recorded_programs": recorded_programs,
            "recorded_total": int(
                (recorded_raw or {}).get("ProgramList", {}).get("TotalAvailable", 0)
            ),
            "encoders": encoders,
            "num_encoders": num_encoders,
            "num_recording": num_recording,
            "num_idle_encoders": num_idle,
            "conflicts": conflicts,
            "num_conflicts": len(conflicts),
            "schedules": schedules,
            "num_schedules": len(schedules),
            "storage_groups": storage_groups,
        }


async def _gather_safe(*coros):
    """Run coroutines concurrently; re-raise MythTVConnectionError if any fails."""
    import asyncio
    results = await asyncio.gather(*coros, return_exceptions=True)
    for r in results:
        if isinstance(r, MythTVConnectionError):
            raise r
        if isinstance(r, Exception):
            _LOGGER.warning("Non-fatal MythTV API error: %s", r)
    # Replace other exceptions with None so callers can handle gracefully
    return [None if isinstance(r, Exception) else r for r in results]
