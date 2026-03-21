# Inductive GNN Workspace

This folder adds a self-contained, topology-aware anomaly pipeline for the campus power graph.

What it does:

- converts the provided graph JSON into node and edge tables
- generates synthetic per-node voltage/current/power telemetry
- trains a window-based spatio-temporal GraphSAGE-style classifier
- holds out a subset of `load` nodes during training to demonstrate inductive generalization
- predicts anomaly labels from a sliding history window ending at the chosen timestamp

## Why this is inductive

The model is trained on node features plus neighborhood aggregation, not on fixed node ids.

That means:

- new `load` nodes can be added later
- unseen nodes can still be scored if you provide:
  - their node features
  - their edges to the graph

## Why this is now spatio-temporal

Prediction is no longer based on a single snapshot.

The model takes a recent history window for every node, learns temporal patterns from that window, and then propagates that information through graph neighborhoods.

So the effective input is:

- graph structure
- recent per-node history of `voltage_v`, `current_a`, `power_kw`, and derived ratios

## Dataset files

Running the generator creates:

- `nodes.csv`
- `edges.csv`
- `timeseries.csv`
- `latest_snapshot.csv`

`timeseries.csv` contains one row per node per timestamp, including:

- `voltage_v`
- `current_a`
- `power_kw`
- `label`

## Run the full pipeline

```powershell
cd C:\Users\Lenovo\OneDrive\Documents\INNOTHON
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\src"
python -m innothon_gnn.cli pipeline `
  --graph-path C:\Users\Lenovo\OneDrive\Documents\INNOTHON\response_1774103530086.json `
  --output-dir C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\generated
```

That will:

1. generate synthetic telemetry under `generated\dataset`
2. train the spatio-temporal inductive model
3. write `latest_predictions.csv`

## Run step by step

Generate data:

```powershell
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\src"
python -m innothon_gnn.cli generate `
  --graph-path C:\Users\Lenovo\OneDrive\Documents\INNOTHON\response_1774103530086.json `
  --output-dir C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\generated\dataset
```

Train:

```powershell
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\src"
python -m innothon_gnn.cli train `
  --dataset-dir C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\generated\dataset `
  --model-path C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\generated\graphsage_inductive_model.npz `
  --window-size 6
```

Predict:

```powershell
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\src"
python -m innothon_gnn.cli predict `
  --dataset-dir C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\generated\dataset `
  --model-path C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\generated\graphsage_inductive_model.npz `
  --output-csv C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\gnn_inductive\generated\latest_predictions.csv
```

## Notes

- `load` nodes are the main anomaly targets.
- `bus` and `external_grid` nodes stay in the graph as structural context.
- The synthetic generator creates correlated bus-level stress events so the GNN can learn from graph structure, not just isolated node values.
- `window-size 6` means the model uses the last 6 timestamps for each node before predicting the current anomaly state.
