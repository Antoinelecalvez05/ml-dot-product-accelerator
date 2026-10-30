#!/usr/bin/env python3
"""Build a readable comparison from measured JSON; reject stale source evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def read_json(path):
    if not path.is_file():
        raise SystemExit(f"Missing {path.relative_to(ROOT)}; run the corresponding test/synthesis command first.")
    return json.loads(path.read_text())


def check_hashes(hashes):
    for relative, expected in hashes.items():
        source = ROOT / relative
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Stale measurement for {relative}; rerun verification/synthesis before making a report.")


def plot(benchmarks):
    cache = ROOT / "build" / "matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("For charts: python -m pip install -r requirements-report.txt") from exc
    entries = [benchmarks[name]["no_stall"] for name in ("serial", "parallel")]
    fig, ax = plt.subplots(figsize=(10.8, 4.6), dpi=180)
    fig.patch.set_facecolor("#f7f9fc")
    ax.set_facecolor("#f7f9fc")
    positions = [1, 0]
    left = [0, 0]
    stages = [
        ("Input pairs", [r["load_cycles_inclusive"] for r in entries], "#4361a8"),
        ("MAC computation", [r["compute_to_valid_cycles"] - 1 for r in entries], "#188772"),
        ("Reduction", [1, 1], "#e0a144"),
        ("Result acceptance", [1, 1], "#6d7390"),
    ]
    for label, values, color in stages:
        ax.barh(positions, values, left=left, height=0.5, color=color, label=label)
        for pos, start, value in zip(positions, left, values):
            if value >= 4:
                ax.text(start + value / 2, pos, str(value), ha="center", va="center",
                        color="white", fontsize=13, weight="bold")
        left = [a + b for a, b in zip(left, values)]
    for pos, total in zip(positions, left):
        ax.text(total + 0.45, pos, f"{total} clocks", va="center", fontsize=12,
                color="#17263c", weight="bold")
    ax.set_yticks(positions, ["Sequential · 1 lane", "Parallel · 4 lanes"], fontsize=11)
    ax.set_xlim(0, max(left) + 5)
    ax.set_ylim(-0.65, 1.65)
    ax.set_xticks(range(0, max(left) + 1, 4))
    ax.set_xlabel("Clocks per frame, including result acceptance", labelpad=10, color="#344054")
    ax.grid(axis="x", alpha=0.14)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0, colors="#344054")
    fig.suptitle("Four lanes speed up arithmetic; loading still takes 16 clocks",
                 x=0.035, y=0.97, ha="left", fontsize=16, weight="bold", color="#17263c")
    ratio = left[0] / left[1]
    fig.text(0.035, 0.89, f"Measured no-stall frame interval: {left[0]} → {left[1]} clocks  |  {ratio:.2f}× frame-rate gain at equal clock frequency",
             color="#526077", fontsize=10.5)
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.32), ncol=4,
              frameon=False, fontsize=9)
    fig.text(0.035, 0.02, "Source: reports/benchmark.json. Functional simulation; achievable FPGA clock frequency is unmeasured.",
             color="#526077", fontsize=9)
    fig.subplots_adjust(left=0.19, right=0.975, top=0.79, bottom=0.30)
    fig.savefig(REPORTS / "latency_breakdown.png", facecolor=fig.get_facecolor())
    fig.savefig(REPORTS / "latency_breakdown.svg", facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot", action="store_true", help="Also generate PNG/SVG chart; needs requirements-report.txt")
    args = parser.parse_args()
    verification = read_json(REPORTS / "verification.json")
    benchmark = read_json(REPORTS / "benchmark.json")
    synthesis = read_json(REPORTS / "synthesis" / "summary.json")
    if verification["status"] != "passed" or benchmark["status"] != "passed":
        raise SystemExit("Current functional evidence does not pass; fix failures first.")
    if synthesis.get("status") != "passed":
        raise SystemExit("Current synthesis did not complete; run make synth successfully first.")
    check_hashes(verification["source_sha256"])
    check_hashes(synthesis["rtl_sha256"])
    if synthesis.get("synthesis_script_sha256"):
        check_hashes({"scripts/synthesize.py": synthesis["synthesis_script_sha256"]})
    measured = benchmark["architectures"]
    defaults = {r["name"]: r for r in verification["configurations"]
                if r["name"] in ("serial", "parallel") and r["status"] == "passed"}
    if len(defaults) != 2 or benchmark["seed"] != verification["seed"]:
        raise SystemExit("Benchmark and verification evidence do not cover the same defaults; rerun make test.")
    for name, record in defaults.items():
        scenarios = next(r for r in record["test_reports"] if r["test"] == "measured_cycle_benchmarks")["scenarios"]
        for scenario, values in scenarios.items():
            if measured[name][scenario] != values:
                raise SystemExit("Benchmark data differs from the verified transactions; rerun make test.")
    serial, parallel = (measured[x]["no_stall"] for x in ("serial", "parallel"))
    stalled_s, stalled_p = (measured[x]["deterministic_stalls"] for x in ("serial", "parallel"))
    rate = serial["repeat_frame_interval_cycles"] / parallel["repeat_frame_interval_cycles"]
    rows = [
        ("MAC lanes", 1, 4),
        ("Accepted input clocks", serial["load_cycles_inclusive"], parallel["load_cycles_inclusive"]),
        ("MAC clocks", serial["compute_to_valid_cycles"] - 1, parallel["compute_to_valid_cycles"] - 1),
        ("Reduction/output-register clocks", 1, 1),
        ("First input through result visible, inclusive edges", serial["first_to_valid_cycles_inclusive"], parallel["first_to_valid_cycles_inclusive"]),
        ("First input through result accepted, inclusive edges", serial["first_to_transfer_cycles_inclusive"], parallel["first_to_transfer_cycles_inclusive"]),
        ("No-stall frame initiation interval", serial["repeat_frame_interval_cycles"], parallel["repeat_frame_interval_cycles"]),
        ("Frame interval with 15 input gaps and 6 output stalls", stalled_s["repeat_frame_interval_cycles"], stalled_p["repeat_frame_interval_cycles"]),
    ]
    tools = verification["tools"]
    lines = [
        "# Measured project results", "",
        "The four-lane design completes the MAC loop in four clocks instead of sixteen. "
        f"With the shared input protocol, the measured no-stall frame interval improves from **{serial['repeat_frame_interval_cycles']} to {parallel['repeat_frame_interval_cycles']} clocks**, "
        f"a **{rate:.3f}× frame-rate improvement at equal clock frequency**.", "",
        f"RTL verification: **{verification['simulation_tests']} simulation tests passed** across "
        f"**{len(verification['configurations'])} configurations**, with **{verification['checked_outputs']:,} checked results** "
        f"and **{verification['python_reference_tests']} Python reference tests**. "
        f"Random seed: `{verification['seed']}`. Quick mode: `{verification['quick']}`.", "",
        f"Recorded tools: Python {tools['python']}, cocotb {tools['cocotb']}, {tools['iverilog']}; {synthesis['yosys_version']}.",
        "", "## Cycle measurements", "",
        "| Measurement | Sequential | Four lanes |", "|---|---:|---:|",
        *[f"| {label} | {a} | {b} |" for label, a, b in rows], "",
        "A frame contains sixteen accepted pairs. The first input edge and the result-acceptance edge "
        "both count in the inclusive-edge total. The frame initiation interval measures the spacing "
        "between first-input edges of consecutive frames. Elapsed first-input-to-result-acceptance "
        "time instead spans 33/21 periods, since it excludes the starting edge. "
        "See `benchmark.json` for the raw edge numbers and four repetitions per scenario.", "",
        "There are 16 input clocks, N/LANES MAC clocks, one reduction clock and one result-acceptance clock. "
        "More lanes do not shorten the input phase. Input pauses and output backpressure add directly "
        "to the frame interval in this non-overlapped architecture.", "",
        "## Mapped hardware resources", "",
        "Core-only mapping to Xilinx 7-series primitives, before placement and routing. "
        "The input buffers and controller are included; board IO and clock buffers are excluded.", "",
        "| Architecture | Mapping | DSP48 blocks | Logic LUT primitives | Fabric FF | RAM32M primitives |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in synthesis["results"]:
        lines.append(f"| {row['design']} | {row['mapping']} | {row['dsp48']} | {row['logic_lut']} | "
                     f"{row['fabric_ff']} | {row['cell_counts'].get('RAM32M', 0)} |")
    lines += ["", "Logic LUT counts exclude distributed-memory primitives. RAM32M consumes LUT resources "
              "and is therefore shown alongside the logic counts. Fabric FF excludes registers inside "
              "DSP/RAM primitives. These different resources cannot be added into one meaningful area number.", "",
              "The parallel mapping uses extra arithmetic, reduction and memory-access resources. "
              "The input arrays support more simultaneous reads; the mapped result demonstrates that "
              "parallelism can affect storage/access hardware as well as multipliers. Explicit memory "
              "banking is a useful next optimization experiment.", "",
              "Raw executed commands, tool output, complete cell counts and RTL hashes are retained "
              "in `synthesis/`. Resource totals may change with synthesis version and mapping choices.", ""]
    gate_file = REPORTS / "netlist_verification.json"
    if gate_file.exists():
        gate = read_json(gate_file)
        if gate["status"] != "passed":
            raise SystemExit("Mapped verification did not pass; rerun make netlist-test.")
        check_hashes(gate["rtl_sha256"])
        check_hashes(gate["verification_source_sha256"])
        current_synthesis_hash = hashlib.sha256((REPORTS / "synthesis" / "summary.json").read_bytes()).hexdigest()
        if gate["synthesis_summary_sha256"] != current_synthesis_hash:
            raise SystemExit("Synthesis report changed after mapped verification; rerun make netlist-test.")
        lines += ["## Synthesized circuit verification", "",
                  f"**{gate['simulation_tests']} mapped-netlist tests passed**, checking "
                  f"**{gate['checked_outputs']:,} results** across four DSP-enabled/LUT-only implementations. "
                  "Separate evidence is included in `netlist_verification.json`, with per-run logs in `netlist_logs/`. "
                  "It checks the synthesized circuits using functional Xilinx primitive models. "
                  "No routed delays or timing annotation are present.", ""]
    lines += ["## Basys 3 integration", "",
              "The separate board-wrapper simulation passes the documented known-vector/button/reset "
              "checks; see `board_smoke.log`. Both engines return 272, and completed LEDs read `0x1107`. "
              "Physical board execution and Vivado place/route have not been performed for this snapshot.", "",
              "## What the measurements support", "",
              "The evidence supports functional correctness for the exercised scenarios, the measured "
              "cycle counts, and the listed mapped resource counts. It does not establish maximum clock "
              "frequency, physical area, measured energy/power savings, or classifier accuracy. "
              "The simulation clock is 10 ns; successful simulation at that period is not timing closure. "
              "The 100 MHz board constraint remains a target until routing and timing checks pass.", "",
              "## Evidence files", "",
              "- `verification.json`: configuration outcomes, test scenarios, event counts and source hashes.",
              "- `benchmark.json`: raw transaction edges, latency definitions and repeated measurements.",
              "- `synthesis/summary.json`, `.csv`, `.md`: mapped resource totals and source hashes.",
              "- `synthesis/*_stat.json`, `.ys`, `.log`: detailed statistics, commands and tool logs.",
              "- `rtl_logs/`: simulator compilation, execution and JUnit evidence.",
              "- `netlist_verification.json`, `netlist_logs/`: synthesized circuit checks.",
              "- `board_smoke.log`: board-wrapper functional smoke-test result.", ""]
    if args.plot:
        plot(measured)
    if (REPORTS / "latency_breakdown.png").is_file():
        lines += ["## Cycle breakdown", "", "![Measured cycle breakdown](latency_breakdown.png)", ""]
    (REPORTS / "results.md").write_text("\n".join(lines))
    print("Wrote reports/results.md" + (" and latency_breakdown.{png,svg}" if args.plot else ""))


if __name__ == "__main__":
    main()
