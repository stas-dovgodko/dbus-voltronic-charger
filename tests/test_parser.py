import unittest

from voltronic_charger.parser import parse_protocol_id, parse_qpigs_pi30
from voltronic_charger.protocol import ProtocolError


DOCUMENTED_SHAPE = (
    "(230.0 50.0 230.0 50.0 0500 0400 010 400 52.40 012 080 0030 "
    "0005 300.0 52.40 00000 00000111 00 01 00420 110"
)


class ParserTest(unittest.TestCase):
    def test_protocol_id(self):
        self.assertEqual("PI30", parse_protocol_id("(PI30"))

    def test_documented_pi30_shape(self):
        status = parse_qpigs_pi30(DOCUMENTED_SHAPE)
        self.assertEqual(52.4, status.battery_voltage)
        self.assertEqual(12.0, status.reported_battery_charging_current)
        self.assertEqual(420, status.pv_charging_power)
        self.assertTrue(status.ac_charging)
        self.assertTrue(status.scc_charging)
        self.assertTrue(status.charging)

    def test_requires_exact_field_count_and_bit_widths(self):
        with self.assertRaises(ProtocolError):
            parse_qpigs_pi30("(230.0 50.0")
        with self.assertRaises(ProtocolError):
            parse_qpigs_pi30(DOCUMENTED_SHAPE.replace("00000111", "111"))


if __name__ == "__main__":
    unittest.main()

