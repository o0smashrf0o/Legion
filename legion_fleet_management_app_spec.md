# Legion — Sentinel Fleet Management App

## Implementation Specification for OpenCode

## 1. Project goal

Build a Linux-first, open-source application named **Legion** with a primary CLI executable named `legionctl`.

Legion manages a fleet of standalone, battery-powered **Sentinel nodes**. Each Sentinel is deployed in a defined physical zone and independently monitors configured wireless technologies. On a validated local signal-of-interest (SOI) match, a Sentinel sends a Discord webhook notification.

Legion is the fleet command-and-control application. It must let an operator:

- Discover Sentinel nodes on a local network.
- Maintain a Sentinel node inventory.
- View the status and health of one or all Sentinel nodes.
- Create, validate, version, store, and deploy SOI detection profiles.
- Assign profiles to individual Sentinel nodes or groups of nodes.
- Trigger safe operational commands such as a Discord test alert.
- Retrieve recent Sentinel event metadata.
- Store per-node API credentials securely.
- Support future OTA and MQTT control-plane additions without requiring them for version 1.

Legion is not required for normal Sentinel alerting. Sentinel nodes continue their local scanning, SOI matching, cooldown enforcement, alert queueing, and Discord webhook delivery if Legion is offline.

## 2. Naming conventions

Use these names consistently across all source code, documentation, CLI output, user interfaces, repository names, and future tools.

| Concept | Canonical name | Recommended technical identifier |
|---|---|---|
| Individual deployed detector | Sentinel node | `sentinel` |
| Collection of deployed nodes | Sentinel fleet | `fleet` |
| Linux command-and-control application | Legion | `legion` |
| Command-line executable | Legion CLI | `legionctl` |
| Node configuration/watchlist document | SOI profile | `profile` |
| A node’s physical assignment | Zone / Area of Responsibility | `zone` / `aor` |
| SOI detection record | Observation | `observation` |
| Validated SOI notification | Alert | `alert` |
| Node management action | Command | `command` |

Avoid thematic names in machine-facing JSON or REST field names. Use conventional, maintainable terms such as `sentinel_id`, `profile_id`, `zone`, `health`, `rules`, `event`, and `command`.

## 3. System context

### 3.1 Sentinel node architecture

Each Sentinel package contains two ESP32-class controllers inside a battery-powered 3D-printed enclosure:

- **ESP32-C5-class primary controller**
  - 2.4 GHz and 5 GHz dual-band Wi-Fi 6.
  - Bluetooth LE scanning.
  - Wi-Fi SOI detection/scan scheduling within hardware capability.
  - Configuration persistence.
  - Local rule engine, confidence filtering, cooldowns, and alert queue.
  - Direct HTTPS Discord webhook alerts.
  - Local HTTPS REST API for Legion.

- **Original ESP32 / ESP-WROOM-32-class Bluetooth Classic coprocessor**
  - Bluetooth Classic BR/EDR inquiry/discovery.
  - Sends normalized Bluetooth Classic sightings and health state to the C5 over UART.

Legion communicates with the Sentinel primary controller only. It does not communicate with the Bluetooth Classic coprocessor directly.

### 3.2 Operational boundaries

- Discord is the Sentinel alert/notification plane.
- Legion is the Sentinel fleet configuration/management plane.
- Legion must not use Discord to issue commands.
- Legion must not receive, store, or request raw packet captures or user payload/content data.
- Legion manages authorized SOI metadata and Sentinel node operations only.
- Sentinel nodes retain their last valid configuration and operate independently when Legion is unavailable.

## 4. Version 1 scope

### 4.1 Required capabilities

Version 1 must implement:

1. CLI-first operation on Linux.
2. mDNS/zeroconf discovery of reachable Sentinel nodes.
3. Persistent local Sentinel inventory with node metadata.
4. Direct HTTPS REST communication to Sentinel nodes.
5. Bearer-token authentication per Sentinel node.
6. Sentinel health/status retrieval.
7. SOI profile creation, validation, import/export, revisioning, and deployment.
8. Atomic configuration/profile deployment.
9. Test Discord alert command.
10. Recent Sentinel event retrieval.
11. Human-readable terminal output and machine-readable JSON output.
12. Local audit log of management actions.
13. A dry-run mode for all write operations.
14. Explicit confirmation for destructive or disruptive operations.

### 4.2 Deferred capabilities

Do not implement these in version 1, but design interfaces so they can be added later:

- Graphical desktop UI.
- Web dashboard/map.
- MQTT broker or remote MQTT command plane.
- OTA firmware upload/deployment.
- SSH access or serial-console management.
- Central long-term RF-event database.
- Raw packet capture or PCAP retrieval.
- Cross-node multilateration/triangulation.
- Cloud account, mandatory cloud service, or vendor lock-in.
- Discord bot command parsing.

## 5. Technology choices

Use the following stack unless a strong implementation reason requires a documented deviation:

| Concern | Requirement |
|---|---|
| Language | Python 3.11 or newer |
| Packaging | `pyproject.toml`; installable console script named `legionctl` |
| CLI | Typer preferred; Click acceptable |
| HTTP client | `httpx` |
| Async support | `asyncio` with concurrent Sentinel node operations |
| mDNS discovery | `zeroconf` |
| Data models | Pydantic v2 |
| Profile schema validation | Pydantic plus JSON Schema export or `jsonschema` |
| Config format | JSON for canonical profiles and app state; YAML import/export may be optional |
| Terminal display | Rich |
| Testing | pytest, pytest-asyncio, respx or equivalent HTTP mock library |
| Static checks | Ruff and mypy or pyright |
| Credential storage | Python `keyring` when available; encrypted local fallback when unavailable |
| TLS | Verify certificates by default; support an explicitly flagged development-only trust override |

Do not make a GUI framework, a database server, Docker, Kubernetes, MQTT, or a web framework required to run the initial CLI.

## 6. Application identity and filesystem layout

The executable name is:

```text
legionctl
```

Use XDG-compliant paths on Linux:

```text
$XDG_CONFIG_HOME/legion/       default: ~/.config/legion/
$XDG_DATA_HOME/legion/         default: ~/.local/share/legion/
$XDG_STATE_HOME/legion/        default: ~/.local/state/legion/
```

Suggested layout:

```text
~/.config/legion/
├── config.json                # non-secret application preferences
├── inventory.json             # Sentinel nodes/groups and non-secret metadata
├── profiles/
│   ├── foxhunt-baseline.json
│   ├── north-door.json
│   └── event-alpha-r4.json
└── trust/
    └── development-ca.pem     # optional, only if explicitly configured

~/.local/share/legion/
└── schema/
    └── profile.schema.json

~/.local/state/legion/
├── audit.jsonl
├── discovery-cache.json
└── last-results.json
```

Secrets must not be written in plaintext to `inventory.json`, profile files, audit logs, or terminal output.

## 7. Fleet model

### 7.1 Sentinel inventory

Represent each known Sentinel node with the following non-secret model:

```json
{
  "sentinel_id": "sentinel-north-door-01",
  "display_name": "North Door",
  "zone": "North Door",
  "hostname": "sentinel-north-door-01.local",
  "base_url": "https://sentinel-north-door-01.local",
  "last_known_ip": "192.168.50.41",
  "api_version": "v1",
  "firmware_version": "0.1.0",
  "capabilities": [
    "wifi_2_4ghz",
    "wifi_5ghz",
    "wifi_6",
    "ble",
    "bt_classic"
  ],
  "groups": ["event-alpha", "entryways"],
  "enabled": true,
  "last_seen_utc": "2026-09-03T22:30:00Z"
}
```

Each Sentinel’s bearer token must be stored separately in the OS keyring under a deterministic service/account combination, for example:

```text
service: legionctl
account: sentinel-north-door-01
```

### 7.2 Groups

Groups are local inventory labels that let one Legion command target multiple Sentinel nodes:

```json
{
  "group": "event-alpha",
  "description": "Sentinel nodes deployed for Event Alpha",
  "members": [
    "sentinel-north-door-01",
    "sentinel-hall-b-01",
    "sentinel-loading-dock-01"
  ]
}
```

Groups may overlap.

### 7.3 Target selectors

Every Legion command that can contact Sentinel nodes should support one or more of:

```text
--node <sentinel-id>
--group <group-name>
--all
--selector zone=<value>
```

Rules:

- Default to no target if one is not explicit.
- `--all` must require confirmation for write/disruptive operations.
- A selector that resolves to zero nodes is an error.
- A selector that resolves to more than one node must display the resolved node list before performing a write operation.

## 8. Sentinel REST API contract

Assume the Sentinel primary ESP32-C5 controller exposes this API. Implement the Legion client as a thin, testable layer so endpoint details can be adjusted in one place later.

Base URL:

```text
https://<sentinel-hostname-or-ip>/api/v1
```

All endpoints except a narrowly defined bootstrap/provisioning endpoint require:

```http
Authorization: Bearer <node-specific-token>
Accept: application/json
```

All requests require timeouts. Use conservative defaults:

```text
Connect timeout: 3 seconds
Read timeout: 10 seconds
Write timeout: 10 seconds
Total retries: 2 for idempotent reads only
```

Do not automatically retry commands that can create duplicate side effects, such as test alerts, reboot, or future firmware updates.

### 8.1 Sentinel information

```http
GET /api/v1/info
```

Expected response:

```json
{
  "api_version": "v1",
  "sentinel_id": "sentinel-north-door-01",
  "display_name": "North Door",
  "zone": "North Door",
  "firmware_version": "0.1.0",
  "build_id": "git-abcdef1",
  "capabilities": [
    "wifi_2_4ghz",
    "wifi_5ghz",
    "wifi_6",
    "ble",
    "bt_classic"
  ],
  "profile_id": "event-alpha",
  "profile_revision": 4,
  "uptime_seconds": 81234
}
```

### 8.2 Sentinel health

```http
GET /api/v1/health
```

Expected response:

```json
{
  "sentinel_id": "sentinel-north-door-01",
  "timestamp_utc": "2026-09-03T22:30:00Z",
  "battery": {
    "voltage_v": 3.92,
    "percent": 67,
    "charging": false
  },
  "wifi": {
    "connected": true,
    "ssid": "REDACTED_OR_OPTIONAL",
    "band": "5ghz",
    "rssi_dbm": -58,
    "ip": "192.168.50.41",
    "reconnect_count": 2
  },
  "scanners": {
    "wifi": "running",
    "ble": "running",
    "bt_classic_coprocessor": "healthy"
  },
  "alert_queue": {
    "depth": 0,
    "last_delivery": "success"
  },
  "system": {
    "free_heap_bytes": 145280,
    "reset_reason": "power_on",
    "watchdog_resets": 0
  }
}
```

### 8.3 Redacted configuration

```http
GET /api/v1/config
```

This endpoint must never return Wi-Fi credentials or a Discord webhook URL. Legion must handle a response such as:

```json
{
  "sentinel_id": "sentinel-north-door-01",
  "zone": "North Door",
  "timezone": "America/New_York",
  "profile_id": "event-alpha",
  "profile_revision": 4,
  "discord_configured": true,
  "wifi_configured": true,
  "scan_policy": {
    "wifi_2_4_channels": [1, 6, 11],
    "wifi_5_channels": [36, 40, 44, 48],
    "wifi_dwell_ms": 250,
    "ble_scan_interval_ms": 100,
    "ble_scan_window_ms": 30,
    "classic_inquiry_seconds": 10,
    "classic_rest_seconds": 20
  }
}
```

### 8.4 Profile/rule retrieval

```http
GET /api/v1/rules
```

Expected response:

```json
{
  "profile_id": "event-alpha",
  "revision": 4,
  "schema_version": 1,
  "rules": []
}
```

### 8.5 Atomic profile deployment

```http
PUT /api/v1/rules
Content-Type: application/json
Idempotency-Key: <uuid>
```

The request body is a full profile document. The Sentinel node must validate, stage, persist, and atomically activate the document only if it is valid.

Expected success response:

```json
{
  "status": "activated",
  "profile_id": "event-alpha",
  "revision": 4,
  "activation_timestamp_utc": "2026-09-03T22:31:00Z"
}
```

Expected validation failure response:

```json
{
  "status": "rejected",
  "errors": [
    {
      "path": "rules[0].minimum_rssi_dbm",
      "message": "must be between -100 and 0"
    }
  ]
}
```

### 8.6 Test Discord alert

```http
POST /api/v1/commands/test-alert
Content-Type: application/json
Idempotency-Key: <uuid>
```

Request:

```json
{
  "message": "Legion test alert",
  "include_health_summary": true
}
```

Expected response:

```json
{
  "accepted": true,
  "queued": false,
  "delivery": "success",
  "timestamp_utc": "2026-09-03T22:32:00Z"
}
```

### 8.7 Diagnostic scan command

```http
POST /api/v1/commands/scan
```

Request:

```json
{
  "action": "start",
  "technology": "ble",
  "duration_seconds": 30
}
```

Constraints:

- Diagnostic scans must be bounded by a maximum duration.
- Legion must not provide unbounded `start` commands.
- Sentinel firmware remains responsible for rejecting unsupported or unsafe scan parameters.

### 8.8 Reboot

```http
POST /api/v1/commands/reboot
```

Request:

```json
{
  "reason": "operator_requested"
}
```

This is disruptive and must require explicit Legion CLI confirmation unless `--yes` is passed.

### 8.9 Recent events

```http
GET /api/v1/events/recent?limit=100
```

Expected response:

```json
{
  "sentinel_id": "sentinel-north-door-01",
  "events": [
    {
      "event_id": "evt_01J7...",
      "timestamp_utc": "2026-09-03T22:20:00Z",
      "event_type": "alert",
      "soi_id": "fox-03",
      "technology": "bt_classic",
      "rssi_dbm": -63,
      "confidence": {
        "hits": 3,
        "window_seconds": 15
      },
      "discord_delivery": "success"
    }
  ]
}
```

Events must remain metadata-only. Do not model packet payloads or request raw captures.

## 9. SOI profile format

### 9.1 Canonical profile document

Profiles are JSON files that define scan policy and SOI rules. Legion must validate them locally before deployment.

```json
{
  "schema_version": 1,
  "profile_id": "event-alpha",
  "revision": 4,
  "description": "Event Alpha baseline SOI profile",
  "default_cooldown_seconds": 300,
  "scan_policy": {
    "wifi_2_4_channels": [1, 6, 11],
    "wifi_5_channels": [36, 40, 44, 48],
    "wifi_scan_interval_seconds": 15,
    "wifi_dwell_ms": 250,
    "ble_scan_interval_ms": 100,
    "ble_scan_window_ms": 30,
    "classic_inquiry_seconds": 10,
    "classic_rest_seconds": 20
  },
  "rules": [
    {
      "id": "fox-03-classic",
      "name": "FOX-03 Bluetooth Classic",
      "enabled": true,
      "technology": "bt_classic",
      "match": {
        "all": [
          {
            "field": "address",
            "equals": "AA:BB:CC:DD:EE:FF"
          }
        ]
      },
      "minimum_rssi_dbm": -78,
      "required_hits": 2,
      "window_seconds": 20,
      "cooldown_seconds": 300,
      "severity": "high"
    },
    {
      "id": "fox-03-ble",
      "name": "FOX-03 BLE",
      "enabled": true,
      "technology": "ble",
      "match": {
        "all": [
          {
            "field": "service_uuid",
            "equals": "12345678-1234-1234-1234-1234567890ab"
          },
          {
            "field": "manufacturer_id",
            "equals": "0x1234"
          }
        ],
        "exclude": [
          {
            "field": "local_name",
            "contains": "TEST"
          }
        ]
      },
      "minimum_rssi_dbm": -75,
      "required_hits": 3,
      "window_seconds": 12,
      "cooldown_seconds": 300,
      "severity": "high"
    },
    {
      "id": "authorized-wifi-asset-01",
      "name": "Authorized Wi-Fi asset",
      "enabled": true,
      "technology": "wifi",
      "band": "5ghz",
      "match": {
        "all": [
          {
            "field": "bssid",
            "equals": "AA:BB:CC:DD:EE:FF"
          }
        ]
      },
      "minimum_rssi_dbm": -78,
      "required_hits": 3,
      "window_seconds": 15,
      "cooldown_seconds": 300,
      "severity": "medium"
    }
  ]
}
```

### 9.2 Supported technologies

Valid `technology` values:

```text
wifi
ble
bt_classic
```

Future values may include:

```text
zigbee
thread
lora
subghz
sdr
```

Legion must reject unknown values by default unless a future schema version explicitly supports them.

### 9.3 Match model

A rule may contain:

```json
{
  "all": [],
  "any": [],
  "exclude": []
}
```

Valid comparison operators for version 1:

```text
equals
contains
prefix
regex
exists
```

Validation requirements:

- A rule must contain at least one positive matcher in `all` or `any`.
- MAC/BSSID addresses must validate as colon-separated hexadecimal addresses.
- OUIs must validate as three octets.
- UUIDs must validate in accepted 16-bit, 32-bit, or canonical 128-bit forms as appropriate.
- RSSI must be within a sensible range, such as `-100` through `0` dBm.
- `required_hits` must be at least 1.
- Windows, cooldowns, inquiry periods, and dwell times must be bounded positive values.
- A Wi-Fi 2.4 GHz rule may only use channels 1–14 unless another regulatory-domain implementation is later introduced.
- A Wi-Fi 5 GHz channel must be validated against a known supported/channel-plan list, with conservative defaults.

### 9.4 Revision policy

- `profile_id` is stable across revisions.
- `revision` is a positive integer.
- Legion must not push a lower revision unless `--allow-downgrade` is passed.
- Before deployment, compare the Sentinel node’s active profile ID/revision to the candidate profile.
- A profile update must be atomic at the node.
- Legion must report success, rejection, timeout, or unreachable status independently for every targeted Sentinel node.

## 10. CLI specification

### 10.1 General behavior

- Exit code `0`: all requested actions succeeded.
- Exit code `1`: command or validation error.
- Exit code `2`: one or more targeted Sentinel nodes failed/unreachable while at least one action succeeded or was attempted.
- Exit code `3`: authentication/TLS/credential error.
- Exit code `4`: user declined a required confirmation.
- Support `--json` for structured output where meaningful.
- Support `--timeout <seconds>` overrides.
- Support `--verbose` and `--debug`; never print bearer tokens, Wi-Fi credentials, or Discord webhook URLs.
- Support `--dry-run` on every write operation.

### 10.2 Required commands

#### Discovery

```bash
legionctl discover
legionctl discover --timeout 8
legionctl discover --add
legionctl discover --json
```

Behavior:

- Discover `_sentinel._tcp.local.` service records using mDNS/zeroconf.
- Resolve hostname, IP, port, and TXT metadata where available.
- Query `GET /api/v1/info` when credentials are already known or the endpoint permits non-secret identification.
- Display discovered vs known inventory state.
- `--add` adds Sentinel nodes after displaying the resolved node details and requesting confirmation.

Expected terminal columns:

```text
ID | Zone | Hostname | IP | Firmware | Profile | Reachable | Known
```

#### Inventory

```bash
legionctl node list
legionctl node show sentinel-north-door-01
legionctl node add --id sentinel-north-door-01 --url https://192.168.50.41 --token-stdin
legionctl node remove sentinel-north-door-01
legionctl node rename sentinel-north-door-01 --display-name "North Door" --zone "North Door"
legionctl group list
legionctl group create event-alpha --description "Event Alpha deployment"
legionctl group add-member event-alpha sentinel-north-door-01
legionctl group remove-member event-alpha sentinel-north-door-01
```

Rules:

- `node add` must accept a token only from stdin, prompt, or keyring import; do not accept token values directly in shell arguments.
- `node remove` requires confirmation.
- Group mutations update local inventory only and do not contact a Sentinel node.

#### Health and status

```bash
legionctl status --node sentinel-north-door-01
legionctl status --group event-alpha
legionctl status --all
legionctl status --all --json
legionctl health --all
```

Behavior:

- Run requests concurrently with bounded concurrency, default 5.
- Display battery, Wi-Fi connectivity, Wi-Fi band/RSSI, scanner state, coprocessor health, alert queue depth, profile revision, and last response timestamp.
- Mark stale/unreachable Sentinel nodes clearly.

#### Profiles

```bash
legionctl profile list
legionctl profile show event-alpha
legionctl profile validate profiles/event-alpha.json
legionctl profile import profiles/event-alpha.json
legionctl profile export event-alpha --output event-alpha.json
legionctl profile create event-alpha
legionctl profile clone event-alpha event-alpha-r5
```

Behavior:

- `profile create` can create a valid minimal skeleton interactively or from a template.
- `profile validate` must report all schema and semantic validation errors with JSON paths.
- `profile import` must not overwrite an existing profile silently.

#### Deploy profiles

```bash
legionctl profile push event-alpha --node sentinel-north-door-01
legionctl profile push event-alpha --group event-alpha
legionctl profile push event-alpha --all
legionctl profile push event-alpha --group event-alpha --dry-run
legionctl profile push event-alpha --group event-alpha --yes
legionctl profile diff event-alpha --node sentinel-north-door-01
```

Deployment flow:

1. Load and validate the local profile.
2. Resolve targets.
3. Retrieve each target’s current profile revision/config summary.
4. Show a per-node diff/summary.
5. Require explicit confirmation unless `--yes` is supplied.
6. Generate a unique `Idempotency-Key` per Sentinel node request.
7. Concurrently call `PUT /api/v1/rules`.
8. Print a per-node result table.
9. Write a Legion audit record.

#### Commands

```bash
legionctl test-alert --node sentinel-north-door-01
legionctl test-alert --group event-alpha
legionctl scan --node sentinel-north-door-01 --technology ble --duration 30
legionctl reboot --node sentinel-north-door-01
legionctl events --node sentinel-north-door-01 --limit 50
legionctl events --group event-alpha --limit 20
```

Rules:

- `test-alert`, `scan`, and `reboot` are write/side-effect actions.
- Require confirmation unless `--yes` is supplied.
- `scan` must require a bounded `--duration`; reject duration above the configured client maximum, initially 300 seconds.
- `reboot --all` should require a second confirmation or reject unless `--force-all` is explicitly supplied.

#### Credentials

```bash
legionctl credential set sentinel-north-door-01 --token-stdin
legionctl credential check sentinel-north-door-01
legionctl credential delete sentinel-north-door-01
```

Behavior:

- Use OS keyring by default.
- Never echo/store the token in terminal history, shell arguments, inventory files, or audit logs.
- `credential check` performs a lightweight authenticated `GET /api/v1/info` request.

## 11. User interaction examples

### 11.1 Discover and add a Sentinel node

```text
$ legionctl discover

Discovered Sentinel nodes

ID                       Zone          Hostname                              IP             Firmware  Known
sentinel-north-door-01   North Door    sentinel-north-door-01.local          192.168.50.41  0.1.0     no

$ legionctl discover --add
Add discovered Sentinel node sentinel-north-door-01 (North Door, 192.168.50.41) to inventory? [y/N]: y
Bearer token for sentinel-north-door-01: [hidden]
Added sentinel-north-door-01 to inventory and stored token in system keyring.
```

### 11.2 Validate and deploy a profile

```text
$ legionctl profile validate profiles/event-alpha.json
Profile event-alpha revision 4 is valid.
Rules: 3
Technologies: ble, bt_classic, wifi

$ legionctl profile push event-alpha --group event-alpha
Resolved targets: 3

Sentinel                   Current profile       Candidate       Action
sentinel-north-door-01     event-alpha r3        event-alpha r4  update
sentinel-hall-b-01         event-alpha r4        event-alpha r4  unchanged
sentinel-loading-dock-01   none                  event-alpha r4  install

Deploy event-alpha revision 4 to 2 Sentinel nodes? [y/N]: y

Sentinel                   Result       Active profile
sentinel-north-door-01     activated    event-alpha r4
sentinel-hall-b-01         skipped      event-alpha r4
sentinel-loading-dock-01   activated    event-alpha r4
```

### 11.3 Query fleet health

```text
$ legionctl status --all

Sentinel                   Zone          Battery  Wi-Fi          Scanners             BT coprocessor  Queue  Profile
sentinel-north-door-01     North Door    67%      5 GHz / -58 dBm running              healthy         0      event-alpha r4
sentinel-hall-b-01         Hall B        41%      2.4 GHz/-70 dBm running              healthy         1      event-alpha r4
sentinel-garage-01         Garage        --       unreachable    unknown              unknown         --     unknown
```

## 12. Security requirements

### 12.1 Credential handling

- Store Sentinel node bearer tokens in an OS credential manager through `keyring` where possible.
- Never put bearer tokens in command-line arguments.
- Never store bearer tokens in profile files, inventory JSON, audit logs, exported state, or exception traces.
- Never store Discord webhook URLs in Legion profile files unless a future explicit secret-management design is introduced.
- Sentinel config retrieval must remain redacted.

### 12.2 TLS

- Verify TLS certificates by default.
- Support a development-only `--insecure-skip-tls-verify` flag, but print an unmissable warning and require explicit use per command.
- Do not persist an insecure setting as the normal default.
- Plan for self-signed-Sentinel certificate enrollment or a local CA trust path, but defer full certificate lifecycle tooling until later.

### 12.3 Authorization

- Treat all Sentinel commands as privileged.
- Require bearer tokens for management operations.
- Require an explicit target selection for all Sentinel write operations.
- Require confirmation for test alert, scanning, profile deployment, reboot, node deletion, and credential deletion unless `--yes` is provided.
- `--yes` must be visibly logged to the Legion audit trail.

### 12.4 Input handling

- Enforce request body and response size limits.
- Validate all API responses with Pydantic models.
- Fail closed on malformed Sentinel responses.
- Do not execute shell commands based on node-provided text.
- Escape or safely render all remote strings in Rich terminal output.

## 13. Audit log requirements

Write an append-only JSON Lines audit log to:

```text
~/.local/state/legion/audit.jsonl
```

Each record must include:

```json
{
  "timestamp_utc": "2026-09-03T22:45:00Z",
  "operation": "profile_push",
  "operator": "local_username",
  "targets": ["sentinel-north-door-01"],
  "profile_id": "event-alpha",
  "profile_revision": 4,
  "dry_run": false,
  "result": "success",
  "details": {
    "activated": ["sentinel-north-door-01"],
    "failed": []
  }
}
```

Never write secrets, full Discord webhook URLs, Wi-Fi credentials, or bearer tokens to the audit log.

## 14. Internal project layout

Create a clean, modular Python package.

```text
legion/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── src/
│   └── legionctl/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── settings.py
│       ├── constants.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── inventory.py
│       │   ├── node_api.py
│       │   ├── profile.py
│       │   └── audit.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── discovery.py
│       │   ├── inventory.py
│       │   ├── credentials.py
│       │   ├── profiles.py
│       │   ├── fleet.py
│       │   └── audit.py
│       ├── clients/
│       │   ├── __init__.py
│       │   └── sentinel_api.py
│       ├── commands/
│       │   ├── __init__.py
│       │   ├── discover.py
│       │   ├── node.py
│       │   ├── group.py
│       │   ├── status.py
│       │   ├── profile.py
│       │   ├── actions.py
│       │   └── credential.py
│       ├── output/
│       │   ├── __init__.py
│       │   ├── console.py
│       │   └── json.py
│       └── resources/
│           └── profile.schema.json
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── docs/
    ├── api-contract.md
    ├── profile-format.md
    └── development.md
```

Keep transport/API code out of Typer command handlers. CLI handlers should parse options, call services, render output, and set exit codes. Business logic must be directly unit-testable without a terminal.

## 15. Implementation milestones

### Milestone 1: Foundation

Implement:

- Python project setup and packaging.
- `legionctl --help`.
- XDG path resolution.
- Settings and logging with secret redaction.
- Pydantic models for inventory, profiles, API responses, and audit records.
- Inventory read/write service with atomic local-file writes.
- Keyring credential abstraction.
- Profile JSON schema generation and local validation.
- Unit tests for all models and validation behavior.

Acceptance:

```bash
legionctl profile validate docs/examples/event-alpha.json
legionctl node list
legionctl group list
```

must operate locally without a network.

### Milestone 2: Sentinel API client

Implement:

- Async `SentinelApiClient` using `httpx`.
- Typed support for `info`, `health`, `config`, `rules`, `put_rules`, `test_alert`, `scan`, `reboot`, and `recent_events`.
- Bearer-token injection from the credential abstraction.
- TLS/timeouts/error mapping.
- Mocked integration tests for success, timeout, HTTP 401, HTTP 409, HTTP 422, malformed JSON, and unreachable-node cases.

Acceptance:

- Client errors map to clear, non-secret terminal errors.
- API responses are validated before use.

### Milestone 3: Discovery and inventory

Implement:

- Zeroconf/mDNS discovery service for `_sentinel._tcp.local.`.
- `discover`, `node add`, `node list`, `node show`, `node remove`, `node rename`.
- Group creation and membership commands.
- Discovery cache.

Acceptance:

- A simulated discovery record can be parsed into a candidate inventory node.
- Duplicate Sentinel IDs and inconsistent hostnames are detected.

### Milestone 4: Fleet observability

Implement:

- Concurrent `status`, `health`, and `events` commands.
- Rich table rendering.
- `--json` output with stable schemas.
- Clear partial-failure reporting and exit code 2 behavior.

Acceptance:

```bash
legionctl status --all
legionctl health --group event-alpha
legionctl events --node sentinel-north-door-01 --limit 50
```

operate against mocked Sentinel nodes and display per-node success/failure independently.

### Milestone 5: Profile lifecycle and deployment

Implement:

- Profile list/show/create/import/export/clone/validate/diff.
- Atomic deployment workflow.
- Target resolution.
- Dry-run behavior.
- Confirmation UX.
- Idempotency keys.
- Audit logging.

Acceptance:

- An invalid profile cannot reach a Sentinel API call.
- A lower revision is rejected unless explicitly overridden.
- A write action displays resolved targets and changes before requesting confirmation.
- Per-node deployment success/failure is recorded in the Legion audit log.

### Milestone 6: Operational commands

Implement:

- `test-alert`.
- Bounded diagnostic `scan`.
- `reboot` with confirmation guard.
- Credential set/check/delete.

Acceptance:

- No duplicate retries on these side-effecting commands.
- Commands support `--dry-run` where meaningful.
- Reboot requires confirmation and displays the affected Sentinel node precisely.

## 16. Testing requirements

### 16.1 Unit tests

Create unit tests for:

- Profile parsing and schema validation.
- MAC, OUI, UUID, RSSI, duration, channel, and revision validation.
- Inventory CRUD and atomic file behavior.
- Group target resolution.
- Secret redaction.
- Audit record generation.
- API error mapping.
- Confirmation behavior.
- CLI exit code behavior.

### 16.2 Integration tests

Use mocked HTTP endpoints to test:

- Successful Sentinel health retrieval.
- Sentinel node unreachable/timeouts.
- Invalid/malformed API responses.
- Unauthorized token.
- TLS failure mapping where feasible.
- Profile validation rejection from Sentinel node.
- Mixed fleet result: one successful Sentinel, one unreachable Sentinel, one rejected profile.
- Idempotency-key creation per target.
- No automatic retry for test-alert/reboot/scan writes.

### 16.3 Manual test plan

Document a manual test plan for real hardware later:

1. Start one Sentinel in a trusted test network.
2. Add the node with a token via stdin/prompt.
3. Run `legionctl status --node ...`.
4. Push a valid BLE/Bluetooth Classic/Wi-Fi profile.
5. Run a test Discord alert.
6. Trigger a known controlled SOI.
7. Verify that Sentinel sends the Discord alert independently.
8. Turn off Legion and repeat the SOI test.
9. Verify Sentinel still alerts.
10. Restore Legion connectivity and inspect recent events.

## 17. Documentation requirements

Create a `README.md` that includes:

- Project purpose and non-goals.
- Supported operating system target: Linux first.
- Installation instructions using `pipx` and editable developer install.
- Example inventory/bootstrap flow.
- Example profile validation and deployment flow.
- Security model and credential handling.
- Explanation that Legion is the management plane, while Discord is the Sentinel notification plane.
- A warning that Sentinel nodes should be used only with authorized SOIs and authorized deployments.

Create `docs/profile-format.md` containing the full profile field reference and at least one valid example per supported technology.

Create `docs/api-contract.md` documenting the assumed Sentinel node API described in this specification.

## 18. Definition of done

The first release is complete when a Linux operator can:

1. Install `legionctl`.
2. Discover or manually add multiple Sentinel nodes.
3. Store Sentinel node tokens without plaintext inventory storage.
4. Check status/health for all Sentinel nodes concurrently.
5. Create and validate a JSON SOI profile.
6. Compare that profile against a Sentinel node’s installed profile.
7. Push it atomically to selected Sentinel nodes/groups with confirmation.
8. Trigger a test Discord notification on selected Sentinel nodes.
9. Retrieve recent metadata-only events.
10. Review an audit log of Legion management actions.
11. Confirm that a Sentinel node continues to operate and alert independently while Legion is offline.

## 19. Implementation guidance

Prioritize a small, dependable, CLI-first application over a polished dashboard.

Key design principles:

- Local Sentinel autonomy is more important than centralized orchestration.
- Profile validation must occur before network deployment.
- Sentinel-specific outcomes matter; never hide partial fleet failures.
- Treat credentials and Discord webhook-related material as secrets.
- Keep write actions explicit, reviewable, confirmed, and auditable.
- Keep the Legion control plane separate from the Discord notification plane.
- Design for later expansion, but avoid adding MQTT, OTA, databases, dashboards, PCAP, or central server requirements to version 1.
