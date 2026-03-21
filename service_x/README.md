# Service X

`Service X` is a small Python API that:

- stores a hardcoded network graph in memory
- converts that graph into the ML module's `pandapower` input format
- runs the real ML/simulation comparison path
- returns analyzed graph data to the frontend
- updates the stored graph when the frontend changes a node or edge

## Run

```powershell
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\src"
uvicorn service_x.app:app --reload
```

The API runs on `http://127.0.0.1:8000` by default.

## Endpoints

- `GET /service-x/state`
- `PUT /service-x/graph`
- `GET /health`
