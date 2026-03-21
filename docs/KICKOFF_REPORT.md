# INNOTHON Kickoff Report

## 1. Project Goal

Build an IoT power-network platform where:

- ESP devices send sensor data over MQTT or HTTP.
- The server stores time-series readings with full metadata.
- The server can piggyback relay instructions in responses to ESP devices.
- Users manage owned devices, sensors, power-network graphs, anomaly settings, and notifications.
- A simulation and analytics layer compares real readings with expected values from `pandapower`.
- An ML/rules engine detects anomalies and can optionally trigger automated handling.

This report is written as a starting blueprint for a greenfield repository.

## 2. Recommended System Shape

Use a monorepo so frontend and backend stay aligned.

Suggested apps/packages:

```text
/apps
  /web                -> frontend dashboard
  /api                -> backend REST + MQTT/HTTP ingestion
  /ml-service         -> anomaly detection, forecasting, optimization
  /simulation-service -> pandapower execution service
/packages
  /contracts          -> shared TypeScript schemas and API DTOs
  /ui                 -> reusable UI components
  /config             -> lint/tsconfig/shared tooling
/docs
  /KICKOFF_REPORT.md
```

## 3. Core Architecture

### 3.1 Main components

1. ESP device
2. API/Ingestion service
3. Relational database
4. Time-series storage
5. Frontend dashboard
6. ML/anomaly service
7. `pandapower` simulation service
8. Notification service

### 3.2 Recommended tech stack

- Frontend: React + Next.js + TypeScript
- Backend API: Node.js + NestJS or Express + TypeScript
- MQTT broker: EMQX or Mosquitto
- Database: PostgreSQL
- Time-series option: PostgreSQL + TimescaleDB extension if available
- Cache/queue: Redis
- ML/Simulation: Python service using `pandapower`, `pandas`, `scikit-learn`/`prophet`/PyTorch as needed
- Auth: JWT/session auth for users, device credentials for ESPs
- Realtime to frontend: WebSocket or Server-Sent Events

Why this split:

- TypeScript helps us keep frontend and backend contracts synced.
- Python is the practical choice for `pandapower` and ML.
- PostgreSQL handles account/device/graph data well.
- A separate ingestion path keeps device traffic reliable.

## 4. Device Communication Design

### 4.1 Supported protocols

Support both:

- MQTT as the preferred production path
- HTTP as a fallback or easier prototype path

### 4.2 Device payload shape

Each sensor upload should include:

- `hardwareId`
- `deviceAuthToken` or signed credential
- `espTimestamp`
- `serverReceivedAt`
- `sensorId`
- `sensorType`
- `value`
- `unit`
- `relayState` if relevant
- `signalStrength` / device health metadata if available

Example device message:

```json
{
  "hardwareId": "ESP-000123",
  "espTimestamp": "2026-03-21T10:30:00Z",
  "readings": [
    {
      "sensorId": "voltage_a",
      "sensorType": "voltage",
      "value": 231.4,
      "unit": "V"
    },
    {
      "sensorId": "current_a",
      "sensorType": "current",
      "value": 8.1,
      "unit": "A"
    }
  ]
}
```

### 4.3 Piggyback response shape

Every device upload response should optionally include pending commands:

```json
{
  "status": "ok",
  "serverTimestamp": "2026-03-21T10:30:02Z",
  "commands": [
    {
      "commandId": "cmd_789",
      "type": "relay.set",
      "relayNumber": 3,
      "targetState": "off",
      "reason": "anomaly_detected"
    }
  ]
}
```

### 4.4 Command handling model

Store relay/device actions in a `device_commands` table with status:

- `pending`
- `sent`
- `acknowledged`
- `expired`
- `failed`

When the ESP next uploads data, the server returns pending commands. The device executes them and confirms in the next payload or a dedicated ack request.

## 5. User and Device Ownership Model

### 5.1 Registration flow

Manufacturer-side `sold_devices` table stores:

- `hardware_id`
- `device_password`
- `device_model`
- `sensor_manifest`
- `relay_count`
- `firmware_version`
- `sold_to_user_id` nullable until claimed
- `claim_status`

User claims a device by entering:

- hardcoded `hardwareId`
- hardcoded manufacturer password

After success:

- device is linked to the user account
- a device auth token is created for the ESP
- device becomes visible in the dashboard

### 5.2 Hardcoded sensor manifest

Do not trust the frontend to define actual hardware capabilities.
The backend should read sensor and relay capability from `sold_devices` or `device_models`.

This directly supports your requirement that "which ESP has what sensors is hardcoded into DB".

## 6. Database Design

Use PostgreSQL tables roughly like this:

### 6.1 Core account/device tables

- `users`
- `accounts`
- `account_members`
- `sold_devices`
- `user_devices`
- `device_sensors`
- `device_relays`

### 6.2 Sensor data and command tables

- `sensor_readings`
- `device_commands`
- `device_command_acks`
- `device_heartbeats`
- `anomalies`
- `notifications`

### 6.3 Power network modeling tables

- `networks`
- `network_nodes`
- `network_edges`
- `sensor_locations`
- `network_snapshots`
- `simulation_runs`
- `simulation_results`
- `optimization_recommendations`

### 6.4 Important modeling note

Store the power network as normalized graph data:

- node types: source, battery, transmission, sink, transformer, relay, meter
- edge types: cable, feeder, logical connection

This lets us:

- render graphs in frontend
- map sensors to graph nodes or edges
- convert the graph into a `pandapower` model

## 7. Frontend-Backend Sync Strategy

This is important for your requirement that frontend changes should reflect in backend.

### 7.1 Rule

Use shared contracts instead of duplicating request/response types.

### 7.2 Practical implementation

Create a shared `packages/contracts` package containing:

- Zod schemas
- TypeScript types
- API DTOs
- event payload schemas

Frontend uses these contracts for forms and API calls.
Backend uses the same schemas for validation and serialization.

### 7.3 Best result

If the frontend adds fields like:

- anomaly toggle
- auto-handling toggle
- sensor location metadata
- graph node properties

the backend contract changes in the same package, so both sides stay aligned.

## 8. Main Product Modules

### 8.1 Device management

- claim/register ESP
- list owned ESPs
- show sensors and relay capabilities
- show last seen/device health

### 8.2 Sensor monitoring

- real-time readings
- historical charts
- current relay states
- alert history

### 8.3 Network graph editor

- drag-and-drop node editor
- create components and edges
- assign sensor-to-node location
- save multiple network versions

### 8.4 Anomaly and automation controls

- enable/disable anomaly notifications
- enable/disable auto handling
- define relay handling policies

### 8.5 Analytics dashboard

- simulated vs actual power
- expected demand in coming days
- recent anomalies
- future risk forecast
- optimization suggestions

## 9. Simulation and ML Design

### 9.1 Pandapower workflow

1. User builds network graph in frontend
2. Backend stores graph in normalized tables
3. Simulation service converts graph to `pandapower` network
4. Service runs load flow / power calculations
5. Results are stored and compared against sensor readings

### 9.2 Analytics outputs

Compute:

- expected voltage/current/power by network component
- actual vs simulated deviation
- anomaly scores per sensor/line/node
- forecasted future load
- likely future anomaly windows
- optimization recommendations

### 9.3 Recommended anomaly approach

Start simple, then improve:

Phase 1:

- threshold rules
- deviation from `pandapower` output
- moving average and z-score checks

Phase 2:

- isolation forest / one-class models
- time-series forecasting residual analysis

Phase 3:

- learned control suggestions
- automated optimization policies

## 10. Notifications and Auto Handling

### 10.1 Notifications

Support:

- in-app notifications
- email
- optional SMS/WhatsApp later

Each account can toggle:

- anomaly notifications on/off
- severity threshold
- per-device/per-network preferences

### 10.2 Automatic handling

If enabled:

- ML/rules engine creates a `device_commands` record
- next device upload returns the command
- device executes relay action
- backend records ack and action history

Important safety rule:

- never auto-execute without account-level opt-in
- record reason and model/rule source for every automated action

## 11. Suggested API Surface

### 11.1 User-facing APIs

- `POST /auth/register`
- `POST /auth/login`
- `POST /devices/claim`
- `GET /devices`
- `GET /devices/:id`
- `GET /devices/:id/readings`
- `POST /devices/:id/commands`
- `PATCH /devices/:id/settings`
- `POST /networks`
- `GET /networks/:id`
- `PUT /networks/:id`
- `POST /networks/:id/simulate`
- `GET /networks/:id/analytics`
- `GET /notifications`
- `PATCH /accounts/preferences`

### 11.2 Device-facing APIs

- `POST /ingest/http`
- `POST /devices/ack-command`

### 11.3 MQTT topics

- publish from device: `devices/{hardwareId}/telemetry`
- publish from server: `devices/{hardwareId}/commands`
- optional ack: `devices/{hardwareId}/acks`

Even if MQTT push commands are supported later, keep piggyback command return on upload because it is simple and robust.

## 12. Delivery Plan

### Phase 1: Core platform

- monorepo setup
- auth
- device claim flow
- sold device inventory
- sensor manifest handling
- HTTP ingestion
- basic dashboard
- store sensor readings

### Phase 2: Device control and realtime

- MQTT ingestion
- pending command piggyback response
- relay command UI
- notification basics
- realtime charts

### Phase 3: Graph and simulation

- graph editor
- sensor location mapping
- normalized graph storage
- `pandapower` conversion
- simulation runs and comparison view

### Phase 4: ML and automation

- anomaly scoring
- forecasting
- optimization recommendations
- optional auto relay handling
- audit trail and safety controls

## 13. First Sprint Recommendation

For the first working version, build only this:

1. User auth
2. Device claim using `hardwareId` + manufacturer password
3. DB tables for sold devices, user devices, sensors, readings, commands
4. HTTP ingestion endpoint for ESP
5. Response with pending relay commands
6. Dashboard showing devices, sensors, latest readings
7. Manual relay toggle from frontend

This gives you an end-to-end demo quickly:

- frontend -> backend
- backend -> database
- ESP -> server
- server -> piggyback command -> ESP

## 14. Risks to Manage Early

### 14.1 Device identity and security

- Do not use only plain hardware ID for trust.
- Issue device tokens after claim/provisioning.

### 14.2 Command duplication

- Devices may retry uploads.
- Commands need idempotent IDs and ack tracking.

### 14.3 Timestamp quality

- ESP clocks may drift.
- Store both device timestamp and server timestamp.

### 14.4 Simulation mismatch

- User-created graphs may be incomplete or invalid.
- Add graph validation before simulation.

### 14.5 Automation safety

- Auto relay actions must be auditable and reversible.

## 15. Recommended Immediate Repo Tasks

When implementation starts, create these first:

1. monorepo structure
2. shared contract package
3. PostgreSQL schema and migrations
4. backend API skeleton
5. frontend auth/device pages
6. HTTP ingestion endpoint
7. sample ESP payload contract

## 16. Collaboration Note

Once you share the repository with actual code, the next step should be:

1. inspect current stack
2. map missing modules against this report
3. create an implementation backlog
4. start with the first end-to-end slice instead of building everything at once

This report is intentionally practical rather than final. We can now turn it into:

- a technical architecture document
- database schema
- API contract files
- folder scaffolding
- first sprint tasks
