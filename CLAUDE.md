# Ruuvi Data Advisor

An MCP server that collects sensor data from Ruuvi sensors and allows conversational access to indoor air quality data.

## Project Status

- **Data collection**: Working - four sources: Gateway HTTP, MQTT, Ruuvi Cloud API, direct BLE
- **Deduplication**: Uses `(device_id, timestamp)` to prevent duplicates across sources
- **Interactive CLI**: Full-featured CLI with subcommands for configuration and data collection
- **MCP server**: Implemented - provides `list_sensors`, `get_current`, `query` tools

## Architecture

```
                                    ┌─────────────────┐
Ruuvi Sensors ──[BLE]──> Gateway ───┤ HTTP /history   ├──> ruuvi-cli gateway poll ──┐
        │                   │       └─────────────────┘                              │
        │                   │       ┌─────────────────┐                              │
        │                   └───────┤ MQTT broker     ├──> ruuvi-cli mqtt listen ────┤
        │                           └─────────────────┘                              │
        │                           ┌─────────────────┐                              ├──> SQLite
        │                Cloud <────┤ Ruuvi Cloud API ├──> ruuvi-cli cloud sync ─────┤        │
        │                           └─────────────────┘                              │   MCP Server
        │                                                                            │        │
        └──────────────────────────> ruuvi-cli ble listen/sync ─────────────────────┘     Claude
```

**Data sources:**
- **Gateway HTTP**: Polls `/history` endpoint (~1 reading/sec per sensor)
- **MQTT**: Real-time subscription to gateway broadcasts (~1 reading/sec)
- **Ruuvi Cloud**: Historical sync (5-min intervals on free plan)
- **Direct BLE**: Scan, listen to broadcasts, sync history via Bluetooth

## Supported Sensors

The system supports both RuuviTag and Ruuvi Air sensors. Sensor type is detected automatically from `dataFormat`:

| Data Format | Sensor Type | Name |
|-------------|-------------|------|
| 3 | tag | RAWv1 |
| 5 | tag | RAWv2 |
| 6 | air | Format6 (BLE4) |
| 225 (0xE1) | air | ExtendedV1 |

### Sensor Fields

| Field | Unit | Sensors | Description |
|-------|------|---------|-------------|
| `temperature` | °C | all | Accuracy ±0.45°C at 15-30°C |
| `humidity` | % RH | all | Accuracy ±4.5% at 30-70% |
| `pressure` | Pa | all | Divide by 100 for hPa |
| `co2` | ppm | air | Range 0-40000. >1000 = poor ventilation |
| `pm_1_0` | µg/m³ | air | Ultra-fine particles |
| `pm_2_5` | µg/m³ | air | Fine particles |
| `pm_4_0` | µg/m³ | air | Coarse particles |
| `pm_10_0` | µg/m³ | air | Large particles |
| `voc` | Index 0-500 | air | 100 = baseline, >100 = more VOCs |
| `nox` | Index 1-500 | air | Combustion/traffic pollutants |
| `acceleration_x/y/z` | G | tag | Range ±32.767 |
| `movement_counter` | count | tag | Increments on motion detection |
| `battery_voltage` | V | tag | Range 1.6-3.646 |
| `tx_power` | dBm | tag | Range -40 to +20 |
| `rssi` | dBm | all | Signal strength |

### Interpreting the data

- **CO2 > 1000 ppm**: Room needs ventilation, can cause fatigue
- **PM2.5 > 25 µg/m³**: Poor air quality (WHO guideline)
- **VOC > 100**: More volatile organic compounds than recent average
- **VOC < 100**: Cleaner than average (open window, air purifier)

## Project Structure

```
ruuvi-mcp-server/
├── pyproject.toml
├── config.yaml              # Configuration (not in git)
├── config.example.yaml      # Template configuration
├── data/
│   ├── readings.db          # SQLite time series database
│   └── devices.yaml         # Device metadata (nickname, type, etc.)
├── cli/                     # Interactive CLI (ruuvi-cli)
│   ├── __init__.py
│   ├── app.py               # Main CLI with cmd.Cmd
│   ├── ui.py                # Terminal UI helpers (Spinner, colors)
│   └── commands/
│       ├── __init__.py
│       ├── ble.py           # ble scan/listen/sync/history
│       ├── cloud.py         # cloud auth/sensors/history/sync
│       ├── config.py        # Configuration helpers
│       ├── devices.py       # devices list/add
│       ├── gateway.py       # gateway config/test/poll
│       ├── mqtt.py          # mqtt config/listen/monitor
│       ├── status.py        # status display
│       └── storage.py       # storage config
├── ruuvi_mcp/               # MCP server package (ruuvi-mcp)
│   ├── __init__.py
│   └── server.py            # MCP server with query tools
├── ruuvi_data/              # Data collection & storage package
│   ├── __init__.py
│   ├── config.py            # YAML config loading (gateway, cloud, mqtt, storage)
│   ├── devices.py           # Device metadata management (data/devices.yaml)
│   ├── models.py            # SensorReading, GatewayReading, format_reading()
│   ├── decoder.py           # BLE advertisement decoder (formats 0x05, 0x06, 0xE1)
│   ├── gateway.py           # Gateway HTTP client (GatewayClient)
│   ├── cloud.py             # Ruuvi Cloud API client (RuuviCloud)
│   ├── mqtt.py              # MQTT subscriber (MqttSubscriber)
│   ├── ble.py               # BLE protocol (download_history, decode_air_record)
│   └── storage.py           # SQLite storage with deduplication (SensorStorage)
└── tests/                   # Unit tests
    ├── test_ble.py
    ├── test_cli.py
    ├── test_decoder.py
    ├── test_devices.py
    ├── test_models.py
    └── test_storage.py
```

The codebase is organized into three main packages:
- **ruuvi_mcp**: Thin MCP server that exposes sensor data to Claude
- **ruuvi_data**: Data layer for collection, storage, and processing
- **cli**: Interactive command-line interface

## Interactive CLI

The CLI provides commands for configuration, testing, and data collection:

```bash
# Start interactive mode
ruuvi-cli

# Or run a single command directly
ruuvi-cli gateway test
ruuvi-cli ble scan
```

### Available Commands

```
gateway                Show gateway status
  gateway config       Configure gateway connection
  gateway test         Test gateway connection
  gateway poll         Poll readings and store to database
  gateway poll raw     Show raw JSON payload (no storage)

cloud                  Show cloud status
  cloud auth           Authenticate with Ruuvi Cloud
  cloud sensors        List sensors
  cloud sensors raw    List sensors (raw JSON)
  cloud history [dev]  Fetch sensor history (prompts if omitted)
  cloud sync [dev] [n] Sync to local database (one device or all)

mqtt                   Show MQTT status
  mqtt config          Configure MQTT broker
  mqtt listen          Subscribe and store readings
  mqtt monitor         Subscribe and display only (no storage)

ble                    Show BLE status
  ble scan             Scan for Ruuvi devices
  ble listen           Listen to broadcasts and store
  ble monitor          Listen to broadcasts (no storage)
  ble sync [dev] [period]    Sync history via Bluetooth (Air only)
  ble history [dev] [period] Display history (no storage)

devices                List configured devices
  devices add          Add a new device

storage                Configure storage settings
status                 Show all configuration status
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and configure via CLI or edit directly:

```yaml
gateway:
  url: http://ruuvigatewayXXXX.local
  token: your-bearer-token
  poll_interval: 1

cloud:
  email: your@email.com
  token: your-cloud-token

mqtt:
  broker: localhost
  port: 1883
  topic: ruuvi/#

storage:
  path: data/readings.db
```

Device metadata is stored separately in `data/devices.yaml`:

```yaml
site: "Home in the tropics. Hot and humid climate, no central AC."

devices:
- mac: AA:BB:CC:DD:EE:FF
  type: air
  nickname: Office
  description: Living room sensor near the window.
  ble_uuid: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
```

The `site` field provides global context for all sensors (returned by `list_sensors()`).
Devices are auto-registered when first seen, or added manually with `devices add`.

### Getting Tokens

- **Gateway token**: Gateway web UI → Settings → Cloud Options → Custom Server
- **Cloud token**: https://station.ruuvi.com → User Menu → Share sensors

## Data Collection

### Gateway Polling

```bash
ruuvi-cli gateway poll    # Poll and store readings continuously
```

Polls the Gateway's `/history` endpoint and stores readings to SQLite.

### MQTT Subscription

```bash
ruuvi-cli mqtt listen     # Subscribe and store readings
ruuvi-cli mqtt monitor    # Display only (no storage)
```

Subscribes to MQTT broker for real-time gateway broadcasts.

### Direct BLE Collection

```bash
ruuvi-cli ble scan        # Discover devices, add to data/devices.yaml
ruuvi-cli ble listen      # Listen to broadcasts and store
ruuvi-cli ble sync 7d     # Sync 7 days of history from device (Air only)
```

Period formats: `30m`, `1h`, `24h`, `7d`, `10d` (default: 10d)

Note: BLE history sync is only supported for Ruuvi Air devices. RuuviTag history sync is not yet implemented.

### Cloud Sync

```bash
ruuvi-cli cloud sync      # Sync last 1000 readings per sensor
```

Fetches historical data from Ruuvi Cloud. Limited to 5-min intervals on free plan.

### Deduplication

All sources store readings via `SensorStorage.insert()`. The database has a UNIQUE constraint on `(device_id, timestamp)`, so duplicate readings are automatically ignored regardless of source.

Devices are auto-registered on first reading with generated nicknames (air1, air2, tag1, etc.).

## MCP Server

The MCP server exposes these tools:

- `list_sensors()`: Discover available sensors and data time range
- `get_current(device?)`: Latest readings with health status
- `query(start, end, resolution, device)`: Historical data with flexible time ranges
  - start/end: ISO datetime or relative like "-1h", "-24h", "-7d"
  - resolution: "auto", "raw", "1m", "5m", "15m", "1h", "6h", "1d"

Resource:
- `ruuvi://guide`: Usage guide with thresholds and examples

```bash
ruuvi-mcp
```

## Dependencies

- `httpx`: HTTP client for Gateway/Cloud
- `paho-mqtt`: MQTT client
- `mcp`: Model Context Protocol server framework
- `pyyaml`: Configuration file parsing
- `bleak`: BLE client (optional, for direct BLE)
- Python 3.12+

## MQTT Setup

To use MQTT collection:

1. Install and run Mosquitto:
   ```bash
   brew install mosquitto
   # Edit /opt/homebrew/etc/mosquitto/mosquitto.conf, add:
   # listener 1883 0.0.0.0
   # allow_anonymous true
   brew services start mosquitto
   ```

2. Configure Gateway to publish MQTT:
   - Gateway web UI → Cloud Options → Custom Server
   - Set type to MQTT
   - Enter `mqtt://YOUR_MAC_IP:1883`

3. Configure and start listener:
   ```bash
   ruuvi-cli mqtt config
   ruuvi-cli mqtt listen
   ```

## BLE Setup

To use direct BLE collection (no gateway needed):

1. Install bleak:
   ```bash
   pip install bleak
   ```

2. Scan for devices:
   ```bash
   ruuvi-cli ble scan
   ```

3. Sync history or listen:
   ```bash
   ruuvi-cli ble sync 7d     # Sync 7 days of history (Air only)
   ruuvi-cli ble listen      # Listen to live broadcasts
   ```

## Reference Links

- [Ruuvi Gateway MQTT Guide](https://ruuvi.com/how-to-use-mqtt-with-your-ruuvi-gateway/)
- [Gateway Configuration Reference](https://docs.ruuvi.com/gw-data-formats/gateway-configuration)
- [MQTT Examples](https://docs.ruuvi.com/gw-examples/mqtt-examples)
- [Private Server Setup](https://ruuvi.com/connecting-ruuvi-gateway-to-a-private-server/)
- [Ruuvi Cloud Station](https://station.ruuvi.com) - Get cloud API token here
