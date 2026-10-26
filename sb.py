"""Read ESP32 receiver CSV over USB and upload sensor readings to Flask.

Expected extended receiver line (16 CSV columns):
DATA,packet,timestampMs,distanceCm,soilRaw,moisturePercent,rain,buzzer,accelX,accelY,accelZ,gyroX,gyroY,gyroZ,tempC,mpuValid

The older 8-column format is accepted for the non-MPU sensors, but it cannot
provide MPU6050 readings.
"""
import logging
import os
import time
from urllib.parse import urlparse

import requests
import serial

PORT = os.getenv("SERIAL_PORT", "COM5")
BAUD = int(os.getenv("BAUD_RATE", "9600"))
BASE_URL = os.getenv("DASHBOARD_URL", "https://energy-hackathon.onrender.com").rstrip("/")
API_KEY = os.getenv("INGEST_API_KEY", "")
SERIAL_TIMEOUT = float(os.getenv("SERIAL_TIMEOUT", "1"))
POST_TIMEOUT = float(os.getenv("POST_TIMEOUT", "8"))
DEBUG_SERIAL = os.getenv("SERIAL_DEBUG", "0").lower() in ("1", "true", "yes", "on")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s: %(message)s",
)


def number(value, cast=float):
    try:
        value = value.strip()
        if not value:
            return None
        return cast(value)
    except (AttributeError, ValueError, TypeError, OverflowError):
        return None


def flag(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on", "valid", "ok")


def parse_line(line):
    """Parse a receiver DATA line into the keys accepted by app.py."""
    parts = line.strip().split(",")
    if len(parts) < 8 or parts[0].strip() != "DATA":
        return None

    data = {
        "packet_number": number(parts[1], int),
        "timestamp_ms": number(parts[2], int),
        "ultrasonic_distance_cm": number(parts[3]),
        "soil_raw_adc_value": number(parts[4], int),
        "soil_moisture_percent": number(parts[5], int),
        "rain_digital_output": number(parts[6], int),
        "buzzer_digital_status": number(parts[7], int),
    }

    if len(parts) >= 16:
        data.update({
            "accel_x": number(parts[8]),
            "accel_y": number(parts[9]),
            "accel_z": number(parts[10]),
            "gyro_x": number(parts[11]),
            "gyro_y": number(parts[12]),
            "gyro_z": number(parts[13]),
            "temperature_c": number(parts[14]),
            "mpu_valid": flag(parts[15]),
        })
    elif len(parts) == 8:
        # Legacy packet: MPU values are genuinely absent.
        data["mpu_valid"] = False
    else:
        logging.warning(
            "DATA line has %d fields; expected 8 (legacy) or at least 16 (MPU6050). Line ignored.",
            len(parts),
        )
        return None

    return data


def main():
    if not API_KEY:
        raise SystemExit(
            "ERROR: INGEST_API_KEY is empty. Set it to the same secret configured in Render."
        )

    parsed = urlparse(BASE_URL)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit("ERROR: DASHBOARD_URL must be a full http(s) URL.")
    url = BASE_URL if BASE_URL.endswith("/api/ingest") else BASE_URL + "/api/ingest"
    headers = {"X-API-Key": API_KEY}

    print("=== SERIAL BRIDGE STARTED ===", flush=True)
    logging.info("Serial port: %s", PORT)
    logging.info("Baud rate: %s", BAUD)
    logging.info("Upload endpoint: %s", url)
    logging.info("Close Arduino Serial Monitor/Plotter before continuing.")

    # Check that the dashboard is reachable. A health-check issue is reported,
    # but serial reading still starts so that connection problems are distinct.
    try:
        health_url = BASE_URL.removesuffix("/api/ingest") + "/health"
        response = requests.get(health_url, timeout=POST_TIMEOUT)
        logging.info("Dashboard health check: HTTP %s", response.status_code)
    except requests.RequestException as exc:
        logging.warning("Dashboard health check failed (serial reading will still start): %s", exc)

    while True:
        try:
            with serial.Serial(PORT, BAUD, timeout=SERIAL_TIMEOUT) as ser:
                time.sleep(2)  # Allow ESP32 reset/serial stream to settle.
                logging.info("Opened %s. Waiting for DATA lines...", PORT)
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    if DEBUG_SERIAL:
                        logging.info("SERIAL RAW: %s", line)
                    data = parse_line(line)
                    if data is None:
                        continue

                    if "accel_x" in data:
                        logging.info(
                            "Packet %s parsed; MPU6050 valid=%s; accel=(%s, %s, %s) m/s^2",
                            data.get("packet_number"), data["mpu_valid"],
                            data.get("accel_x"), data.get("accel_y"), data.get("accel_z"),
                        )
                    else:
                        logging.warning(
                            "Packet %s has only legacy sensor fields; upload will not contain MPU6050 readings.",
                            data.get("packet_number"),
                        )

                    try:
                        response = requests.post(url, json=data, headers=headers, timeout=POST_TIMEOUT)
                        if response.ok:
                            logging.info("Upload OK (HTTP %s), packet %s", response.status_code, data.get("packet_number"))
                        else:
                            logging.error("Dashboard rejected packet: HTTP %s: %s", response.status_code, response.text[:300])
                    except requests.RequestException as exc:
                        logging.error("Upload failed: %s", exc)
                        time.sleep(2)

        except serial.SerialException as exc:
            logging.error("Serial error on %s: %s", PORT, exc)
            logging.error("Check the COM port, baud rate, USB cable, and that Serial Monitor is closed. Retrying in 4 seconds.")
            time.sleep(4)
        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            break


if __name__ == "__main__":
    main()
