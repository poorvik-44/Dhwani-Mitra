import json
from pathlib import Path
from threading import RLock

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "patterns.json"
HISTORY_FILE = DATA_DIR / "history.json"
LOCK = RLock()

DEFAULTS = {
    "ALARM": {"preset": "Triple Pulse", "intensity": 75, "repeat": 2, "pulses": [{"on_ms": 240, "off_ms": 150}, {"on_ms": 240, "off_ms": 0}]},
    "VEHICLE_HORN": {"preset": "Double Pulse", "intensity": 75, "repeat": 2, "pulses": [{"on_ms": 240, "off_ms": 150}, {"on_ms": 240, "off_ms": 0}]},
    "DOORBELL": {"preset": "Single Pulse", "intensity": 60, "repeat": 1, "pulses": [{"on_ms": 450, "off_ms": 0}]},
    "KNOCKING": {"preset": "Double Pulse", "intensity": 65, "repeat": 2, "pulses": [{"on_ms": 120, "off_ms": 100}, {"on_ms": 120, "off_ms": 0}]},
    "SIREN": {"preset": "Long Vibration", "intensity": 85, "repeat": 1, "pulses": [{"on_ms": 900, "off_ms": 0}]},
}


def read_json(path: Path, fallback):
    with LOCK:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback


def write_json(path: Path, value) -> None:
    with LOCK:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(path)


def get_patterns():
    saved = read_json(CONFIG_FILE, {})
    return {**DEFAULTS, **saved}


def save_pattern(category: str, pattern: dict):
    patterns = get_patterns()
    patterns[category] = pattern
    write_json(CONFIG_FILE, patterns)
    return patterns


def get_history():
    return read_json(HISTORY_FILE, [])


def save_history(events):
    write_json(HISTORY_FILE, events[-500:])
