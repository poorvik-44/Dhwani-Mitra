"""Example adapter for the YAMNet process; send classifications, never audio."""
import asyncio
import json
import os
from datetime import datetime, timezone

import websockets

BRIDGE_WS = os.getenv("DHVANI_DETECTOR_WS", "ws://127.0.0.1:8000/ws/detector")


async def run_detector_adapter(classifications):
    """Forward async iterable items shaped as {category, confidence} to FastAPI."""
    while True:
        try:
            async with websockets.connect(BRIDGE_WS, ping_interval=20, ping_timeout=20) as socket:
                async for result in classifications:
                    await socket.send(json.dumps({
                        "type": "sound_detected",
                        "category": result["category"],
                        "confidence": float(result["confidence"]),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }))
        except (OSError, websockets.ConnectionClosed):
            await asyncio.sleep(2)

