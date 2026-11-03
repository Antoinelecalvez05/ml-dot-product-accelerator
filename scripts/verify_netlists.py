#!/usr/bin/env python3
"""Run the same protocol/arithmetic tests against four mapped Xilinx netlists.

Run synthesis first. The cells_sim.v path normally comes from the synthesis
report; --cells-sim overrides it if the project has moved between computers.
These are functional, zero-delay simulations, not static timing analysis.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from run_tests import ROOT, preserve_logs, run_configuration


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def library_path(result, override):
    candidates = []
    if override is not None:
        candidates.append(override)
    else:
        if result.get("simulation_library"):
            candidates.append(Path(result["simulation_library"]))
        if os.environ.get("YOSYS_DATDIR"):
            candidates.append(Path(os.environ["YOSYS_DATDIR"]) / "xilinx" / "cells_sim.v")
        config = shutil.which("yosys-config")
        if config:
            datdir = subprocess.run([config, "--datdir"], capture_output=True, text=True, check=True).stdout.strip()
            candidates.append(Path(datdir) / "xilinx" / "cells_sim.v")
        executable = shutil.which("yosys")
        if executable:
            candidates.append(Path(executable).resolve().parent.parent / "share" / "yosys" / "xilinx" / "cells_sim.v")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Cannot locate Yosys's Xilinx cells_sim.v. Supply --cells-sim /absolute/path/to/cells_sim.v")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells-sim", type=Path)
    parser.add_argument("--summary", type=Path, default=ROOT / "reports" / "synthesis" / "summary.json")
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=20261029)
    parser.add_argument("--waves", action="store_true")
    args = parser.parse_args()
    args.quick = True
    if not args.summary.is_file():
        parser.error("No synthesis summary. Run the synthesis script before testing netlists.")
    synthesis = json.loads(args.summary.read_text())
    required = {(design, mapping) for design in ("serial", "parallel") for mapping in ("dsp", "lut")}
    available = {(item["design"], item["mapping"]) for item in synthesis["results"]}
    if not required.issubset(available):
        parser.error("The synthesis summary must contain serial/parallel with both DSP and LUT mapping.")
    for relative, expected in synthesis["rtl_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or digest(path) != expected:
            parser.error(f"RTL has changed since synthesis: {relative}. Rerun synthesis first.")
    for executable in ("iverilog", "vvp"):
        if not shutil.which(executable):
            parser.error(f"{executable} is not on PATH")
    try:
        import cocotb
    except ImportError:
        parser.error("Install requirements.txt before running this script")

    output_path = ROOT / "reports" / "netlist_verification.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps({"status": "running", "seed": args.seed}, indent=2) + "\n")
    records = []
    for result in synthesis["results"]:
        design, mapping = result["design"], result["mapping"]
        if (design, mapping) not in required:
            continue
        config = dict(name=f"gate_{design}_{mapping}", top=f"dot_product_{design}",
                      vector_len=16, data_width=8, lanes=result["lanes"])
        print(f"Verifying mapped {design}/{mapping}...", flush=True)
        try:
            netlist = (ROOT / result["mapped_verilog"]).resolve()
            if not netlist.is_file():
                raise FileNotFoundError(f"Missing mapped netlist: {netlist}")
            library = library_path(result, args.cells_sim)
            record = run_configuration(config, args, sources_override=[netlist, library], parameters_override={})
            record["mapping"] = mapping
            record["netlist"] = {"path": result["mapped_verilog"], "sha256": digest(netlist)}
            record["simulation_library"] = {"path": str(library), "sha256": digest(library)}
            record["logs"] = preserve_logs(config["name"], "netlist_logs")
        except (Exception, SystemExit) as exc:
            record = {**config, "mapping": mapping, "status": "failed", "error": str(exc)}
        records.append(record)
        print(f"  {record['status'].upper()}: " + (f"{record['coverage']['checked_outputs']} checked results"
              if record["status"] == "passed" else record.get("error", "see simulation log")), flush=True)

    status = "passed" if len(records) == 4 and all(record["status"] == "passed" for record in records) else "failed"
    report = {
        "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Functional simulation of mapped Xilinx primitive netlists; no SDF or timing proof.",
        "seed": args.seed,
        "tools": {
            "python": sys.version.split()[0], "cocotb": cocotb.__version__,
            "iverilog": subprocess.run(["iverilog", "-V"], capture_output=True, text=True).stdout.splitlines()[0],
            "yosys": synthesis["yosys_version"],
        },
        "synthesis_summary_sha256": digest(args.summary),
        "rtl_sha256": synthesis["rtl_sha256"],
        "verification_source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in [
            ROOT / "scripts" / "run_tests.py", Path(__file__), ROOT / "tests" / "cocotb_dot_product.py", ROOT / "model" / "reference.py"]},
        "simulation_tests": sum(record.get("junit", {}).get("tests", 0) for record in records),
        "checked_outputs": sum(record.get("coverage", {}).get("checked_outputs", 0) for record in records),
        "configurations": records,
    }
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Overall: {status.upper()} — {report['simulation_tests']} mapped tests, {report['checked_outputs']} checked results.", flush=True)
    print("Evidence: reports/netlist_verification.json and reports/netlist_logs/", flush=True)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
