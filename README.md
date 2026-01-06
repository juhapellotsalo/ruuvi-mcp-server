# Ruuvi MCP Server

Monitor any space with natural language. This MCP server connects Claude to your Ruuvi sensors, letting you ask questions about temperature, humidity, air quality, and more in plain English.

## What Can You Do?

Once connected, just ask Claude about your sensors:

> **"How's the air quality in my office right now?"**
>
> Your office CO2 is at 847 ppm (good) and PM2.5 is 8.2 µg/m³ (excellent). Temperature is 24.1°C with 62% humidity. The air quality is healthy for extended work.

> **"Compare garage and workshop temperatures over the past week"**
>
> The garage averaged 28.4°C while the workshop was cooler at 25.1°C. The garage shows more variation (22-38°C) due to sun exposure, while the workshop stayed stable (24-27°C) thanks to better insulation.

> **"When does my office get stuffy? Look at the last month of data."**
>
> CO2 consistently rises above 1000 ppm on weekday afternoons between 2-5 PM, peaking around 1400 ppm. This correlates with closed windows. Opening a window around 2 PM or taking a short break would help maintain concentration.

> **"Did the humidity drop when I turned on the AC yesterday?"**
>
> Yes, humidity dropped from 68% to 51% within 2 hours of the AC being turned on around 10 AM. It stabilized around 48% by noon.

## Features

- **Conversational queries** - Ask about your environment in natural language
- **Smart health insights** - Get WHO guideline-based assessments (good/elevated/poor)
- **Historical analysis** - Query trends over hours, days, or weeks
- **Multiple sensor types** - RuuviTag (temperature, humidity, pressure) and Ruuvi Air (CO2, PM2.5, VOC, NOx)
- **Flexible data collection** - Gateway HTTP, MQTT, Ruuvi Cloud API, or direct BLE

## Quick Start

### 1. Install

```bash
git clone https://github.com/juhapellotsalo/ruuvi-mcp-server.git
cd ruuvi-mcp-server
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure

```bash
cp config.example.yaml config.yaml
```

Choose your data source based on your setup:

**Option A: Ruuvi Cloud (paid subscription)**
```bash
ruuvi-cli
> cloud auth    # Authenticate with Ruuvi Cloud
> cloud sync    # Sync historical data (runs continuously with paid plan)
```

**Option B: Gateway with HTTP polling**
```bash
ruuvi-cli
> gateway config   # Set gateway URL and token
> gateway test     # Verify connection
> gateway poll     # Start continuous collection
```

**Option C: Gateway with MQTT**
```bash
ruuvi-cli
> mqtt config      # Set broker address
> mqtt listen      # Start continuous collection
```

**Option D: Direct BLE (no gateway or paid cloud)**
```bash
ruuvi-cli
> ble scan         # Find nearby Ruuvi devices
> ble sync         # Sync history via Bluetooth
> ble listen       # Listen to live broadcasts
```

### 3. Add to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "Ruuvi": {
      "command": "/path/to/ruuvi-mcp-server/.venv/bin/ruuvi-mcp"
    }
  }
}
```

Restart Claude Desktop and ask Claude about your indoor air quality.

## Data Sources

| Source | Update Frequency                | Setup |
|--------|---------------------------------|-------|
| **Gateway HTTP** | ~1 sec                          | `gateway config` then `gateway poll` |
| **MQTT** | ~1 sec                          | `mqtt config` then `mqtt listen` |
| **Ruuvi Cloud** | Depends on the plan             | `cloud auth` then `cloud sync` |
| **Direct BLE** | ~1 sec (listen) or history sync | `ble scan` then `ble listen` or `ble sync` |

## MCP Tools

The server exposes three tools to Claude:

- **`list_sensors()`** - Discover available sensors and data range
- **`get_current(device?)`** - Latest readings with health status
- **`query(start, end, resolution, device)`** - Historical data with flexible time ranges

## CLI Commands

```bash
ruuvi-cli                    # Interactive mode
ruuvi-cli cloud sync         # Sync from Ruuvi Cloud
ruuvi-cli gateway poll       # Live readings from gateway
ruuvi-cli mqtt monitor       # Monitor MQTT messages
ruuvi-cli devices            # List configured devices
ruuvi-cli status             # Show configuration status
```


## Requirements

- Python 3.12+
- Ruuvi sensors (RuuviTag or Ruuvi Air)
- One of: Ruuvi Gateway, Ruuvi Cloud account, or direct BLE (no additional hardware needed)

## License

MIT
