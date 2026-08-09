# Powerpal BLE

[![Validate](https://github.com/alexiswl/powerpal/actions/workflows/validate.yml/badge.svg)](https://github.com/alexiswl/powerpal/actions/workflows/validate.yml)

A Home Assistant custom integration that connects Powerpal energy monitors directly over Bluetooth Low Energy (BLE). All data is collected locally — no cloud dependency required.

## Table of Contents

- [Features](#features)
- [Connection Modes](#connection-modes)
- [What you need](#what-you-need)
- [Installation](#installation)
- [Configuration: Direct BLE Mode](#configuration-direct-ble-mode)
- [Configuration: ESPHome Mode](#configuration-esphome-mode)
  - [Cloud Upload via ESPHome](#cloud-upload-via-esphome-optional)
- [Sensors and Energy Dashboard](#sensors-and-energy-dashboard)
- [BlueZ Bonding Option](#bluez-bonding-option)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Notes](#notes)
- [Credits & Acknowledgements](#credits--acknowledgements)
- [License](#license)

## Features

- Real-time power consumption monitoring (W)
- Energy dashboard compatible (total increasing kWh sensors)
- Automatic reconnection with exponential backoff
- Two connection modes: direct BLE or ESPHome-sourced

## Connection Modes

This integration supports two ways to connect to your Powerpal:

| Mode | How it works | Best for |
|------|-------------|----------|
| **Direct BLE** | Home Assistant connects to the Powerpal via a local Bluetooth adapter | HA server is within BLE range of the meter |
| **ESPHome** | An ESP32 running ESPHome handles the BLE connection and computes power measurements locally; the custom component receives power (W) readings and derives energy sensors | Meter is far from the HA server (e.g. external meter box) |

In ESPHome mode, the ESP32 is the BLE frontend (handles pairing, connection, notifications, and pulse-to-power conversion) and this integration is the backend (accumulates energy from power readings, tracks daily totals, integrates with the Energy Dashboard).

## What you need

### For Direct BLE mode

- **Home Assistant** (2023.8 or newer)
- **A Bluetooth adapter** recognised by Home Assistant (e.g. Asus BT500 USB dongle, or the device's built-in adapter)
- **Your Powerpal pairing code** — the 6-digit PIN from initial setup
- **Your meter's pulse rate** — usually 1000 pulses per kWh (check your meter's label)
- **Your Powerpal's BLE MAC address** — from the device sticker or HA's Bluetooth integration

### For ESPHome mode

- **Home Assistant** (2023.8 or newer)
- **An ESP32** running the ESPHome firmware from this repo (`esphome/powerpal_esphome.yaml`)
- **Your Powerpal pairing code** — the 6-digit PIN (configured in the ESPHome YAML)
- **Your meter's pulse rate** — usually 1000 pulses per kWh (configured in the ESPHome YAML as `pulses_per_kwh`)

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Go to **Integrations** → **⋮** (top right) → **Custom repositories**
3. Add `https://github.com/alexiswl/powerpal` with category **Integration**
4. Search for "Powerpal BLE" and install
5. Restart Home Assistant

### Manual

Copy the entire `powerpal_ble` folder into your Home Assistant `custom_components` directory:

```
<your_ha_config>/
├── configuration.yaml
├── custom_components/
│   └── powerpal_ble/
│       ├── __init__.py
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py
│       ├── esphome_coordinator.py
│       ├── manifest.json
│       ├── sensor.py
│       ├── strings.json
│       └── translations/
│           └── en.json
```

Your HA config directory is typically:
- **Home Assistant OS / Supervised:** `/config/`
- **Home Assistant Container:** wherever you mounted the config volume
- **Home Assistant Core:** `~/.homeassistant/`

Then restart Home Assistant (**Settings → System → Restart**).

## Configuration: Direct BLE Mode

### Step 1: Check your Bluetooth adapter

1. Go to **Settings → Devices & Services**
2. Look for the **Bluetooth** integration — it should show your adapter as active

### Step 2: Disconnect your phone from the Powerpal

Only one BLE device can connect to the Powerpal at a time. Disconnect or forget the Powerpal from your phone's Bluetooth.

### Step 3: Add the integration

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration** → search for **"Powerpal BLE"**
3. Select **"Direct BLE (local Bluetooth adapter)"** as the connection mode
4. The integration will either auto-discover your Powerpal or let you enter the MAC address manually

### Step 4: Enter your pairing details

| Field | What to enter |
|-------|---------------|
| **Pairing Code** | Your 6-digit PIN (e.g. `123456`) |
| **Pulses per kWh** | Your smart meter's pulse rate (usually `1000`) |
| **Update Interval** | How often you want readings (1-15 minutes) |
| **Enable Bluetooth Bonding** | Leave enabled (required for most setups) |

### Step 5: Verify it's working

Go to **Settings → Devices & Services → Powerpal BLE** and check for three sensors:
- **Power** (W) — instantaneous power draw
- **Total Energy** (kWh) — cumulative energy
- **Daily Energy** (kWh) — resets at midnight

## Configuration: ESPHome Mode

### Step 1: Flash the ESP32

1. Copy `esphome/powerpal_esphome.yaml` from this repository
2. Update the `substitutions` section:
   - `powerpal_mac`: Your Powerpal's BLE MAC address
   - `powerpal_passkey`: Your 6-digit pairing code
3. Create a `secrets.yaml` with your WiFi credentials and API key
4. Flash to your ESP32 using ESPHome Dashboard or CLI
5. Place the ESP32 within 1-5 metres of your Powerpal

### Cloud Upload via ESPHome (Optional)

The ESPHome firmware can upload readings directly to the Powerpal cloud API, keeping your Powerpal app and history functional. This requires your Powerpal's **Device ID** and **API Key**, which are stored on the device itself and read over BLE during connection.

Because the credentials are read *after* flashing, you need to flash the ESP32 **twice**:

#### First flash — collect credentials

1. In your `secrets.yaml`, set the cloud credentials to empty strings:
   ```yaml
   powerpal_ble__device_id: ""
   powerpal_ble__api_key: ""
   ```
2. Flash the ESP32 and let it connect to your Powerpal
3. Once connected, the firmware reads the API Key and Device ID from the Powerpal and exposes them as diagnostic entities:
   - **Powerpal API Key** (`text_sensor`)
   - **Powerpal Device ID** (`text_sensor`)
4. Find these values in **Settings → Devices & Services → ESPHome → your device → Diagnostic entities**, or check the ESP32 logs for lines like:
   ```
   [powerpal] === API Key: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx ===
   [powerpal] === Device ID: xxxxxxxx ===
   ```

#### Second flash — enable cloud upload

1. Update your `secrets.yaml` with the values you just collected:
   ```yaml
   powerpal_ble__device_id: "your-device-id-here"
   powerpal_ble__api_key: "your-api-key-here"
   ```
2. Flash the ESP32 again
3. On boot, the firmware will log `Cloud upload enabled for device <id>` and start POSTing readings to the Powerpal API alongside local HA reporting

> **Note:** Cloud upload is entirely optional. If you leave the credentials empty, the ESP32 operates in local-only mode and no data is sent to Powerpal's servers.

### Step 2: Verify ESPHome is working

1. The ESP32 device should appear in **Settings → Devices & Services → ESPHome**
2. Check that the `sensor.powerpal_power` entity exists and shows power values in Watts

### Step 3: Add the Powerpal BLE integration

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration** → search for **"Powerpal BLE"**
3. Select **"ESPHome device (ESP32 handles BLE)"** as the connection mode
4. Enter the entity ID of the power sensor (e.g. `sensor.powerpal_power`)

### Step 4: Done

The integration creates the same three sensors as Direct BLE mode:
- **Power** (W) — received directly from the ESP32
- **Total Energy** (kWh) — accumulated from power readings over time
- **Daily Energy** (kWh) — resets at midnight

These are fully compatible with the Energy Dashboard.

### How ESPHome mode works

```
┌─────────────┐     BLE       ┌──────────────┐    WiFi/API    ┌─────────────────┐
│  Powerpal   │◄─────────────►│   ESP32      │◄──────────────►│ Home Assistant  │
│  (meter)    │  pairing +    │  (ESPHome)   │  power (W)     │                 │
│             │  notifications│  converts    │                │  powerpal_ble   │
│             │  (raw pulses) │  pulses → W  │                │  integration    │
└─────────────┘               └──────────────┘                │  (ESPHome mode) │
                                                              │                 │
                                                              │  → Power (W)    │
                                                              │  → Total (kWh)  │
                                                              │  → Daily (kWh)  │
                                                              └─────────────────┘
```

The ESP32 handles all BLE complexity (pairing, encryption, reconnection) and converts raw pulses into power measurements locally. The custom component receives power (W) values and focuses on energy accumulation and HA integration (Energy Dashboard, statistics, daily resets).

## Sensors and Energy Dashboard

The **Total Energy** sensor uses `state_class: total_increasing`, which means it's compatible with Home Assistant's **Energy Dashboard**:

1. Go to **Settings → Dashboards → Energy**
2. Under **Electricity Grid → Grid Consumption**, click **Add Consumption**
3. Select the **Powerpal Total Energy** sensor

## BlueZ Bonding Option

*(Direct BLE mode only)*

By default, this integration performs BlueZ-level bonding with the Powerpal device before connecting. Bonding establishes link-layer encryption, which protects the pairing code from being intercepted by nearby BLE sniffers.

### When to disable bonding

In rare cases where `bluetoothctl` is unavailable or the host system doesn't support interactive pairing, you can disable BlueZ bonding. The integration will still attempt to authenticate at the GATT level using the pairing code.

**Trade-off:** With bonding disabled, BLE traffic between the adapter and the Powerpal is unencrypted over the air. In most home environments this is low risk.

### Recommendation

Keep BlueZ bonding **enabled** unless you have a specific reason to disable it. If your Bluetooth adapter is too far from the Powerpal for reliable direct BLE, use ESPHome mode instead.

## Troubleshooting

### Direct BLE mode

#### "Powerpal device not found"
- Make sure your phone's Bluetooth is disconnected from the Powerpal
- Check that your BT adapter is showing in HA's Bluetooth integration
- Ensure you're within Bluetooth range (typically 5-10m)

#### "Could not connect" or frequent disconnects
- Move your HA machine or Bluetooth adapter closer to the Powerpal
- Check HA logs for RSSI values — below -70 dBm is problematic
- The integration retries automatically with exponential backoff

#### Checking RSSI (signal strength)

RSSI guidelines:
| RSSI (dBm)  | Signal Quality |
|-------------|---------------|
| -30 to -50  | Excellent     |
| -50 to -70  | Good          |
| -70 to -85  | Weak — may cause disconnects |
| Below -85   | Very poor — use ESPHome mode instead |

### ESPHome mode

#### No power data appearing
- Check the ESP32 logs in ESPHome Dashboard for BLE connection status
- Verify the ESP32 is within BLE range of the Powerpal (1-5m ideal)
- Ensure your phone is disconnected from the Powerpal
- Confirm the passkey in the YAML matches your Powerpal's pairing code

#### Entity not found during setup
- Make sure the ESPHome device is online and connected to HA
- Check that `sensor.powerpal_power` (or your custom entity name) exists in HA

### General

#### Readings seem wrong
- Verify the pulse rate matches your meter (check the label for "imp/kWh")
- The first reading after connection may include buffered data

## Development

```bash
git clone https://github.com/alexiswl/powerpal.git
cd powerpal
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r tests/requirements_test.txt
pip install ruff pylint mypy pre-commit
pre-commit install
pytest
```

## Notes

- Only one BLE device can connect to the Powerpal at a time — if your phone reconnects, the BLE connection (direct or ESP32) will drop and retry automatically.
- In direct BLE mode, the integration reads and logs your Powerpal Cloud API Key and Device ID on connection.
- Battery level reading is not yet implemented.

## Credits & Acknowledgements

This integration is heavily based on the reverse-engineering work and code from **WeekendWarrior1's** [Powerpal BLE repository](https://github.com/WeekendWarrior1/powerpal_ble). Their work documenting the Powerpal BLE GATT characteristics, notification format, pairing sequence, and cloud API extraction made this integration possible.

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
