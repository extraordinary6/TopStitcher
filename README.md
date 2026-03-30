# TopStitcher

A graphical RTL integration assistant tool for IC designers, built with Python and PyQt6. TopStitcher automates the generation of top-level Verilog modules by parsing sub-module `.v` files, intelligently resolving inter-module connections, and outputting synthesizable, professionally formatted Verilog code.

## Features

### Smart Auto-Connection Engine
- **Direction-Aware Rule A**: Automatically connects same-name ports across instances when direction compatibility is verified (output drives input). Detects and flags multi-output conflicts.
- **Width Mismatch Tolerance**: Ports with matching names but different widths are still connected (using the larger width), with a visible `Width Mismatch` warning.
- **Suggested Connections**: After rule-based matching, the engine scans remaining ports and suggests output-to-input links when there is exactly one unambiguous candidate.
- **Rule B Fallback**: Unmatched ports are promoted to top-level I/O with automatic name deduplication.

### Global Signal Management
Configurable global signal list (default: `clk`, `rst_n`, etc.) ensures clock and reset signals are always promoted to top-level inputs, never buried as internal wires.

### Multiple Instantiation
The same parsed module can be instantiated multiple times with unique instance names. The Module Library and Active Instances are fully decoupled.

### Parameter Support
- Parses `parameter` declarations from both ANSI-style `#(...)` and old-style module bodies.
- Supports complex default value expressions (`$clog2(N)`, `A + 1`, etc.).
- Generates `#(.PARAM(value), ...)` blocks in instantiation code.
- Editable parameter values per instance via the GUI.

### Manual Override Table
An interactive `QTableWidget` serves as the core connection matrix:
- Columns: Instance Name, Port Name, Direction, Width, **Assigned Net** (editable), Status.
- Users can manually edit any net name. Ports sharing the same net string are automatically tied via a `wire`.
- **Promote / Demote** controls to force specific ports as top-level I/O (reversible).

### Diagnostics & Visual Feedback
The Status column provides color-coded indicators:

| Status | Color | Meaning |
|---|---|---|
| Global | Blue | Clock/reset promoted to top-level input |
| Promoted | Orange | User-forced top-level port |
| Suggested | Green | Engine-suggested output-to-input connection |
| Width Mismatch | Yellow | Connected despite different bit widths |
| Multi-Driver | Red | Multiple outputs driving the same net |
| Undriven | Amber | Net has only inputs, no driver |
| Conflict | Red | All-output name collision, not auto-connected |

### Professional Code Generation
- ANSI-style module declaration with vertically aligned ports.
- Aligned `.port_name(net_name)` formatting in instantiation blocks.
- Aligned parameter blocks `#(.PARAM(value))`.
- `timescale` directive and header comments.
- Round-trip verified: generated code is parseable by PyVerilog.

## Project Structure

```
TopStitcher/
├── main.py                              # Application entry point
├── requirements.txt                     # pyverilog, PyQt6
├── topstitcher/
│   ├── core/
│   │   ├── data_model.py               # Dataclasses: PortInfo, ModuleInfo, InstanceInfo, etc.
│   │   ├── rtl_parser.py               # PyVerilog-based parser (ANSI + old-style + parameters)
│   │   ├── connection_engine.py         # Smart connection engine with diagnostics
│   │   └── verilog_generator.py         # Aligned Verilog code generator
│   └── gui/
│       ├── main_window.py              # Main window layout and event handling
│       ├── module_tree.py              # Module Library + Active Instances panel
│       ├── connection_view.py          # Interactive connection table + parameter editor
│       └── code_preview_dialog.py      # Code preview with Save/Copy
└── tests/
    ├── test_data/                       # Sample Verilog files (adder, register, param_adder)
    ├── test_rtl_parser.py
    ├── test_connection_engine.py
    └── test_verilog_generator.py
```

## Quick Start

### Install Dependencies

```bash
pip install pyverilog PyQt6
```

### Run

```bash
python main.py
```

### Workflow

1. **File > Import Verilog Files** (Ctrl+O) — select one or more `.v` files.
2. The Module Library tree and Active Instances list are populated automatically.
3. The connection table auto-fills with default assignments (Rule A/B + suggestions).
4. Review the **Status** column for warnings. Edit **Assigned Net** values as needed.
5. Adjust **Instance Parameters** in the second tab if needed.
6. Click **Generate Top Module** (Ctrl+G) to preview the output.
7. **Save As** or **Copy to Clipboard** from the preview dialog.

### Run Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## GUI Controls

| Control | Description |
|---|---|
| Top Module Name | Editable name for the generated module |
| Global Signals | Comma-separated list of signals to promote as top-level inputs |
| Add Instance | Instantiate a selected library module with a custom name |
| Remove Instance | Remove an instance from the active design |
| Promote Selected to Top (Ctrl+P) | Force selected ports as top-level I/O |
| Demote Selected (Ctrl+D) | Revert promoted ports back to auto-connection |
| Re-run Auto-Connect (Ctrl+R) | Recompute all assignments (preserves parameter edits) |
| Generate Top Module (Ctrl+G) | Generate and preview Verilog output |

## Example Output

```verilog
`timescale 1ns / 1ps

module chip_top (
    input        clk,
    input  [7:0] a,
    input  [7:0] b,
    input        rst_n,
    output [7:0] q
);

// Internal wires
wire [7:0] sum_to_d;

// adder instance
adder #(
    .WIDTH(8)
) u_adder (
    .clk  (clk      ),
    .rst_n(rst_n     ),
    .a    (a         ),
    .b    (b         ),
    .sum  (sum_to_d  )
);

// register instance
register u_register (
    .clk  (clk      ),
    .rst_n(rst_n     ),
    .d    (sum_to_d  ),
    .q    (q         )
);

endmodule
```

## License

See [LICENSE](LICENSE) for details.
