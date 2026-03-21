# Power Graph Frontend

This is a simple React + React Flow prototype for building and inspecting a power network.

## What it does

- drag and drop components onto the graph canvas
- add and remove nodes
- connect components with edges
- edit a selected node's label and nominal power
- load network structure and sensor readings from a mock `service X` adapter
- send the current graph structure into a model adapter on every edit
- push graph updates back to the `service X` adapter when users change the canvas
- color nodes based on high, low, normal, or off power state
- show problem cards with two actions:
  - `Turn off`
  - `No, it's fine lk,kp`
  

## Current architecture

- `service X` sends network structure and sensor readings
- `service X` calls the real Python ML module in [ml](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml)
- the frontend converts that payload into React Flow nodes and edges
- the frontend renders the analyzed graph returned by `service X`
- when the user edits the graph, the frontend pushes the updated graph back to `service X`

## Current model behavior

The frontend no longer computes the analysis locally. The real analysis now comes from the Python API in [service_x/app.py](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\service_x\app.py), which uses the ML module.

That means:

- the graph is stored in the Python service
- the service converts it to the `pandapower` input contract
- the service runs the ML/simulation comparison path
- the frontend receives already-analyzed node states and problems

## Main files

- [App.tsx](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\frontend\src\App.tsx): main page and editor state
- [PowerNode.tsx](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\frontend\src\PowerNode.tsx): custom node card UI
- [model.ts](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\frontend\src\model.ts): frontend-side reference model logic kept for comparison and future cleanup
- [serviceX.ts](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\frontend\src\serviceX.ts): HTTP client for `service X`
- [types.ts](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\frontend\src\types.ts): shared frontend graph/model types

## Run locally

```powershell
cd C:\Users\Lenovo\OneDrive\Documents\INNOTHON
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\src"
uvicorn service_x.app:app --reload
```

In a second terminal:

```powershell
cd C:\Users\Lenovo\OneDrive\Documents\INNOTHON\frontend
npm install
npm run dev
```

Then open the local Vite URL shown in the terminal.

## Build check

```powershell
npm run build
npm run lint
```

## Integration note

When the backend or ML API is ready, replace the mock `analyzeGraph()` function with a real request while keeping the payload structure stable.
