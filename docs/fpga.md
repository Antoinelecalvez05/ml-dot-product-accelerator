# Synthesis and Basys 3 demonstration

## What the resource comparison measures

Run from the project directory:

```sh
python3 scripts/synthesize.py
```

The script synthesizes both cores for the Xilinx 7-series architecture twice:
normal DSP mapping, then `-nodsp` mapping. It retains the command files, complete
Yosys logs, per-design statistics and `summary.json`, `summary.csv`, `summary.md`
under `reports/synthesis/`. Mapped JSON and Verilog netlists are under
`build/synthesis/`; the Verilog exports preserve the public top-module ports.
`--mode dsp` or `--mode lut` runs just one mapping; `--yosys PATH` chooses a tool.
Each summary row identifies its mapped Verilog and the local Yosys Xilinx
`cells_sim.v` model for a gate-level functional simulation. `--sim-lib PATH`
overrides the recorded model path if automatic detection cannot locate it.

The identical settings include the core's vector input buffers and controller,
but exclude external I/O buffers and clock buffers. Counts come from the actual
flattened netlist. A source SHA-256 and the exact Yosys version accompany them.
These are **mapped primitive counts before placement and routing**. DSPs,
flip-flops and LUTs are different resources and cannot be added into one silicon
area measure. The reported `logic_lut` count excludes distributed-memory
primitives; `distributed_ram_cells` and the full per-type breakdown disclose
those separately. Fabric FF counts exclude registers internal to DSP and RAM
primitives. Different synthesis versions can make different packing decisions.

The Yosys report does not establish maximum frequency, timing closure, physical
area in mm², power or energy per result. In particular, four multipliers do not
establish either four times the chip area or lower energy.

Official command documentation: [Yosys Xilinx synthesis](https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/index_techlibs_xilinx.html).

## Board behavior

`fpga/basys3_demo.v` connects both cores to one deterministic source. It emits:

\[
a_i=i-8,\quad b_i=i+1,\quad i=0,\ldots,15,
\qquad \sum_i a_i b_i=272=\texttt{0x110}.
\]

The wrapper tracks each engine's acceptance independently, so one consumer
cannot cause the other to accept a duplicated pair. Each result is captured
independently because the parallel result arrives first. The output consumers
are always ready. Buttons pass through two synchronizer flip-flops and a filter
requiring 1,000,000 stable samples (10 ms at the target clock).

After configuring the board:

1. Press the centre button, **btnC**, to start.
2. LEDs show the result and remain lit until another run or reset.
3. Hold **btnU** for at least 10 ms to reset; it also abandons an in-flight run.
4. Release and press **btnC** again to repeat. Holding it does not repeat runs.

| Output | Meaning |
|---|---|
| LED 0 | Sequential result captured |
| LED 1 | Parallel result captured |
| LED 2 | Both captured results match |
| LED 3 | A captured result differs from 272; should stay off |
| LEDs 15:4 | Low 12 bits of the sequential result (`0x110`) |

A successful completed run produces the full LED word **`0x1107`**. The
difference in completion time is too short to distinguish by eye. Use the
simulation cycle reports to compare it. The four-cycle initialized power-on
reset in this wrapper is FPGA-specific; the accelerator cores use explicit
synchronous reset and have no such initialization dependency.

This demo uses fixed built-in inputs. Sending arbitrary samples from a computer
would require an additional interface, such as UART; that is not part of this
board wrapper.

## Check the wrapper in simulation

```sh
python3 fpga/smoke.py
```

This uses Icarus Verilog and reduces the debounce interval for simulation. It
checks initialization, rejected button bounce, the parallel result arriving
first, both numerical results, output LED mapping, no retrigger from a held
button, reset and a new run. Its recorded output is `reports/board_smoke.log`.
This checks digital behavior; it cannot simulate analog metastability or
physical switches.

## Build a Basys 3 bitstream with Vivado

The supplied target is **`xc7a35tcpg236-1`**, with a **10 ns clock constraint**.
The relevant pins are a subset of [Digilent's official Basys 3 master
XDC](https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc):
W5 for the clock, U18 for btnC and T18 for btnU, plus the 16 LED pins. All top
ports have explicit LVCMOS33 I/O constraints. Button paths to the first
synchronizer stage are asynchronous; the paths between synchronizer stages
remain timed. The supplied Tcl script resolves the two first-stage D pins after
synthesis and stops if it cannot find exactly two. If importing the RTL/XDC into
your own Vivado project, also reproduce that post-synthesis button exception;
the XDC alone does not contain it. LEDs have no external synchronous timing
requirement. The constraint flow follows [AMD's non-project constraint
guidance](https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/Synthesis-and-Implementation-Constraint-Files).

On a machine with Vivado available:

```sh
vivado -mode batch -source fpga/build_vivado.tcl
```

The Tcl flow runs synthesis, optimization, placement and routing. It writes
utilization, timing, routing, DRC and timing-exception reports to `build/vivado/`. It checks routed
setup/hold slack before writing `basys3_demo.bit`. **100 MHz is a requested
constraint until a real routed timing report passes.** This script creates a
bitstream but does not connect to or program hardware. Load the resulting
bitstream through your existing Basys 3 programming workflow or Vivado Hardware
Manager after inspecting the reports. A bitstream does not by itself program
the board's nonvolatile configuration flash.

The supplied build flow has not been executed in Vivado or tested on a physical
Basys 3 as part of this project delivery. The runnable RTL and recorded Icarus
smoke test are separate evidence from those still-to-be-performed steps.

The wrapper is intentionally a small demonstration; resource comparisons use
the cores on general streamed inputs, so the constant demo vectors cannot be
optimized into a misleading accelerator benchmark.
