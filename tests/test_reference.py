"""Arithmetic boundary checks for the independent model (standard library)."""

import unittest

from model.reference import decode_signed, dot_product, encode_signed, required_accumulator_width


class ReferenceTests(unittest.TestCase):
    def test_known_example(self):
        self.assertEqual(dot_product(list(range(-8, 8)), list(range(1, 17))), 272)

    def test_positive_extreme_needs_twenty_bits(self):
        self.assertEqual(dot_product([-128] * 16, [-128] * 16), 262144)
        self.assertEqual(required_accumulator_width(8, 16), 20)
        self.assertGreater(262144, (1 << 18) - 1)  # 19-bit signed maximum.

    def test_negative_extreme(self):
        self.assertEqual(dot_product([-128] * 16, [127] * 16), -260096)

    def test_cancellation(self):
        self.assertEqual(dot_product([127, 127, -127, -127], [-128] * 4), 0)

    def test_signed_wire_roundtrip(self):
        for value in range(-128, 128):
            self.assertEqual(decode_signed(encode_signed(value, 8), 8), value)

    def test_rejects_invalid_inputs(self):
        for a, b in [([], []), ([1], [1, 2]), ([128], [1]), ([-129], [1]), ([1.5], [1])]:
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                dot_product(a, b)

    def test_single_and_non_power_of_two_widths(self):
        self.assertEqual(required_accumulator_width(8, 1), 16)
        self.assertEqual(required_accumulator_width(4, 12), 12)


if __name__ == "__main__":
    unittest.main()
