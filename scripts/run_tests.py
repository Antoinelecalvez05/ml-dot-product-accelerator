#!/usr/bin/env python3
"""Compile the actual RTL, run cocotb, and publish reproducible test evidence.

Requires Icarus Verilog (iverilog and vvp) on PATH and requirements.txt installed.
The script returns a nonzero exit status for compile, simulator, or assertion
failures. It reads JUnit XML explicitly, so failure detection does not depend on
whether the cocotb runner was invoked through pytest.
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
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "tests"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))


def configurations():
    return [
        dict(name="serial", top="dot_product_serial", vector_len=16, data_width=8, lanes=1),
        dict(name="parallel", top="dot_product_parallel", vector_len=16, data_width=8, lanes=4),
        dict(name="core_n1_w8_l1", top="dot_product_core", vector_len=1, data_width=8, lanes=1),
        dict(name="core_n2_w2_l1", top="dot_product_core", vector_len=2, data_width=2, lanes=1),
        dict(name="core_n4_w4_l1", top="dot_product_core", vector_len=4, data_width=4, lanes=1),
        dict(name="core_n4_w4_l2", top="dot_product_core", vector_len=4, data_width=4, lanes=2),
        dict(name="core_n4_w4_l4", top="dot_product_core", vector_len=4, data_width=4, lanes=4),
        dict(name="core_n6_w8_l3", top="dot_product_core", vector_len=6, data_width=8, lanes=3),
        dict(name="core_n8_w8_l2", top="dot_product_core", vector_len=8, data_width=8, lanes=2),
        dict(name="core_n12_w8_l4", top="dot_product_core", vector_len=12, data_width=8, lanes=4),
    ]


def xml_results(path):
    tree = ET.parse(path)
    cases = list(tree.iter("testcase"))
    failed = [case.attrib.get("name", "unnamed") for case in cases
              if case.find("failure") is not None or case.find("error") is not None]
    skipped = [case.attrib.get("name", "unnamed") for case in cases if case.find("skipped") is not None]
    return dict(tests=len(cases), failed=failed, skipped=skipped)


def preserve_logs(config_name, group):
    destination = ROOT / "reports" / group / config_name
    destination.mkdir(parents=True, exist_ok=True)
    copied = {}
    for filename in ("compile.log", "simulation.log", "results.xml"):
        source = ROOT / "build" / "sim" / config_name / filename
        target = destination / filename
        if source.exists():
            shutil.copy2(source, target)
            copied[filename] = str(target.relative_to(ROOT))
        elif target.exists():
            target.unlink()
    return copied


def run_configuration(config, args, *, sources_override=None, parameters_override=None, extra_build_args=()):
    from cocotb_tools.runner import get_runner

    work = ROOT / "build" / "sim" / config["name"]
    fragments = work / "reports"
    fragments.mkdir(parents=True, exist_ok=True)
    for path in fragments.glob("*.json"):
        path.unlink()
    xml = work / "results.xml"
    if xml.exists():
        xml.unlink()
    for log in (work / "compile.log", work / "simulation.log"):
        if log.exists():
            log.unlink()
    parameters = {"VECTOR_LEN": config["vector_len"], "DATA_WIDTH": config["data_width"]}
    if config["top"] == "dot_product_core":
        parameters["LANES"] = config["lanes"]
    if parameters_override is not None:
        parameters = parameters_override
    random_frames = (32 if args.quick else 512) if config["name"] in ("serial", "parallel") else (8 if args.quick else 32)
    runner = get_runner("icarus")
    sources = [ROOT / "rtl" / name for name in
               ("dot_product_core.v", "dot_product_serial.v", "dot_product_parallel.v")]
    if sources_override is not None:
        sources = sources_override
    record = {**config, "random_frames": random_frames, "status": "failed"}
    try:
        runner.build(sources=sources, hdl_toplevel=config["top"], parameters=parameters,
                     build_dir=work, always=True, build_args=["-Wall", *extra_build_args],
                     timescale=("1ns", "1ps"), waves=args.waves,
                     log_file=work / "compile.log")
        path_entries = [str(ROOT), str(ROOT / "tests")]
        if os.environ.get("PYTHONPATH"):
            path_entries.append(os.environ["PYTHONPATH"])
        runner.test(hdl_toplevel=config["top"], test_module="cocotb_dot_product",
                    seed=args.seed, build_dir=work, test_dir=work,
                    results_xml="results.xml", waves=args.waves,
                    log_file=work / "simulation.log",
                    extra_env={
                        "PYTHONPATH": os.pathsep.join(path_entries),
                        "DP_VECTOR_LEN": str(config["vector_len"]),
                        "DP_DATA_WIDTH": str(config["data_width"]),
                        "DP_LANES": str(config["lanes"]),
                        "DP_RANDOM_FRAMES": str(random_frames),
                        "DP_SEED": str(args.seed),
                        "DP_REPORT_DIR": str(fragments),
                        "COCOTB_LOG_LEVEL": "INFO",
                    })
        result = xml_results(xml)
        record["junit"] = result
        if result["tests"] != 4 or result["failed"] or result["skipped"]:
            raise RuntimeError(f"JUnit test failures or missing tests: {result}")
        reports = [json.loads(path.read_text()) for path in sorted(fragments.glob("*.json"))]
        if len(reports) != 4 or any(report["status"] != "passed" for report in reports):
            raise RuntimeError("Missing passing test evidence")
        record["test_reports"] = reports
        record["coverage"] = {key: sum(report["coverage"][key] for report in reports)
                              for key in reports[0]["coverage"]}
        record["status"] = "passed"
    except (Exception, SystemExit) as exc:
        record["error"] = str(exc)
        current_log = work / "simulation.log"
        if not current_log.exists():
            current_log = work / "compile.log"
        record["log"] = str(current_log.relative_to(ROOT))
        if xml.exists():
            record["junit"] = xml_results(xml)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="32 random vectors per wrapper, 8 per parameter case")
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=20261029)
    parser.add_argument("--waves", action="store_true", help="Retain FST waveforms in each build/sim directory")
    parser.add_argument("--parameters-only", action="store_true", help="Run only the eight additional core configurations")
    parser.add_argument("--no-parameter-sweep", action="store_true", help="Run only serial and parallel defaults")
    parser.add_argument("--configuration", choices=[item["name"] for item in configurations()])
    args = parser.parse_args()
    if args.parameters_only and args.no_parameter_sweep:
        parser.error("--parameters-only and --no-parameter-sweep are mutually exclusive")
    for executable in ("iverilog", "vvp"):
        if not shutil.which(executable):
            parser.error(f"{executable} is missing. Install Icarus Verilog and put it on PATH.")
    try:
        import cocotb
    except ImportError:
        parser.error("cocotb is missing. Run: python -m pip install -r requirements.txt")

    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "benchmark.json").unlink(missing_ok=True)
    (ROOT / "reports" / "verification.json").write_text(json.dumps({
        "status": "running", "seed": args.seed, "quick": args.quick,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")
    unit = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_reference.py", "-v"],
                          cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (ROOT / "build" / "reference_tests.log").write_text(unit.stdout)
    print(unit.stdout, end="", flush=True)
    if unit.returncode:
        (ROOT / "reports" / "verification.json").write_text(json.dumps({
            "status": "failed", "stage": "python_reference_tests", "seed": args.seed,
            "log": "build/reference_tests.log",
        }, indent=2) + "\n")
        return unit.returncode

    selected = configurations()
    if args.parameters_only:
        selected = [item for item in selected if item["top"] == "dot_product_core"]
    if args.no_parameter_sweep:
        selected = [item for item in selected if item["top"] != "dot_product_core"]
    if args.configuration:
        selected = [item for item in selected if item["name"] == args.configuration]
    if not selected:
        parser.error("The selected filters leave no configurations")

    records = []
    for config in selected:
        print(f"\nVerifying {config['name']} (N={config['vector_len']}, W={config['data_width']}, lanes={config['lanes']})...", flush=True)
        record = run_configuration(config, args)
        record["logs"] = preserve_logs(config["name"], "rtl_logs")
        records.append(record)
        print(f"  {record['status'].upper()}: " + (f"{record['coverage']['checked_outputs']} checked outputs"
              if record["status"] == "passed" else f"{record.get('error', '')}; see {record.get('log', '')}"), flush=True)

    source_paths = sorted((ROOT / "rtl").glob("*.v")) + [Path(__file__), ROOT / "tests" / "cocotb_dot_product.py",
                   ROOT / "tests" / "test_reference.py", ROOT / "model" / "reference.py", ROOT / "requirements.txt"]
    iverilog_version = subprocess.run(["iverilog", "-V"], capture_output=True, text=True).stdout.splitlines()[0]
    passed = all(record["status"] == "passed" for record in records)
    summary = {
        "status": "passed" if passed else "failed",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "quick": args.quick,
        "tools": {"python": sys.version.split()[0], "cocotb": cocotb.__version__, "iverilog": iverilog_version},
        "python_reference_tests": 7,
        "simulation_tests": sum(record.get("junit", {}).get("tests", 0) for record in records),
        "checked_outputs": sum(record.get("coverage", {}).get("checked_outputs", 0) for record in records),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths},
        "configurations": records,
    }
    (ROOT / "reports" / "verification.json").write_text(json.dumps(summary, indent=2) + "\n")
    default_records = {record["name"]: record for record in records if record["name"] in ("serial", "parallel") and record["status"] == "passed"}
    if len(default_records) == 2:
        benchmarks = {}
        for name, record in default_records.items():
            benchmark = next(report for report in record["test_reports"] if report["test"] == "measured_cycle_benchmarks")
            benchmarks[name] = {"lanes": record["lanes"], **benchmark["scenarios"]}
        output = {
            "status": "passed", "seed": args.seed, "vector_len": 16, "data_width": 8,
            "definitions": {
                "edge": "Rising edges numbered from 1 within each test, including reset edges.",
                "result_visible_edge": "Edge after which out_valid first becomes 1 (postedge observation).",
                "result_transfer_edge": "Following eligible edge with pre-edge out_valid=1 and out_ready=1.",
                "inclusive": "Both endpoint edges count: last minus first plus one.",
                "compute_to_valid_cycles": "Result visible edge minus last accepted input edge; includes reduction.",
                "repeat_frame_interval_cycles": "Distance between first accepted input edges of consecutive frames.",
            },
            "simulation_clock_period_ns": 10,
            "frequency_caveat": "A 10 ns simulation clock is not a timing-closure or Fmax measurement.",
            "architectures": benchmarks,
        }
        (ROOT / "reports" / "benchmark.json").write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nOverall: {summary['status'].upper()} — {summary['simulation_tests']} RTL tests, {summary['checked_outputs']} checked results.", flush=True)
    print("Evidence: reports/verification.json; reports/benchmark.json (when both defaults ran).", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
