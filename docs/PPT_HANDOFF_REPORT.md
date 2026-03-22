# INNOTHON Presentation Handoff Report

Prepared on 22 March 2026 for PPT creation.

This report is written for someone who knows only a little about the project and needs enough context to build a clear presentation quickly.

## 1. Project in One Paragraph

INNOTHON is a smart power-network monitoring platform for campuses or building clusters. It connects ESP-based IoT devices to a web dashboard, collects sensor readings over HTTP or MQTT, stores them in the backend, maps them to buildings in a power network, and compares real readings with simulated expected behavior using `pandapower`. The system then highlights possible issues such as overload, undervoltage, outage-like behavior, or abnormal deviation. The current working prototype uses a simplified model where one ESP device represents one building.

## 2. Simple Problem Statement

Many power systems are still monitored in a fragmented way:

- raw sensor values are available, but they are hard to interpret in context
- operators may not know whether a value is normal for that location in the network
- manual checking is slow and can miss early warning signs
- there is often no single visual system combining live telemetry, network structure, and anomaly analysis

## 3. Our Solution

The project combines four ideas in one platform:

1. IoT data collection from ESP devices
2. backend storage and device management
3. a network model of the electrical system
4. comparison of actual readings vs simulated expected values

In simple words, the platform does not only show sensor data. It tries to answer:

"What should this building or node be doing right now, and is the real reading close to that or not?"

## 4. Current Project Scope

The current repo is aligned to a simplified but working demo model:

- `1 ESP = 1 building`
- one building is shown as one monitored node in the dashboard
- one building can contain multiple sensor-linked load points in the network model
- the dashboard currently focuses on building-level supervision rather than a dense device-per-room or device-per-line architecture

This is important for the PPT because it is the current truth of the project, not just the original long-term idea.

## 5. What the System Currently Does

### Backend

The backend currently supports:

- user registration and login
- device claiming using `hardwareId` and manufacturer password
- device inventory listing
- telemetry ingestion through HTTP
- telemetry ingestion through MQTT
- relay command creation and pending-command return in device responses
- network persistence in MongoDB
- model simulation and comparison endpoints

### Frontend

The frontend currently supports:

- login and register flow
- map-based dashboard for buildings
- claimed vs unclaimed building view
- supervision mode to compare expected vs actual readings
- live notification and anomaly panels
- operator review action for red/deviation nodes
- adding a new building from the map
- adding a new sensor/load node to an existing building

### Model Layer

The current model layer supports:

- parsing network payloads
- validating network structure
- running power simulation using `pandapower`
- comparing actual values against expected simulated values
- returning deviation details for the UI

### Experimental ML Work

The repo also contains an experimental inductive GNN pipeline in `ml/gnn_inductive`.

This is useful to mention as advanced work, but it should be presented carefully:

- it shows the project is moving toward graph-aware anomaly detection
- it is not the main runtime path of the current demo

## 6. End-to-End Flow

Here is the simplest way to explain the product flow in the PPT:

1. A user creates an account or logs in.
2. The user claims a building/device using a known `hardwareId` and manufacturer password.
3. The backend links that device to the user account.
4. The ESP device sends telemetry readings through HTTP or MQTT.
5. The backend stores those readings and can also return pending relay commands.
6. The frontend loads the network model and device data.
7. The model layer simulates expected network behavior.
8. The system compares expected values with actual sensor values.
9. The dashboard marks nodes/buildings as healthy, deviation, or unclaimed.
10. The operator reviews suspicious nodes and can take action.

## 7. Main Features to Highlight in the PPT

These are the best current features to showcase:

- secure user login and registration
- device claim flow
- live telemetry ingestion
- MQTT plus HTTP support
- building-level dashboard on a map
- expected vs actual comparison using power simulation
- anomaly/deviation highlighting
- operator review workflow
- editable network structure through building and sensor addition

## 8. Why This Project Is Interesting

The project is stronger than a normal sensor dashboard because it combines:

- IoT telemetry
- electrical network modeling
- simulation-based validation
- anomaly indication
- visual decision support for operators

A simple way to pitch the innovation:

"Instead of only showing sensor numbers, the system checks whether the numbers make sense in the context of the electrical network."

## 9. Current Tech Stack

### Frontend

- React
- TypeScript
- Vite
- Leaflet / React Leaflet

### Backend

- FastAPI
- Python
- MongoDB
- JWT-based auth flow

### Device / Communication

- HTTP ingestion
- MQTT ingestion

### Simulation / Analytics

- `pandapower`
- Python network comparison logic

### Advanced / Experimental

- inductive GraphSAGE-style GNN pipeline for anomaly classification

## 10. Honest Current Status

This section is important so the PPT stays accurate.

### What is already working

- end-to-end frontend and backend connection
- auth and claim flow
- device inventory and claimed device listing
- telemetry ingestion endpoints
- network storage and retrieval
- simulation and comparison endpoints
- map-based dashboard and supervision UI

### What is partly demo-oriented

- the frontend also uses a simulated live window for continuous visual updates and predictive insight cards
- operator review is currently a UI action and is not yet persisted back to the backend

### What is not yet the final form

- the project is still using the simplified `1 ESP per building` assumption
- advanced ML is not yet the primary production path
- final topology realism still depends on better network data

## 11. Safe Wording for the Presentation

### Safe claims

You can safely say:

- "We built an end-to-end prototype for smart power-network monitoring."
- "The current prototype monitors one ESP gateway per building."
- "The system compares actual readings with simulated expected values."
- "The dashboard visualizes building status, anomaly risk, and operator review."
- "The architecture is ready to grow into more advanced graph-based analytics."

### Avoid overclaiming

It is better not to say:

- "This is already a fully deployed industrial system."
- "All anomaly detection is already handled by a production-trained AI model."
- "Every live value shown in the UI is always coming from real deployed hardware."
- "Operator feedback is already stored and used for retraining."

## 12. Suggested PPT Structure

Your friend can turn this into a strong 9 to 11 slide deck.

### Slide 1: Title

Title idea:

`INNOTHON: Smart IoT-Based Power Network Monitoring and Anomaly Detection`

Put:

- team/project name
- one-line pitch

One-line pitch:

"A platform that combines IoT telemetry, network simulation, and anomaly monitoring for smart power systems."

### Slide 2: Problem Statement

Put:

- power systems are hard to monitor in real time
- raw values alone are not enough
- operators need context-aware alerts

Visual suggestion:

- simple diagram of scattered sensors and a confused operator

### Slide 3: Proposed Solution

Put:

- ESP devices collect power data
- backend stores and manages the data
- model simulates expected system behavior
- dashboard compares expected vs actual and highlights anomalies

Visual suggestion:

- left-to-right flow diagram

### Slide 4: Architecture

Put:

- ESP devices
- HTTP/MQTT ingestion
- FastAPI backend
- MongoDB
- simulation/model layer
- React dashboard

Visual suggestion:

- block diagram with arrows

### Slide 5: How the System Works

Put:

1. claim device
2. collect telemetry
3. store readings
4. simulate expected values
5. compare with actual values
6. show alert/deviation on map

Visual suggestion:

- numbered workflow graphic

### Slide 6: Key Features

Put:

- auth and device claiming
- telemetry ingestion
- map dashboard
- anomaly supervision
- operator review
- network editing

Visual suggestion:

- feature icons or dashboard screenshots

### Slide 7: Current Demo Status

Put:

- current model is `1 ESP = 1 building`
- working backend, frontend, and simulation flow
- map-based monitoring already implemented

Visual suggestion:

- screenshot of the dashboard if available

### Slide 8: Innovation / USP

Put:

- not just dashboarding
- compares actual readings with expected simulated behavior
- supports future graph-aware ML

Visual suggestion:

- compare "normal dashboard" vs "simulation-aware dashboard"

### Slide 9: Limitations and Honest Status

Put:

- simplified building-level model
- operator review not yet persisted
- advanced ML still experimental

This slide actually increases credibility.

### Slide 10: Future Scope

Put:

- persist operator decisions
- improve topology realism
- move toward multi-device-per-building
- integrate stronger graph ML in runtime
- enable safer automation and closed-loop control

### Slide 11: Conclusion

Put:

- recap the value
- smart monitoring
- faster anomaly detection
- better operator visibility

Closing line:

"INNOTHON shows how IoT, simulation, and graph-aware analytics can work together for smarter energy monitoring."

## 13. Short Speaker Summary

If your friend needs a short explanation before making the PPT, send this:

"INNOTHON is a smart energy monitoring prototype. ESP devices send electrical readings to a FastAPI backend through HTTP or MQTT. The backend stores device and network data in MongoDB. A simulation layer uses pandapower to estimate expected behavior of the electrical network, and the dashboard compares that expected behavior with real readings. The frontend shows buildings on a map, highlights anomalies, and lets operators review suspicious nodes. Right now the prototype is simplified to one ESP per building, but the architecture is designed to expand into richer graph-based monitoring and ML."

## 14. One-Line Summary for the Final Slide

`IoT + Network Simulation + Anomaly Monitoring = Smarter Power Infrastructure Supervision`
