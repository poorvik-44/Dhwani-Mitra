# Dhvani Mitra ESP32-C6 wristband firmware

This ESP-IDF application joins a 2.4 GHz Wi-Fi network, connects to the project's FastAPI bridge at `ws://<laptop-ip>:8000/ws/device`, and drives the tested TB6612FNG channel-A output from category-specific vibration commands. The Windows/laptop YAMNet detector remains responsible for microphone capture and sound classification.

## Motor wiring

This build uses the channel-A control pins from the successful one-shot motor test:

| TB6612FNG | ESP32-C6 |
|---|---:|
| PWMA | GPIO10 |
| AIN1 | GPIO11 |
| AIN2 | GPIO18 |
| STBY | GPIO21 |
| AO1 / AO2 | Vibration motor terminals |

Motor supply and driver ground must be wired as already tested. Outputs start disabled and return to standby after each pattern. Do not connect a vibration motor directly to an ESP32 GPIO.

## Build and flash

Open an ESP-IDF 6.1 PowerShell environment from the repository root:

```powershell
idf.py -C .\firmware\wristband set-target esp32c6
idf.py -C .\firmware\wristband build
idf.py -C .\firmware\wristband -p COMx flash monitor
```

The first build fetches `espressif/esp_websocket_client` through the ESP-IDF Component Manager. Replace `COMx` with the ESP32's actual serial port.

## Configure Wi-Fi and bridge

At the serial prompt, enter:

```text
wifi <SSID>|<password>|<laptop IPv4>
```

The credentials are stored in the ESP32's NVS flash, not in source/config files, and the board restarts to join the network. The ESP32-C6 requires a 2.4 GHz Wi-Fi network. The laptop and board must be on the same LAN, and port 8000 must be reachable from the board. The laptop IPv4 can change; re-enter this command if it changes.

Use `status` to print Wi-Fi and bridge connectivity. Use `motor` for one 150 ms local pulse. Keep FastAPI running on `0.0.0.0:8000` and allow inbound TCP port 8000 from the ESP32 through Windows Firewall on the active network. The firmware reports `device_status` and 15-second heartbeats, reconnects after WebSocket close events, acknowledges each accepted vibration, plays the received pulse durations/intensity once, and reports `haptic_complete`.

## End-to-end run order

1. Start FastAPI from the backend with `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
2. Flash and provision this firmware over USB serial.
3. Confirm the dashboard shows the wristband connected and the device IP.
4. Start the laptop-microphone detector with `detector\\run_laptop_mic.ps1`.
5. Play one supported target sound near the laptop microphone and confirm the dashboard event reaches `acknowledged`/`completed` while the motor runs its category pattern.

This firmware does not sample the ESP32 microphone. It uses the laptop microphone/YAMNet path currently implemented in the project.
