from __future__ import annotations
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import (
    generate_alerts_from_comparisons,
    get_network_bundle,
    get_network_payload,
    initialize_database,
    latest_network_sensor_readings,
    sync_network_payload,
    upsert_network_component,
)
from app.dependencies import get_current_user
from app.model_runtime import (
    analyze_model_graph,
    compare_model_network,
    sample_graph_snapshot,
    simulate_model_network,
)
from app.mqtt_service import mqtt_bridge
from app.schemas import (
    AuthResponse,
    ClaimDeviceRequest,
    DeviceCommandCreateRequest,
    DeviceCommandResponse,
    DeviceSummary,
    IngestResponse,
    LoginRequest,
    ModelCompareRequest,
    ModelGraphAnalyzeRequest,
    ModelServiceResponse,
    MqttStatusResponse,
    RegisterRequest,
    TelemetryPayload,
)
from app.services import (
    claim_device,
    create_device_command,
    get_device_summary,
    ingest_telemetry,
    list_device_inventory,
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
    if getattr(settings, "model_only_mode", False):
        return
    initialize_database()
    mqtt_bridge.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    if getattr(settings, "model_only_mode", False):
        return
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


@app.get("/devices/inventory", response_model=list[DeviceSummary])
def get_device_inventory(current_user: dict = Depends(get_current_user)) -> list[DeviceSummary]:
    return list_device_inventory()


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


@app.post("/model/simulate-network", response_model=ModelServiceResponse)
def simulate_network(payload: dict) -> ModelServiceResponse:
    return ModelServiceResponse(**simulate_model_network(payload))


@app.post("/model/compare-network", response_model=ModelServiceResponse)
def compare_network(payload: ModelCompareRequest) -> ModelServiceResponse:
    return ModelServiceResponse(
        **compare_model_network(payload.network_payload, payload.readings_payload)
    )


@app.post("/model/analyze-graph", response_model=ModelServiceResponse)
def analyze_graph(payload: ModelGraphAnalyzeRequest) -> ModelServiceResponse:
    return ModelServiceResponse(**analyze_model_graph(payload.snapshot))


@app.get("/model/sample-graph")
def get_model_sample_graph() -> dict:
    return sample_graph_snapshot()


@app.get("/model/nitw-reference")
def get_nitw_reference() -> dict:
    return get_network_payload("NITW") or {}


@app.get("/networks/{network_name}")
def get_network(network_name: str) -> dict:
    bundle = get_network_bundle(network_name)
    if bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")
    return bundle


@app.get("/networks/{network_name}/collections")
def get_network_collections(network_name: str) -> dict:
    bundle = get_network_bundle(network_name)
    if bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")
    return {
        "status": "ok",
        "network_name": network_name,
        "collections": bundle["collections"],
        "component_counts": bundle["component_counts"],
    }


@app.post("/networks/sync")
def sync_network(payload: dict) -> dict:
    try:
        return sync_network_payload(payload)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@app.post("/networks/{network_name}/components/{section_name}")
def upsert_network_section_component(network_name: str, section_name: str, payload: dict) -> dict:
    try:
        return upsert_network_component(network_name, section_name, payload)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@app.get("/networks/{network_name}/compare-latest")
def compare_network_with_latest_readings(network_name: str) -> dict:
    payload = get_network_payload(network_name)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

    readings_payload = latest_network_sensor_readings(network_name)
    comparison = compare_model_network(payload, readings_payload)
    alerts = generate_alerts_from_comparisons(comparison.get("comparisons", []))
    return {
        **comparison,
        "readings_payload": readings_payload,
        "alerts": alerts["alerts"],
        "alerts_summary": alerts["summary"],
    }


@app.get("/model/test-ui", response_class=HTMLResponse)
def get_model_test_ui() -> str:
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>INNOTHON Model Tester</title>
    <style>
      body {
        margin: 0;
        font-family: Segoe UI, sans-serif;
        background: #f5efe7;
        color: #1f1a17;
      }
      .page {
        display: grid;
        grid-template-columns: 420px minmax(0, 1fr);
        min-height: 100vh;
      }
      .panel {
        padding: 24px;
        background: #fff8f1;
        border-right: 1px solid #e6d7c7;
      }
      .panel h1 {
        margin: 0 0 12px;
        font-size: 32px;
      }
      .panel p {
        color: #6d5b4d;
      }
      textarea {
        width: 100%;
        min-height: 420px;
        margin-top: 12px;
        padding: 12px;
        box-sizing: border-box;
        border-radius: 12px;
        border: 1px solid #d8c7b7;
        background: #fffdf9;
        font: 13px/1.45 Consolas, monospace;
      }
      .actions {
        display: flex;
        gap: 12px;
        margin-top: 12px;
      }
      button {
        border: 0;
        border-radius: 999px;
        background: #1f1a17;
        color: #fff8f1;
        padding: 12px 18px;
        font-weight: 700;
        cursor: pointer;
      }
      button.secondary {
        background: #c46027;
      }
      .results {
        padding: 24px;
      }
      pre {
        margin: 0;
        padding: 16px;
        border-radius: 14px;
        background: #1f1a17;
        color: #f8eee0;
        overflow: auto;
        min-height: 100px;
      }
      .status {
        margin-top: 12px;
        color: #6d5b4d;
        font-weight: 600;
      }
      @media (max-width: 980px) {
        .page {
          grid-template-columns: 1fr;
        }
        .panel {
          border-right: 0;
          border-bottom: 1px solid #e6d7c7;
        }
      }
    </style>
  </head>
  <body>
    <div class="page">
      <section class="panel">
        <h1>Model Tester</h1>
        <p>Load the sample graph, tweak it, and send it to the backend model endpoint.</p>
        <div class="actions">
          <button id="loadSample">Load sample</button>
          <button id="runAnalyze" class="secondary">Run analyze-graph</button>
        </div>
        <div class="status" id="status">Ready.</div>
        <textarea id="payloadEditor"></textarea>
      </section>
      <section class="results">
        <h2>Response</h2>
        <pre id="responseViewer">{}</pre>
      </section>
    </div>
    <script>
      const payloadEditor = document.getElementById('payloadEditor');
      const responseViewer = document.getElementById('responseViewer');
      const status = document.getElementById('status');

      async function loadSample() {
        status.textContent = 'Loading sample graph...';
        const response = await fetch('/model/sample-graph');
        const payload = await response.json();
        payloadEditor.value = JSON.stringify({ snapshot: payload }, null, 2);
        status.textContent = 'Sample graph loaded.';
      }

      async function runAnalyze() {
        try {
          status.textContent = 'Calling /model/analyze-graph...';
          const payload = JSON.parse(payloadEditor.value);
          const response = await fetch('/model/analyze-graph', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          const body = await response.json();
          responseViewer.textContent = JSON.stringify(body, null, 2);
          status.textContent = response.ok ? 'Analysis complete.' : 'Request failed.';
        } catch (error) {
          status.textContent = 'Invalid JSON or request error.';
          responseViewer.textContent = String(error);
        }
      }

      document.getElementById('loadSample').addEventListener('click', loadSample);
      document.getElementById('runAnalyze').addEventListener('click', runAnalyze);
      loadSample();
    </script>
  </body>
</html>
"""
