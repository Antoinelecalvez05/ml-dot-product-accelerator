# A small parallel ML arithmetic accelerator in Verilog

A complete, runnable comparison of two signed integer dot-product architectures:
one multiply–accumulate lane reused over time, and four lanes working in parallel.
Both calculate

\[
y = \sum_{i=0}^{15} a_i b_i
\]

from sixteen pairs of signed 8-bit integers, returning a full-precision signed
20-bit result. The design is useful as a small building block for a quantized
neural-network layer. The project includes RTL, a Python reference model,
self-checking cocotb tests, measured cycle counts, mapped synthesis resource
counts, a Basys 3 demonstration, and an explanation of the architectural choices.

**Start here:** run the tests, read [the results](reports/results.md), then follow
the [architecture guide](docs/architecture.md). The [learning guide](docs/learning-guide.md)
explains what each file does and suggests changes you can make yourself.

## What is implemented

| Feature | Implementation |
|---|---|
| Sequential architecture | `rtl/dot_product_serial.v`, one MAC lane |
| Parallel architecture | `rtl/dot_product_parallel.v`, four MAC lanes |
| Shared architecture | `rtl/dot_product_core.v`, configurable vector length, input width and lanes |
| Numeric format | Signed two's-complement integers; default 8-bit input, 20-bit result |
| Input control | One pair per accepted ready/valid handshake; exactly 16 pairs per frame |
| Output control | Stable valid result until the receiver accepts it |
| Reset | Synchronous active-high reset; discards incomplete or unconsumed work |
| Verification | Independent Python sum-of-products model, directed and randomized tests |
| Synthesis | Actual Yosys `xc7` primitive counts, DSP-enabled and LUT-only mappings |
| FPGA demonstration | Basys 3 example, constraints, simulation smoke test, Vivado build script |

The two wrappers specialize one shared core. Synthesizing each wrapper produces
a distinct circuit: one multiplier versus four. Shared control code keeps the
comparison consistent and makes the differences easier to inspect.

## Run on your Mac

Clone the repository, then open Terminal in the project folder:

```sh
git clone https://github.com/Antoinelecalvez05/ml-dot-product-accelerator.git
cd ml-dot-product-accelerator
```

You can also download and extract the repository ZIP. If Homebrew is already
available:

```sh
brew install icarus-verilog yosys
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
make reference
make test
make synth
make netlist-test
make board-test
make report
```

The Homebrew packages provide `iverilog`/`vvp` and `yosys`. The Python dependency
is pinned to cocotb 2.0.1. The delivered regression was executed with Icarus
Verilog 12.0 and Yosys 0.33; newer synthesis versions can produce different
resource counts. Python 3.10 or later is recommended. The measured environment
is recorded in the reports. The two official Homebrew package pages are listed
under [Sources](#sources).

On Debian/Ubuntu, the equivalent simulator/synthesis installation is:

```sh
sudo apt-get update
sudo apt-get install iverilog yosys python3-venv make
```

Then use the same virtual-environment and `make` commands above, starting with
`python3 -m venv .venv`.

The complete simulation and synthesis flow does not require the FPGA to be
connected. For physical deployment, see [the Basys 3 guide](docs/fpga.md).

## Commands

| Command | Purpose |
|---|---|
| `make reference` | Print the example vectors and expected result, 272 |
| `make test-model` | Check the pure Python reference |
| `make test-quick` | Short RTL regression for use while editing |
| `make test` | Full randomized RTL regression and parameter sweep |
| `make waves` | Short regression with simulator waveform files |
| `make synth` | Synthesize both architectures with and without DSP blocks |
| `make netlist-test` | Check all four synthesized circuits against the Python model |
| `make board-test` | Simulate the Basys 3 demo, buttons and status LEDs |
| `make report` | Regenerate the comparison from the saved measurement JSON |
| `make all` | Run the complete verification, synthesis and report sequence |

`make` alone lists the commands. You can also call each Python script directly.
All generated simulator outputs live under `build/`. Evidence and readable
summaries live under `reports/`.

To regenerate the optional PNG/SVG cycle chart, install
`requirements-report.txt` and run `python scripts/make_report.py --plot`.
The delivered chart is already included; those plotting dependencies are not
needed for simulation, synthesis, or the text report.

## What the comparison means

Both engines receive **one input pair per clock**, so they each need sixteen
accepted input clocks. Arithmetic then takes sixteen MAC clocks for one lane
or four MAC clocks for four lanes. Both use one reduction/output-register clock,
followed by the result-acceptance edge.

With no input pauses and a ready receiver, the designed frame initiation
interval is **34 clocks versus 22 clocks**. The arithmetic loop is four times
faster, while the complete frame rate improves by **34/22, about 1.55×** at the
same clock frequency. The measured report checks these quantities against the
actual simulated handshakes and spells out the counting convention.

This intentionally buffered architecture makes the resource/performance tradeoff
easy to see. A single-lane streaming MAC could accumulate during loading, while
a wider input bus or double buffering could make the parallel datapath more useful.
Those are documented follow-up experiments, not features claimed by this version.

Synthesis reports count FPGA primitives, including DSP48 blocks, logic LUTs,
fabric registers and distributed-memory primitives. They do not measure silicon
area, maximum clock frequency, energy or power. A 10 ns simulation clock and a
10 ns board constraint are targets, not evidence of physical timing closure.

## Interface at a glance

| Signal | Direction | Meaning |
|---|---|---|
| `clk` | Input | Rising-edge clock |
| `rst` | Input | Active-high synchronous reset |
| `in_a`, `in_b` | Input | Signed 8-bit operands for the next pair |
| `in_valid` | Input | The sender is presenting a valid pair |
| `in_ready` | Output | The engine can accept that pair |
| `result` | Output | Signed 20-bit dot product |
| `out_valid` | Output | `result` is valid |
| `out_ready` | Input | The receiver can accept `result` |

A transfer happens only at a rising edge with both valid and ready high. The
sender must hold its valid pair while ready is low. The engine holds an
unconsumed result. All ports share the same clock domain. There is no frame
length field or `last` signal: every group of sixteen accepted pairs is a frame.

## Project map

| Path | What to read or run |
|---|---|
| `rtl/` | Synthesizable core and the two wrappers |
| `model/reference.py` | Independent exact-integer specification |
| `tests/cocotb_dot_product.py` | Drivers, protocol monitor, scoreboard and test scenarios |
| `scripts/run_tests.py` | Simulator build, test execution and measurement collection |
| `scripts/synthesize.py` | Reproducible mapped synthesis comparison |
| `scripts/make_report.py` | Comparison report derived from measured JSON |
| `fpga/` | Board demo, XDC, build Tcl and board-level smoke test |
| `docs/architecture.md` | Datapath, FSM, arithmetic widths, protocol and timing |
| `docs/learning-guide.md` | Guided reading and extension exercises |
| `docs/verification.md` | Test plan, coverage scope and failure interpretation |
| `reports/` | Delivered measurement snapshot, raw logs and machine-readable evidence |
| `.github/workflows/test.yml` | CI workflow to rerun verification when you push code |

## Save and push your changes

After cloning, edit the source and rerun `make test` plus any affected synthesis
or board checks. To record and push your changes:

```sh
git status
git add rtl tests model scripts docs README.md
git commit -m "Describe the change and its purpose"
git push
```

Include other changed project files explicitly when needed. The `.gitignore`
excludes local environments, simulator build files, and waveform files. A clone
already has its `origin` remote configured. Repository collaborators with write
access can push; other contributors can fork the repository and open a pull
request. The GitHub Actions workflow runs verification, synthesis and the
comparison report on pushes and pull requests.

## Next directions

An ML layer can apply one dot product per output neuron, then add a bias and
apply an activation. Possible extensions include stored weights, matrix–vector
control, quantization/rescaling, a host interface, or a neural-signal experiment
using a properly sourced dataset. This project implements the arithmetic kernel;
it does not include model training, a medical classifier, or neural recordings.

## Sources

These primary sources informed the tool setup and board integration. Arithmetic,
protocol details, and benchmark conclusions describe this repository's own code
and measured reports.

- [cocotb example: Python reference model and randomized stimulus](https://docs.cocotb.org/en/stable/matrix_multiplier.html)
- [cocotb 2.0 Python runner](https://docs.cocotb.org/en/v2.0.0/runner.html)
- [cocotb 2.0 simulator support](https://docs.cocotb.org/en/v2.0.0/simulator_support.html)
- [Yosys Xilinx synthesis command reference](https://yosyshq.readthedocs.io/projects/yosys/en/v0.70/cmd/index_techlibs_xilinx.html)
- [Digilent Basys 3 master constraints](https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc)
- [Homebrew Icarus Verilog package](https://formulae.brew.sh/formula/icarus-verilog)
- [Homebrew Yosys package](https://formulae.brew.sh/formula/yosys)

Tool documentation URLs may describe newer versions than the recorded measurement
environment. The exact tool versions and the executed commands are retained in
the delivered reports.
