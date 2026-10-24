# Disaster Monitoring Dashboard Pack

This pack uses the uploaded HTML layout: four sensor cards, four charts, current alert, alert history, and recent readings. It supports real data through the Flask API and a Python serial bridge. To preview the UI without hardware, append `?demo=1` to the local/public URL. Demo mode is simulated and is not real sensor data.

## Files
- `app.py`: Flask web app + JSON API.
- `templates/index.html`: dashboard matching the requested HTML format.
- `serial_bridge.py`: reads receiver USB serial and posts data to the web API.
- `requirements.txt`, `Procfile`, `render.yaml`: deployment configuration.

## Expected receiver serial line
`DATA,packet_number,timestamp,distance_cm,soil_raw_adc,moisture_percent,rain_digital_output,buzzer_status`

Example: `DATA,510,123450,79.35,4095,0,0,0`

If your actual C++ receiver prints a different line, adjust `parse_line()` in `serial_bridge.py` to match the real output.

## Deploy
1. Upload all project files and `templates/index.html` to GitHub.
2. In Render create a Web Service connected to the repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 30`
5. Add `INGEST_API_KEY` as a private secret in Render. Optionally set `SENSOR_REFERENCE_DISTANCE_CM` only after calibrating the sensor reference.
6. Deploy and copy the public URL.
7. On your laptop, install dependencies and run the serial bridge with the Render URL and the same API key.

## Windows bridge
```
py -m pip install pyserial requests
set SERIAL_PORT=COM5
set BAUD_RATE=9600
set DASHBOARD_URL=https://YOUR-RENDER-URL
set INGEST_API_KEY=YOUR_PRIVATE_SECRET
py serial_bridge.py
```
Use the actual COM port and receiver baud rate. Close Arduino Serial Monitor first.

## Google Sites
Google Sites -> Insert -> Embed -> By URL -> paste the Render dashboard URL. If embedding is blocked, add a link to open it in a new tab.

## Safety
The provisional thresholds in the code are demo thresholds only, not official Tawi River flood-warning limits. The app stores recent data in memory and clears it if the service restarts. Do not use as a certified life-safety system.
