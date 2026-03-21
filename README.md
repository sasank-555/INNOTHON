# INNOTHON

Phase 1 FastAPI backend scaffold for the frontend/backend connection layer.

## What is included

- FastAPI server with CORS enabled for frontend development
- User registration and login
- Device claim flow backed by sold-device inventory
- Device listing and detail APIs
- HTTP ingestion endpoint for ESP telemetry
- MQTT telemetry subscription for continuous ESP-to-backend ingestion
- Pending relay command piggyback response
- MongoDB persistence for users, devices, readings, and commands

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r apps/api/requirements.txt
uvicorn app.main:app --reload --app-dir apps/api
```

Server base URL: `http://127.0.0.1:8000`

Swagger docs: `http://127.0.0.1:8000/docs`

MongoDB defaults:

- `INNOTHON_MONGODB_URI=mongodb://127.0.0.1:27017`
- `INNOTHON_MONGODB_DATABASE=innothon`

## MQTT support

The backend listens for ESP telemetry on MQTT as well as HTTP.

- Default broker host: `127.0.0.1`
- Default broker port: `1883`
- Telemetry subscription: `devices/+/telemetry`
- Command publish topic: `devices/{hardwareId}/commands`

Useful environment variables:

- `INNOTHON_MQTT_ENABLED=true`
- `INNOTHON_MQTT_HOST=127.0.0.1`
- `INNOTHON_MQTT_PORT=1883`
- `INNOTHON_MQTT_USERNAME=`
- `INNOTHON_MQTT_PASSWORD=`

## Seeded demo device

- `hardwareId`: `ESP-000123`
- `manufacturerPassword`: `demo-password`

Claim the device after registering a user, then use the device's `deviceAuthToken` for ingestion calls.

Known sold devices can send telemetry before claim as long as they use the correct `hardwareId` and `deviceAuthToken`. Claiming controls which logged-in user can see and control the device.

## Frontend connection flow

1. `POST /auth/register` or `POST /auth/login`
2. Store `access_token` and send it as `Authorization: Bearer <token>`
3. `POST /devices/claim` with the demo device credentials
4. `GET /devices` to populate the dashboard
5. `POST /devices/{deviceId}/commands` for manual relay toggles

## Model endpoints

The backend now also exposes model-analysis endpoints backed by the Python ML layer.

- `GET /model/sample-graph`
- `POST /model/simulate-network`
- `POST /model/compare-network`
- `POST /model/analyze-graph`
- `GET /model/test-ui`

Quick way to test in the browser:

1. Start the backend:

```bash
uvicorn app.main:app --reload --app-dir apps/api
```

2. Open:

`http://127.0.0.1:8000/model/test-ui`

That page loads a sample graph and lets you call `POST /model/analyze-graph` from a basic frontend.

## Example frontend payloads

Register:

```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

Claim device:

```json
{
  "hardwareId": "ESP-000123",
  "manufacturerPassword": "demo-password"
}
```

Create relay command:

```json
{
  "relayNumber": 1,
  "targetState": "off",
  "reason": "manual_frontend_toggle"
}
```

MQTT telemetry payload:

```json
{
  "hardwareId": "ESP-000123",
  "deviceAuthToken": "paste-device-token-here",
  "espTimestamp": "2026-03-21T10:30:00Z",
  "signalStrength": -65,
  "readings": [
    {
      "sensorId": "voltage_a",
      "sensorType": "voltage",
      "value": 231.4,
      "unit": "V"
    }
  ]
}
```
