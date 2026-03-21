# Model Service

This is the dedicated microservice for the model layer.

It wraps the existing Python ML code in [ml](C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml) and exposes HTTP endpoints so other services can call it.

## What it does

- accepts the raw ML network contract and runs simulation
- accepts network + readings and runs comparison
- accepts a higher-level graph snapshot and converts it into the ML contract
- returns analyzed output over HTTP

## Run

```powershell
cd C:\Users\Lenovo\OneDrive\Documents\INNOTHON
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\src"
uvicorn model_service.app:app --reload --port 8010
```

## Endpoints

- `GET /health`
- `POST /model/simulate-network`
- `POST /model/compare-network`
- `POST /model/analyze-graph`
