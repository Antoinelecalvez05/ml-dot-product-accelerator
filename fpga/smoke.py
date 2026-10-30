#!/usr/bin/env python3
"""Compile and run the board-wrapper smoke test with Icarus Verilog."""
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
for tool in ("iverilog", "vvp"):
    if not shutil.which(tool):
        raise SystemExit(f"Missing {tool}; install Icarus Verilog first.")
build = root / "build" / "board"
build.mkdir(parents=True, exist_ok=True)
reports = root / "reports"
reports.mkdir(parents=True, exist_ok=True)
sources = [root / "rtl" / name for name in
           ("dot_product_core.v", "dot_product_serial.v", "dot_product_parallel.v")]
sources += [root / "fpga" / name for name in
            ("button_filter.v", "basys3_demo.v", "tb_basys3_demo.v")]
exe = build / "board.vvp"
subprocess.run(["iverilog", "-g2012", "-Wall", "-s", "tb_basys3_demo", "-o", str(exe),
                *map(str, sources)], check=True)
completed = subprocess.run(["vvp", str(exe)], text=True, capture_output=True)
log = completed.stdout + completed.stderr
(reports / "board_smoke.log").write_text(log)
print(log, end="")
if completed.returncode or "PASS:" not in log:
    raise SystemExit(completed.returncode or 1)
