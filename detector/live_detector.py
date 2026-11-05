"""Live laptop microphone YAMNet detector with optional FastAPI WebSocket output.

This preserves the supplied YAMNet category aggregation, thresholds, temporal
confirmation, and cooldown. It forwards only confirmed classifications; raw
microphone audio never leaves this process.
"""

import asyncio
import csv
import io
import json
import os
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone

import numpy as np
import sounddevice as sd
import tensorflow as tf
import tensorflow_hub as hub
import websockets
from websockets.exceptions import WebSocketException
from scipy.signal import resample_poly

from sound_categories import SOUND_CATEGORIES

MIC_DEVICE = int(os.getenv("DHVANI_MIC_DEVICE", "1"))
MIC_SAMPLE_RATE = int(os.getenv("DHVANI_MIC_SAMPLE_RATE", "44100"))
MODEL_SAMPLE_RATE = 16000
DURATION = 2
MIN_AUDIO_LEVEL = 0.003
COOLDOWN = 3
TOP_FRAME_FRACTION = 0.40
CONFIRM_WINDOWS = 2
HISTORY_WINDOWS = 3
AMBIGUITY_MARGIN = 0.08
THRESHOLDS = {
    "ALARM": 0.20,
    "VEHICLE_HORN": 0.20,
    "DOORBELL": 0.15,
    "KNOCKING": 0.15,
    "SIREN": 0.20,
}
BRIDGE_WS = os.getenv("DHVANI_DETECTOR_WS", "ws://127.0.0.1:8000/ws/detector")
LABEL_URL = (
    "https://raw.githubusercontent.com/tensorflow/models/master/"
    "research/audioset/yamnet/yamnet_class_map.csv"
)


def top_frame_average(values):
    values = np.asarray(values)
    k = max(1, int(np.ceil(len(values) * TOP_FRAME_FRACTION)))
    return float(np.mean(np.partition(values, len(values) - k)[-k:]))


def load_yamnet():
    print("Loading YAMNet...")
    model = hub.load("https://tfhub.dev/google/yamnet/1")
    with urllib.request.urlopen(LABEL_URL, timeout=30) as response:
        label_text = response.read().decode("utf-8")
    labels = [row["display_name"] for row in csv.DictReader(io.StringIO(label_text))]
    label_indices = {label: i for i, label in enumerate(labels)}
    category_indices = {}
    for category, names in SOUND_CATEGORIES.items():
        indices = [label_indices[name] for name in names if name in label_indices]
        if not indices:
            raise RuntimeError(f"No YAMNet labels mapped for {category}")
        category_indices[category] = indices
    print(f"YAMNet ready; mapped {len(category_indices)} alert categories.")
    return model, labels, category_indices


def score_audio(model, category_indices, audio):
    audio_16k = resample_poly(audio, MODEL_SAMPLE_RATE, MIC_SAMPLE_RATE).astype(np.float32)
    scores, _, _ = model(tf.convert_to_tensor(audio_16k, dtype=tf.float32))
    frame_scores = scores.numpy()
    category_scores = {}
    for category, indices in category_indices.items():
        per_frame = np.max(frame_scores[:, indices], axis=1)
        category_scores[category] = top_frame_average(per_frame)
    return frame_scores, category_scores


async def send_detection(socket, category, confidence):
    await socket.send(
        json.dumps(
            {
                "type": "sound_detected",
                "category": category,
                "confidence": round(float(confidence), 5),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    )


async def run():
    model, labels, category_indices = load_yamnet()
    print("Using microphone device:", MIC_DEVICE)
    print(sd.query_devices(MIC_DEVICE, "input"))
    sd.check_input_settings(device=MIC_DEVICE, channels=1, samplerate=MIC_SAMPLE_RATE)

    histories = {category: deque(maxlen=HISTORY_WINDOWS) for category in SOUND_CATEGORIES}
    last_alert_time = {}
    socket = None

    print("Listening. Confirmed detections will be sent to:", BRIDGE_WS)
    print("Press Ctrl+C to stop. Only sound labels and scores are sent; audio stays local.")
    try:
        while True:
            try:
                if socket is None or socket.state.name != "OPEN":
                    socket = await websockets.connect(BRIDGE_WS, ping_interval=20, ping_timeout=20)
                    print("Connected to Dhvani Mitra FastAPI bridge.")
            except (OSError, WebSocketException) as error:
                print(f"Bridge unavailable ({error}); continuing local detection and retrying.")
                socket = None

            audio = sd.rec(
                int(DURATION * MIC_SAMPLE_RATE),
                samplerate=MIC_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=MIC_DEVICE,
            ).flatten()
            sd.wait()
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < MIN_AUDIO_LEVEL:
                for history in histories.values():
                    history.append(False)
                print(f"Quiet ({rms:.4f})")
                continue

            frame_scores, category_scores = score_audio(model, category_indices, audio)
            improved = np.array([top_frame_average(frame_scores[:, i]) for i in range(frame_scores.shape[1])])
            top = np.argsort(improved)[-5:][::-1]
            print("\nTop YAMNet:", ", ".join(f"{labels[i]} {improved[i]:.2f}" for i in top))

            for category, score in category_scores.items():
                histories[category].append(score >= THRESHOLDS[category])
            candidates = [c for c, history in histories.items() if sum(history) >= CONFIRM_WINDOWS]

            if "ALARM" in candidates and "SIREN" in candidates:
                if abs(category_scores["ALARM"] - category_scores["SIREN"]) < AMBIGUITY_MARGIN:
                    print("Ambiguous alarm/siren scores; waiting for a clearer result.")
                    continue
            if not candidates:
                print("No confirmed target sound.")
                continue

            category = max(candidates, key=lambda c: category_scores[c])
            now = time.time()
            if now - last_alert_time.get(category, 0) < COOLDOWN:
                print(f"{category} confirmed; cooldown active.")
                continue
            confidence = category_scores[category]
            last_alert_time[category] = now
            print(f"CONFIRMED {category}: {confidence:.3f}")
            if socket is not None:
                try:
                    await send_detection(socket, category, confidence)
                    print("Classification sent to website bridge.")
                except (OSError, WebSocketException) as error:
                    print(f"Could not send classification ({error}); will reconnect.")
                    socket = None
    finally:
        if socket is not None:
            await socket.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nDhvani Mitra detector stopped.")
