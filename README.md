# Dhvani Mitra

Dhvani Mitra is an assistive sound-awareness prototype. A laptop microphone feeds ambient audio to a local YAMNet detector. When the detector recognizes one of the configured sound categories, a FastAPI bridge sends its haptic pattern to an ESP32-C6 wristband over Wi-Fi. The web dashboard displays connection status, detections, history, and vibration settings.

```text
Microphone → YAMNet detector → FastAPI/WebSocket bridge → ESP32-C6 → TB6612FNG → vibration motor
                                      ↕
                                React dashboard
```

The detector processes audio locally and sends event labels and scores to FastAPI; it does not stream raw microphone audio. This prototype currently maps five categories: alarm, vehicle horn, doorbell, knocking, and siren.

## Repository layout

| Path | Contents |
| --- | --- |
| `web/` | React/Vite dashboard |
| `backend/` | FastAPI REST and WebSocket bridge, saved vibration patterns |
| `detector/` | Laptop microphone capture and YAMNet classification |
| `firmware/wristband/` | ESP-IDF Wi-Fi and haptic firmware for ESP32-C6 |
| `firmware/hardware_diagnostic/` | Separate I2S microphone and manual motor diagnostic firmware |

## Requirements

- Windows 10/11 for the supplied PowerShell launch scripts (other OSes can run the Python and Node commands directly)
- Python 3.10 or newer
- Node.js 18 or newer and npm
- ESP-IDF 6.1 for building and flashing the ESP32-C6 firmware
- ESP32-C6 board, TB6612FNG motor driver, and vibration motor
- A shared 2.4 GHz Wi-Fi network for the laptop and wristband

The first YAMNet run downloads the model and AudioSet labels through TensorFlow Hub. An internet connection is needed for that initial download.

## Run the system

Open separate PowerShell terminals from the repository root.

### 1. Install and start FastAPI

```powershell
py -3.11 -m venv .venv-backend
.\.venv-backend\Scripts\Activate.ps1
pip install -r .\backend\requirements.txt
python -m uvicorn app.main:app --app-dir .\backend --host 0.0.0.0 --port 8000
```

Keep this terminal open. The backend serves the API and WebSockets on port `8000`. When Windows Firewall prompts, allow Python on the network the laptop and ESP32 share.

### 2. Install and start the dashboard

```powershell
cd .\web
npm install
npm run dev
```

Open <http://localhost:5173>. For access from another device on the same network, use the laptop's LAN address instead of `localhost`.

### 3. Install and start the YAMNet detector

In another terminal at the repository root:

```powershell
py -3.11 -m venv .venv-detector
.\.venv-detector\Scripts\Activate.ps1
pip install -r .\detector\requirements.txt
```

Select the desired Windows input device under **Settings → System → Sound → Input**, then run:

```powershell
Remove-Item Env:DHVANI_MIC_DEVICE -ErrorAction SilentlyContinue
.\detector\run_laptop_mic.ps1
```

If `DHVANI_MIC_DEVICE` is already set in the terminal, remove it as shown above to return to the Windows default. To pin a particular input device instead, set a substring of its device name first, for example:

```powershell
$env:DHVANI_MIC_DEVICE = 'AB13X USB Audio'
.\detector\run_laptop_mic.ps1
```

The detector reports the selected device in its terminal and sends microphone level and confirmed category events to FastAPI. Keep the detector running while listening. Press Ctrl+C to stop it.

### 4. Build, flash, and connect the wristband

Use an ESP-IDF 6.1 PowerShell environment. Connect the motor through the TB6612FNG driver; do not connect a motor directly to an ESP32 GPIO.

| TB6612FNG | ESP32-C6 |
| --- | --- |
| PWMA | GPIO10 |
| AIN1 | GPIO11 |
| AIN2 | GPIO18 |
| STBY | GPIO21 |
| AO1 / AO2 | Vibration motor terminals |

From the repository root in an ESP-IDF terminal:

```powershell
idf.py -C .\firmware\wristband set-target esp32c6
idf.py -C .\firmware\wristband build
idf.py -C .\firmware\wristband -p COMx flash monitor
```

Replace `COMx` with the board's port in Windows Device Manager. At the firmware serial prompt, provision the same 2.4 GHz Wi-Fi network used by the laptop:

```text
wifi <SSID>|<password>|<laptop IPv4 address>
```

The ESP32 stores these settings in NVS and reboots. Enter the laptop's current LAN IPv4 address, not `localhost`; re-provision if that address changes. Use `status` in the serial console to inspect Wi-Fi and bridge state, and `motor` to trigger one local 150 ms test pulse.

## Verify connections

- `GET http://localhost:8000/api/health` — backend health and bridge status
- `GET http://localhost:8000/api/status` — detector, mic, and wristband state
- Dashboard connection badges — browser view of live clients
- ESP32 serial `status` command — board Wi-Fi and WebSocket bridge state

Keep the backend, detector, and dashboard running. The wristband should show a valid hotspot/LAN IP and `bridge=connected`; the dashboard should show the detector and wristband connected before end-to-end sound testing.

## API and WebSocket routes

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Health and connection summary |
| `GET /api/status` | Live detector, microphone, and device state |
| `GET /api/patterns` | Read saved category vibration patterns |
| `PUT /api/patterns/{category}` | Update a vibration pattern |
| `GET /api/history` | Read detection history |
| `DELETE /api/history` | Clear detection history |
| `/ws/web` | Dashboard updates and controls |
| `/ws/detector` | YAMNet classification events and mic status |
| `/ws/device` | ESP32 haptic commands and acknowledgements |

Patterns are stored in `backend/data/patterns.json`. Runtime detection history is local data and is excluded from Git.

## Troubleshooting

- **Wristband disconnected:** Run `status` in its serial console. Confirm Wi-Fi is 2.4 GHz, laptop and board share the same network, the laptop IPv4 is current, and FastAPI listens on `0.0.0.0:8000`. If the ESP serial log shows a connection timeout and Windows marks the hotspot as Public, add a firewall rule scoped to the board's current IP from an elevated PowerShell:

  ```powershell
  $espIp = Read-Host 'ESP32 IP from the serial status'
  New-NetFirewallRule -DisplayName 'Dhvani Mitra ESP32 bridge' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -RemoteAddress $espIp -Profile Public
  ```
- **Wrong microphone:** Select the intended input in Windows Sound settings and restart the detector. Check the detector terminal and dashboard for the selected device name. Set `DHVANI_MIC_DEVICE` to a device-name substring to choose it explicitly.
- **No sound category appears:** First confirm the mic level changes while making sound near the microphone. YAMNet recognizes sound classes rather than matching any arbitrary noise; use a clear example of one of the five supported categories.
- **Motor does not vibrate:** Use the ESP32 serial `motor` command to test the motor path independently, and check the TB6612FNG wiring and motor supply.

## Security and local settings

Do not commit Wi-Fi passwords, personal `.env` files, build output, virtual environments, or microphone recordings. `.env.example` contains non-secret local configuration examples. The ESP32 Wi-Fi credentials are provisioned directly to device NVS and are not stored in this repository.
