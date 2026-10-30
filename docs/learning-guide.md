# Learning guide: understand the accelerator before extending it

Start with the result you want: two vectors go in, their dot product comes out, and a four-lane datapath finishes its multiplication stage sooner than a one-lane datapath. The useful engineering question is how much that helps the complete transaction, once data movement and output waiting are included.

You already know the building blocks from an ALU and a finite-state machine. This project joins them into a datapath controlled across many clock edges. You do not need to understand every line before running the example.

## 1. Read the architecture, then calculate one answer

Read [architecture.md](architecture.md), especially the interface contract and clock-edge table. You should be able to answer these questions before changing code:

- What event counts an input pair as accepted?
- Why are there 16 accepted pairs in a frame even if the source pauses?
- What happens to a pending result when `out_ready=0`?
- Why does the four-lane version still need 16 loading clocks?
- What does reset do to a half-loaded vector?

Run the independent model from the project directory:

```bash
make reference
```

The supplied example is `a[i]=i-8` and `b[i]=i+1`, for `i=0..15`. Its answer is **272**. For a smaller example you can check by hand:

```bash
python3 -m model.reference --a=2,-3,4 --b=5,6,-2
```

That computes `2×5 + (-3)×6 + 4×(-2) = -16`. This command exercises the general Python model, which accepts any nonempty pair of equally sized vectors. It does not reconfigure the default 16-element RTL by itself.

Open `model/reference.py`. The central expression is deliberately simple:

```python
sum(x * y for x, y in zip(a, b))
```

The model checks the input range, then uses Python integer arithmetic to obtain the mathematical answer. It does not copy the controller or the lane schedule. That independence matters: a mistake in the RTL's index counter should not be repeated by the reference model.

`encode_signed` and `decode_signed` convert between signed integers and their wire bit patterns. For example, an 8-bit wire pattern of `11111111` represents −1 when treated as signed, although the same bits represent 255 when treated as unsigned.

Run the reference checks:

```bash
make test-model
```

Pay attention to the all-`-128` test: `16 × (-128) × (-128) = 262144`. This is the case that makes a 19-bit signed result insufficient.

## 2. Read the two wrappers before the core

Open `rtl/dot_product_serial.v` and `rtl/dot_product_parallel.v` side by side. Their ports are the same. The significant change is:

```verilog
.LANES(1)   // Serial wrapper
.LANES(4)   // Parallel wrapper
```

The parameter determines how much hardware is created. It does not ask one existing circuit to switch between two operating modes. If you synthesize the serial wrapper, the elaborated core contains one lane. If you synthesize the parallel wrapper, it contains four.

This arrangement keeps the comparison controlled: frame length, widths, external bandwidth, reset behavior, and protocol stay the same. The shared source also means a bug in that core can affect both wrappers. Agreement between the two hardware versions is therefore useful, but an independent Python answer is still needed.

## 3. Follow one frame through the controller

Now open `rtl/dot_product_core.v`. Read the state constants and `assign in_ready` / `assign out_valid` first. Then read the `case (state)` block without studying the datapath yet.

### LOAD: count accepted inputs

The controller writes the buffers only inside:

```verilog
if (in_valid && in_ready) begin
    // Store this pair and advance the accepted-pair index.
end
```

The counter measures accepted transfers, not elapsed time. If `in_valid` stays low for five clocks between input pairs 6 and 7, those five clocks do not create extra vector elements.

The input pair accepted when `write_index == VECTOR_LEN-1` is the final one. At that edge, the design writes the last data values, clears the lane sums, initializes the compute-group counter, and changes state to `COMPUTE`.

### COMPUTE: update all active lane sums

For one lane, the group counter runs through 16 groups of one pair. For four lanes, it runs through four groups of four pairs. A lane's update is:

```verilog
lane_accumulator[k] <= lane_accumulator[k] + extended_product[k];
```

Think of this as a register with an adder feeding its input. Before the clock edge, the register outputs the old partial sum. The multiplier and adder calculate the next partial sum. At the edge, the register captures it.

### REDUCE: capture the complete sum

The last compute edge updates the lane registers. Their new values then propagate through the combinational reduction tree. The following edge captures that completed total in `result`.

### OUTPUT: wait until the result transfers

The engine keeps the result available until the receiver accepts it. It does not silently discard the result after one clock. Holding `out_ready=0` for 20 clocks should produce the same pending result on all 20 clocks.

On the eventual output-transfer edge, state returns to `LOAD`. The next frame can begin on the following edge.

## 4. Settle the `=` versus `<=` question

`always` means “run this procedural block when its event condition occurs.” It does not by itself mean “use `<=`.”

| Hardware being described | Usual Verilog form | Usual assignment |
| --- | --- | --- |
| Clocked registers | `always @(posedge clk)` | Nonblocking `<=` |
| Combinational procedural calculation | `always @(*)` | Blocking `=` |
| Continuous combinational connection | `assign ...` | Continuous assignment syntax |

The core's main `always` block is clocked, so its register updates use `<=`. Consider this small, separate illustration:

```verilog
always @(posedge clk) begin
    a <= b;
    b <= a;
end
```

Both right-hand sides use the old values. After the edge, the registers exchange values. The second line does not read the newly assigned value from the first line.

That same rule explains the reduction stage. Writing these two statements on the final MAC edge would capture a total built from the **old** partial sums:

```verilog
// Illustration of the scheduling mistake, not the implementation:
lane_accumulator[k] <= lane_accumulator[k] + extended_product[k];
result <= reduction_tree[0];
```

The implemented controller waits one more edge before assigning `result`. Another architecture could calculate the final total directly from the accumulator next values, but that would be a different datapath and should be measured separately.

Likewise, this sequence does not run two case branches on the same clock edge:

```verilog
state <= REDUCE;
```

It schedules a register update. The `REDUCE` branch executes when the clocked block runs on the next edge and reads the new state.

## 5. Recognize hardware replication

A software loop often means “do this operation again later.” A bounded elaboration loop in Verilog can mean “create several copies of this circuit.”

In this project, `generate` creates one multiplier and its associated wiring for each lane. The clocked `for` loop describes updates to each lane's register on the same edge. The loop variable is not a little processor executing each MAC instruction in sequence.

Time advances because clocks arrive. The `group_index` register changes which buffered inputs feed the lanes on successive clocks. Lane number answers **which circuit**; group number answers **which compute step**.

As a useful paper exercise, list the four pairs that each lane processes. You should obtain lane 0 indices `0,4,8,12`, lane 1 indices `1,5,9,13`, lane 2 indices `2,6,10,14`, and lane 3 indices `3,7,11,15`. Every index from 0 to 15 should appear once.

## 6. Run verification, then read how it checks the interface

After following the environment setup in the README, run:

```bash
make test-quick
make test
```

Read `tests/cocotb_dot_product.py` together with the runner in `scripts/run_tests.py`. The tests drive a simulator; the Python model supplies expected arithmetic results. The runner chooses the RTL configuration and collects test results.

When reading a ready/valid testbench, always ask which values are sampled before the rising edge and which register changes become visible after it. A test should count a transfer using the handshake values that apply at that edge, not accidentally count a ready signal that only became high because of the edge.

Useful properties to locate in the checks include:

- Negative values and both numerical extremes produce exact signed answers.
- Pausing the source does not insert, drop, or reorder operands.
- A stalled output preserves both validity and its result.
- A next-frame input offered during a busy period is accepted only when ready.
- Reset during loading, computation, or an output wait cancels old work.
- Random frames agree with the independent model.
- Completed frames have the documented cycle counts when no stalls occur.

Random inputs complement directed cases. Random testing alone is unlikely to produce sixteen copies of `-128` in both vectors, so the critical positive extreme should be tested explicitly. Passing a finite test suite establishes evidence for the tested cases; it is not a formal proof for every possible input sequence.

For waveforms:

```bash
make waves
```

Use the generated waveforms to follow `clk`, `rst`, both handshakes, `result`, and the core's state/counters. A particularly useful trace is one short input pause followed by output backpressure. Check accepted pairs at rising edges and watch the result remain unchanged while the receiver waits.

The [official cocotb matrix-multiplier example](https://docs.cocotb.org/en/stable/matrix_multiplier.html) describes the same broad separation between stimulus, monitoring, and a pure Python reference model.

## 7. Read the reports with the correct performance definition

After the tests, open the generated results in `reports/`. Distinguish these questions:

| Question | Evidence to use |
| --- | --- |
| Did the implementation behave as specified? | `reports/verification.json`: test results and checks against the Python model. |
| How many clocks did a transaction take? | `reports/benchmark.json`: measured timings and their counting convention. |
| What hardware did synthesis map? | `reports/synthesis/summary.md` and the corresponding JSON/CSV files: separate resource counts and the synthesis configuration. |
| Did the board demonstration pass its simulation? | `reports/board_smoke.log`: simulation evidence for the wrapper, distinct from physical board validation. |

For the default buffered designs, the MAC stage falls from 16 to 4 clocks. The complete no-stall frame initiation interval falls from 34 to 22 clocks, an improvement of `34/22 ≈ 1.545`. Explain both numbers when discussing the project.

A 100 MHz simulation clock is a chosen stimulus. It does not establish a 100 MHz physical timing result. Similarly, four MAC lanes are an architectural description; check the synthesis report for the actual DSP, LUT, register, and memory mapping. Do not infer measured power savings from fewer simulation clocks or from a lower count of one resource type.

Before claiming an FPGA frequency, the design must be implemented with appropriate constraints and its timing reports checked. Before claiming measured power or energy, obtain a corresponding measurement or explicitly identified estimate with its assumptions.

## 8. What this has to do with machine learning

A linear model or neuron calculation often contains:

\[
y=\mathbf{w}\cdot\mathbf{x}+b.
\]

This project implements the integer dot-product part, `w·x`. You can treat one input vector as integer weights and the other as integer features. A bias addition, activation function, scaling rule, and a way to supply model parameters would be further design steps.

There is no training engine, floating-point arithmetic, complete neural network, or real neural-signal classification experiment in this project. Its connection to ML is the arithmetic kernel and the architectural questions around computing it efficiently.

A future neural-signal experiment could extract features from a suitable dataset, define and validate an integer representation, and compare a small model's hardware output with a software implementation. Dataset provenance, signal processing, model validation, and numerical scaling would all matter in that separate experiment.

## 9. Exercises that lead to meaningful new versions

The changes below are **future work**. Keep the current version as a baseline, implement one idea at a time, and rerun the arithmetic, protocol, reset, and timing checks after changing it.

### A. Measure a two-lane configuration

Instantiate the core with `LANES=2`. Predict the group count, the final-input-to-valid latency, and the complete frame interval before running it. The same controller should need 8 MAC clocks, 1 reduction clock, and a 26-clock no-stall frame initiation interval. Compare measured results and synthesis resources with the one- and four-lane configurations.

### B. Make the sequential engine compute while loading

Use each accepted pair immediately in a streaming MAC instead of first filling the input buffers. Decide how to initialize the first partial sum and include the final product in the output. Keep the same ready/valid and reset guarantees.

This can change the comparison substantially: with only one incoming pair per clock, an optimized streaming sequential engine may match or beat a simple buffered parallel engine. Measure it and explain why. That is a useful architectural result.

### C. Add double buffering

Use two sets of input buffers so the source can load the next frame while the current frame computes. Work out who owns each buffer, when ownership changes, and what happens if an output stalls. Do not overwrite a buffer still being read.

Predict the new steady-state throughput separately from the latency of one isolated frame. Overlap can improve throughput without reducing every frame's individual latency.

### D. Broaden the input interface

Allow four pairs per accepted transfer, giving a 64-bit data payload for 8-bit A and B values. A full vector would then need four accepted input transfers. Define the ordering of values within that payload and update both the driver and scoreboard.

This is a new interface and a different bandwidth assumption. Present its results separately from the existing one-pair-per-clock comparison.

### E. Pipeline the reduction tree

Register intermediate tree sums. The combinational work between registers can decrease, but the controller must wait for extra pipeline stages. Add checks for the new latency and preserve output stability under backpressure.

An extra pipeline stage does not automatically improve complete-frame throughput in a design that processes only one frame at a time. To assess the benefit, consider achievable clock frequency, controller overlap, and resources together.

### F. Add a small matrix–vector operation

Reuse the dot-product engine for several matrix rows. Decide how weights and the feature vector are stored, whether the feature vector must be resent, and how results are ordered. Build a Python reference for the complete operation before writing the controller.

## 10. Explain the project in your own words

You understand the first version when you can sketch the four states, calculate the 20-bit width, trace the four lane sums for the 272 example, and explain why fourfold MAC parallelism produces about a 1.55-fold improvement in this complete-frame comparison.

Then pick one extension and keep a short investigation record: your prediction, the actual change, what the tests checked, what the measurements showed, and what you learned. That turns a working example into an architectural study you can discuss with confidence.
