import os
import time
import threading
from collections import deque
from functools import wraps
from flask import Flask, jsonify, render_template, request, abort

app = Flask(__name__)
history = deque(maxlen=300)
lock = threading.Lock()
API_KEY = os.environ.get("INGEST_API_KEY", "")
latest = {"connected": False, "received_at": None, "received_at_epoch": None,
          "packet_number": None, "ultrasonic_distance_cm": None, "water_level_cm": None,
          "rate_cm_s": None, "rate_cm_min": None, "soil_raw_adc_value": None,
          "soil_moisture_percent": None, "rain_digital_output": None,
          "buzzer_digital_status": None, "alert": "WAITING",
          "message": "Waiting for sensor data"}

def require_api_key(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not API_KEY or request.headers.get("X-API-Key", "") != API_KEY:
            abort(401, description="Invalid or missing API key")
        return fn(*args, **kwargs)
    return wrapped

def as_number(value, cast=float):
    try:
        return None if value is None or value == "" else cast(value)
    except (ValueError, TypeError):
        return None

def classify(rate):
    # Prototype values only; not validated Tawi River warning thresholds.
    if rate is None or rate < 0.008:
        return "NORMAL", "No rapid rise threshold crossed by this prototype"
    if rate >= 0.033:
        return "HIGH", "Rapid rise threshold crossed — verify with official river warnings"
    return "LOW", "Water level rising — monitor closely"

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "disaster-monitoring-dashboard"})

@app.get("/api/latest")
def api_latest():
    with lock:
        data = dict(latest)
    ts = data.get("received_at_epoch")
    data["connected"] = ts is not None and time.time() - ts <= 15
    data.pop("received_at_epoch", None)
    return jsonify(data)

@app.get("/api/history")
def api_history():
    with lock:
        return jsonify(list(history))

@app.post("/api/ingest")
@require_api_key
def ingest():
    global latest
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Expected JSON object"}), 400
    distance = as_number(body.get("ultrasonic_distance_cm"))
    moisture = as_number(body.get("soil_moisture_percent"))
    soil_raw = as_number(body.get("soil_raw_adc_value"))
    rain = as_number(body.get("rain_digital_output"), int)
    buzzer = as_number(body.get("buzzer_digital_status"), int)
    reference = as_number(os.environ.get("SENSOR_REFERENCE_DISTANCE_CM"))
    water_level = reference - distance if reference is not None and distance is not None else None
    now = time.time()
    with lock:
        prev_distance = latest.get("ultrasonic_distance_cm")
        prev_time = latest.get("received_at_epoch")
        rate = None
        if distance is not None and prev_distance is not None and prev_time is not None:
            dt = now - prev_time
            if dt >= 0.25:
                # Positive rate means rising water: sensor-to-water distance decreases.
                rate = (prev_distance - distance) / dt
        alert, message = classify(rate)
        latest = {
            "connected": True,
            "received_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)),
            "received_at_epoch": now,
            "packet_number": body.get("packet_number"),
            "ultrasonic_distance_cm": distance,
            "water_level_cm": water_level,
            "rate_cm_s": round(rate, 4) if rate is not None else None,
            "rate_cm_min": round(rate * 60, 2) if rate is not None else None,
            "soil_raw_adc_value": soil_raw,
            "soil_moisture_percent": moisture,
            "rain_digital_output": rain,
            "buzzer_digital_status": buzzer,
            "alert": alert,
            "message": message
        }
        history.append(dict(latest))
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
