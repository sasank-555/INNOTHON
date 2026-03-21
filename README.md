# INNOTHON

Phase 1 FastAPI backend scaffold for the frontend/backend connection layer.

## What is included

- FastAPI server with CORS enabled for frontend development
- User registration and login
- Device claim flow backed by sold-device inventory
- Device listing and detail APIs
- HTTP ingestion endpoint for ESP telemetry
- Pending relay command piggyback response
- SQLite persistence for quick local setup

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r apps/api/requirements.txt
uvicorn app.main:app --reload --app-dir apps/api
```

Server base URL: `http://127.0.0.1:8000`

Swagger docs: `http://127.0.0.1:8000/docs`

## Seeded demo device

- `hardwareId`: `ESP-000123`
- `manufacturerPassword`: `demo-password`

Claim the device after registering a user, then use the generated `deviceAuthToken` for ingestion calls.

## Frontend connection flow

1. `POST /auth/register` or `POST /auth/login`
2. Store `access_token` and send it as `Authorization: Bearer <token>`
3. `POST /devices/claim` with the demo device credentials
4. `GET /devices` to populate the dashboard
5. `POST /devices/{deviceId}/commands` for manual relay toggles

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
