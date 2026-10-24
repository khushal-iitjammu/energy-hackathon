"""Read ESP32 receiver CSV lines and forward sensor data to the Flask API.

Accepted serial formats:
  Legacy:  DATA,packet,timestampMs,distanceCm,soilRaw,moisturePercent,rain,buzzer
  MPU6050: DATA,packet,timestampMs,distanceCm,soilRaw,moisturePercent,rain,buzzer,accelX,accelY,accelZ,gyroX,gyroY,gyroZ,tempC,mpuValid

Windows example (run in the same CMD window):
  set SERIAL_PORT=COM5
  set BAUD_RATE=9600
  set DASHBOARD_URL=https://energy-hackathon.onrender.com
  set INGEST_API_KEY=your_actual_render_secret
  py -u serial_bridge.py
"""

import logging
import os
import time
from typing import Any, Optional

import requests
import serial

PORT = os.getenv("SERIAL_PORT", "COM5").strip()
BAUD = int(os.getenv("BAUD_RATE", "9600"))
BASE_URL = os.getenv("DASHBOARD_URL", "https://energy-hackathon.onrender.com").strip().rstrip("/")
API_KEY = os.getenv("INGEST_API_KEY", "").strip()
SERIAL_TIMEOUT = float(os.getenv("SERIAL_TIMEOUT", "1"))
POST_TIMEOUT = float(os.getenv("POST_TIMEOUT", "8"))
RECONNECT_DELAY = float(os.getenv("RECONNECT_DELAY", "4"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s: %(message)s",
)


def to_num(value: str, cast: type = float) -> Optional[Any]:
    """Convert a CSV field to a number; return None for empty/invalid fields."""
    try:
        value = value.strip()
        if not value:
            return None
        return cast(value)
    except (ValueError, TypeError, OverflowError):
        return None


def to_bool(value: str) -> bool:
    """Accept common textual and numeric true values from Arduino CSV output."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_line(line: str) -> Optional[dict]:
    """Parse a receiver DATA CSV line into the Flask /api/ingest payload."""
    parts = [part.strip() for part in line.strip().split(",")]

    if not parts or parts[0] != "DATA":
        return None
    if len(parts) not in (8, 16):
        logging.warning(
            "Skipping DATA line with %d comma-separated fields; expected 8 or 16. Line: %s",
            len(parts), line[:180],
        )
        return None

    data = {
        "packet_number": to_num(parts[1], int),
        "timestamp_ms": to_num(parts[2], int),
        "ultrasonic_distance_cm": to_num(parts[3]),
        "soil_raw_adc_value": to_num(parts[4], int),
        "soil_moisture_percent": to_num(parts[5]),
        "rain_digital_output": to_num(parts[6], int),
        "buzzer_digital_status": to_num(parts[7], int),
    }

    if len(parts) == 16:
        data.update({
            "accel_x": to_num(parts[8]),
            "accel_y": to_num(parts[9]),
            "accel_z": to_num(parts[10]),
            "gyro_x": to_num(parts[11]),
            "gyro_y": to_num(parts[12]),
            "gyro_z": to_num(parts[13]),
            "temperature_c": to_num(parts[14]),
            "mpu_valid": to_bool(parts[15]),
        })

    return data


def get_ingest_url() -> str:
    """Accept either the base dashboard URL or a URL already ending in /api/ingest."""
    if BASE_URL.endswith("/api/ingest"):
        return BASE_URL
    return BASE_URL + "/api/ingest"
