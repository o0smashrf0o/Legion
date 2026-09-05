APP_NAME = "legion"
CLI_NAME = "legionctl"
KEYRING_SERVICE = "legionctl"
MDNS_SERVICE_TYPE = "_sentinel._tcp.local."
API_PREFIX = "/api/v1"
PROFILE_SCHEMA_VERSION = 1
INVENTORY_SCHEMA_VERSION = 2
NOMINAL_COHORT_SIZE = 5

CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 10.0
WRITE_TIMEOUT_SECONDS = 10.0
IDEMPOTENT_READ_RETRIES = 2
DEFAULT_CONCURRENCY = 5
MAX_SCAN_DURATION_SECONDS = 300
MAX_RESPONSE_BYTES = 1_048_576
MAX_REQUEST_BYTES = 262_144

WIFI_24_CHANNELS = frozenset(range(1, 15))
WIFI_5_CHANNELS = frozenset(
    {
        36,
        40,
        44,
        48,
        52,
        56,
        60,
        64,
        100,
        104,
        108,
        112,
        116,
        120,
        124,
        128,
        132,
        136,
        140,
        144,
        149,
        153,
        157,
        161,
        165,
    }
)

RSSI_MIN_DBM = -100
RSSI_MAX_DBM = 0
