# ML Phase 1: pandapower Workspace

This folder contains the first ML/simulation slice for the project.

Scope of this phase:

- define a machine-readable network format
- convert that format into a `pandapower` network
- run load-flow simulations
- compare simulated values with future sensor readings
- keep everything isolated from frontend and backend work

## Folder layout

```text
ml/
  README.md
  requirements.txt
  sample_data/
    simple_radial_network.json
  src/
    innothon_sim/
      __init__.py
      cli.py
      compare.py
      exceptions.py
      io.py
      models.py
      pandapower_adapter.py
  tests/
    test_io.py
```

## Input model

The JSON format is intentionally close to `pandapower` so we can later build a converter from the user-created graph editor into this structure.

Supported components in this first pass:

- buses
- external grids
- lines
- transformers
- loads
- static generators
- storage
- switches
- sensor links for later actual-vs-simulated comparisons

## Install

```powershell
python -m pip install -r ml\requirements.txt
```

## Run a sample simulation

```powershell
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\src"
python -m innothon_sim.cli simulate ml\sample_data\simple_radial_network.json
```

## Compare real readings later

When real readings exist, save them as JSON like:

```json
{
  "sensor_bus_slack_voltage": 1.0,
  "sensor_load_line_loading": 42.5,
  "sensor_main_load_p_mw": 0.61
}
```

Then run:

```powershell
$env:PYTHONPATH="C:\Users\Lenovo\OneDrive\Documents\INNOTHON\ml\src"
python -m innothon_sim.cli compare ml\sample_data\simple_radial_network.json readings.json
```

## Collaboration notes

- Frontend/backend can later export or send network graphs into this JSON contract.
- Sensor mappings belong in `sensor_links`, which lets us compare real telemetry to `pandapower` outputs without coupling to the API yet.
- If `pandapower` is not installed locally, the code will fail with a clear error instead of silently faking a simulation.
