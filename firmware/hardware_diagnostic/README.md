# ESP32-C6 hardware diagnostic

This standalone ESP-IDF project is for bench checks of the ESP32-C6 I2S microphone input and motor output. It is separate from `../wristband`, which is the application firmware used for Wi-Fi/WebSocket haptic alerts.

## What it checks

- Reads INMP441 I2S input and prints left/right peak and RMS values once per second.
- Supports a single 180 ms motor pulse from the serial console, but the motor test is locked by default.

The I2S pin suggestions and motor-driver pin assignments are documented in `main/hardware_pins.h`. Verify them against the actual wiring before enabling the manual motor test. Never connect a vibration motor directly to an ESP32 GPIO.

## Build and flash

Open an ESP-IDF 6.1 PowerShell environment and run from the repository root:

```powershell
idf.py -C .\firmware\hardware_diagnostic set-target esp32c6
idf.py -C .\firmware\hardware_diagnostic build
idf.py -C .\firmware\hardware_diagnostic -p COMx flash monitor
```

Replace `COMx` with the serial port shown by Windows. The serial output confirms I2S data levels; it does not measure microphone acoustic sensitivity or classify sounds. Type `M` only after verifying the motor driver, wiring, and supply, and after enabling the motor test in the source.
