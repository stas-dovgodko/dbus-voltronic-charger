import unittest

from voltronic_charger.parser import (
    build_charge_current_capabilities,
    parse_charge_current_options,
    parse_protocol_id,
    parse_qpiri_charger_source_priority,
    parse_qpigs_pi30,
    parse_qpiri_charge_limits,
)
from voltronic_charger.protocol import ProtocolError


DOCUMENTED_SHAPE = (
    "(230.0 50.0 230.0 50.0 0500 0400 010 400 52.40 012 080 0030 "
    "0005 300.0 52.40 00000 00000111 00 01 00420 110"
)

KING_II_FIRST_CAPTURE = (
    "(000.0 00.0 230.0 49.9 0003 0003 000 365 52.50 000 073 0043 "
    "0000 000.0 00.00 00000 00010000 00 00 00000 010"
)

QPIRI_WITH_30A_UTILITY_AND_140A_TOTAL = (
    "(230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 46.0 42.0 "
    "56.4 54.0 2 030 140 0 2 2 9 01 0 00 48.0 0 1 120"
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

    def test_first_real_king_ii_capture(self):
        status = parse_qpigs_pi30(KING_II_FIRST_CAPTURE)
        self.assertEqual(230.0, status.output_voltage)
        self.assertEqual(3, status.output_active_power)
        self.assertEqual(52.5, status.battery_voltage)
        self.assertEqual(73, status.battery_capacity_percent)
        self.assertEqual(43.0, status.heatsink_temperature)
        self.assertEqual(0.0, status.reported_battery_charging_current)
        self.assertFalse(status.charging)
        self.assertFalse(status.ac_charging)
        self.assertFalse(status.scc_charging)

    def test_qpiri_reports_current_limits_at_protocol_defined_positions(self):
        self.assertEqual(
            (30, 140),
            parse_qpiri_charge_limits(QPIRI_WITH_30A_UTILITY_AND_140A_TOTAL),
        )
        self.assertEqual(
            2,
            parse_qpiri_charger_source_priority(
                QPIRI_WITH_30A_UTILITY_AND_140A_TOTAL
            ),
        )

    def test_current_options_are_read_from_inverter_without_hard_coding(self):
        self.assertEqual((7, 13, 29), parse_charge_current_options("(007 013 029"))
        capabilities = build_charge_current_capabilities(
            QPIRI_WITH_30A_UTILITY_AND_140A_TOTAL,
            "(010 020 060 080 100 120 140",
            "(002 010 020 030",
        )
        self.assertEqual(140, capabilities.total_limit)
        self.assertEqual(30, capabilities.utility_limit)
        self.assertEqual(
            (10, 20, 60, 80, 100, 120, 140),
            capabilities.selectable_total_limits,
        )
        self.assertEqual((2, 10, 20, 30), capabilities.selectable_utility_limits)

    def test_invalid_current_capability_frames_fail_closed(self):
        with self.assertRaises(ProtocolError):
            parse_qpiri_charge_limits("(230.0 21.7")
        with self.assertRaises(ProtocolError):
            parse_charge_current_options("(010 twenty 030")
        with self.assertRaises(ProtocolError):
            parse_charge_current_options("(NAK")


if __name__ == "__main__":
    unittest.main()
