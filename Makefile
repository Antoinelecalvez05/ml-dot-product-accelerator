PYTHON ?= python3
.DEFAULT_GOAL := help
.PHONY: help test test-quick test-model reference waves netlist-test synth board-test report all

help:
	@echo "make test        Full cocotb regression and parameter sweep"
	@echo "make test-quick  Short regression, useful while editing"
	@echo "make test-model  Pure Python reference checks"
	@echo "make reference   Print the example dot product (272)"
	@echo "make waves       Short regression with simulator waveforms"
	@echo "make netlist-test  Verify mapped netlists after synthesis"
	@echo "make synth       Compare DSP-enabled and LUT-only mappings"
	@echo "make board-test  Check the Basys 3 demonstration in simulation"
	@echo "make report      Summarize the measured JSON reports"
	@echo "make all         Run verification, synthesis, mapped checks and report"

test:
	$(PYTHON) scripts/run_tests.py

test-quick:
	$(PYTHON) scripts/run_tests.py --quick

test-model:
	$(PYTHON) -m unittest discover -s tests -p test_reference.py -v

reference:
	$(PYTHON) -m model.reference

waves:
	$(PYTHON) scripts/run_tests.py --quick --waves

netlist-test:
	$(PYTHON) scripts/verify_netlists.py

synth:
	$(PYTHON) scripts/synthesize.py

board-test:
	$(PYTHON) fpga/smoke.py

report:
	$(PYTHON) scripts/make_report.py

all:
	$(PYTHON) scripts/run_tests.py
	$(PYTHON) scripts/synthesize.py
	$(PYTHON) scripts/verify_netlists.py
	$(PYTHON) fpga/smoke.py
	$(PYTHON) scripts/make_report.py
