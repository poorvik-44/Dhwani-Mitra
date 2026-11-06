# Laptop microphone and YAMNet detector

This process captures sound from a Windows input device, classifies it locally with YAMNet, and sends confirmed category events to the FastAPI bridge at `ws://127.0.0.1:8000/ws/detector`. The microphone audio itself is not sent to the backend.

## Install

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv-detector
.\.venv-detector\Scripts\Activate.ps1
pip install -r .\detector\requirements.txt
```

Start FastAPI first, then run:

```powershell
Remove-Item Env:DHVANI_MIC_DEVICE -ErrorAction SilentlyContinue
.\detector\run_laptop_mic.ps1
```

With `DHVANI_MIC_DEVICE` unset, the detector uses the Windows default recording device. Choose it under **Settings → System → Sound → Input**. To select a named device explicitly, set an identifying substring before running the script:

```powershell
$env:DHVANI_MIC_DEVICE = 'AB13X USB Audio'
.\detector\run_laptop_mic.ps1
```

The terminal prints the selected device. Check that the reported audio level changes when speaking or making sound near the mic. Press Ctrl+C to stop the detector.

## Model and categories

YAMNet and AudioSet labels are downloaded/cached by TensorFlow Hub on first use. The detector maps model labels to `ALARM`, `VEHICLE_HORN`, `DOORBELL`, `KNOCKING`, and `SIREN`, applies temporal confirmation, and forwards confirmed classifications. It is a sound classifier: arbitrary speech, music, or noise will not necessarily trigger one of those categories.

## Environment settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DHVANI_MIC_DEVICE` | Windows default input | Device-name substring or PortAudio input index |
| `DHVANI_DETECTOR_WS` | `ws://127.0.0.1:8000/ws/detector` | FastAPI detector WebSocket |

The optional `start_detector.ps1` launcher starts the process in the background and records its PID/log under the ignored `work/` directory.
