from collections import deque
import json
import os
from pathlib import Path
import random

import cocotb
from cocotb.triggers import Timer

from model.reference import decode_signed, dot_product, encode_signed


N = int(os.environ["DP_VECTOR_LEN"])
W = int(os.environ["DP_DATA_WIDTH"])
LANES = int(os.environ["DP_LANES"])
SEED = int(os.environ.get("DP_SEED", "20261029"))
RANDOM_FRAMES = int(os.environ.get("DP_RANDOM_FRAMES", "512"))
REPORT_DIR = Path(os.environ["DP_REPORT_DIR"])


class Bench:

    def __init__(self, dut):
        self.dut = dut
        self.edge = 0
        self.current_a = []
        self.current_b = []
        self.input_edges = []
        self.pending = deque()
        self.completed = []
        self.held_output = None
        self.held_input = None
        self.coverage = dict(clock_edges=0, input_pairs=0, complete_input_frames=0,
                             checked_outputs=0, reset_edges=0, aborted_partial_frames=0,
                             aborted_complete_frames=0, input_pause_cycles=0,
                             input_backpressure_cycles=0, output_backpressure_cycles=0)
        dut.clk.value = 0
        dut.rst.value = 1
        dut.in_valid.value = 0
        dut.in_a.value = 0
        dut.in_b.value = 0
        dut.out_ready.value = 0

    def sample(self):
        valid = int(self.dut.out_valid.value)
        return {
            "in_ready": int(self.dut.in_ready.value),
            "out_valid": valid,
            "result": decode_signed(int(self.dut.result.value), len(self.dut.result)) if valid else None,
        }

    async def tick(self, *, valid=0, a=0, b=0, ready=1, reset=0):
        self.dut.clk.value = 0
        self.dut.rst.value = reset
        self.dut.in_valid.value = valid
        self.dut.out_ready.value = ready
        self.dut.in_a.value = encode_signed(a, W) if valid else (self.edge * 31 + 7) % (1 << W)
        self.dut.in_b.value = encode_signed(b, W) if valid else (self.edge * 17 + 3) % (1 << W)
        await Timer(5, unit="ns")
        before = self.sample()
        self.edge += 1
        self.coverage["clock_edges"] += 1

        if reset:
            assert before["in_ready"] == 0, "Input ready must be masked during reset"
            assert before["out_valid"] == 0, "Output valid must be masked during reset"
        else:
            if self.held_input is not None:
                assert valid and (a, b) == self.held_input, "Test driver violated input hold protocol"
            if self.held_output is not None:
                assert before["out_valid"], "DUT withdrew a result before its handshake"
                assert before["result"] == self.held_output, "DUT changed a pending result"
            if before["out_valid"]:
                assert self.pending, "Unexpected/duplicate result or result before a full input vector"
                assert before["result"] == self.pending[0]["expected"], (
                    f"edge {self.edge}: got {before['result']}, expected {self.pending[0]['expected']}"
                )

        input_fire = bool(valid and before["in_ready"] and not reset)
        output_fire = bool(before["out_valid"] and ready and not reset)
        self.dut.clk.value = 1
        await Timer(5, unit="ns")

        if reset:
            self.coverage["reset_edges"] += 1
            self.coverage["aborted_partial_frames"] += bool(self.current_a)
            self.coverage["aborted_complete_frames"] += len(self.pending)
            self.current_a.clear()
            self.current_b.clear()
            self.input_edges.clear()
            self.pending.clear()
            self.held_output = None
            self.held_input = None
        else:
            if self.current_a and not valid and before["in_ready"]:
                self.coverage["input_pause_cycles"] += 1
            if valid and not before["in_ready"]:
                self.coverage["input_backpressure_cycles"] += 1
            if before["out_valid"] and not ready:
                self.coverage["output_backpressure_cycles"] += 1
            self.held_input = (a, b) if valid and not before["in_ready"] else None
            if output_fire:
                assert not input_fire, "This interface does not load on the output-retirement edge"
                record = self.pending.popleft()
                record["result_transfer_edge"] = self.edge
                record["observed"] = before["result"]
                self.completed.append(record)
                self.coverage["checked_outputs"] += 1
            if input_fire:
                assert not self.pending, "DUT accepted a new vector while the preceding one was pending"
                self.current_a.append(a)
                self.current_b.append(b)
                self.input_edges.append(self.edge)
                self.coverage["input_pairs"] += 1
                if len(self.current_a) == N:
                    self.pending.append({
                        "expected": dot_product(self.current_a, self.current_b, W),
                        "first_input_edge": self.input_edges[0],
                        "last_input_edge": self.input_edges[-1],
                        "input_edges": self.input_edges.copy(),
                        "result_visible_edge": None,
                    })
                    self.coverage["complete_input_frames"] += 1
                    self.current_a.clear()
                    self.current_b.clear()
                    self.input_edges.clear()

        after = self.sample()
        if reset:
            assert not after["out_valid"] and not after["in_ready"]
        else:
            assert bool(after["in_ready"]) == (not self.pending), (
                "Ready must remain high while loading and low until a pending result retires"
            )
            if after["out_valid"]:
                assert self.pending, "Result appeared before N accepted input pairs"
                record = self.pending[0]
                assert after["result"] == record["expected"], "Incorrect registered result"
                if record["result_visible_edge"] is None:
                    record["result_visible_edge"] = self.edge
                self.held_output = after["result"]
            else:
                self.held_output = None
        return dict(edge=self.edge, input_fire=input_fire, output_fire=output_fire, **after)

    async def reset(self):
        await self.tick(reset=1, ready=0)
        await self.tick(reset=1, ready=0)

    async def send_pair(self, a, b, *, ready=0):
        for _ in range(100 + 20 * N):
            event = await self.tick(valid=1, a=a, b=b, ready=ready)
            if event["input_fire"]:
                return event
        raise AssertionError("Timed out waiting for input ready")

    async def send_vector(self, a, b, *, pauses=None, ready=0):
        assert len(a) == N and len(b) == N
        pauses = pauses or [0] * N
        for x, y, pause in zip(a, b, pauses):
            for _ in range(pause):
                await self.tick(ready=ready)
            await self.send_pair(x, y, ready=ready)
        return self.pending[-1]

    async def await_valid(self, *, ready=0):
        for _ in range(100 + 20 * N):
            if int(self.dut.out_valid.value):
                return
            await self.tick(ready=ready)
        raise AssertionError("Timed out waiting for output valid")

    async def retire(self, *, stall_cycles=0, ready_during_compute=0):
        await self.await_valid(ready=ready_during_compute)
        for _ in range(stall_cycles):
            await self.tick(ready=0)
        event = await self.tick(ready=1)
        assert event["output_fire"], "Ready receiver did not consume the pending result"
        return self.completed[-1]

    async def quiesce(self):
        assert not self.pending and not self.current_a, "Outstanding work left by test driver"
        for _ in range(N + 5):
            await self.tick(ready=1)
        assert not int(self.dut.out_valid.value), "Unexpected extra result after the test"

    def report(self, name, **extra):
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report = {"test": name, "status": "passed", "vector_len": N, "data_width": W,
                  "lanes": LANES, "seed": SEED, "coverage": self.coverage, **extra}
        (REPORT_DIR / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")


def directed_vectors():
    lo, hi = -(1 << (W - 1)), (1 << (W - 1)) - 1
    vectors = [
        ("zero", [0] * N, [hi] * N),
        ("ones", [1] * N, [1] * N),
        ("all_max", [hi] * N, [hi] * N),
        ("min_times_min", [lo] * N, [lo] * N),
        ("minimum_sum", [lo] * N, [hi] * N),
        ("minimum_sum_swapped", [hi] * N, [lo] * N),
        ("minus_ones", [-1] * N, [1] * N),
        ("alternating", [hi if i % 2 else -hi for i in range(N)], [lo] * N),
        ("mixed_extrema", [lo if i % 2 else hi for i in range(N)],
         [lo if i % 3 else hi for i in range(N)]),
        ("ramp", [max(lo, min(hi, i - N // 2)) for i in range(N)],
         [max(lo, min(hi, i + 1)) for i in range(N)]),
    ]
    for index in range(N):
        a = [0] * N
        a[index] = hi
        b = [lo + (i * 7 + 3) % (1 << W) for i in range(N)]
        vectors.append((f"impulse_{index}", a, b))
    return vectors


@cocotb.test()
async def arithmetic_and_random_protocol(dut):
    bench = Bench(dut)
    await bench.reset()
    rng = random.Random(SEED)
    vectors = directed_vectors()
    directed_results = []
    for label, a, b in vectors:
        pauses = [0] * N
        if label == "mixed_extrema":
            pauses[N // 2] = 37
        record = await bench.send_vector(a, b, pauses=pauses)
        await bench.retire(stall_cycles=37 if label == "all_max" else 2)
        directed_results.append({"case": label, "expected": record["expected"]})

    lo, hi = -(1 << (W - 1)), (1 << (W - 1)) - 1
    for _ in range(RANDOM_FRAMES):
        a = [rng.randint(lo, hi) for _ in range(N)]
        b = [rng.randint(lo, hi) for _ in range(N)]
        pauses = [rng.randrange(4) if rng.random() < 0.45 else 0 for _ in range(N)]
        await bench.send_vector(a, b, pauses=pauses)
        await bench.retire(stall_cycles=rng.randrange(10))
    await bench.quiesce()
    assert len(bench.completed) == len(vectors) + RANDOM_FRAMES
    bench.report("arithmetic_and_random_protocol", random_frames=RANDOM_FRAMES,
                 directed_cases=directed_results)


@cocotb.test()
async def continuous_valid_back_to_back(dut):
    bench = Bench(dut)
    await bench.reset()
    rng = random.Random(SEED + 1)
    lo, hi = -(1 << (W - 1)), (1 << (W - 1)) - 1
    frames = 12
    pairs = [(rng.randint(lo, hi), rng.randint(lo, hi)) for _ in range(frames * N)]
    next_pair = 0
    for cycle in range(frames * (N + N // LANES + 30) + 100):
        valid = next_pair < len(pairs)
        a, b = pairs[next_pair] if valid else (0, 0)
        ready = (cycle % 13) not in (4, 5, 6, 7, 8)
        event = await bench.tick(valid=valid, a=a, b=b, ready=ready)
        if event["input_fire"]:
            next_pair += 1
        if len(bench.completed) == frames:
            break
    else:
        raise AssertionError("Timed out with continuous valid and receiver stalls")
    assert next_pair == len(pairs)
    assert bench.coverage["input_backpressure_cycles"] > 0
    assert bench.coverage["output_backpressure_cycles"] > 0
    await bench.quiesce()
    bench.report("continuous_valid_back_to_back", frames=frames)


@cocotb.test()
async def reset_abort_and_recovery(dut):
    bench = Bench(dut)
    await bench.reset()
    a, b = [1] * N, [-1] * N
    poison_a, poison_b = -(1 << (W - 1)), (1 << (W - 1)) - 1
    scenarios = []

    async def recover(label):
        await bench.send_vector(a, b)
        await bench.retire()
        await bench.quiesce()
        scenarios.append(label)

    if N > 1:
        for _ in range(max(1, N // 2)):
            await bench.send_pair(poison_a, poison_b)
        await bench.tick(reset=1, ready=1, valid=1, a=poison_a, b=poison_b)
        await recover("reset_during_partial_load")

    for _ in range(N - 1):
        await bench.send_pair(poison_a, poison_b)
    await bench.tick(reset=1, valid=1, a=poison_a, b=poison_b, ready=1)
    await recover("reset_on_final_input_edge")

    await bench.send_vector([poison_a] * N, [poison_b] * N)
    for _ in range((N // LANES) // 2):
        await bench.tick(ready=0)
    await bench.tick(reset=1, ready=1)
    await recover("reset_during_compute")

    await bench.send_vector([poison_a] * N, [poison_b] * N)
    for _ in range(max(0, N // LANES - 1)):
        await bench.tick(ready=0)
    await bench.tick(reset=1, ready=1)
    await recover("reset_on_final_compute_edge")

    await bench.send_vector([poison_a] * N, [poison_b] * N)
    for _ in range(N // LANES):
        await bench.tick(ready=0)
    assert not int(dut.out_valid.value)
    await bench.tick(reset=1, ready=1)
    await recover("reset_on_reduction_edge")

    for ready_at_reset in (0, 1):
        await bench.send_vector([poison_a] * N, [poison_b] * N)
        await bench.await_valid()
        for _ in range(5):
            await bench.tick(ready=0)
        await bench.tick(reset=1, ready=ready_at_reset)
        await recover(f"reset_pending_result_ready_{ready_at_reset}")

    await bench.tick(reset=1, ready=1, valid=1, a=1, b=1)
    await bench.tick(reset=1, ready=1, valid=1, a=1, b=1)
    await recover("held_reset_with_valid_and_ready")
    bench.report("reset_abort_and_recovery", scenarios=scenarios)


def timing_record(record):
    first = record["first_input_edge"]
    last = record["last_input_edge"]
    visible = record["result_visible_edge"]
    transferred = record["result_transfer_edge"]
    return {
        "first_input_edge": first,
        "last_input_edge": last,
        "result_visible_edge": visible,
        "result_transfer_edge": transferred,
        "load_cycles_inclusive": last - first + 1,
        "compute_to_valid_cycles": visible - last,
        "first_to_valid_cycles_inclusive": visible - first + 1,
        "first_to_transfer_cycles_inclusive": transferred - first + 1,
        "result": record["observed"],
    }


@cocotb.test()
async def measured_cycle_benchmarks(dut):
    bench = Bench(dut)
    await bench.reset()
    a = [max(-(1 << (W - 1)), min((1 << (W - 1)) - 1, i - N // 2)) for i in range(N)]
    b = [max(-(1 << (W - 1)), min((1 << (W - 1)) - 1, i + 1)) for i in range(N)]
    scenarios = {}
    for name, pauses, stalls in [
        ("no_stall", [0] * N, 0),
        ("deterministic_stalls", [0] + [1] * (N - 1), 6),
    ]:
        results = []
        for _ in range(4):
            record = await bench.send_vector(a, b, pauses=pauses, ready=(stalls == 0))
            await bench.retire(stall_cycles=stalls, ready_during_compute=(stalls == 0))
            results.append(timing_record(record))
        intervals = [right["first_input_edge"] - left["first_input_edge"]
                     for left, right in zip(results, results[1:])]
        assert len(set(intervals)) == 1, "Unexpected inter-frame timing jitter"
        expected_compute = N // LANES + 1
        for record in results:
            assert record["compute_to_valid_cycles"] == expected_compute
            assert record["load_cycles_inclusive"] == N + sum(pauses)
            assert record["first_to_transfer_cycles_inclusive"] == N + sum(pauses) + expected_compute + 1 + stalls
        scenarios[name] = {
            **results[0],
            "repeat_frame_interval_cycles": intervals[0],
            "input_pause_cycles_per_frame": sum(pauses),
            "output_stall_cycles_per_frame": stalls,
            "repetitions": results,
        }
    await bench.quiesce()
    bench.report("measured_cycle_benchmarks", clock_period_ns=10,
                 note="The simulation period is stimulus only; it does not prove achievable clock frequency.",
                 scenarios=scenarios)
