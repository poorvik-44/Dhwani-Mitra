import asyncio
import json
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .schemas import Detection, PatternUpdate, new_event_id
from .storage import get_history, get_patterns, save_history, save_pattern


class Bridge:
    def __init__(self):
        self.web_clients: set[WebSocket] = set()
        self.device: WebSocket | None = None
        self.detector_connected = False
        self.detector_last_seen: datetime | None = None
        self.microphone_rms: float | None = None
        self.microphone_device: str | None = None
        self.microphone_sample_rate: int | None = None
        self.device_last_seen: datetime | None = None
        self.device_ip: str | None = None
        self.lock = asyncio.Lock()
        self.events = get_history()

    def status(self):
        return {
            "detector": self.detector_connected,
            "device": self.device is not None,
            "microphone": self.detector_connected,
            "listening": self.detector_connected,
            "microphone_rms": self.microphone_rms,
            "microphone_device": self.microphone_device,
            "microphone_sample_rate": self.microphone_sample_rate,
            "last_signal": self.device_last_seen.isoformat() if self.device_last_seen else None,
            "device_ip": self.device_ip,
            "detector_last_seen": self.detector_last_seen.isoformat() if self.detector_last_seen else None,
        }

    async def broadcast(self, message):
        stale = []
        for client in list(self.web_clients):
            try:
                await client.send_json(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.web_clients.discard(client)

    async def broadcast_status(self):
        await self.broadcast({"type": "status", "status": self.status()})

    async def send_device(self, message):
        device = self.device
        if device is None:
            return False
        try:
            await device.send_json(message)
            self.device_last_seen = datetime.now(timezone.utc)
            return True
        except Exception:
            self.device = None
            return False

    async def handle_detection(self, raw):
        detection = Detection.model_validate(raw)
        pattern = get_patterns()[detection.category]
        event = {
            "type": "sound_detected",
            "event_id": new_event_id(),
            "category": detection.category,
            "confidence": detection.confidence,
            "timestamp": detection.timestamp.isoformat(),
            "pattern_name": pattern["preset"],
            "delivery_status": "pending",
        }
        self.events.append(event)
        self.events = self.events[-500:]
        save_history(self.events)
        await self.broadcast(event)
        command = {"type": "haptic_command", "event_id": event["event_id"], "category": detection.category, **pattern}
        sent = await self.send_device(command)
        event["delivery_status"] = "sent" if sent else "unavailable"
        await self.broadcast({"type": "haptic_status", "event_id": event["event_id"], "status": event["delivery_status"]})
        save_history(self.events)


bridge = Bridge()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    if bridge.device:
        try:
            await bridge.device.close()
        except Exception:
            pass


app = FastAPI(title="Dhvani Mitra Bridge", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
        "http://localhost:4174", "http://127.0.0.1:4174",
        "http://localhost:4175", "http://127.0.0.1:4175",
        "http://localhost:4176", "http://127.0.0.1:4176",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "dhvani-mitra-bridge", "status": bridge.status()}


@app.get("/api/status")
async def status():
    return bridge.status()


@app.get("/api/patterns")
async def patterns():
    return get_patterns()


@app.put("/api/patterns/{category}")
async def put_pattern(category: str, payload: PatternUpdate):
    normalized = category.upper()
    if normalized != payload.category:
        return {"error": "Path category and payload category must match"}
    saved = save_pattern(normalized, payload.model_dump(exclude={"type", "category"}))
    await bridge.broadcast({"type": "patterns_updated", "patterns": saved})
    if bridge.device:
        await bridge.send_device({"type": "sync_config", "patterns": saved})
    return {"ok": True, "category": normalized, "pattern": saved[normalized]}


@app.get("/api/history")
async def history():
    return bridge.events


@app.delete("/api/history")
async def clear_history():
    bridge.events = []
    save_history([])
    await bridge.broadcast({"type": "history", "events": []})
    return {"ok": True}


@app.websocket("/ws/web")
async def web_socket(websocket: WebSocket):
    await websocket.accept()
    bridge.web_clients.add(websocket)
    await websocket.send_json({"type": "status", "status": bridge.status()})
    await websocket.send_json({"type": "history", "events": bridge.events})
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "update_pattern":
                    parsed = PatternUpdate.model_validate(message)
                    saved = save_pattern(parsed.category, parsed.model_dump(exclude={"type", "category"}))
                    await bridge.broadcast({"type": "patterns_updated", "patterns": saved})
                    await websocket.send_json({"type": "notice", "message": f"{parsed.category} pattern saved to the bridge."})
                    if bridge.device:
                        await bridge.send_device({"type": "sync_config", "patterns": saved})
                elif kind == "test_haptic":
                    command = {**message, "type": "haptic_test"}
                    if not await bridge.send_device(command):
                        await websocket.send_json({"type": "notice", "message": "Wristband is disconnected; test command was not sent."})
                elif kind == "sync_config":
                    if not await bridge.send_device({"type": "sync_config", "patterns": get_patterns()}):
                        await websocket.send_json({"type": "notice", "message": "Wristband is disconnected; configuration was not sent."})
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                await websocket.send_json({"type": "notice", "message": f"Invalid message: {str(exc)[:180]}"})
    except WebSocketDisconnect:
        bridge.web_clients.discard(websocket)


@app.websocket("/ws/device")
async def device_socket(websocket: WebSocket):
    await websocket.accept()
    async with bridge.lock:
        prior = bridge.device
        bridge.device = websocket
        bridge.device_ip = websocket.client.host if websocket.client else None
    if prior and prior is not websocket:
        try:
            await prior.close(code=4001, reason="Replaced by a new wristband connection")
        except Exception:
            pass
    await websocket.send_json({"type": "sync_config", "patterns": get_patterns()})
    await bridge.broadcast_status()
    try:
        while True:
            message = await websocket.receive_json()
            bridge.device_last_seen = datetime.now(timezone.utc)
            kind = message.get("type")
            if kind in {"haptic_ack", "haptic_complete"}:
                event_id = message.get("event_id")
                new_status = "acknowledged" if kind == "haptic_ack" else "completed"
                for event in bridge.events:
                    if event.get("event_id") == event_id:
                        event["delivery_status"] = new_status
                        break
                save_history(bridge.events)
                await bridge.broadcast({"type": "haptic_status", "event_id": event_id, "status": new_status, "category": message.get("category")})
            elif kind in {"device_status", "heartbeat"}:
                reported_ip = message.get("ip")
                if reported_ip:
                    bridge.device_ip = str(reported_ip)[:64]
                await bridge.broadcast_status()
            else:
                await bridge.broadcast({"type": "device_message", "message": message})
    except WebSocketDisconnect:
        pass
    finally:
        if bridge.device is websocket:
            bridge.device = None
            await bridge.broadcast_status()


@app.websocket("/ws/detector")
async def detector_socket(websocket: WebSocket):
    await websocket.accept()
    bridge.detector_connected = True
    bridge.detector_last_seen = datetime.now(timezone.utc)
    await bridge.broadcast_status()
    await websocket.send_json({"type": "detector_ready"})
    try:
        while True:
            raw = await websocket.receive_text()
            bridge.detector_last_seen = datetime.now(timezone.utc)
            try:
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "detector_status":
                    device_name = message.get("microphone_device")
                    bridge.microphone_device = str(device_name)[:128] if device_name else None
                    sample_rate = message.get("sample_rate")
                    bridge.microphone_sample_rate = int(sample_rate) if sample_rate else None
                    await bridge.broadcast_status()
                elif kind == "audio_level":
                    rms = float(message.get("rms"))
                    if not math.isfinite(rms) or rms < 0 or rms > 1:
                        raise ValueError("RMS must be a finite value from 0 to 1")
                    bridge.microphone_rms = rms
                    await bridge.broadcast_status()
                else:
                    await bridge.handle_detection(message)
            except (json.JSONDecodeError, ValidationError, KeyError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)[:180]})
            except (TypeError, ValueError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)[:180]})
    except WebSocketDisconnect:
        pass
    finally:
        bridge.detector_connected = False
        bridge.microphone_rms = None
        bridge.microphone_device = None
        bridge.microphone_sample_rate = None
        await bridge.broadcast_status()
