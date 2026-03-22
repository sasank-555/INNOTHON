from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.dependencies import get_current_user

from .schemas import (
    NotificationDispatchRequest,
    NotificationDispatchResponse,
    SafetyTriggerRequest,
    SafetyTriggerResponse,
    SensorControlRequest,
    SensorControlResponse,
)
from .sendnotifications import (
    SafetyTrigger,
    apply_notification_action,
    apply_sensor_control_action,
    handle_sensor_status_event,
)
from .service import NotificationEvent, render_notifications_html, send_notifications


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/dispatch", response_model=NotificationDispatchResponse)
def dispatch_notification(
    payload: NotificationDispatchRequest,
    current_user: dict = Depends(get_current_user),
) -> NotificationDispatchResponse:
    recipients = payload.recipients or [current_user["email"]]
    try:
        result = send_notifications(
            recipients,
            [
                NotificationEvent(
                    title=payload.title,
                    message=payload.message,
                    severity=payload.severity,
                    building_name=payload.buildingName,
                    sensor_name=payload.sensorName,
                    network_name=payload.networkName,
                    metadata=payload.metadata,
                )
            ],
        )
        return NotificationDispatchResponse(
            success=True,
            sent=result.sent,
            recipientCount=len(result.recipients),
            highestSeverity=result.highest_severity,
            subject=result.subject,
            transport=result.transport,
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Notification delivery failed: {error}",
        ) from error


@router.post("/preview", response_class=HTMLResponse)
def preview_notification_email(
    payload: NotificationDispatchRequest,
    current_user: dict = Depends(get_current_user),
) -> str:
    event = NotificationEvent(
        title=payload.title,
        message=payload.message,
        severity=payload.severity,
        building_name=payload.buildingName,
        sensor_name=payload.sensorName,
        network_name=payload.networkName or "NITW",
        metadata={
            **payload.metadata,
            "previewedBy": current_user["email"],
        },
    )
    return render_notifications_html([event])


@router.post("/safety-trigger", response_model=SafetyTriggerResponse)
def trigger_sensor_safety_notification(
    payload: SafetyTriggerRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> SafetyTriggerResponse:
    result = handle_sensor_status_event(
        SafetyTrigger(
            sensor_id=payload.sensorId,
            severity=payload.severity,
            title=payload.title,
            message=payload.message,
            hardware_id=payload.hardwareId,
            device_id=payload.deviceId,
            relay_number=payload.relayNumber,
            building_name=payload.buildingName,
            sensor_name=payload.sensorName,
            network_name=payload.networkName,
            metadata={
                **payload.metadata,
                "triggeredBy": current_user["email"],
            },
        ),
        action_base_url=str(request.url_for("perform_notification_action")),
    )
    return SafetyTriggerResponse(
        success=True,
        severity=result.severity,
        emailsSent=result.emails_sent,
        recipientEmails=list(result.recipient_emails),
        autoShutdownQueued=result.auto_shutdown_queued,
        commandId=result.command_id,
        actionLinks=result.action_links,
        transport=result.notification_result.transport if result.notification_result else None,
        subject=result.notification_result.subject if result.notification_result else None,
        detail=result.detail,
    )


@router.post("/sensor-control", response_model=SensorControlResponse)
def control_sensor(
    payload: SensorControlRequest,
    current_user: dict = Depends(get_current_user),
) -> SensorControlResponse:
    try:
        result = apply_sensor_control_action(
            sensor_id=payload.sensorId,
            hardware_id=payload.hardwareId,
            device_id=payload.deviceId,
            relay_number=payload.relayNumber,
            target_state=payload.targetState,
            reason=f"dashboard_{payload.targetState}_action:{payload.sensorId}:{current_user['email']}"[:120],
        )
        return SensorControlResponse(
            success=True,
            targetState=payload.targetState,
            commandId=result.command_id,
            hardwareId=result.hardware_id,
            loadId=result.load_id,
            detail=result.detail,
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sensor control failed: {error}",
        ) from error


@router.get("/action", response_class=HTMLResponse)
def perform_notification_action(action: str, token: str) -> str:
    normalized_action = action.strip().lower()
    if normalized_action not in {"keep", "off", "on"}:
        return _action_result_html("Invalid action requested.", "#b43d3d")

    try:
        result = apply_notification_action(normalized_action, token)  # type: ignore[arg-type]
        return _action_result_html(
            (
                f"{result.detail} Device: {result.hardware_id or 'unknown'}"
                + (f" | Command: {result.command_id}" if result.command_id else "")
            ),
            "#1d6d52" if normalized_action in {"keep", "on"} else "#b43d3d",
        )
    except Exception as error:
        return _action_result_html(str(error), "#b43d3d")


def _action_result_html(message: str, accent: str) -> str:
    safe_message = escape(message)
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>INNOTHON Notification Action</title>
  </head>
  <body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f7f6;font-family:Segoe UI,Arial,sans-serif;color:#163041;padding:24px;">
    <section style="max-width:640px;width:100%;background:#ffffff;border:1px solid {accent};border-radius:18px;padding:28px;box-shadow:0 20px 50px rgba(15,31,39,0.08);">
      <div style="font-size:12px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:{accent};">Notification Action</div>
      <h1 style="margin:8px 0 10px;font-size:28px;">Request Processed</h1>
      <p style="margin:0;line-height:1.6;color:#3d5567;">{safe_message}</p>
    </section>
  </body>
</html>
"""
