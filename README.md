# MythTV Home Assistant Integration

A custom integration for [Home Assistant](https://www.home-assistant.io/) that connects to your **MythTV** backend via the [MythTV Services API](https://www.mythtv.org/wiki/Services_API) and exposes useful information as sensors and binary sensors.

> **Version 0.3** — fixes recording status codes, storage group data source, active recording detection, and conflict attribute structure. See [Changelog](#changelog) for details.

---

## Features

| Entity | Type | Description |
| --- | --- | --- |
| Backend Connected | Binary Sensor | Whether the MythTV backend is reachable |
| Currently Recording | Binary Sensor | `on` when any tuner is actively recording |
| Recording Conflicts | Binary Sensor | `on` when scheduling conflicts exist |
| All Encoders Busy | Binary Sensor | `on` when every tuner is in use |
| Active Recordings | Sensor | Count of current recordings + details in attributes |
| Next Recording | Sensor | Title of the next scheduled recording |
| Next Recording Start | Sensor | Timestamp of the next scheduled recording |
| Upcoming Recordings | Sensor | Total count of upcoming recordings |
| Total Recordings | Sensor | Size of recorded library |
| Last Recorded | Sensor | Most recently recorded title |
| Recording Schedules | Sensor | Number of active recording rules |
| Total Encoders | Sensor | Number of capture cards |
| Storage Groups | Sensor | Count + free space per storage group directory |
| Backend Hostname | Sensor | MythTV host profile name + version |

All sensors expose rich **extra_state_attributes** (viewable in Developer Tools → States) with full programme details, schedules, encoder states, and storage group statistics.

> **Note on storage space:** The MythTV Services API (`Myth/GetStorageGroupDirs`) reports free space per directory but does not expose total or used space. The Storage Groups sensor and dashboard card therefore show free space only.

---

## Repository Structure

```
mythtv-homeasssistant/
├── __init__.py          # Integration entry point
├── binary_sensor.py     # Binary sensors (connected, recording, conflicts, busy)
├── config_flow.py       # UI config flow
├── const.py             # Constants and defaults
├── coordinator.py       # DataUpdateCoordinator — fetches all backend data
├── manifest.json        # HA integration manifest
├── mythtv_api.py        # Async MythTV Services API client
├── mythtv-card.js       # Lovelace dashboard card (copy to www/)
├── mythtv-card-preview.png  # Card screenshot for README
├── sensor.py            # Sensors (counts, titles, timestamps, storage)
├── strings.json         # UI strings
└── README.md            # This file
```

---

## Installation

### Via HACS (recommended)

1. In HACS, click **Custom repositories** and add `https://github.com/bangadrum/mythtv-homeasssistant` with category **Integration**.
2. Search for *MythTV* and install.
3. Restart Home Assistant.

### Manual

1. Copy all `.py` files and `manifest.json` into `config/custom_components/mythtv/`.
2. Restart Home Assistant.

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **MythTV**.
3. Fill in:
   * **Host** – IP address or hostname of the machine running `mythbackend`.
   * **Port** – default `6544`.
   * **Upcoming recordings to track** – how many upcoming entries to fetch (1–50, default 10).
   * **Recent recordings to track** – how many recorded entries to fetch (1–50, default 10).

> **Note:** All MythTV timestamps are UTC. Home Assistant will convert them to your local timezone automatically for `timestamp` device-class sensors.

---

## Custom Card

![MythTV Dashboard Card preview](mythtv-card-preview.png)

*The card showing 2 active recordings, upcoming schedule, recent library entries, and storage groups (collapsed). Sections are collapsible. The encoder strip shows per-tuner recording state.*

**Step 1** — copy `mythtv-card.js` to:

```
config/www/mythtv-card.js
```

**Step 2** — register the resource in your Lovelace `configuration.yaml` or via the UI (**Settings → Dashboards → Resources**):

```yaml
resources:
  - url: /local/mythtv-card.js
    type: module
```

**Step 3** — add the card in your dashboard YAML:

```yaml
type: custom:mythtv-card
title: MythTV

# All entity IDs below are auto-detected if you used the integration as-is.
# Only override if yours differ:
connected_entity:    binary_sensor.mythtv_backend_connected
recording_entity:    binary_sensor.mythtv_currently_recording
conflicts_entity:    binary_sensor.mythtv_recording_conflicts
upcoming_entity:     sensor.mythtv_upcoming_recordings
active_count_entity: sensor.mythtv_active_recordings
recorded_entity:     sensor.mythtv_total_recordings
encoders_entity:     sensor.mythtv_total_encoders
storage_entity:      sensor.mythtv_storage_groups
hostname_entity:     sensor.mythtv_backend_hostname
```

All entity IDs default to the names the integration creates, so in the simplest case `type: custom:mythtv-card` with no other config is sufficient.

---

## Example Automations

### Notify when a recording starts

```yaml
automation:
  - alias: "MythTV recording started"
    trigger:
      - platform: state
        entity_id: binary_sensor.mythtv_currently_recording
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "🔴 MythTV Recording"
          message: >
            Now recording:
            {{ state_attr('binary_sensor.mythtv_currently_recording', 'titles') | join(', ') }}
```

### Alert on scheduling conflicts

```yaml
automation:
  - alias: "MythTV conflict alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.mythtv_recording_conflicts
        to: "on"
    action:
      - service: persistent_notification.create
        data:
          title: "MythTV Conflict"
          message: >
            {{ state_attr('binary_sensor.mythtv_recording_conflicts', 'conflict_count') }}
            recording conflict(s) detected.
```

### Show next recording in a dashboard card

```yaml
type: entities
title: MythTV
entities:
  - entity: binary_sensor.mythtv_currently_recording
  - entity: sensor.mythtv_next_recording
  - entity: sensor.mythtv_next_recording_start
  - entity: sensor.mythtv_upcoming_recordings
  - entity: binary_sensor.mythtv_recording_conflicts
  - entity: sensor.mythtv_active_recordings
```

---

## API Endpoints Used

| MythTV Endpoint | Purpose |
| --- | --- |
| `Myth/GetHostName` | Connectivity test + hostname |
| `Myth/GetBackendInfo` | Version info |
| `Myth/GetStorageGroupDirs` | Storage group directory free-space data |
| `Status/GetBackendStatus` | Raw backend status (retained for future use) |
| `Dvr/GetUpcomingList` | Upcoming & active recordings |
| `Dvr/GetRecordedList` | Recorded library |
| `Dvr/GetEncoderList` | Tuner/encoder states |
| `Dvr/GetRecordScheduleList` | Recording rules |
| `Dvr/GetConflictList` | Scheduling conflicts |

Data is refreshed every **60 seconds** by default.

---

## Requirements

* Home Assistant 2023.x or later
* MythTV v0.28 or later (v32+ recommended; v34+ for accurate recording status labels)
* `mythbackend` reachable from the Home Assistant host on port 6544
* Python package: `aiohttp>=3.9.0` (installed automatically by HA)

---

## Changelog

### 0.3
- **Fixed recording status codes** — the entire `RECORDING_STATUS` table was wrong. Values are now sourced directly from the MythTV v34 wiki (`Dvr/RecStatusToString`) and cross-referenced with the MythTV scheduler source. The previous table had every negative status shifted by several positions.
- **Fixed active recording detection** — `ACTIVE_RECORDING_STATUSES` corrected to `{-2, -10, -15}` (Recording, Tuning, Pending). The previous set `{-6, -14, -16}` mapped to Cancelled, Failing, and Unknown.
- **Fixed storage group data source** — storage groups are now fetched from `Myth/GetStorageGroupDirs` (the correct documented endpoint) rather than `Status/GetBackendStatus`. Free space is derived from `KiBFree` per directory and aggregated by group.
- **Fixed conflict attributes** — `binary_sensor.mythtv_recording_conflicts` now exposes a `conflicts` list (with programme details) alongside the existing `conflict_count` scalar.
- **Fixed manifest URLs** — `documentation` and `issue_tracker` now point to the correct repository. Added `aiohttp>=3.9.0` to `requirements`.
- **Dashboard card v1.0.2** — recording status bar colours corrected for v34 codes; conflict banner count sourced from `conflicts` list; storage display updated to show `free_gb` and directory paths; `Pending` status shown as active.

### 0.2
- Initial public release.
