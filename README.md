# Dhvani Mitra

Responsive sound awareness dashboard and FastAPI bridge for a Python/YAMNet detector and ESP32-C6 wristband.

## Run locally

Requirements: Node.js 18+ and Python 3.10+.

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend (new terminal)

```powershell
cd web
npm install
npm run dev
```

### YAMNet laptop detector

The detector uses the laptop microphone and forwards confirmed classifications
to FastAPI. Follow [detector/README.md](detector/README.md) to install its
Python dependencies and run it. The detector sends sound labels and scores;
microphone audio stays local. ESP32 serial audio capture is not part of this
detector integration yet.

Open http://localhost:5173. Until real clients connect, the detector and wristband show as disconnected. Vibration settings are saved in browser localStorage and can be previewed without hardware.

## Bridge protocol

- Browser: `ws://localhost:8000/ws/web`
- Detector: `ws://localhost:8000/ws/detector`
- ESP32-C6: `ws://<computer-ip>:8000/ws/device`
- Health/status: `GET /api/health`, `GET /api/status`
- Pattern persistence: `GET /api/patterns`, `PUT /api/patterns/{category}`
- Event log: `GET /api/history`, `DELETE /api/history`

The detector sends only `{type:"sound_detected",category,confidence,timestamp}`. FastAPI forwards the event to browsers and routes the category's saved pulse configuration to the device. The device should answer with `{type:"haptic_ack",event_id,category,status:"received"}` and may send `{type:"haptic_complete",event_id,category}` only when motor completion is known. Supported categories are `ALARM`, `VEHICLE_HORN`, `DOORBELL`, `KNOCKING`, and `SIREN`.

The integrated `detector/live_detector.py` sends confirmed YAMNet classifications to `/ws/detector`. It preserves local microphone processing and does not send audio to FastAPI.
