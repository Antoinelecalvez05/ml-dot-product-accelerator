"""Exact signed-integer dot product, independent of RTL scheduling and lanes.

Run ``python -m model.reference`` for the built-in 16-element example, or supply
comma-separated integer lists with ``--a`` and ``--b``. No third-party package
is required. Python's unbounded integers deliberately avoid hardware overflow.
"""

import argparse
import json


def required_accumulator_width(data_width, vector_len):
    if data_width < 2 or vector_len < 1:
        raise ValueError("data_width must be >= 2 and vector_len must be >= 1")
    return 2 * data_width + (vector_len - 1).bit_length()


def dot_product(a, b, data_width=8):
    if data_width < 2:
        raise ValueError("data_width must be >= 2")
    if len(a) != len(b) or not a:
        raise ValueError("a and b must have the same nonzero length")
    lower, upper = -(1 << (data_width - 1)), (1 << (data_width - 1)) - 1
    for value in [*a, *b]:
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"{value!r} is not a signed {data_width}-bit integer")
    return sum(x * y for x, y in zip(a, b))


def encode_signed(value, width):
    if not -(1 << (width - 1)) <= value < (1 << (width - 1)):
        raise ValueError(f"{value} does not fit in {width} signed bits")
    return value & ((1 << width) - 1)


def decode_signed(bits, width):
    if not 0 <= bits < (1 << width):
        raise ValueError(f"{bits} does not fit in {width} unsigned bits")
    return bits - (1 << width) if bits & (1 << (width - 1)) else bits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", help="Comma-separated signed integers")
    parser.add_argument("--b", help="Comma-separated signed integers")
    parser.add_argument("--width", type=int, default=8)
    args = parser.parse_args()
    if (args.a is None) != (args.b is None):
        parser.error("Supply both --a and --b, or neither")
    try:
        a = [int(x) for x in args.a.split(",")] if args.a is not None else list(range(-8, 8))
        b = [int(x) for x in args.b.split(",")] if args.b is not None else list(range(1, 17))
        result = dot_product(a, b, args.width)
        print(json.dumps({"a": a, "b": b, "result": result,
                          "accumulator_width": required_accumulator_width(args.width, len(a))}, indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
