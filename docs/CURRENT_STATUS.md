# Current Status

This document captures the current working state of the repository after the recent rollback to the simpler monitoring model.

## Snapshot

- Date: 2026-03-21
- Branch: `sarang`
- Git state at time of writing: clean before this document was added
- Current simplification: `1 ESP = 1 building`

## Current System Model

For now, the project is using the simpler building-level model:

- One ESP device is associated with one building
- One building is shown as one monitored node in the UI
- The ESP is treated as the building-level telemetry source
- The network simulation still uses one load per building/node

This is not the final dense multi-device-per-building model.
That larger model was discussed, but the repo is currently aligned to the simpler version again.

## What The App Currently Does

### Backend

The backend provides:

- user registration and login
- device claiming
- device inventory listing
- telemetry ingestion over HTTP
- telemetry ingestion over MQTT
- model simulation and model comparison endpoints
- MongoDB-backed persistence

Main backend entrypoints:

- [main.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/apps/api/app/main.py)
- [services.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/apps/api/app/services.py)
- [database.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/apps/api/app/database.py)
- [schemas.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/apps/api/app/schemas.py)

### Frontend

The frontend provides:

- login/register flow
- map-based dashboard for buildings/nodes
- node claiming
- supervision action to compare model output with current readings
- operator review action to mark red nodes as normal in the UI

Main frontend files:

- [App.tsx](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/frontend/src/App.tsx)
- [serviceX.ts](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/frontend/src/serviceX.ts)
- [App.css](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/frontend/src/App.css)

### ML / Simulation

The ML/simulation layer currently supports:

- parsing network payloads
- validating network structure
- running power simulation through `pandapower`
- comparing actual sensor values against simulated values
- reporting deviation, missing values, and topology issues

Main ML files:

- [compare.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/ml/src/innothon_sim/compare.py)
- [service.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/ml/src/innothon_sim/service.py)
- [models.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/ml/src/innothon_sim/models.py)
- [pandapower_adapter.py](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/ml/src/innothon_sim/pandapower_adapter.py)

## Current Network Persistence

The network is persisted in MongoDB with section-based collections.

Important collections:

- `networks`
- `network_buses`
- `network_external_grids`
- `network_lines`
- `network_transformers`
- `network_loads`
- `network_static_generators`
- `network_storage`
- `network_switches`
- `network_sensor_links`

Supporting app collections:

- `users`
- `sold_devices`
- `sensor_readings`
- `device_commands`
- `claims`

## Current Meaning Of `sold_devices`

`sold_devices` is still part of the current auth/claim/telemetry flow.

Right now it is used for:

- device inventory
- claim flow
- device auth token storage
- linking recent readings to claimed hardware

It should be treated as the current device registry layer, not as the canonical source for graph topology.
The graph/network truth should come from the network collections and the reconstructed network payload.

## Current API Areas

### Auth and Device APIs

- `POST /auth/register`
- `POST /auth/login`
- `POST /devices/claim`
- `GET /devices`
- `GET /devices/inventory`
- `GET /devices/{device_id}`
- `POST /devices/{device_id}/commands`
- `POST /ingest/http`
- `GET /mqtt/status`

### Model APIs

- `POST /model/simulate-network`
- `POST /model/compare-network`
- `POST /model/analyze-graph`
- `GET /model/sample-graph`
- `GET /model/nitw-reference`

### Network Persistence APIs

- `GET /networks/{network_name}`
- `GET /networks/{network_name}/collections`
- `POST /networks/sync`
- `POST /networks/{network_name}/components/{section_name}`
- `GET /networks/{network_name}/compare-latest`

## Current UI Behavior

The dashboard currently assumes a building-level node representation.

That means:

- one marker on the map represents one building/node
- each node can be claimed
- supervise compares readings against simulation
- comparison details can show exact simulated, measured, and delta values
- red nodes can be marked as normal by the operator in UI-only state

The operator review action is currently not persisted to the backend.
It is only a frontend action for now.

## Current Topology Handling

The backend includes repair/normalization logic to keep the saved network usable:

- missing buses can be auto-created when referenced by other sections
- disconnected buses can be auto-connected to the slack bus with generated lines

This keeps the simulation structurally connected, but it is still a fallback approximation.
It is not a substitute for modeling the true physical feeder layout.

## Current Known Limitations

- The project is currently using the simpler `1 ESP per building` model
- The dense multi-device-per-building architecture is not the active working assumption right now
- Operator anomaly review is UI-only and not stored as training/feedback data yet
- Some compatibility logic still exists around `sold_devices`
- Accurate power-flow quality still depends on realistic line/transformer topology
- `pandapower` must be installed locally for full simulation execution

## Recommended Next Steps

If development continues from the current simplified state, the most sensible next steps are:

1. Keep the `1 ESP per building` model stable first
2. Persist operator review decisions to the backend
3. Cleanly separate graph truth from claim/device registry logic
4. Improve feeder topology realism
5. Reintroduce multi-device-per-building only when the UI, ingestion model, and persistence model are all ready together

## Repository Structure

Top-level folders:

- [apps](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/apps)
- [frontend](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/frontend)
- [ml](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/ml)
- [model_service](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/model_service)
- [service_x](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/service_x)
- [docs](C:/Users/Asus/OneDrive/Desktop/INNOTHON/INNOTHON/docs)

## Short Summary

Current repo state is stable and back on the simpler monitoring model:

- one ESP per building
- one building-level node in the dashboard
- section-based network persistence in MongoDB
- simulation and comparison flow working through the model endpoints
- UI anomaly review present, but not yet persisted
