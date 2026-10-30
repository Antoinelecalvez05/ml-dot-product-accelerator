#!/usr/bin/env python3
"""Compare actual Yosys xc7 mapped resources; never infer area from RTL lines."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def yosys_quote(path: Path) -> str:
    """Quote an absolute filename for a Yosys command file, not for a shell."""
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yosys", default="yosys", help="Yosys executable")
    parser.add_argument("--mode", choices=("all", "dsp", "lut"), default="all")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports" / "synthesis")
    parser.add_argument("--sim-lib", type=Path, help="Optional Yosys xilinx/cells_sim.v path for gate simulation")
    args = parser.parse_args()
    executable = shutil.which(args.yosys)
    if executable is None:
        raise SystemExit(f"Missing {args.yosys}. Install Yosys, then rerun this command.")
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    build = ROOT / "build" / "synthesis"
    build.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl" / name for name in (
        "dot_product_core.v", "dot_product_serial.v", "dot_product_parallel.v")]
    for source in sources:
        if not source.is_file():
            raise SystemExit(f"Missing RTL source: {source}")
    version = subprocess.check_output([executable, "-V"], text=True).strip()
    provenance = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sources}
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    # Invalidate only generated summaries before beginning a new measurement.
    # A failure or interruption must not leave an older passing table looking
    # like the result of this invocation; raw logs remain available for review.
    pending = {"status": "running", "yosys_version": version, "rtl_sha256": provenance,
               "synthesis_script_sha256": script_hash,
               "generated_utc": datetime.now(timezone.utc).isoformat()}
    (out / "summary.json").write_text(json.dumps(pending, indent=2) + "\n")
    for name in ("summary.csv", "summary.md"):
        (out / name).unlink(missing_ok=True)

    def fail(message: str) -> None:
        (out / "summary.json").write_text(json.dumps(
            {**pending, "status": "failed", "error": message}, indent=2) + "\n")
        raise SystemExit(message)

    rows = []
    modes = ("dsp", "lut") if args.mode == "all" else (args.mode,)
    for mode in modes:
        for design, lanes in (("serial", 1), ("parallel", 4)):
            top = "dot_product_" + design
            tag = f"{design}_{mode}"
            netlist = build / f"{tag}.json"
            verilog = build / f"{tag}.v"
            script = out / f"{tag}.ys"
            log = out / f"{tag}.log"
            stats = out / f"{tag}_stat.json"
            commands = [
                "read_verilog -sv " + " ".join(yosys_quote(p) for p in sources),
                f"hierarchy -check -top {top}",
                f"synth_xilinx -top {top} -family xc7 -flatten -noiopad -noclkbuf"
                + (" -nodsp" if mode == "lut" else ""),
                "check -assert",
                # Older Yosys tee does not unquote filenames; run in the
                # report directory and use this controlled, simple basename.
                f"tee -o {stats.name} stat -json -tech xilinx",
                f"write_json {yosys_quote(netlist)}",
                f"write_verilog -noattr {yosys_quote(verilog)}",
            ]
            script.write_text("\n".join(commands) + "\n")
            print(f"Synthesizing {top}, {mode} mapping...", flush=True)
            with log.open("w") as handle:
                completed = subprocess.run(
                    [executable, "-s", str(script)], cwd=out,
                    stdout=handle, stderr=subprocess.STDOUT, text=True,
                )
            if completed.returncode:
                fail(f"Yosys failed for {tag}; inspect {log}")
            mapped = json.loads(netlist.read_text())
            sim_match = re.search(r"Parsing Verilog input from [`']([^`']*/xilinx/cells_sim\.v)", log.read_text())
            sim_library = str(args.sim_lib.resolve()) if args.sim_lib else (sim_match.group(1) if sim_match else None)
            counts = Counter(cell["type"] for cell in mapped["modules"][top]["cells"].values())
            # The design was flattened: these are physical primitive instances
            # in this core, not sums that double-count nested module statistics.
            unknown = {kind: count for kind, count in counts.items() if kind.startswith("$")}
            if unknown:
                fail(f"Unmapped internal cells in {tag}: {unknown}")
            row = {
                "design": design, "mapping": mode, "lanes": lanes,
                "dsp48": sum(n for k, n in counts.items() if k.startswith("DSP48")),
                "logic_lut": sum(n for k, n in counts.items() if k.startswith("LUT")),
                "fabric_ff": sum(n for k, n in counts.items() if k.startswith("FD")),
                "carry4": counts.get("CARRY4", 0),
                "distributed_ram_cells": sum(n for k, n in counts.items()
                    if k.startswith("RAM") and not k.startswith("RAMB")),
                "block_ram_cells": sum(n for k, n in counts.items() if k.startswith("RAMB")),
                "total_primitive_instances": sum(counts.values()),
                "cell_counts": dict(sorted(counts.items())),
                "log": log.name, "command_file": script.name, "statistics": stats.name,
                "mapped_verilog": str(verilog.relative_to(ROOT)),
                "simulation_library": sim_library,
            }
            if mode == "lut" and row["dsp48"]:
                fail(f"Unexpected DSP inference in LUT-only run: {tag}")
            rows.append(row)
            print(f"  DSP48={row['dsp48']} LUT={row['logic_lut']} FF={row['fabric_ff']}", flush=True)
    report = {
        "status": "passed",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "yosys_version": version,
        "target_family": "Xilinx 7-series (xc7), suitable for Artix-7",
        "parameters": {"VECTOR_LEN": 16, "DATA_WIDTH": 8, "ACC_WIDTH": 20},
        "measurement": "Mapped synthesis primitive counts, before placement and routing",
        "scope": "Core including input buffers and controller; excludes board IO/clock buffers",
        "rtl_sha256": provenance,
        "synthesis_script_sha256": script_hash,
        "notes": [
            "LUT is the sum of LUT* primitive instances, not packed slices or total physical LUT sites.",
            "Distributed RAM primitives are listed separately and consume FPGA LUT resources too.",
            "Fabric FF excludes registers within DSP and RAM primitives.",
            "Different primitive kinds are not interchangeable units of area.",
            "No clock-frequency, board timing, energy or power result is measured by this script.",
        ],
        "results": rows,
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    fields = ["design", "mapping", "lanes", "dsp48", "logic_lut", "fabric_ff", "carry4",
              "distributed_ram_cells", "block_ram_cells", "total_primitive_instances"]
    with (out / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Measured mapped synthesis resources", "", f"Tool: `{version}`.", "",
             report["measurement"] + ". " + report["scope"] + ".", "",
             "| Design | Mapping | DSP48 | Logic LUT primitives | Fabric FF | Carry4 | LUT-RAM primitives |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['design']} | {row['mapping']} | {row['dsp48']} | "
                     f"{row['logic_lut']} | {row['fabric_ff']} | {row['carry4']} | "
                     f"{row['distributed_ram_cells']} |")
    lines += ["", *["- " + note for note in report["notes"]], "",
              "Full primitive counts and source hashes: `summary.json`. Raw commands/logs are adjacent."]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"Reports: {out}")


if __name__ == "__main__":
    main()
