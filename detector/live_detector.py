
import time
import csv
import urllib.request
import io
import json
import os
from datetime import datetime, timezone
from collections import deque
from fractions import Fraction

import numpy as np
import sounddevice as sd
import tensorflow as tf
import tensorflow_hub as hub
from websockets.sync.client import connect

from scipy.signal import resample_poly


# ==========================================
# DHVANI MITRA - IMPROVED SOUND DETECTOR
# ==========================================

MIC_DEVICE_REQUEST = os.getenv(
    "DHVANI_MIC_DEVICE",
    "",
)
MODEL_SAMPLE_RATE = 16000
BRIDGE_WS = os.getenv("DHVANI_DETECTOR_WS", "ws://127.0.0.1:8000/ws/detector")

DURATION = 2
MIN_AUDIO_LEVEL = 0.003
COOLDOWN = 3

TOP_FRAME_FRACTION = 0.40

CONFIRM_WINDOWS = 2
HISTORY_WINDOWS = 3

# If ALARM and SIREN scores are this close,
# avoid making an uncertain classification.
AMBIGUITY_MARGIN = 0.08

THRESHOLDS = {
    "ALARM": 0.20,
    "VEHICLE HORN": 0.20,
    "DOORBELL": 0.15,
    "KNOCKING": 0.15,
    "SIREN": 0.20
}


# ==========================================
# SOUND LABELS
# ==========================================

SOUND_LABELS = {

    "ALARM": [
        "Alarm clock",
        "Smoke detector, smoke alarm",
        "Fire alarm",
        "Car alarm",
        "Buzzer"
    ],

    "VEHICLE HORN": [
        "Vehicle horn, car horn, honking",
        "Air horn, truck horn",
        "Train horn"
    ],

    "DOORBELL": [
        "Doorbell"
    ],

    "KNOCKING": [
        "Knock"
    ],

    "SIREN": [
        "Siren",
        "Civil defense siren",
        "Police car (siren)",
        "Ambulance (siren)",
        "Fire engine, fire truck (siren)"
    ]
}


# ==========================================
# TOP FRAME AGGREGATION
# ==========================================

def top_frame_average(values):

    values = np.asarray(values)

    frame_count = len(values)

    k = max(
        1,
        int(np.ceil(frame_count * TOP_FRAME_FRACTION))
    )

    strongest = np.partition(
        values,
        frame_count - k
    )[-k:]

    return float(np.mean(strongest))


# ==========================================
# LOAD YAMNET
# ==========================================

print("\n====================================")
print("          DHVANI MITRA")
print("       IMPROVED AI DETECTOR")
print("====================================")

print("\nLoading YAMNet AI model...")

model = hub.load("https://tfhub.dev/google/yamnet/1")

print("YAMNet loaded successfully!")


# ==========================================
# LOAD AUDIOSET LABELS
# ==========================================

print("\nLoading sound labels...")

LABEL_URL = (
    "https://raw.githubusercontent.com/"
    "tensorflow/models/master/research/"
    "audioset/yamnet/yamnet_class_map.csv"
)

with urllib.request.urlopen(LABEL_URL) as response:

    csv_data = response.read().decode("utf-8")

reader = csv.DictReader(io.StringIO(csv_data))

labels = [row["display_name"] for row in reader]

print("Loaded", len(labels), "sound labels.")


# ==========================================
# MAP CATEGORY LABELS
# ==========================================

category_indices = {}

for category, sound_names in SOUND_LABELS.items():

    indices = []

    for sound_name in sound_names:

        if sound_name in labels:

            indices.append(labels.index(sound_name))

        else:

            print("WARNING: Label not found:", sound_name)

    category_indices[category] = indices

    if not indices:

        raise RuntimeError(
            "No AudioSet labels mapped for " + category
        )


# Generic Alarm is kept for debugging only.
# It is deliberately excluded from ALARM scoring.

if "Alarm" in labels:

    generic_alarm_index = labels.index("Alarm")

else:

    generic_alarm_index = None


print("\nCategory mapping completed.")

for category, indices in category_indices.items():

    print(category, ":", len(indices), "labels")


# ==========================================
# TEMPORAL CONFIRMATION
# ==========================================

detection_history = {

    category: deque(maxlen=HISTORY_WINDOWS)

    for category in SOUND_LABELS

}

last_alert_time = {}


# ==========================================
# MICROPHONE CHECK
# ==========================================

print("\nChecking microphone...")

try:

    devices = sd.query_devices()
    if not MIC_DEVICE_REQUEST:
        MIC_DEVICE = sd.default.device[0]
        if MIC_DEVICE is None or MIC_DEVICE < 0:
            raise RuntimeError("Windows has no default microphone. Set DHVANI_MIC_DEVICE to an input name or index.")
    else:
        try:
            MIC_DEVICE = int(MIC_DEVICE_REQUEST)
        except ValueError:
            matches = [
                device["index"]
                for device in devices
                if device["max_input_channels"] > 0
                and MIC_DEVICE_REQUEST.casefold() in device["name"].casefold()
            ]
            if not matches:
                raise RuntimeError(
                    f"No input device matches {MIC_DEVICE_REQUEST!r}. "
                    "Set DHVANI_MIC_DEVICE to an input name or index."
                )
            host_api_names = {i: api["name"] for i, api in enumerate(sd.query_hostapis())}
            matches.sort(
                key=lambda index: 0
                if "WASAPI" in host_api_names.get(devices[index]["hostapi"], "").upper()
                else 1
            )
            MIC_DEVICE = matches[0]

    MIC_SAMPLE_RATE = int(sd.query_devices(MIC_DEVICE, "input")["default_samplerate"])

    selected_microphone = sd.query_devices(MIC_DEVICE, "input")
    print("Selected microphone input:", selected_microphone)

    sd.check_input_settings(
        device=MIC_DEVICE,
        channels=1,
        samplerate=MIC_SAMPLE_RATE
    )

    print("\nMicrophone is ready!")

except Exception as error:

    print("\nMicrophone error:", error)

    raise SystemExit


# ==========================================
# LIVE DETECTION
# ==========================================

print("\n====================================")
print("       LIVE LISTENING STARTED")
print("====================================")

print("\nDetection improvements:")
print("1. Specific alarm label mapping")
print("2. Generic Alarm excluded from scoring")
print("3. Top-frame score aggregation")
print("4. Temporal confirmation")
print("5. Alarm/Siren ambiguity handling")

print("\nPlay an alarm, horn, doorbell,")
print("knocking sound or siren near the mic.")

print("Press CTRL+C to stop.\n")

category_ids = {
    "ALARM": "ALARM",
    "VEHICLE HORN": "VEHICLE_HORN",
    "DOORBELL": "DOORBELL",
    "KNOCKING": "KNOCKING",
    "SIREN": "SIREN",
}

bridge_socket = None


def connect_bridge():
    global bridge_socket
    try:
        bridge_socket = connect(BRIDGE_WS, open_timeout=4, close_timeout=1)
        print(f"Connected to Dhvani Mitra website bridge: {BRIDGE_WS}")
        send_detector_status()
    except Exception as error:
        bridge_socket = None
        print(f"Website bridge is not connected yet: {error}")


def send_detector_status():
    if bridge_socket is None:
        return
    try:
        bridge_socket.send(json.dumps({
            "type": "detector_status",
            "microphone_device": selected_microphone["name"],
            "sample_rate": MIC_SAMPLE_RATE,
        }))
    except Exception as error:
        print(f"Could not send microphone status to website: {error}")


def send_audio_level(rms):
    global bridge_socket
    try:
        if bridge_socket is None:
            connect_bridge()
        if bridge_socket is not None:
            bridge_socket.send(json.dumps({"type": "audio_level", "rms": float(rms)}))
    except Exception as error:
        print(f"Could not send microphone level to website: {error}")
        try:
            bridge_socket.close()
        except Exception:
            pass
        bridge_socket = None


def send_detection(category, confidence):
    global bridge_socket
    payload = {
        "type": "sound_detected",
        "category": category_ids[category],
        "confidence": max(0.0, min(1.0, float(confidence))),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    for attempt in range(2):
        try:
            if bridge_socket is None:
                connect_bridge()
            if bridge_socket is not None:
                bridge_socket.send(json.dumps(payload))
                return True
        except Exception as error:
            print(f"Could not send detection to website: {error}")
            try:
                bridge_socket.close()
            except Exception:
                pass
            bridge_socket = None
        if attempt == 0:
            time.sleep(0.5)
    return False


connect_bridge()


try:

    while True:

        # ----------------------------------
        # RECORD AUDIO
        # ----------------------------------

        audio = sd.rec(
            int(DURATION * MIC_SAMPLE_RATE),
            samplerate=MIC_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=MIC_DEVICE
        )

        sd.wait()

        audio = audio.flatten()

        # ----------------------------------
        # AUDIO LEVEL
        # ----------------------------------

        rms = np.sqrt(np.mean(audio ** 2))

        print(f"\nAudio level: {rms:.4f}")
        send_audio_level(rms)

        if rms < MIN_AUDIO_LEVEL:

            print("Quiet environment - listening...")

            for history in detection_history.values():

                history.append(False)

            continue

        # ----------------------------------
        # RESAMPLE TO 16000 HZ
        # ----------------------------------

        if MIC_SAMPLE_RATE == MODEL_SAMPLE_RATE:
            audio_16k = audio.astype(np.float32)
        else:
            ratio = Fraction(MODEL_SAMPLE_RATE, MIC_SAMPLE_RATE)
            audio_16k = resample_poly(audio, ratio.numerator, ratio.denominator).astype(np.float32)

        waveform = tf.convert_to_tensor(
            audio_16k,
            dtype=tf.float32
        )

        # ----------------------------------
        # YAMNET INFERENCE
        # ----------------------------------

        scores, embeddings, spectrogram = model(waveform)

        frame_scores = scores.numpy()

        # ----------------------------------
        # IMPROVED SCORE AGGREGATION
        # ----------------------------------

        improved_scores = np.array([

            top_frame_average(frame_scores[:, i])

            for i in range(frame_scores.shape[1])

        ])

        # ----------------------------------
        # TOP 8 PREDICTIONS
        # ----------------------------------

        top_indices = np.argsort(
            improved_scores
        )[-8:][::-1]

        print("\n========== TOP YAMNET PREDICTIONS ==========")

        for idx in top_indices:

            print(
                f"{labels[idx]:35s} "
                f"{improved_scores[idx]:.3f}"
            )

        # ----------------------------------
        # GENERIC ALARM DIAGNOSTIC
        # ----------------------------------

        if generic_alarm_index is not None:

            generic_score = improved_scores[
                generic_alarm_index
            ]

            print(
                f"\nGENERIC ALARM (diagnostic only): "
                f"{generic_score:.3f}"
            )

        # ----------------------------------
        # CATEGORY SCORE CALCULATION
        # ----------------------------------

        category_scores = {}

        for category, indices in category_indices.items():

            frame_category_scores = np.max(
                frame_scores[:, indices],
                axis=1
            )

            category_scores[category] = top_frame_average(
                frame_category_scores
            )

        print("\n========== SOUND ANALYSIS ==========")

        for category, score in category_scores.items():

            print(
                f"{category:18s}: {score:.3f}"
            )

        print("------------------------------------")

        # ----------------------------------
        # TEMPORAL CONFIRMATION
        # ----------------------------------

        for category, score in category_scores.items():

            detected = score >= THRESHOLDS[category]

            detection_history[category].append(detected)

        candidates = []

        for category, history in detection_history.items():

            if sum(history) >= CONFIRM_WINDOWS:

                candidates.append(category)

        # ----------------------------------
        # CATEGORY COMPETITION
        # ----------------------------------

        current_time = time.time()

        if candidates:

            # Check ALARM vs SIREN ambiguity.

            if (
                "ALARM" in candidates
                and "SIREN" in candidates
            ):

                alarm_score = category_scores["ALARM"]

                siren_score = category_scores["SIREN"]

                difference = abs(
                    alarm_score - siren_score
                )

                if difference < AMBIGUITY_MARGIN:

                    print("\n*** AMBIGUOUS SOUND ***")

                    print(
                        f"ALARM score: {alarm_score:.3f}"
                    )

                    print(
                        f"SIREN score: {siren_score:.3f}"
                    )

                    print(
                        "Waiting for clearer classification."
                    )

                    print("\n------------------------------------")

                    continue

            # Select highest scoring confirmed category.

            best_category = max(
                candidates,
                key=lambda category: category_scores[category]
            )

            best_score = category_scores[best_category]

            previous_time = last_alert_time.get(
                best_category,
                0
            )

            if current_time - previous_time >= COOLDOWN:

                print(
                    f"\n*** {best_category} DETECTED! ***"
                )

                print(
                    f"Aggregated model score: {best_score:.3f}"
                )

                print(
                    "Temporal confirmation: PASSED"
                )

                if send_detection(best_category, best_score):
                    print("Detection sent to the website.")

                last_alert_time[best_category] = current_time

            else:

                print(
                    "\nDetection confirmed - alert cooldown."
                )

        else:

            print("\nNo confirmed target sound.")

            pending = [

                category

                for category, history in detection_history.items()

                if sum(history) > 0

            ]

            if pending:

                print(
                    "Waiting for confirmation:",
                    ", ".join(pending)
                )

        print("\n------------------------------------")


except KeyboardInterrupt:

    print("\n\nDhvani Mitra stopped.")

    if bridge_socket is not None:
        bridge_socket.close()

    print("Thank you!")
