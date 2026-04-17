# TopStitcher

TopStitcher is a PyQt6-based manual-first RTL integration workspace for building top-level Verilog modules from existing submodules.

Current version: **3.0.0**

## What changed in this version

This project no longer uses the old RuleA/RuleB workflow where import immediately auto-connected ports and auto-promoted leftover ports to top-level IO.

The current model is:

- import modules
- create instances
- initialize a **manual-first workspace**
- explicitly use:
  - `Connect`
  - `Disconnect`
  - `Auto IO`
  - `Auto Connect`
- generate Verilog from the workspace state

The workspace is now the single source of truth.

## Core concepts

### DesignWorkspace
The main runtime state for a design.

Contains:
- instances
- nets
- `port_to_net` mapping

### Net types
Every net has a real type:
- `WIRE`
- `INPUT`
- `OUTPUT`

This means top-level IO is now a net property, not a side flag.

### PortRef
Ports are addressed explicitly as:
- `(instance_name, port_name)`

Top-level pseudo endpoints are also supported internally so that:
- top input -> instance input
- instance output -> top output

can be expressed explicitly.

## Main features

### 1. Manual-first workspace initialization
On import / instance refresh:
- no automatic connection
- no automatic top-level IO promotion
- every instance port starts on its own singleton `WIRE` net
- default net names use `{instance}_{port}`

### 2. Three-column workspace editor
The main workspace UI is organized as:

- **Left**
  - instance inputs
  - top outputs
- **Center**
  - `Connect`
  - `Disconnect`
  - `Auto IO`
  - `Auto Connect`
  - `Rename Net`
- **Right**
  - instance outputs
  - top inputs
- **Inout**
  - shown separately

### 3. Explicit actions

#### Connect
Allowed pairs:
- `output -> input`
- `top input -> instance input`
- `instance output -> top output`

Behavior:
- merges two nets into one
- default merged net name is derived from endpoints
- width mismatch is allowed
- resulting net width uses the larger width
- width mismatch warning is attached

#### Disconnect
Behavior:
- disconnects only the selected pair
- if the net has only 2 ports, both return to singleton nets
- if the net has more ports, only the selected receiver side is detached
- top-level pseudo endpoint disconnect keeps the top IO net and detaches the instance port back to a `WIRE` net

#### Auto IO
Behavior:
- on instance input: net becomes `INPUT`
- on instance output: net becomes `OUTPUT`
- corresponding top IO appears on the opposite side of the workspace

#### Auto Connect
Behavior:
- explicit command only
- does not run on import
- only connects same-name, same-width ports
- parameterized widths only connect when expressions match exactly
- does not connect `inout`
- does not promote top IO

### 4. Workspace-driven Verilog generation
Generation rules:
- `WIRE` nets -> internal wires
- `INPUT` / `OUTPUT` nets -> top ports
- singleton wires stay wires
- no leftover-port auto-promotion

### 5. Workspace-driven schematic canvas
The schematic canvas now:
- displays workspace projections
- routes wires from workspace state
- performs connect/disconnect through workspace actions
- is no longer driven by the debug table

## Project structure

```text
TopStitcher/
├── main.py
├── requirements.txt
├── README.md
├── topstitcher/
│   ├── __init__.py
│   ├── core/
│   │   ├── data_model.py
│   │   ├── rtl_parser.py
│   │   ├── connection_engine.py
│   │   └── verilog_generator.py
│   └── gui/
│       ├── main_window.py
│       ├── module_tree.py
│       ├── connection_view.py
│       ├── schematic_canvas.py
│       └── code_preview_dialog.py
└── tests/
    ├── test_rtl_parser.py
    ├── test_connection_engine.py
    ├── test_verilog_generator.py
    └── test_gui_smoke.py
```

## Dependencies

From `requirements.txt`:

- `pyverilog>=1.3.0`
- `PyQt6>=6.5.0`

For tests:
- `pytest`

## Recommended Python environment
A verified example Python interpreter path:

```bash
<path-to-your-python>/python.exe
```

This environment format successfully ran the GUI smoke test.

## Installation

### Option A: pip

```bash
pip install -r requirements.txt
pip install pytest
```

### Option B: use a conda environment

```bash
<path-to-your-python>/python.exe -m pip install -r requirements.txt
<path-to-your-python>/python.exe -m pip install pytest
```

## Run the application

### Default

```bash
python main.py
```

### With a specified environment

```bash
<path-to-your-python>/python.exe main.py
```

## Run tests

### Core + generator + GUI smoke

```bash
<path-to-your-python>/python.exe -m pytest tests/test_connection_engine.py tests/test_verilog_generator.py tests/test_gui_smoke.py -v
```

### Full suite

```bash
<path-to-your-python>/python.exe -m pytest tests -v
```

## How to use the project now

### Step 1: start the app

Run:

```bash
<path-to-your-python>/python.exe main.py
```

### Step 2: import Verilog files

Use:
- `File -> Import Verilog Files...`
- or `Ctrl+O`

TopStitcher will:
- parse all selected modules
- populate the module library
- auto-create one instance per imported module
- initialize a manual-first workspace

It will **not** auto-connect ports and **not** auto-promote ports to top-level IO.

### Step 3: inspect the workspace

In the **Workspace** tab:
- left side shows instance inputs and top outputs
- right side shows instance outputs and top inputs
- `Inout` is shown separately

### Step 4: build the design explicitly

Use the center actions:

#### Connect
- select one endpoint on the left
- select one endpoint on the right
- click `Connect`

#### Disconnect
- select the currently connected pair
- click `Disconnect`

#### Auto IO
- select one instance input or output
- click `Auto IO`
- this changes the underlying net type to `INPUT` or `OUTPUT`

#### Auto Connect
- click `Auto Connect`
- this only connects same-name, same-width ports

#### Rename Net
- select any endpoint
- type the new net name in the center panel
- click `Rename Selected Net`

### Step 5: review debug / visual projections if needed

Optional tabs:
- **Netlist Table (Debug)**: flattened workspace projection
- **Schematic Canvas**: visual view and wiring interaction
- **Instance Parameters**: per-instance parameter editing

### Step 6: generate Verilog

Use:
- `Generate -> Generate Top Module`
- or `Ctrl+G`

This opens a preview dialog where you can:
- inspect generated Verilog
- copy to clipboard
- save to file

## Current UI workflow summary

- bottom shortcut buttons are still present for convenience
- the primary interaction model is the **center action panel** in the Workspace tab

## Notes on project conventions

### Versioning
There was no formal packaging metadata in the repo (`pyproject.toml`, `setup.py`, `setup.cfg` are absent), so the safest cleanup was to add a single source version constant:

- `topstitcher/__init__.py`
  - `__version__ = "3.0.0"`

### Naming / product semantics
The codebase previously had mixed legacy labels like `V2`, `V5`, `automatic generator`, and older RuleA/RuleB language.

This cleanup aligns the visible product description with the current behavior:
- manual-first workspace
- explicit actions
- workspace-driven generation

There may still be some historical names in comments or old test descriptions, but the user-facing workflow is now aligned.

## Known limitations

- the canvas still visualizes instance nodes only; top-level pseudo endpoints are represented in the workspace UI and core model, not as separate canvas nodes
- the debug table still exists as a projection view for inspection/debugging
- packaging metadata is still not set up as an installable package release system

## License

See `LICENSE`.
