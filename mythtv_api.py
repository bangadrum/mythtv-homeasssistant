"""MythTV Services API client."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

RECORDING_STATUS: dict[int, str] = {
    -17: "OtherRecording",
    -16: "OtherTuning",
    -15: "MissedFuture",
    -14: "Tuning",
    -13: "Failed",
    -12: "TunerBusy",
    -11: "LowDiskSpace",
    -10: "Cancelled",
    -9: "Missed",
    -8: "Aborted",
    -7: "Recorded",
    -6: "CurrentRecording",
    -5: "EarlierShowing",
    -4: "TooManyRecordings",
    -3: "NotListed",
    -2: "Conflict",
    -1: "Overlap",
    0: "Unknown",
    1: "ManualOverride",
    2: "PreviousRecording",
    3: "CurrentRecording",
    4: "EarlierShowing",
    5: "NeverRecord",
    6: "Offline",
    7: "AbortedRecording",
    8: "WillRecord",
    9: "Unknown",
    10: "DontRecord",
    11: "MissedFuture",
    12: "Tuning",
    13: "Failed",
}

# Statuses that mean "is currently recording right now"
ACTIVE_RECORDING_STATUSES = {-6, -14, -16}


class MythTVConnectionError(Exception):
    """Raised when connection to MythTV backend fails."""


class MythTVAPI:
    """Async client for the MythTV Services API."""

    def __init__(
        self,
        host: str,
        port: int = 6544,
        session: aiohttp.ClientSession | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._base_url = f"http://{host}:{port}"
        self._session = session
        self._auth = (
            aiohttp.BasicAuth(username, password)
            if username and password
            else None
        )
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(auth=self._auth)
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        session = await self._get_session()
        url = f"{self._base_url}/{endpoint}"
        try:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                raise MythTVConnectionError(f"HTTP {resp.status} from {url}")
        except aiohttp.ClientConnectorError as err:
            raise MythTVConnectionError(
                f"Cannot connect to MythTV at {self._base_url}: {err}"
            ) from err
        except asyncio.TimeoutError as err:
            raise MythTVConnectionError(
                f"Timeout connecting to MythTV at {self._base_url}"
            ) from err

    # ── Myth service ──────────────────────────────────────────────────────────

    async def get_hostname(self) -> str:
        data = await self._get("Myth/GetHostName")
        return data.get("String", "")

    async def get_backend_info(self) -> dict:
        return await self._get("Myth/GetBackendInfo")

    async def get_connection_info(self) -> dict:
        return await self._get("Myth/GetConnectionInfo")

    # ── Status service ────────────────────────────────────────────────────────

    async def get_backend_status(self) -> dict:
        return await self._get("Status/GetBackendStatus")

    # ── DVR service ───────────────────────────────────────────────────────────

    async def get_recorded_list(
        self,
        count: int = 20,
        start_index: int = 0,
        descending: bool = True,
        rec_group: str | None = None,
        ignore_deleted: bool = True,
        ignore_live_tv: bool = True,
    ) -> dict:
        params: dict[str, Any] = {
            "Count": count,
            "StartIndex": start_index,
            "Descending": "true" if descending else "false",
            "IgnoreDeleted": "true" if ignore_deleted else "false",
            "IgnoreLiveTV": "true" if ignore_live_tv else "false",
        }
        if rec_group:
            params["RecGroup"] = rec_group
        return await self._get("Dvr/GetRecordedList", params)

    async def get_upcoming_list(
        self,
        count: int = 20,
        start_index: int = 0,
        show_all: bool = False,
    ) -> dict:
        params: dict[str, Any] = {
            "Count": count,
            "StartIndex": start_index,
            "ShowAll": "true" if show_all else "false",
        }
        return await self._get("Dvr/GetUpcomingList", params)

    async def get_encoder_list(self) -> dict:
        return await self._get("Dvr/GetEncoderList")

    async def get_record_schedule_list(self) -> dict:
        return await self._get("Dvr/GetRecordScheduleList")

    async def get_conflict_list(self) -> dict:
        return await self._get("Dvr/GetConflictList")

    async def get_expiring_list(self, count: int = 10) -> dict:
        return await self._get("Dvr/GetExpiringList", {"Count": count})

    async def get_title_info_list(self) -> dict:
        return await self._get("Dvr/GetTitleInfoList")

    # ── Channel service ───────────────────────────────────────────────────────

    async def get_channel_info_list(self, only_visible: bool = True) -> dict:
        return await self._get(
            "Channel/GetChannelInfoList",
            {"OnlyVisible": "true" if only_visible else "false"},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def test_connection(self) -> bool:
        try:
            await self.get_hostname()
            return True
        except MythTVConnectionError:
            return False

    def get_currently_recording(self, upcoming_programs: list[dict]) -> list[dict]:
        """Filter upcoming programmes to those currently being recorded."""
        result = []
        for prog in upcoming_programs:
            code = prog.get("Recording", {}).get("Status")
            if code is not None and int(code) in ACTIVE_RECORDING_STATUSES:
                result.append(prog)
        return result

    @staticmethod
    def parse_utc(ts: str | None) -> datetime | None:
        if not ts:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def rec_status_label(code: int | str) -> str:
        return RECORDING_STATUS.get(int(code), f"Status({code})")
