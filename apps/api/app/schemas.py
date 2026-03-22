from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    id: str
    email: EmailStr


class ClaimDeviceRequest(BaseModel):
    hardwareId: str
    manufacturerPassword: str


class SensorManifestItem(BaseModel):
    sensorId: str
    sensorType: str
    unit: str
    measurement: str | None = None
    loadId: str | None = None
    loadName: str | None = None
    buildingId: str | None = None
    busId: str | None = None


class DeviceSummary(BaseModel):
    id: str
    hardwareId: str
    deviceModel: str
    displayName: str | None = None
    networkName: str | None = None
    nodeId: str | None = None
    nodeKind: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    relayCount: int
    firmwareVersion: str | None = None
    claimStatus: str
    claimCount: int = 0
    sensorManifest: list[SensorManifestItem]
    deviceAuthToken: str | None = None
    latestReadings: list["ReadingResponse"] = Field(default_factory=list)


class DeviceCommandCreateRequest(BaseModel):
    relayNumber: int = Field(ge=1)
    targetState: Literal["on", "off"]
    reason: str = Field(default="manual_frontend_toggle", min_length=3, max_length=120)


class DeviceCommandResponse(BaseModel):
    commandId: str
    type: Literal["relay.set"]
    relayNumber: int
    targetState: Literal["on", "off"]
    reason: str
    status: str


class TelemetryReading(BaseModel):
    sensorId: str
    sensorType: str
    value: float
    unit: str
    relayState: str | None = None


class TelemetryPayload(BaseModel):
    hardwareId: str
    deviceAuthToken: str
    espTimestamp: datetime | None = None
    signalStrength: int | None = None
    readings: list[TelemetryReading] = Field(min_length=1)


class IngestResponse(BaseModel):
    status: Literal["ok"]
    serverTimestamp: datetime
    commands: list[DeviceCommandResponse]


class MqttStatusResponse(BaseModel):
    enabled: bool
    connected: bool
    lastMessageAt: datetime | None = None
    lastError: str | None = None


class ReadingResponse(BaseModel):
    sensorId: str
    sensorType: str
    value: float
    unit: str
    relayState: str | None = None
    espTimestamp: datetime | None = None
    serverReceivedAt: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCompareRequest(BaseModel):
    network_payload: dict[str, Any]
    readings_payload: dict[str, Any]


class ModelGraphAnalyzeRequest(BaseModel):
    snapshot: dict[str, Any]


class ModelServiceResponse(BaseModel):
    status: str
    network_payload: dict[str, Any] | None = None
    readings_payload: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    comparisons: list[dict[str, Any]] | None = None
    analysis: dict[str, Any] | None = None
    network_name: str | None = None
    converged: bool | None = None
    snapshot: dict[str, Any] | None = None
    alerts: list[dict[str, Any]] | None = None
    alerts_summary: dict[str, Any] | None = None


UserResponse.model_rebuild()
AuthResponse.model_rebuild()
ReadingResponse.model_rebuild()
DeviceSummary.model_rebuild()
