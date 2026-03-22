from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class NotificationDispatchRequest(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    message: str = Field(min_length=3, max_length=2000)
    severity: Literal["info", "low", "medium", "high", "critical"] = "info"
    buildingName: str | None = Field(default=None, max_length=140)
    sensorName: str | None = Field(default=None, max_length=140)
    networkName: str | None = Field(default=None, max_length=140)
    metadata: dict[str, Any] = Field(default_factory=dict)
    recipients: list[EmailStr] = Field(default_factory=list)


class NotificationDispatchResponse(BaseModel):
    success: bool
    sent: bool
    recipientCount: int
    highestSeverity: str
    subject: str | None = None
    transport: str | None = None
    detail: str | None = None


class SafetyTriggerRequest(BaseModel):
    sensorId: str = Field(min_length=2, max_length=140)
    severity: Literal["green", "yellow", "red"]
    title: str = Field(min_length=3, max_length=140)
    message: str = Field(min_length=3, max_length=2000)
    hardwareId: str | None = Field(default=None, max_length=140)
    deviceId: str | None = Field(default=None, max_length=40)
    relayNumber: int = Field(default=1, ge=1)
    buildingName: str | None = Field(default=None, max_length=140)
    sensorName: str | None = Field(default=None, max_length=140)
    networkName: str | None = Field(default=None, max_length=140)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SafetyTriggerResponse(BaseModel):
    success: bool
    severity: Literal["green", "yellow", "red"]
    emailsSent: bool
    recipientEmails: list[EmailStr] = Field(default_factory=list)
    autoShutdownQueued: bool
    commandId: str | None = None
    actionLinks: dict[str, str] = Field(default_factory=dict)
    transport: str | None = None
    subject: str | None = None
    detail: str


class SensorControlRequest(BaseModel):
    sensorId: str = Field(min_length=2, max_length=140)
    targetState: Literal["on", "off"]
    hardwareId: str | None = Field(default=None, max_length=140)
    deviceId: str | None = Field(default=None, max_length=40)
    relayNumber: int = Field(default=1, ge=1)


class SensorControlResponse(BaseModel):
    success: bool
    targetState: Literal["on", "off"]
    commandId: str | None = None
    hardwareId: str | None = None
    loadId: str | None = None
    detail: str
