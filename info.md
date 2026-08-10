# Powerpal BLE

Connect your Powerpal energy monitor directly to Home Assistant over Bluetooth Low Energy (BLE). Monitor your real-time power consumption and energy usage locally — no cloud service required.

## Supported Devices

- Powerpal energy monitors (all BLE-enabled models)

## Key Features

- **Local BLE connection** — communicates directly with your Powerpal device, no cloud dependency
- **Real-time power monitoring** — instantaneous power consumption in watts (W)
- **Energy tracking** — total energy (kWh) and daily energy (kWh) sensors
- **Energy Dashboard compatible** — tracks cumulative energy for Home Assistant's Energy Dashboard
- **Auto-reconnection** — maintains a reliable connection with exponential backoff
- **ESPHome mode** — use an ESP32 as a dedicated BLE client when the meter is out of range
- **Auto-discovery** — detects Powerpal devices via Home Assistant's Bluetooth integration
