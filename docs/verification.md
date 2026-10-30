# Verification: what the tests establish

The golden model is the mathematical operation itself:

```python
sum(x * y for x, y in zip(a, b))
```

Python uses unbounded integers here. The reference model does not imitate lane
accumulators, memory addressing, or the controller. That independence matters:
copying the RTL algorithm into the checker could reproduce the same bug twice.
It also rejects out-of-range input values instead of silently truncating them.

## Run and reproduce

```sh
make test
python scripts/run_tests.py --seed 20261029
python scripts/run_tests.py --quick --configuration parallel
make waves
```

The default seed is recorded in `reports/verification.json`. The full run uses
512 random input vectors for each default architecture and a smaller randomized
run for each additional parameter configuration. `--quick` reduces the number
of random vectors; it is identified as a quick run in the report.

The runner compiles the actual Verilog with Icarus and runs four cocotb test
functions per configuration. It explicitly parses JUnit results and checks that
all four evidence fragments exist. Compilation errors, missing/skipped tests,
unexpected results, timeouts and assertion failures produce a nonzero exit.
Old per-run evidence is removed before executing a configuration.

## Test plan

| Test group | Stimulus | Property checked |
|---|---|---|
| Directed arithmetic | Zero, ones, negative ones, maximum positive inputs, minimum inputs, mixed signs | Signed arithmetic and exact results |
| Positive full-scale sum | Every pair is `(-128, -128)` for the default width | Result is 262,144 without positive overflow |
| Negative full-scale sum | Every pair is `(-128, 127)`, also with operands swapped | Result is -260,096 with correct sign extension |
| Impulse at every position | Only one element of one vector is nonzero | Indexing, every lane and every memory position |
| Random vectors | Reproducibly sampled signed integers | General arithmetic against the independent model |
| Input pauses | Invalid cycles between accepted pairs, including a long pause mid-frame | No skipped/duplicated pairs or premature result |
| Output backpressure | Receiver delays acceptance, including a long held result | `out_valid` and `result` stay stable |
| Continuous source | Sender offers the next vector while the core is busy | Sender holds its pair, core accepts it exactly once when ready |
| Consecutive frames | Multiple complete transactions without reset | Proper clearing of previous accumulations and transaction ordering |
| Reset during load | Partial frame and would-be final input edge | Partial frame is discarded |
| Reset during compute | Middle and last MAC edge | Aborted calculation never leaks a result |
| Reset during reduction | Edge that would register the output | Reset takes priority |
| Reset with pending result | Output ready low and high | Pending result is discarded, not transferred |
| Held reset | Valid and ready presented while reset remains asserted | No transfer during reset, clean recovery |
| Cycle benchmarks | Four consecutive copies of a known vector | Measured latency and initiation interval match the stated architecture |

The parameter sweep tests the default wrappers plus shorter vectors, narrower
inputs, two lanes, a non-power-of-two vector length, a three-lane reduction tree,
and the legal minimum input width. The exact configurations and their outcomes
are listed in the saved JSON, rather than inferred from the documentation.

## How the monitor works

The testbench changes inputs while the clock is low, waits half a cycle, samples
the pre-edge ready/valid values, then generates the rising edge. After another
half cycle it observes the settled outputs. A single `tick()` method performs
this process for every simulated clock, including idle and reset clocks.

This separates two events that are easy to confuse:

- A pair or result transfers using the values present **before** the rising edge.
- A registered result may become visible **after** that edge, and can transfer on
  the next eligible rising edge.

The scoreboard stores expected results only after a complete set of accepted
input pairs. It checks every valid output, including outputs held under
backpressure, and detects an unexpected or duplicate result even when the
receiver is not ready. Drivers use bounded waiting loops so a stuck controller
fails instead of hanging forever. Invalid-cycle input data is deliberately
changed to expose accidental capture when `in_valid` is low.

On reset, the scoreboard discards pending work, just like the specified
interface. It then sends a fresh vector and checks recovery. The test never
reads internal FSM state to decide whether the arithmetic result is correct.

## Reading the cycle measurements

`reports/benchmark.json` records actual edge numbers for each transaction:

| Field | Definition |
|---|---|
| `first_input_edge` | Rising edge that accepted the first pair |
| `last_input_edge` | Rising edge that accepted the last pair |
| `result_visible_edge` | Edge after which registered output valid first appears |
| `result_transfer_edge` | Edge that accepts the result using pre-edge valid and ready |
| `compute_to_valid_cycles` | Visible edge minus last input edge; includes reduction |
| `first_to_valid_cycles_inclusive` | Visible edge minus first input edge plus one |
| `first_to_transfer_cycles_inclusive` | Transfer edge minus first input edge plus one |
| `repeat_frame_interval_cycles` | Difference between first-input edges of consecutive frames |

For the default no-stall benchmark, the frame interval is 34 or 22 clocks. If
you measure elapsed time from the instant of the first input edge to the instant
of the result-transfer edge, there are 33 or 21 clock periods between those
edges. Both numbers are correct for their stated definitions. Prefer the
initiation interval when discussing sustained results per second.

The deterministic stalled benchmark adds one idle input clock between each
pair, for 15 extra clocks, and six output-stall clocks. Its initiation intervals
are therefore 55 and 43 clocks. Arbitrary external stalls have no finite worst
case unless the surrounding system promises eventual progress.

## Synthesized circuit checks

After `make synth`, run:

```sh
make netlist-test
```

This reuses the Python checker against the four generated mapped netlists
(one/four lanes, DSP-enabled/LUT-only), with Yosys's Xilinx primitive simulation
models. It uses shorter random runs and retains its own separate report and
logs in `reports/netlist_verification.json` and `reports/netlist_logs/`.
The model path can be supplied with `--cells-sim` if automatic discovery is not
available in your Yosys installation.

These are functional gate-level checks: no placement/routing delays or timing
annotation are included. They provide evidence that signed arithmetic and
control behavior survived the tested synthesis mapping. They do not constitute
formal equivalence or a timing proof.

## Board wrapper check

`make board-test` runs a Verilog smoke test for the Basys 3 wrapper using a short
debounce interval. It checks power-on reset, button filtering, no repeated start
while held, the order of completion, matching results, LED bits, and reset/restart.
Digital simulation does not reproduce analog switch bounce or metastability;
the hardware wrapper includes input synchronizers and a debounce counter.

## Evidence and scope

`reports/results.md` is the readable overview. `verification.json` records test
counts, configuration outcomes, observed protocol-event counts and source hashes.
The event counts are scenario coverage, not a line/branch coverage percentage.
The `rtl_logs/` and `netlist_logs/` folders retain simulator logs and JUnit files
from the delivered runs. The synthesis folder retains commands, raw output and
complete primitive counts.

The delivered evidence covers functional RTL simulation, functional mapped
simulation, mapped resource counts and a digital board-wrapper simulation.
Vivado place/route, static timing closure, an actual loaded Basys 3, measured
power and an ML classification experiment are separate future measurements.

The verification organization follows the ideas in the official
[cocotb matrix example](https://docs.cocotb.org/en/stable/matrix_multiplier.html):
a pure Python reference and randomized data. The specific protocol, checker and
test cases here are written for this project.
