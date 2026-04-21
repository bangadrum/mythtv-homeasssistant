"""MythTV Services API client."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Recording status codes as returned by the MythTV Services API.
# Generated from MythTV v34+ via Dvr/RecStatusToString and cross-referenced
# against the Recording_Status wiki page.
#
# Negative codes are "in-progress" or "terminal" states for a scheduled entry.
# Positive codes are scheduler decision states (will/won't record, etc.).
#
# IMPORTANT: These values changed across major MythTV releases.
# The table below reflects the values reported by v32+ (API v2) backends.
# On older v31/v30 backends the numeric values for the same status names
# may differ by a few positions in the negative range.
RECORDING_STATUS: dict[int, str] = {
    # ── Negative: active / terminal states ───────────────────────────────
    -20: "OtherRecording",      # Being recorded by another virtual tuner
    -19: "OtherTuning",         # Being tuned by another virtual tuner
    -18: "MissedFuture",        # Missed; will not be rescheduled
    -17: "Pending",             # About to start recording
    -16: "Failing",             # Failing due to errors (tuner lock lost, etc.)
    -15: "Unknown",
    -14: "Unknown",
    -13: "Missed",              # Missed because master backend was not running
    -12: "Tuning",              # Being tuned right now
    -11: "RecorderFailed",      # Recorder failed
    -10: "Aborted",             # Recording was aborted
    -9:  "Recorded",            # Successfully recorded
    -8:  "Recording",           # Currently being recorded  ← primary active state
    -7:  "WillRecord",          # Scheduled (future)
    -6:  "Cancelled",           # Manually cancelled
    -5:  "LowDiskSpace",        # Not recorded: low disk space
    -4:  "TunerBusy",           # Not recorded: tuner was busy
    -3:  "Failed",              # Generic failure
    -2:  "NotListed",           # Not in the program guide
    -1:  "Conflict",            # Conflicts with another recording
    0:   "Unknown",
    # ── Positive: scheduler decision states ──────────────────────────────
    1:   "DontRecord",          # Marked "don't record"
    2:   "PreviousRecording",   # Previously recorded; duplicate suppressed
    3:   "CurrentRecording",    # Already recorded and file still exists
    4:   "EarlierShowing",      # An earlier showing will be recorded instead
    5:   "TooManyRecordings",   # Too many recordings of this title
    6:   "NotListed",           # Not in program guide
    7:   "NeverRecord",         # Marked "never record"
    8:   "Offline",             # Recorder is offline
    9:   "WillRecord",          # Will record
    10:  "Repeat",              # Repeat episode; duplicate suppressed
    11:  "Inactive",            # Recording rule is inactive
    12:  "LaterShowing",        # A later showing will be recorded instead
    13:  "Overlap",             # Overlaps another recording on same tuner
}

# Statuses that mean "a tuner is actively recording/tuning right now".
#
# FIX: The original code used {-6, -14, -16} which mapped to wrong labels
# (Cancelled, Tuning, OtherTuning under the old broken table).
#
# The two statuses that represent active tuner use are:
#   -8  → Recording  (file is being written)
#   -12 → Tuning     (tuner lock in progress, recording imminent)
#
# -16 (Failing) is intentionally excluded: the tuner has lost its lock and
# is not producing usable content, so it should not count as "recording".
ACTIVE_RECORDING_STATUSES = {-8, -12}


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

    async def get_storage_group_dirs(
        self, group_name: str | None = None
    ) -> dict:
        """Return storage group directory info via Myth/GetStorageGroupDirs.

        This is the correct endpoint for per-directory free-space data
        (fields: GroupName, HostName, DirName, DirRead, DirWrite, KiBFree).
        Each entry in StorageGroupDirList → StorageGroupDirs is one directory.
        """
        params: dict[str, Any] = {}
        if group_name:
            params["GroupName"] = group_name
        return await self._get("Myth/GetStorageGroupDirs", params or None)

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
        }
        if rec_group:
            params["RecGroup"] = rec_group
        # FIX: IgnoreDeleted and IgnoreLiveTV were introduced in v32.
        # On v28–v31 backends these parameters are silently ignored, so it is
        # safe to always send them — but they only take effect on v32+.
        params["IgnoreDeleted"] = "true" if ignore_deleted else "false"
        params["IgnoreLiveTV"] = "true" if ignore_live_tv else "false"
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
        """Filter upcoming programmes to those currently being recorded/tuned.

        Uses ACTIVE_RECORDING_STATUSES which correctly identifies statuses
        -8 (Recording) and -12 (Tuning) as active tuner states.

        Note: on v32+ backends the Status field is returned as a string name
        rather than a number.  We attempt to handle both forms.
        """
        result = []
        for prog in upcoming_programs:
            raw = prog.get("Recording", {}).get("Status")
            if raw is None:
                continue
            # v32+ may return the string name; try numeric first.
            try:
                code = int(raw)
                if code in ACTIVE_RECORDING_STATUSES:
                    result.append(prog)
            except (ValueError, TypeError):
                # String form: compare against the label table.
                label = str(raw)
                active_labels = {
                    RECORDING_STATUS[c] for c in ACTIVE_RECORDING_STATUSES
                }
                if label in active_labels:
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
        try:
            return RECORDING_STATUS.get(int(code), f"Status({code})")
        except (ValueError, TypeError):
            return str(code)
