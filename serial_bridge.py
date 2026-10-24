import os, time, logging
import requests
import serial

PORT = os.getenv("SERIAL_PORT", "COM5")
BAUD = int(os.getenv("BAUD_RATE", "9600"))
BASE_URL = os.getenv("DASHBOARD_URL", "http://127.0.0.1:5000").rstrip("/")
API_KEY = os.getenv("INGEST_API_KEY", "")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def to_num(s, cast=float):
    try: return cast(s)
    except (ValueError, TypeError): return None

def parse_line(line):
    # Expected: DATA,packet,timestamp,distance_cm,soil_raw,moisture_percent,rain_digital,buzzer
    p = line.strip().split(",")
    if len(p) < 8 or p[0].strip() != "DATA":
        return None
    return {
        "packet_number": to_num(p[1], int),
        "timestamp_seconds": to_num(p[2], int),
        "ultrasonic_distance_cm": to_num(p[3]),
        "soil_raw_adc_value": to_num(p[4], int),
        "soil_moisture_percent": to_num(p[5]),
        "rain_digital_output": to_num(p[6], int),
        "buzzer_digital_status": to_num(p[7], int)
    }

def main():
    if not API_KEY:
        raise SystemExit("Set INGEST_API_KEY to the same private secret used on Render.")
    url = BASE_URL + "/api/ingest"
    headers = {"X-API-Key": API_KEY}
    logging.info("Reading %s at %s baud and uploading to %s", PORT, BAUD, url)
    logging.info("Close Arduino Serial Monitor/Plotter before running.")
    while True:
        try:
            with serial.Serial(PORT, BAUD, timeout=1) as ser:
                time.sleep(2)
                while True:
                    raw = ser.readline()
                    if not raw: continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    data = parse_line(line)
                    if data is None: continue
                    try:
                        r = requests.post(url, json=data, headers=headers, timeout=8)
                        if r.ok:
                            logging.info("Uploaded packet %s", data["packet_number"])
                        else:
                            logging.error("HTTP %s: %s", r.status_code, r.text[:200])
                    except requests.RequestException as exc:
                        logging.error("Upload error: %s", exc)
                        time.sleep(2)
        except serial.SerialException as exc:
            logging.error("Serial error (%s): %s", PORT, exc)
            logging.error("Check COM port and close Serial Monitor. Retrying in 4 seconds.")
            time.sleep(4)
        except KeyboardInterrupt:
            logging.info("Stopped")
            break

if __name__ == "__main__":
    main()
