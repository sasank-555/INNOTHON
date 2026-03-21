from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import initialize_database
from app.dependencies import get_current_user
from app.mqtt_service import mqtt_bridge
from app.schemas import (
    AuthResponse,
    ClaimDeviceRequest,
    DeviceCommandCreateRequest,
    DeviceCommandResponse,
    DeviceSummary,
    IngestResponse,
    LoginRequest,
    MqttStatusResponse,
    RegisterRequest,
    TelemetryPayload,
)
from app.services import (
    claim_device,
    create_device_command,
    get_device_summary,
    ingest_telemetry,
    list_user_devices,
    login_user,
    register_user,
)


app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    initialize_database()
    mqtt_bridge.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    mqtt_bridge.stop()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/mqtt/status", response_model=MqttStatusResponse)
def get_mqtt_status() -> MqttStatusResponse:
    return MqttStatusResponse(
        enabled=mqtt_bridge.status.enabled,
        connected=mqtt_bridge.status.connected,
        lastMessageAt=mqtt_bridge.status.last_message_at,
        lastError=mqtt_bridge.status.last_error,
    )


@app.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest) -> AuthResponse:
    token, user = register_user(payload.email, payload.password)
    return AuthResponse(access_token=token, user=user)


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    token, user = login_user(payload.email, payload.password)
    return AuthResponse(access_token=token, user=user)


@app.post("/devices/claim", response_model=DeviceSummary)
def claim(payload: ClaimDeviceRequest, current_user: dict = Depends(get_current_user)) -> DeviceSummary:
    return claim_device(current_user["id"], payload.hardwareId, payload.manufacturerPassword)


@app.get("/devices", response_model=list[DeviceSummary])
def list_devices(current_user: dict = Depends(get_current_user)) -> list[DeviceSummary]:
    return list_user_devices(current_user["id"])


@app.get("/devices/{device_id}", response_model=DeviceSummary)
def get_device(device_id: str, current_user: dict = Depends(get_current_user)) -> DeviceSummary:
    return get_device_summary(device_id, current_user["id"], include_token=True)


@app.post("/devices/{device_id}/commands", response_model=DeviceCommandResponse, status_code=201)
def create_command(
    device_id: str,
    payload: DeviceCommandCreateRequest,
    current_user: dict = Depends(get_current_user),
) -> DeviceCommandResponse:
    return create_device_command(current_user["id"], device_id, payload)


@app.post("/ingest/http", response_model=IngestResponse)
def ingest_http(payload: TelemetryPayload) -> IngestResponse:
    commands = ingest_telemetry(
        payload.hardwareId,
        payload.deviceAuthToken,
        payload.espTimestamp,
        payload.readings,
        payload.signalStrength,
    )
    return IngestResponse(
        status="ok",
        serverTimestamp=datetime.now(timezone.utc),
        commands=commands,
    )
