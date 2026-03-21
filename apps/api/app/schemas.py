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
    id: int
    email: EmailStr


class ClaimDeviceRequest(BaseModel):
    hardwareId: str
    manufacturerPassword: str


class SensorManifestItem(BaseModel):
    sensorId: str
    sensorType: str
    unit: str


class DeviceSummary(BaseModel):
    id: int
    hardwareId: str
    deviceModel: str
    relayCount: int
    firmwareVersion: str | None = None
    claimStatus: str
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


class ReadingResponse(BaseModel):
    sensorId: str
    sensorType: str
    value: float
    unit: str
    relayState: str | None = None
    espTimestamp: datetime | None = None
    serverReceivedAt: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


UserResponse.model_rebuild()
AuthResponse.model_rebuild()
ReadingResponse.model_rebuild()
DeviceSummary.model_rebuild()
