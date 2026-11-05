# YAMNet detector integration

`live_detector.py` uses the supplied YAMNet model flow, category mapping,
thresholds, temporal confirmation, and cooldown. It captures audio locally on
the laptop, then sends only confirmed category, score, and timestamp messages
to FastAPI at `/ws/detector`. Microphone audio is never sent to the website.

The current capture path is the laptop microphone. The ESP32-C6 USB serial
audio path described in the project handoff is a separate future integration;
this script does not read ESP32 serial audio or send motor commands directly.
FastAPI routes detections and the saved vibration patterns to a connected
wristband.

## Setup

The supplied YAMNet scripts already ran in a Python 3.10 environment. Reuse
that environment if it is still available; activate it and install only the
WebSocket client if needed:

```powershell
& "C:\path\to\existing\.venv\Scripts\Activate.ps1"
python -m pip install websockets
```

For a fresh environment, use Python 3.10 from the repository root:

```powershell
py -3.10 -m venv detector\.venv
detector\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r detector\requirements.txt
```

Start the FastAPI backend from another terminal:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start the website from a third terminal:

```powershell
cd web
npm install
npm run dev
```

Then run the detector from the repository root, with the YAMNet environment
active:

```powershell
detector\.venv\Scripts\Activate.ps1
python detector\live_detector.py
```

The first run loads YAMNet and AudioSet labels using TensorFlow Hub/network
access. Choose the microphone with `DHVANI_MIC_DEVICE` if device 1 is not the
intended input. For example:

```powershell
$env:DHVANI_MIC_DEVICE = "0"
```

If FastAPI is on another computer, set `DHVANI_DETECTOR_WS` to that computer's
reachable address, for example `ws://192.168.1.20:8000/ws/detector`.

## Classification behavior

The supplied mapping is preserved in `sound_categories.py`: alarm, vehicle
horn, doorbell, knocking, and siren. The thresholds and temporal confirmation
remain prototype settings; YAMNet scores are not validated accuracy. Tune them
with representative recordings before relying on the alerts.
