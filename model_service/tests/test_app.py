from fastapi.testclient import TestClient

from model_service.app import app


client = TestClient(app)


SAMPLE_SNAPSHOT = {
    "network": {
        "id": "network-alpha",
        "name": "North Feeder",
    },
    "graph": {
        "nodes": [
            {
                "id": "source-grid",
                "type": "source",
                "label": "Main Grid",
                "x": 50,
                "y": 200,
                "nominalPowerKw": 500,
                "active": True,
            },
            {
                "id": "transformer-1",
                "type": "transformer",
                "label": "T1",
                "x": 250,
                "y": 200,
                "nominalPowerKw": 300,
                "active": True,
            },
            {
                "id": "sink-a",
                "type": "sink",
                "label": "Factory A",
                "x": 500,
                "y": 200,
                "nominalPowerKw": 180,
                "active": True,
            },
        ],
        "edges": [
            {"id": "e1", "source": "source-grid", "target": "transformer-1"},
            {"id": "e2", "source": "transformer-1", "target": "sink-a"},
        ],
    },
    "sensorReadings": [
        {
            "nodeId": "source-grid",
            "powerKw": 470,
            "voltageKv": 20,
            "timestamp": "2026-03-21T10:30:00Z",
        },
        {
            "nodeId": "transformer-1",
            "powerKw": 260,
            "voltageKv": 11,
            "timestamp": "2026-03-21T10:30:00Z",
        },
        {
            "nodeId": "sink-a",
            "powerKw": 230,
            "voltageKv": 11,
            "timestamp": "2026-03-21T10:30:00Z",
        },
    ],
}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_graph() -> None:
    response = client.post("/model/analyze-graph", json={"snapshot": SAMPLE_SNAPSHOT})
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["analysis"]["summary"]["totalNodes"] == 3
    assert "sink-a" in payload["analysis"]["nodes"]
