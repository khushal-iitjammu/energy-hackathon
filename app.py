
import os
import time
import threading
import math
from collections import deque
from functools import wraps
from flask import Flask, jsonify, render_template, request, abort

app = Flask(__name__)

history = deque(maxlen=300)
lock = threading.Lock()

API_KEY = os.environ.get("INGEST_API_KEY", "")

# MPU6050 settings
GRAVITY = 9.80665  # m/s^2
VIBRATION_THRESHOLD = float(
    os.environ.get("MPU6050_VIBRATION_THRESHOLD_M_S2", "2.5")
)
REQUIRED_HITS = 3
vibration_hits = 0

latest = {
    "connected": False,
    "received_at": None,
    "received_at_epoch": None,
    "packet_number": None,
    "ultrasonic_distance_cm": None,
    "water_level_cm": None,
    "rate_cm_s": None,
    "rate_cm_min": None,
    "soil_raw_adc_value": None,
    "soil_moisture_percent": None,
    "rain_digital_output": None,
    "buzzer_digital_status": None,

    # MPU6050 fields
    "mpu_valid": False,
    "accel_x": None,
    "accel_y": None,
    "accel_z": None,
    "acceleration_magnitude_m_s2": None,
    "vibration_m_s2": None,
    "vibration_g": None,
    "earthquake_detected": False,
    "earthquake_status": "WAITING_FOR_MPU6050",

    "alert": "WAITING",
    "message": "Waiting for sensor data"
}


def require_api_key(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if (
            not API_KEY
            or request.headers.get("X-API-Key", "") != API_KEY
        ):
            abort(401, description="Invalid or missing API key")
        return fn(*args, **kwargs)
    return wrapped


def as_number(value, cast=float):
    try:
        return None if value is None or value == "" else cast(value)
    except (ValueError, TypeError, OverflowError):
        return None


def classify(rate):
    # Prototype values only; not validated river warning thresholds.
    if rate is None or rate < 0.008:
        return "NORMAL", "No rapid rise threshold crossed by this prototype"
    if rate >= 0.033:
        return (
            "HIGH",
            "Rapid rise threshold crossed — verify with official river warnings"
        )
    return "LOW", "Water level rising — monitor closely"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "disaster-monitoring-dashboard"
    })


@app.get("/api/latest")
def api_latest():
    with lock:
        data = dict(latest)

    ts = data.get("received_at_epoch")
    data["connected"] = (
        ts is not None and time.time() - ts <= 15
    )
    data.pop("received_at_epoch", None)

    return jsonify(data)


@app.get("/api/history")
def api_history():
    with lock:
        return jsonify(list(history))


@app.post("/api/ingest")
@require_api_key
def ingest():
    global latest, vibration_hits

    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return jsonify({"error": "Expected JSON object"}), 400

    # Existing sensors
    distance = as_number(body.get("ultrasonic_distance_cm"))
    moisture = as_number(body.get("soil_moisture_percent"))
    soil_raw = as_number(body.get("soil_raw_adc_value"))
    rain = as_number(body.get("rain_digital_output"), int)
    buzzer = as_number(body.get("buzzer_digital_status"), int)

    reference = as_number(
        os.environ.get("SENSOR_REFERENCE_DISTANCE_CM")
    )

    water_level = (
        reference - distance
        if reference is not None and distance is not None
        else None
    )

    # MPU6050: accept snake_case or ESP32-style camelCase keys
    ax = as_number(body.get("accel_x", body.get("accelX")))
    ay = as_number(body.get("accel_y", body.get("accelY")))
    az = as_number(body.get("accel_z", body.get("accelZ")))

    mpu_flag = body.get("mpu_valid", body.get("mpuValid"))

    # If the sender supplies an MPU-valid flag, respect it.
    mpu_valid = (
        str(mpu_flag).lower() in ("1", "true", "yes")
        if mpu_flag is not None
        else all(v is not None for v in (ax, ay, az))
    )

    magnitude = None
    vibration = None
    vibration_g = None

    if mpu_valid and all(v is not None for v in (ax, ay, az)):
        # Total acceleration magnitude, including gravity
        magnitude = math.sqrt(ax * ax + ay * ay + az * az)

        # Approximate dynamic acceleration relative to gravity
        vibration = abs(magnitude - GRAVITY)
        vibration_g = vibration / GRAVITY

    now = time.time()

    with lock:
        prev_distance = latest.get("ultrasonic_distance_cm")
        prev_time = latest.get("received_at_epoch")

        rate = None

        if (
            distance is not None
            and prev_distance is not None
            and prev_time is not None
        ):
            dt = now - prev_time

            if dt >= 0.25:
                # Positive rate means rising water
                rate = (prev_distance - distance) / dt

        alert, message = classify(rate)

        # Basic vibration-event detector.
        # Require several consecutive high readings to reduce single-sample
        # false alarms. This is not a validated earthquake detection method.
        if not mpu_valid or vibration is None:
            vibration_hits = 0
            earthquake_detected = False
            earthquake_status = "MPU6050_UNAVAILABLE"
        elif vibration >= VIBRATION_THRESHOLD:
            vibration_hits += 1
            earthquake_detected = vibration_hits >= REQUIRED_HITS
            earthquake_status = (
                "VIBRATION_ALERT"
                if earthquake_detected
                else "VIBRATION_CHECK"
            )
        else:
            vibration_hits = 0
            earthquake_detected = False
            earthquake_status = "NORMAL"

        latest = {
            "connected": True,
            "received_at": time.strftime(
                "%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)
            ),
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

            # MPU6050 output
            "mpu_valid": bool(mpu_valid and magnitude is not None),
            "accel_x": ax,
            "accel_y": ay,
            "accel_z": az,
            "acceleration_magnitude_m_s2": (
                round(magnitude, 3)
                if magnitude is not None else None
            ),
            "vibration_m_s2": (
                round(vibration, 3)
                if vibration is not None else None
            ),
            "vibration_g": (
                round(vibration_g, 3)
                if vibration_g is not None else None
            ),
            "earthquake_detected": earthquake_detected,
            "earthquake_status": earthquake_status,

            "alert": alert,
            "message": message
        }

        history.append(dict(latest))

    return jsonify({
        "ok": True,
        "earthquake_detected": earthquake_detected,
        "earthquake_status": earthquake_status
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
