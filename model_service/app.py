from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
ML_SRC = ROOT / "ml" / "src"
if str(ML_SRC) not in sys.path:
    sys.path.insert(0, str(ML_SRC))

from innothon_sim.service import compare_network_payload, simulate_network_payload  # noqa: E402

from .graph_adapter import comparison_to_node_analysis, graph_to_ml_payload


class CompareNetworkRequest(BaseModel):
    network_payload: dict[str, Any]
    readings_payload: dict[str, Any]


class AnalyzeGraphRequest(BaseModel):
    snapshot: dict[str, Any]


app = FastAPI(title="INNOTHON Model Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/model/simulate-network")
def simulate_network(network_payload: dict[str, Any]) -> dict[str, Any]:
    return simulate_network_payload(network_payload)


@app.post("/model/compare-network")
def compare_network(request: CompareNetworkRequest) -> dict[str, Any]:
    return compare_network_payload(
        request.network_payload,
        request.readings_payload,
    )


@app.post("/model/analyze-graph")
def analyze_graph(request: AnalyzeGraphRequest) -> dict[str, Any]:
    network_payload, readings_payload, sensor_to_node = graph_to_ml_payload(
        request.snapshot
    )
    comparison = compare_network_payload(network_payload, readings_payload)
    analysis = comparison_to_node_analysis(
        request.snapshot,
        comparison,
        sensor_to_node,
    )
    return {
        "status": "ok",
        "network_payload": network_payload,
        "readings_payload": readings_payload,
        "comparison": comparison,
        "analysis": analysis,
    }
