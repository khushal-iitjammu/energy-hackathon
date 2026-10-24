"""Read ESP32 receiver CSV lines and forward sensor data to the Flask API.

Expected extended line:
DATA,packet,timestampMs,distanceCm,soilRaw,moisturePercent,rain,buzzer,accelX,accelY,accelZ,gyroX,gyroY,gyroZ,tempC,mpuValid

The bridge also accepts the older 8-field DATA line, so it can be used
before the MPU6050 is connected or while testing the original sensors.
"""

import logging
import os
import time

import requests
import serial

PORT = os.getenv("SERIAL_PORT", "COM5")
BAUD = int(os.getenv("BAUD_RATE", "9600"))
BASE_URL = os.getenv("DASHBOARD_URL", "http://127.0.0.1:5000").rstrip("/")
API_KEY = os.getenv("INGEST_API_KEY", "")
SERIAL_TIMEOUT = float(os.getenv("SERIAL_TIMEOUT", "1"))
POST_TIMEOUT = float(os.getenv("POST_TIMEOUT", "8"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s: %(message)s",
)


def to_num(value, cast=float):
    """Convert a CSV field to a number; return None for empty/invalid fields."""
    try:
        value = value.strip()
        if not value:
            return None
        return cast(value)
    except (ValueError, TypeError):
        return None


def parse_line(line):
    """Parse one ESP-NOW receiver DATA line into an /api/ingest payload."""
    parts = line.strip().split(",")
    if len(parts) < 8 or parts[0].strip() != "DATA":
        return None

    # Base fields used by the original dashboard/backend.
    data = {
        "packet_number": to_num(parts[1], int),
        # Kept under the legacy key expected by the existing Flask app.
        "timestamp_seconds": to_num(parts[2], int),
        "ultrasonic_distance_cm": to_num(parts[3]),
        "soil_raw_adc_value": to_num(parts[4], int),
        "soil_moisture_percent": to_num(parts[5]),
        "rain_digital_output": to_num(parts[6], int),
        "buzzer_digital_status": to_num(parts[7], int),
    }

    # MPU6050 fields are optional for backward compatibility.
    if len(parts) >= 16:
        data.update({
            "accel_x": to_num(parts[8]),
            "accel_y": to_num(parts[9]),
            "accel_z": to_num(parts[10]),
            "gyro_x": to_num(parts[11]),
            "gyro_y": to_num(parts[12]),
            "gyro_z": to_num(parts[13]),
            "temperature_c": to_num(parts[14]),
            "mpu_valid": to_num(parts[15], int) == 1,
        })
    elif len(parts) > 8:
        logging.warning(
            "Received %d CSV fields; expected 8 (legacy) or 16 (MPU6050). Skipping line.",
            len(parts),
        )
        return None

    return data


def main():
    if not API_KEY:
        raise SystemExit(
            "Set INGEST_API_KEY to the same private secret configured on Render."
        )

    url = BASE_URL + "/api/ingest"
    headers = {"X-API-Key": API_KEY}
    logging.info("Reading %s at %s baud and uploading to %s", PORT, BAUD, url)
    logging.info("Close Arduino Serial Monitor/Plotter before running this bridge.")

    while True:
        try:
            with serial.Serial(PORT, BAUD, timeout=SERIAL_TIMEOUT) as ser:
                time.sleep(2)  # Allow the serial connection/board to settle.
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue

                    line = raw.decode("utf-8", errors="replace").strip()
                    data = parse_line(line)
                    if data is None:
                        continue

                    try:
                        response = requests.post(
                            url, json=data, headers=headers, timeout=POST_TIMEOUT
                        )
                        if response.ok:
                            logging.info(
                                "Uploaded packet %s (MPU6050 fields: %s)",
                                data.get("packet_number"),
                                "yes" if "mpu_valid" in data else "no",
                            )
                        else:
                            logging.error(
                                "HTTP %s: %s", response.status_code, response.text[:200]
                            )
                    except requests.RequestException as exc:
                        logging.error("Upload error: %s", exc)
                        time.sleep(2)

        except serial.SerialException as exc:
            logging.error("Serial error (%s): %s", PORT, exc)
            logging.error("Check the COM port and close Serial Monitor. Retrying in 4 seconds.")
            time.sleep(4)
        except KeyboardInterrupt:
            logging.info("Stopped.")
            break
